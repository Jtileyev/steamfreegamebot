import importlib
import os
import unittest
from unittest import mock

import config


def reload_config(env):
    with mock.patch.dict(os.environ, env, clear=True), mock.patch('dotenv.load_dotenv'):
        return importlib.reload(config)


class ConfigTests(unittest.TestCase):
    def tearDown(self):
        importlib.reload(config)

    def test_defaults(self):
        cfg = reload_config({'TELEGRAM_BOT_TOKEN': 't', 'TELEGRAM_CHAT_ID': '1'})
        self.assertEqual(cfg.DATABASE_PATH, 'data/steam_bot.db')
        self.assertEqual(cfg.STEAM_CC, 'kz')
        self.assertEqual((cfg.MIN_DISCOUNT_PERCENT, cfg.MIN_REVIEW_PCT, cfg.MIN_REVIEWS), (70, 80, 200))
        self.assertEqual(cfg.EXCLUDE_TAG_IDS, [3799, 4085, 12095, 9130, 6650])
        self.assertEqual((cfg.STEAM_MAX_PAGES, cfg.STEAM_TOTAL_COUNT_MIN, cfg.STEAM_TOTAL_COUNT_MAX), (1, 50, 12000))
        self.assertEqual((cfg.CHECK_INTERVAL_HOURS, cfg.MAX_MESSAGES_PER_CYCLE, cfg.FORGET_AFTER_DAYS,
                          cfg.HEARTBEAT_HOURS), (12, 10, 3, 24))
        self.assertTrue(cfg.validate_config())

    def test_empty_values_fall_back_to_defaults(self):
        cfg = reload_config({'TELEGRAM_BOT_TOKEN': 't', 'TELEGRAM_CHAT_ID': '1',
                             'DATABASE_PATH': '', 'MIN_DISCOUNT_PERCENT': '', 'STEAM_CC': ' '})
        self.assertEqual(cfg.DATABASE_PATH, 'data/steam_bot.db')
        self.assertEqual(cfg.MIN_DISCOUNT_PERCENT, 70)
        self.assertEqual(cfg.STEAM_CC, 'kz')
        self.assertTrue(cfg.validate_config())

    def test_empty_exclude_list_keeps_defaults(self):
        cfg = reload_config({'EXCLUDE_TAG_IDS': ''})
        self.assertEqual(cfg.EXCLUDE_TAG_IDS, [3799, 4085, 12095, 9130, 6650])

    def test_none_disables_exclusion(self):
        cfg = reload_config({'EXCLUDE_TAG_IDS': 'None'})
        self.assertEqual(cfg.EXCLUDE_TAG_IDS, [])

    def test_telegram_optional_for_dry_run(self):
        cfg = reload_config({})
        self.assertTrue(cfg.validate_config(require_telegram=False))
        with self.assertRaisesRegex(EnvironmentError, 'TELEGRAM_BOT_TOKEN'):
            cfg.validate_config()

    def test_forget_period_must_exceed_interval(self):
        cfg = reload_config({'FORGET_AFTER_DAYS': '1', 'CHECK_INTERVAL_HOURS': '24'})
        with self.assertRaisesRegex(EnvironmentError, 'FORGET_AFTER_DAYS'):
            cfg.validate_config(require_telegram=False)

    def test_custom_values(self):
        cfg = reload_config({'TELEGRAM_BOT_TOKEN': 't', 'TELEGRAM_CHAT_ID': '1', 'STEAM_CC': 'US',
                             'MIN_REVIEWS': '50', 'EXCLUDE_TAG_IDS': '597, 493'})
        self.assertEqual(cfg.STEAM_CC, 'us')
        self.assertEqual(cfg.MIN_REVIEWS, 50)
        self.assertEqual(cfg.EXCLUDE_TAG_IDS, [597, 493])

    def test_invalid_values_reported_not_crashing(self):
        cfg = reload_config({'MIN_DISCOUNT_PERCENT': 'abc', 'MIN_REVIEW_PCT': '150', 'STEAM_CC': 'kaz',
                             'EXCLUDE_TAG_IDS': '1,x'})
        with self.assertRaises(EnvironmentError) as ctx:
            cfg.validate_config()
        message = str(ctx.exception)
        for name in ('MIN_DISCOUNT_PERCENT', 'MIN_REVIEW_PCT', 'STEAM_CC', 'EXCLUDE_TAG_IDS',
                     'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
            self.assertIn(name, message)

    def test_total_count_range_order(self):
        cfg = reload_config({'TELEGRAM_BOT_TOKEN': 't', 'TELEGRAM_CHAT_ID': '1',
                             'STEAM_TOTAL_COUNT_MIN': '5000', 'STEAM_TOTAL_COUNT_MAX': '100'})
        with self.assertRaisesRegex(EnvironmentError, 'STEAM_TOTAL_COUNT_MIN'):
            cfg.validate_config()


if __name__ == '__main__':
    unittest.main()
