"""Общие заготовки для тестов"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import config
import database

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')
TEST_TOKEN = '123456:TEST-TOKEN-abcdefghijklmnopqrstuv'


def load_fixture(name: str):
    with open(os.path.join(FIXTURES, name), encoding='utf-8') as f:
        return json.load(f)


def make_deal(app_id: str, discount: int = 80, title: str = None, review_pct: int = 95,
              review_count: int = 1000, tag_ids=None, page: int = 0) -> dict:
    return {
        'page': page,
        'app_id': app_id,
        'title': title or f'Game {app_id}',
        'discount': discount,
        'price_final_minor': 50000,
        'price_final': '500,00₸',
        'price_original': '2 500,00₸',
        'review_label': 'Very Positive',
        'review_pct': review_pct,
        'review_count': review_count,
        'tag_ids': tag_ids or [],
        'released': '1 Jan, 2020',
        'steam_url': f'https://store.steampowered.com/app/{app_id}',
    }


class TempDbTestCase(unittest.TestCase):
    """Отдельная база SQLite и тестовые настройки на каждый тест"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='steambot-test-')
        self.db_path = os.path.join(self.tmpdir, 'data', 'steam_bot.db')
        patches = {
            'DATABASE_PATH': self.db_path,
            'TELEGRAM_BOT_TOKEN': TEST_TOKEN,
            'TELEGRAM_CHAT_ID': '42',
            'STEAM_CC': 'kz',
            'EXCLUDE_TAG_IDS': list(config.DEFAULT_EXCLUDE_TAG_IDS),
            'MIN_DISCOUNT_PERCENT': 70,
            'MIN_REVIEW_PCT': 80,
            'MIN_REVIEWS': 200,
            'STEAM_MAX_PAGES': 1,
            'STEAM_TOTAL_COUNT_MIN': 50,
            'STEAM_TOTAL_COUNT_MAX': 12000,
            'CHECK_INTERVAL_HOURS': 12,
            'MAX_MESSAGES_PER_CYCLE': 10,
            'FORGET_AFTER_DAYS': 3,
            'HEARTBEAT_HOURS': 24,
        }
        for name, value in patches.items():
            patcher = mock.patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def init_db(self):
        database.init_db()

    def execute(self, sql: str, params=()):
        with database.get_db_cursor() as cursor:
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
