"""
Планировщик задач - запуск проверки каждые CHECK_INTERVAL_HOURS часов
"""
import logging
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
import pytz

import config
from bot import check_and_notify
from database import init_db
from logging_setup import setup_logging

logger = logging.getLogger(__name__)


def job_check_and_notify():
    """
    Обертка для задачи: исключение не должно остановить планировщик
    """
    try:
        check_and_notify()
    except Exception as e:
        logger.error(f"Ошибка выполнения задачи: {e}", exc_info=True)


def main():
    """
    Главная функция - запуск планировщика.
    Ошибка запуска завершает процесс с кодом 1, чтобы systemd перезапустил сервис.
    """
    setup_logging()
    logger.info("=== Запуск Steam Deals Bot ===")

    # Проверяем конфигурацию
    try:
        config.validate_config()
        logger.info("Конфигурация проверена успешно")
    except EnvironmentError as e:
        logger.error(f"Ошибка конфигурации: {e}")
        sys.exit(1)

    # Инициализируем базу данных
    try:
        init_db()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}", exc_info=True)
        sys.exit(1)

    scheduler = BlockingScheduler(timezone=pytz.UTC)

    # Первый запуск сразу, дальше с интервалом
    scheduler.add_job(
        job_check_and_notify,
        trigger=IntervalTrigger(hours=config.CHECK_INTERVAL_HOURS, timezone=pytz.UTC),
        id='check_deals',
        name='Проверка скидок Steam',
        replace_existing=True,
        next_run_time=datetime.now(pytz.UTC),
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    logger.info(f"Планировщик настроен (интервал: {config.CHECK_INTERVAL_HOURS} ч)")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Планировщик остановлен")
    except Exception as e:
        logger.error(f"Критическая ошибка планировщика: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
