import io
import json
import sqlite3
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

import bot
import config
import database
import steam_search
import telegram_client
from tests.helpers import TempDbTestCase, make_deal

SENT, FAILED, UNCERTAIN = telegram_client.SENT, telegram_client.FAILED, telegram_client.UNCERTAIN


class BotTestCase(TempDbTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()
        self.deals = []
        self.source_error = None
        self.total_count = 2500

        def fake_get_deals(previous_total_count=None, check_language=False, max_pages=None):
            if self.source_error:
                raise steam_search.SourceError(self.source_error)
            return steam_search.SearchResult(total_count=self.total_count, rows=100, games=list(self.deals),
                                             deals=list(self.deals))

        self.send_results = []
        patches = [
            mock.patch('bot.steam_search.get_deals', side_effect=fake_get_deals),
            mock.patch('bot.telegram_client.send_deal_notification', side_effect=self._send),
            mock.patch('bot.telegram_client.send_text', return_value=True),
            mock.patch('bot.time.sleep'),
            mock.patch.dict(bot._memory_state, {database.META_LAST_SUCCESS: None, database.META_ALERT_SENT: None}),
            mock.patch.object(bot, '_unsynced', set()),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.get_deals, self.send_deal, self.send_text = mocks[0], mocks[1], mocks[2]

    def _send(self, token, chat_id, deal):
        return self.send_results.pop(0) if self.send_results else SENT

    def sent_ids(self):
        return [c.args[2]['app_id'] for c in self.send_deal.call_args_list]

    def initialize(self, deals=()):
        """Первый цикл: текущие скидки запоминаются без отправки"""
        self.deals = list(deals)
        stats = bot.check_and_notify()
        self.assertEqual(stats.seeded, len(self.deals))
        self.send_deal.reset_mock()
        self.send_text.reset_mock()
        return stats


class CycleTests(BotTestCase):
    def test_first_run_seeds_without_sending(self):
        self.deals = [make_deal('1'), make_deal('2')]
        stats = bot.check_and_notify()
        self.assertTrue(stats.ok)
        self.assertEqual(stats.seeded, 2)
        self.send_deal.assert_not_called()
        self.send_text.assert_called_once()
        self.assertIsNotNone(database.get_meta(database.META_INITIALIZED))
        self.assertEqual(set(database.load_known_deals()), {'1', '2'})

    def test_known_deals_not_resent(self):
        self.initialize([make_deal('1'), make_deal('2')])
        stats = bot.check_and_notify()
        self.assertEqual((stats.sent, stats.known), (0, 2))
        self.send_deal.assert_not_called()

    def test_new_and_changed_deals_sent_once(self):
        self.initialize([make_deal('1', 80), make_deal('2', 80)])
        self.deals = [make_deal('1', 90), make_deal('2', 80), make_deal('3', 75)]
        stats = bot.check_and_notify()
        self.assertEqual(stats.sent, 2)
        self.assertEqual(sorted(self.sent_ids()), ['1', '3'])

        self.send_deal.reset_mock()
        bot.check_and_notify()
        self.send_deal.assert_not_called()

    def test_limit_carries_over(self):
        self.initialize()
        self.deals = [make_deal(str(i), 90 - i) for i in range(5)]
        with mock.patch.object(config, 'MAX_MESSAGES_PER_CYCLE', 2):
            first = bot.check_and_notify()
            self.assertEqual((first.sent, first.deferred), (2, 3))
            self.assertEqual(self.sent_ids(), ['0', '1'])
            bot.check_and_notify()
            bot.check_and_notify()
        self.assertEqual(self.sent_ids(), ['0', '1', '2', '3', '4'])

    def test_failed_send_is_retried_next_cycle(self):
        self.initialize()
        self.deals = [make_deal('1'), make_deal('2')]
        self.send_results = [FAILED, SENT]
        stats = bot.check_and_notify()
        self.assertEqual((stats.sent, stats.failed, stats.status), (1, 1, 'ok'))
        self.assertEqual(set(database.load_known_deals()), {'2'})

        self.send_deal.reset_mock()
        bot.check_and_notify()
        self.assertEqual(self.sent_ids(), ['1'])

    def test_failed_resend_restores_previous_discount(self):
        self.initialize([make_deal('1', 75)])
        self.deals = [make_deal('1', 90)]
        self.send_results = [FAILED]
        stats = bot.check_and_notify()
        self.assertEqual(stats.status, 'telegram_error')
        self.assertEqual(database.load_known_deals()['1']['discount'], 75)

    def test_uncertain_delivery_keeps_reservation(self):
        self.initialize()
        self.deals = [make_deal('1')]
        self.send_results = [UNCERTAIN]
        stats = bot.check_and_notify()
        self.assertEqual((stats.status, stats.uncertain, stats.failed), ('telegram_error', 1, 0))
        self.assertIn('1', database.load_known_deals())

        self.send_deal.reset_mock()
        bot.check_and_notify()
        self.send_deal.assert_not_called()

    def test_uncertain_delivery_stops_cycle(self):
        self.initialize()
        self.deals = [make_deal('1', 90), make_deal('2', 85), make_deal('3', 80)]
        self.send_results = [SENT, UNCERTAIN]
        stats = bot.check_and_notify()
        self.assertEqual((stats.status, stats.sent, stats.uncertain, stats.deferred), ('ok', 1, 1, 1))
        self.assertEqual(self.sent_ids(), ['1', '2'])

        self.send_deal.reset_mock()
        bot.check_and_notify()
        self.assertEqual(self.sent_ids(), ['3'])

    def test_reserve_failure_prevents_send(self):
        self.initialize()
        self.deals = [make_deal('1')]
        with mock.patch('bot.database.reserve_deal', side_effect=sqlite3.OperationalError('disk I/O error')):
            stats = bot.check_and_notify()
        self.assertEqual(stats.status, 'error')
        self.send_deal.assert_not_called()

    def test_counters_survive_exception_mid_cycle(self):
        self.initialize()
        self.deals = [make_deal('1', 90), make_deal('2', 80)]
        real_reserve = database.reserve_deal
        calls = []

        def reserve(deal):
            calls.append(deal['app_id'])
            if len(calls) == 2:
                raise sqlite3.OperationalError('disk I/O error')
            real_reserve(deal)

        with mock.patch('bot.database.reserve_deal', side_effect=reserve), \
                self.assertLogs('bot', level='ERROR') as logs:
            stats = bot.check_and_notify()
        self.assertEqual((stats.status, stats.sent, stats.selected), ('error', 1, 2))
        summary = [line for line in logs.output if 'Итог цикла' in line][0]
        self.assertIn('отправлено 1', summary)

    def test_source_error_is_not_empty_result_and_keeps_db(self):
        self.initialize([make_deal('1')])
        self.execute("UPDATE sent_games SET last_seen_at = datetime('now', '-10 days')")
        self.source_error = 'Steam ограничил частоту запросов (HTTP 429)'
        with self.assertLogs('bot', level='ERROR') as logs:
            stats = bot.check_and_notify()
        self.assertEqual(stats.status, 'source_error')
        self.assertIn('429', '\n'.join(logs.output))
        self.send_deal.assert_not_called()
        self.assertIn('1', database.load_known_deals())  # сбой источника не старит записи

    def test_total_count_is_remembered_and_passed(self):
        self.initialize()
        self.assertEqual(database.get_meta(database.META_LAST_TOTAL_COUNT), '2500')
        self.total_count = 2600
        bot.check_and_notify()
        self.assertEqual(self.get_deals.call_args.kwargs['previous_total_count'], 2500)
        self.assertEqual(database.get_meta(database.META_LAST_TOTAL_COUNT), '2600')

    def test_first_cycle_has_no_previous_total(self):
        bot.check_and_notify()
        self.assertIsNone(self.get_deals.call_args.kwargs['previous_total_count'])

    def test_language_check_once_a_day(self):
        start = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)

        def cycle(hours, checked):
            self.get_deals.side_effect = lambda **kw: steam_search.SearchResult(
                total_count=2500, rows=100, language_checked=kw['check_language'])
            bot.run_cycle(bot.CycleStats(started_at=start + timedelta(hours=hours)))
            self.assertEqual(self.get_deals.call_args.kwargs['check_language'], checked, hours)

        cycle(0, True)
        cycle(12, False)
        cycle(24 - 0.001, True)
        cycle(36, False)

    def test_settings_change_reseeds_only_newly_eligible(self):
        self.initialize([make_deal('1', 80)])
        self.deals = [
            make_deal('1', 80),
            make_deal('2', 90, page=1),   # видна только при двух страницах
            make_deal('3', 75, page=1),
            make_deal('4', 85, page=0),   # новая и прошла бы старые настройки
        ]
        with mock.patch.object(config, 'STEAM_MAX_PAGES', 2):
            stats = bot.check_and_notify()
            self.assertEqual((stats.seeded, stats.sent), (2, 1))
            self.assertEqual(self.sent_ids(), ['4'])
            self.assertIn('только под новые настройки: 2', self.send_text.call_args.args[2])

            self.send_deal.reset_mock()
            self.deals.append(make_deal('5', 95, page=1))
            bot.check_and_notify()
        self.assertEqual(self.sent_ids(), ['5'])

    def test_narrowing_change_keeps_backlog(self):
        self.initialize()
        self.deals = [make_deal(str(i), 90 - i) for i in range(4)]
        with mock.patch.object(config, 'MAX_MESSAGES_PER_CYCLE', 2):
            bot.check_and_notify()
            with mock.patch.object(config, 'MIN_REVIEWS', 500):
                stats = bot.check_and_notify()
        self.assertEqual((stats.seeded, stats.sent), (0, 2))
        self.assertEqual(self.sent_ids(), ['0', '1', '2', '3'])
        self.send_text.assert_not_called()

    def test_every_selection_setting_triggers_reseed(self):
        # Для каждой настройки: скидка, которая проходит только новое значение
        cases = {
            'STEAM_CC': ('us', {}),
            'STEAM_MAX_PAGES': (3, {'page': 2}),
            'MIN_DISCOUNT_PERCENT': (60, {'discount': 65}),
            'MIN_REVIEW_PCT': (70, {'review_pct': 75}),
            'MIN_REVIEWS': (100, {'review_count': 150}),
            'EXCLUDE_TAG_IDS': ([597], {'tag_ids': [3799]}),
        }
        self.initialize()
        for name, (value, attrs) in cases.items():
            with self.subTest(setting=name):
                database.set_meta(database.META_SELECTION, bot.selection_fingerprint())
                self.deals = [dict(make_deal(f'new-{name}'), **attrs)]
                self.send_deal.reset_mock()
                with mock.patch.object(config, name, value):
                    stats = bot.check_and_notify()
                self.assertEqual((stats.seeded, stats.sent), (1, 0))
                self.send_deal.assert_not_called()

    def test_forget_period_comes_from_config(self):
        self.initialize([make_deal('1'), make_deal('2')])
        self.deals = []
        self.execute("UPDATE sent_games SET last_seen_at = datetime('now', '-5 days') WHERE app_id = '1'")
        self.execute("UPDATE sent_games SET last_seen_at = datetime('now', '-8 days') WHERE app_id = '2'")
        with mock.patch.object(config, 'FORGET_AFTER_DAYS', 7):
            stats = bot.check_and_notify()
        self.assertEqual(stats.forgotten, 1)
        self.assertEqual(set(database.load_known_deals()), {'1'})

    def test_deal_forgotten_after_absence_and_sent_again(self):
        self.initialize([make_deal('1', 80)])
        self.deals = []
        bot.check_and_notify()
        self.assertIn('1', database.load_known_deals())

        self.execute("UPDATE sent_games SET last_seen_at = datetime('now', '-4 days')")
        stats = bot.check_and_notify()
        self.assertEqual(stats.forgotten, 1)

        self.deals = [make_deal('1', 80)]
        bot.check_and_notify()
        self.assertEqual(self.sent_ids(), ['1'])

    def test_present_deal_is_not_forgotten(self):
        self.initialize([make_deal('1', 80)])
        self.execute("UPDATE sent_games SET last_seen_at = datetime('now', '-4 days')")
        stats = bot.check_and_notify()
        self.assertEqual(stats.forgotten, 0)
        self.send_deal.assert_not_called()

    def test_locked_cycle_is_skipped(self):
        self.initialize()
        with database.cycle_lock():
            stats = bot.check_and_notify()
        self.assertEqual(stats.status, 'locked')
        self.assertEqual(self.get_deals.call_count, 1)  # только initialize

    def test_summary_line(self):
        self.initialize()
        self.deals = [make_deal('1')]
        with self.assertLogs('bot', level='INFO') as logs:
            bot.check_and_notify()
        summary = [line for line in logs.output if 'Итог цикла' in line]
        self.assertEqual(len(summary), 1)
        self.assertIn('отправлено 1', summary[0])


class HeartbeatTests(BotTestCase):
    def setUp(self):
        super().setUp()
        self.now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)

    def at(self, hours):
        return self.now + timedelta(hours=hours)

    def fail_cycle(self, hours_later, status='source_error'):
        bot.update_heartbeat(bot.CycleStats(status=status, error='HTTP 503'), now=self.at(hours_later))

    def succeed(self, hours_later):
        bot.update_heartbeat(bot.CycleStats(), now=self.at(hours_later))

    def test_alert_after_threshold_once_then_recovery(self):
        self.succeed(0)
        self.fail_cycle(12)
        self.send_text.assert_not_called()

        self.fail_cycle(25)
        self.send_text.assert_called_once()
        self.assertIn('25 ч', self.send_text.call_args.args[2])
        self.assertIn('HTTP 503', self.send_text.call_args.args[2])

        self.fail_cycle(37)
        self.assertEqual(self.send_text.call_count, 1)

        self.fail_cycle(50)
        self.assertEqual(self.send_text.call_count, 2)

        self.succeed(51)
        self.assertEqual(self.send_text.call_count, 3)
        self.assertIn('снова работает', self.send_text.call_args.args[2])

        self.succeed(63)
        self.assertEqual(self.send_text.call_count, 3)

    def test_repeat_alert_at_exact_multiple_of_interval(self):
        self.succeed(0)
        self.fail_cycle(24)
        self.fail_cycle(36)
        self.fail_cycle(48 - 0.001)
        self.assertEqual(self.send_text.call_count, 2)

    def test_threshold_comes_from_config(self):
        self.succeed(0)
        with mock.patch.object(config, 'HEARTBEAT_HOURS', 6):
            self.fail_cycle(5)
            self.send_text.assert_not_called()
            self.fail_cycle(7)
            self.send_text.assert_called_once()

    def test_cycle_start_time_is_used(self):
        started = self.at(0)
        bot.update_heartbeat(bot.CycleStats(started_at=started))
        self.assertEqual(database.get_meta(database.META_LAST_SUCCESS), started.isoformat(timespec='seconds'))

    def test_failed_delete_does_not_repeat_recovery(self):
        self.succeed(0)
        self.fail_cycle(25)
        with mock.patch('bot.database.delete_meta', side_effect=sqlite3.OperationalError('locked')):
            self.succeed(26)
        self.assertEqual(self.send_text.call_count, 2)
        self.succeed(38)
        self.assertEqual(self.send_text.call_count, 2)

    def test_unsynced_key_is_flushed_and_db_is_trusted_again(self):
        self.succeed(0)
        self.fail_cycle(25)
        with mock.patch('bot.database.delete_meta', side_effect=sqlite3.OperationalError('locked')):
            self.succeed(26)
        self.assertEqual(database.get_meta(database.META_ALERT_SENT), self.at(25).isoformat(timespec='seconds'))
        self.succeed(38)  # база снова пишется: несохранённое удаление повторяется
        self.assertIsNone(database.get_meta(database.META_ALERT_SENT))
        self.assertEqual(bot._unsynced, set())

        # Другой процесс записал новое состояние: этот процесс следует базе
        database.set_meta(database.META_ALERT_SENT, self.at(39).isoformat())
        self.succeed(50)
        self.assertEqual(self.send_text.call_count, 3)
        self.assertIn('снова работает', self.send_text.call_args.args[2])

    def test_failed_alert_write_keeps_throttle(self):
        self.succeed(0)
        real_set_meta = database.set_meta

        def set_meta(key, value):
            if key == database.META_ALERT_SENT:
                raise sqlite3.OperationalError('disk full')
            real_set_meta(key, value)

        with mock.patch('bot.database.set_meta', side_effect=set_meta):
            for hours in (24, 36, 48 - 0.001, 60):
                self.fail_cycle(hours)
        self.assertEqual(self.send_text.call_count, 2)

    def test_alert_at_exact_multiple_of_interval(self):
        # Циклы по 12 ч: второй неудачный цикл стартует на миллисекунды раньше 24 ч
        self.succeed(0)
        self.fail_cycle(12)
        self.fail_cycle(24 - 0.001)
        self.send_text.assert_called_once()

    def test_no_success_yet_counts_from_process_start(self):
        with mock.patch.object(bot, '_PROCESS_STARTED_AT', self.now):
            self.fail_cycle(23)
            self.send_text.assert_not_called()
            self.fail_cycle(24)
            self.send_text.assert_called_once()

    def test_state_survives_process_restart(self):
        self.succeed(0)
        self.fail_cycle(25)
        self.send_text.assert_called_once()

        bot._memory_state.update({database.META_LAST_SUCCESS: None, database.META_ALERT_SENT: None})
        with mock.patch.object(bot, '_PROCESS_STARTED_AT', self.at(30)):
            self.fail_cycle(31)
            self.assertEqual(self.send_text.call_count, 1)  # повтор не раньше 24 ч после прошлого
            self.fail_cycle(50)
            self.assertEqual(self.send_text.call_count, 2)

    def test_recovery_sent_once_across_processes(self):
        self.succeed(0)
        self.fail_cycle(25)
        # Ручной запуск в другом процессе прошёл успешно и отправил сообщение о восстановлении
        database.delete_meta(database.META_ALERT_SENT)
        database.set_meta(database.META_LAST_SUCCESS, self.at(26).isoformat())
        self.succeed(36)
        self.assertEqual(self.send_text.call_count, 1)

    def test_failed_alert_delivery_is_retried(self):
        self.succeed(0)
        self.send_text.return_value = False
        self.fail_cycle(25)
        self.assertIsNone(database.get_meta(database.META_ALERT_SENT))
        self.send_text.return_value = True
        self.fail_cycle(26)
        self.assertEqual(self.send_text.call_count, 2)
        self.assertIsNotNone(database.get_meta(database.META_ALERT_SENT))

    def test_works_when_database_is_broken(self):
        self.succeed(0)
        with mock.patch('bot.database.get_meta', side_effect=sqlite3.OperationalError('locked')), \
                mock.patch('bot.database.set_meta', side_effect=sqlite3.OperationalError('locked')):
            self.fail_cycle(30)
        self.send_text.assert_called_once()

    def test_stuck_lock_eventually_alerts(self):
        self.succeed(0)
        self.fail_cycle(25, status='locked')
        self.send_text.assert_called_once()

    def test_alert_text_is_redacted(self):
        self.succeed(0)
        stats = bot.CycleStats(status='error', error='x' * 495 + config.TELEGRAM_BOT_TOKEN)
        bot.update_heartbeat(stats, now=self.at(25))
        self.assertNotIn(config.TELEGRAM_BOT_TOKEN[:5], self.send_text.call_args.args[2])


