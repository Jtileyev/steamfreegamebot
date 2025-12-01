"""
Планировщик задач - запуск проверки каждые 12 часов
"""
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
import pytz

from bot import check_and_notify
from database import init_db
from config import validate_config

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Отключаем избыточное логирование от APScheduler
logging.getLogger('apscheduler').setLevel(logging.WARNING)


def job_check_and_notify():
    """
    Обертка для задачи с обработкой ошибок
    """
    try:
        logger.info("Запуск задачи проверки бесплатных игр и событий")
        games, events = check_and_notify()
        logger.info(f"Задача завершена. Отправлено: игр - {games}, событий - {events}")
    except Exception as e:
        logger.error(f"Ошибка выполнения задачи: {e}", exc_info=True)


def main():
    """
    Главная функция - запуск планировщика
    """
    logger.info("=== Запуск Steam Free Game Bot ===")
    
    # Проверяем конфигурацию
    try:
        validate_config()
        logger.info("Конфигурация проверена успешно")
    except EnvironmentError as e:
        logger.error(f"Ошибка конфигурации: {e}")
        return
    
    # Инициализируем базу данных
    try:
        init_db()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")
        return
    
    # Создаем планировщик
    scheduler = BlockingScheduler(timezone=pytz.UTC)
    
    # Добавляем задачу с интервалом 12 часов
    scheduler.add_job(
        job_check_and_notify,
        trigger=IntervalTrigger(hours=12),
        id='check_free_games',
        name='Проверка бесплатных игр и событий',
        replace_existing=True
    )
    
    logger.info("Планировщик настроен (интервал: 12 часов)")
    
    # Немедленный запуск при старте
    logger.info("Выполняем первоначальную проверку...")
    job_check_and_notify()
    
    # Запускаем планировщик
    try:
        logger.info("Запуск планировщика...")
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Планировщик остановлен")
    except Exception as e:
        logger.error(f"Критическая ошибка планировщика: {e}", exc_info=True)


if __name__ == "__main__":
    main()
