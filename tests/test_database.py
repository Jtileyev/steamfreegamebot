import os
import sqlite3
import unittest
from unittest import mock

import database
from tests.helpers import TempDbTestCase, make_deal


class InitTests(TempDbTestCase):
    def test_init_is_idempotent(self):
        self.init_db()
        self.init_db()
        tables = {r['name'] for r in self.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({'sent_games', 'meta'} <= tables)

    def test_migration_from_old_schema(self):
        # Схема и формат времени коммита 03a11fa
        conn = database.get_connection()
        conn.executescript("""
            CREATE TABLE sent_games (app_id TEXT PRIMARY KEY, title TEXT NOT NULL,
                                     discount INTEGER DEFAULT 0, sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE sent_events (event_name TEXT PRIMARY KEY, sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO sent_games VALUES ('10', 'Old', 90, '2026-02-15T10:00:00.123456');
            INSERT INTO sent_events VALUES ('Winter Sale', '2026-02-15T10:00:00');
        """)
        conn.commit()
        conn.close()

        self.init_db()

        tables = {r['name'] for r in self.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn('sent_events', tables)
        rows = self.execute("SELECT * FROM sent_games")
        self.assertEqual(rows[0]['last_seen_at'], '2026-02-15T10:00:00.123456')

        # Запись полугодовой давности забывается
        self.assertEqual(database.forget_missing(3), 1)


class DealTests(TempDbTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()

    def test_should_notify(self):
        self.assertTrue(database.should_notify(None, 80))
        self.assertFalse(database.should_notify({'discount': 80}, 80))
        self.assertTrue(database.should_notify({'discount': 80}, 90))
        self.assertTrue(database.should_notify({'discount': 90}, 80))
        self.assertTrue(database.should_notify({'discount': None}, 80))

    def test_remember_and_load(self):
        database.remember_deals([make_deal('1', 80), make_deal('2', 90)])
        database.remember_deals([make_deal('1', 85, title='Renamed')])
        known = database.load_known_deals()
        self.assertEqual(set(known), {'1', '2'})
        self.assertEqual(known['1']['discount'], 85)
        self.assertEqual(known['1']['title'], 'Renamed')

    def test_restore_new_deal_deletes(self):
        database.reserve_deal(make_deal('1'))
        database.restore_deal('1', None)
        self.assertEqual(database.load_known_deals(), {})

    def test_restore_existing_deal(self):
        database.remember_deals([make_deal('1', 75)])
        previous = database.load_known_deals()['1']
        database.reserve_deal(make_deal('1', 90))
        database.restore_deal('1', previous)
        restored = database.load_known_deals()['1']
        self.assertEqual(restored['discount'], 75)
        self.assertEqual(restored['sent_at'], previous['sent_at'])

    def test_forget_missing(self):
        database.remember_deals([make_deal('fresh'), make_deal('stale'), make_deal('broken')])
        self.execute("UPDATE sent_games SET last_seen_at = datetime('now', '-4 days') WHERE app_id = 'stale'")
        self.execute("UPDATE sent_games SET last_seen_at = 'garbage' WHERE app_id = 'broken'")
        self.assertEqual(database.forget_missing(3), 2)
        self.assertEqual(set(database.load_known_deals()), {'fresh'})

    def test_touch_seen_keeps_deal(self):
        database.remember_deals([make_deal('1')])
        self.execute("UPDATE sent_games SET last_seen_at = datetime('now', '-10 days')")
        self.assertEqual(database.touch_seen(['1', 'unknown']), 1)
        self.assertEqual(database.forget_missing(3), 0)

    def test_meta(self):
        self.assertIsNone(database.get_meta('k'))
        database.set_meta('k', 'v1')
        database.set_meta('k', 'v2')
        self.assertEqual(database.get_meta('k'), 'v2')
        database.delete_meta('k')
        self.assertIsNone(database.get_meta('k'))

    def test_errors_are_raised(self):
        self.execute("DROP TABLE sent_games")
        with self.assertRaises(sqlite3.Error):
            database.load_known_deals()


class PeekStateTests(TempDbTestCase):
    def test_missing_database(self):
        self.assertEqual(database.peek_state(), ({}, {}))
        self.assertFalse(os.path.exists(self.db_path))

    def test_old_schema_without_meta(self):
        conn = database.get_connection()
        conn.executescript("""
            CREATE TABLE sent_games (app_id TEXT PRIMARY KEY, title TEXT NOT NULL,
                                     discount INTEGER DEFAULT 0, sent_at TIMESTAMP);
            INSERT INTO sent_games VALUES ('10', 'Old', 90, '2026-02-15T10:00:00');
        """)
        conn.commit()
        conn.close()
        self.assertEqual(database.peek_state(), ({}, {'10': 90}))
        columns = {r['name'] for r in self.execute("PRAGMA table_info(sent_games)")}
        self.assertNotIn('last_seen_at', columns)  # без миграции

    def test_initialized(self):
        self.init_db()
        database.remember_deals([make_deal('1', 80)])
        database.set_meta(database.META_INITIALIZED, '2026-09-12T00:00:00+00:00')
        meta, known = database.peek_state()
        self.assertEqual(meta, {database.META_INITIALIZED: '2026-09-12T00:00:00+00:00'})
        self.assertEqual(known, {'1': 80})


class LockTests(TempDbTestCase):
    def test_existing_lock_file_is_not_chmodded(self):
        # Файл, созданный ручным запуском от root, сервис не может chmod: EPERM
        with database.cycle_lock():
            pass
        with mock.patch('database.os.fchmod', side_effect=PermissionError(1, 'Operation not permitted')) as fchmod:
            with database.cycle_lock() as acquired:
                self.assertTrue(acquired)
        fchmod.assert_not_called()

    def test_read_only_lock_file_still_works(self):
        # Файл открывается только на чтение: lock без права записи всё равно берётся
        with database.cycle_lock():
            pass
        os.chmod(f'{self.db_path}.lock', 0o444)
        with database.cycle_lock() as first:
            with database.cycle_lock() as second:
                self.assertTrue(first)
                self.assertFalse(second)

    def test_symlink_is_not_followed(self):
        os.makedirs(os.path.dirname(self.db_path))
        victim = os.path.join(self.tmpdir, 'victim')
        with open(victim, 'w') as f:
            f.write('secret')
        os.chmod(victim, 0o600)
        os.symlink(victim, f'{self.db_path}.lock')
        with self.assertRaises(OSError):
            with database.cycle_lock():
                pass
        self.assertEqual(os.stat(victim).st_mode & 0o777, 0o600)

    def test_new_lock_file_is_readable_despite_umask(self):
        old_umask = os.umask(0o077)
        try:
            with database.cycle_lock():
                pass
        finally:
            os.umask(old_umask)
        self.assertEqual(os.stat(f'{self.db_path}.lock').st_mode & 0o777, 0o644)

    def test_second_lock_is_refused(self):
        with database.cycle_lock() as first:
            with database.cycle_lock() as second:
                self.assertTrue(first)
                self.assertFalse(second)
        with database.cycle_lock() as again:
            self.assertTrue(again)


if __name__ == '__main__':
    unittest.main()