class DryRunTests(BotTestCase):
    def run_dry(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = bot.dry_run()
        return code, out.getvalue()


    def test_dry_run_on_uninitialized_db(self):
        self.deals = [make_deal('1')]
        code, out = self.run_dry()
        self.assertEqual(code, 0)
        self.assertIn('Первый запуск', out)
        self.assertNotIn('NEW', out)
        self.send_deal.assert_not_called()
        self.send_text.assert_not_called()

    def test_dry_run_marks_new_and_does_not_write(self):
        self.initialize([make_deal('1', 80)])
        self.deals = [make_deal('1', 80), make_deal('2', 90)]
        # Пишущее соединение и блокировка цикла в dry-run запрещены
        with mock.patch('database.get_connection', side_effect=AssertionError('get_connection')), \
                mock.patch('database.cycle_lock', side_effect=AssertionError('cycle_lock')):
            code, out = self.run_dry()
        self.assertEqual(code, 0)
        self.assertIn('К отправке 1', out)
        self.assertEqual([line for line in out.splitlines() if 'NEW' in line][0].split()[-1], '(2)')
        self.send_deal.assert_not_called()

    def test_dry_run_after_settings_change(self):
        self.initialize([make_deal('1', 80)])
        self.deals = [make_deal('2', 90, review_count=100), make_deal('3', 85)]
        with mock.patch.object(config, 'MIN_REVIEWS', 50):
            code, out = self.run_dry()
        self.assertEqual(code, 0)
        self.assertIn('Настройки отбора изменились: 1 скидок', out)
        new_lines = [line for line in out.splitlines() if 'NEW' in line]
        self.assertEqual([line.split()[-1] for line in new_lines], ['(3)'])

    def test_dry_run_forces_language_control(self):
        self.get_deals.side_effect = lambda **kw: steam_search.SearchResult(
            total_count=2500, rows=100, language_checked=kw['check_language'])
        code, out = self.run_dry()
        self.assertEqual(code, 0)
        self.assertEqual(self.get_deals.call_args.kwargs, {'previous_total_count': None, 'check_language': True})
        self.assertIn('контроль фильтра языка: пройден', out)

    def test_dry_run_validates_config_without_telegram(self):
        with mock.patch.object(config, 'TELEGRAM_BOT_TOKEN', None), \
                mock.patch.object(config, '_errors', ['MIN_REVIEWS: плохо']):
            code, out = self.run_dry()
        self.assertEqual(code, 1)
        self.assertIn('MIN_REVIEWS', out)
        self.assertNotIn('TELEGRAM_BOT_TOKEN', out)
        self.get_deals.assert_not_called()



class MainTests(BotTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch('bot.setup_logging')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dry_run_never_runs_cycle(self):
        with mock.patch('bot.dry_run', return_value=0) as dry, \
                mock.patch('bot.check_and_notify') as cycle, mock.patch('bot.database.init_db') as init:
            self.assertEqual(bot.main(['--dry-run']), 0)
        dry.assert_called_once()
        cycle.assert_not_called()
        init.assert_not_called()

    def test_startup_errors_exit_1(self):
        with mock.patch('bot.config.validate_config', side_effect=EnvironmentError('нет токена')), \
                mock.patch('bot.check_and_notify') as cycle:
            self.assertEqual(bot.main([]), 1)
        cycle.assert_not_called()
        with mock.patch('bot.database.init_db', side_effect=OSError('read-only')), \
                mock.patch('bot.check_and_notify') as cycle:
            self.assertEqual(bot.main([]), 1)
        cycle.assert_not_called()

    def test_exit_code_follows_cycle_status(self):
        with mock.patch('bot.check_and_notify', return_value=bot.CycleStats(status='source_error')):
            self.assertEqual(bot.main([]), 1)
        with mock.patch('bot.check_and_notify', return_value=bot.CycleStats()):
            self.assertEqual(bot.main([]), 0)


if __name__ == '__main__':
    unittest.main()
