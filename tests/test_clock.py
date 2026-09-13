import sqlite3
import unittest
from unittest import mock

import clock


class StartupTests(unittest.TestCase):
    """Ошибка запуска завершает процесс с кодом 1, чтобы systemd перезапустил сервис"""

    def setUp(self):
        patcher = mock.patch('clock.setup_logging')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_config_error_exits_1(self):
        with mock.patch('clock.config.validate_config', side_effect=EnvironmentError('нет токена')), \
                mock.patch('clock.BlockingScheduler') as scheduler:
            with self.assertRaises(SystemExit) as ctx:
                clock.main()
        self.assertEqual(ctx.exception.code, 1)
        scheduler.assert_not_called()

    def test_database_error_exits_1(self):
        with mock.patch('clock.config.validate_config'), \
                mock.patch('clock.init_db', side_effect=sqlite3.OperationalError('readonly')), \
                mock.patch('clock.BlockingScheduler') as scheduler:
            with self.assertRaises(SystemExit) as ctx:
                clock.main()
        self.assertEqual(ctx.exception.code, 1)
        scheduler.assert_not_called()

    def test_scheduler_crash_exits_1(self):
        with mock.patch('clock.config.validate_config'), mock.patch('clock.init_db'), \
                mock.patch('clock.BlockingScheduler') as scheduler:
            scheduler.return_value.start.side_effect = RuntimeError('boom')
            with self.assertRaises(SystemExit) as ctx:
                clock.main()
        self.assertEqual(ctx.exception.code, 1)
        job = scheduler.return_value.add_job.call_args.kwargs
        self.assertIsNotNone(job['next_run_time'])  # первый цикл сразу после старта


if __name__ == '__main__':
    unittest.main()
