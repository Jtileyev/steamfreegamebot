"""
Основная логика бота - объединение всех модулей
"""
import logging
import time
import re
from typing import Tuple

import scraper
import database
import telegram_client
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, MIN_DISCOUNT_PERCENT

logger = logging.getLogger(__name__)

# Задержка между отправками сообщений (секунды)
MESSAGE_DELAY = 2

# Через сколько дней можно отправить повторно ту же игру
RESEND_DAYS_THRESHOLD = 7


def extract_discount_number(discount_str: str) -> int:
    """
    Извлекает число из строки скидки
    "-90%" -> 90, "Скидка" -> 0
    """
    if not discount_str:
        return 0
    match = re.search(r'(\d+)', discount_str)
    return int(match.group(1)) if match else 0


def check_and_notify() -> Tuple[int, int]:
    """
    Выполняет полный цикл проверки и отправки уведомлений
    
    Returns:
        Кортеж (количество отправленных скидок, количество отправленных событий)
    """
    logger.info(f"=== Начало проверки скидок (порог: -{MIN_DISCOUNT_PERCENT}%) ===")
    
    deals_sent = 0
    events_sent = 0
    
    # === Обработка скидок из r/steamdeals ===
    logger.info("Получение списка скидок из r/steamdeals...")
    try:
        deals = scraper.get_all_deals(min_discount=MIN_DISCOUNT_PERCENT)
        logger.info(f"Найдено {len(deals)} скидок от -{MIN_DISCOUNT_PERCENT}%")
        
        for deal in deals:
            app_id = deal.get('app_id')
            title = deal.get('title', 'Unknown')
            discount_str = deal.get('discount', '')
            discount_num = extract_discount_number(discount_str)
            
            if not app_id:
                logger.warning(f"Пропущена скидка без app_id: {title}")
                continue
            
            try:
                # Проверяем, нужно ли отправлять (с учётом скидки и времени)
                if not database.should_notify_deal(app_id, discount_num, RESEND_DAYS_THRESHOLD):
                    logger.debug(f"Скидка уже отправлялась: {title} ({app_id}) -{discount_num}%")
                    continue
                
                # Отправляем уведомление
                logger.info(f"Отправка уведомления о скидке: {title} ({discount_str})")
                success = telegram_client.send_deal_notification(
                    TELEGRAM_BOT_TOKEN,
                    TELEGRAM_CHAT_ID,
                    deal
                )
                
                if success:
                    # Отмечаем как отправленную с указанием скидки
                    database.mark_game_sent(app_id, title, discount_num)
                    deals_sent += 1
                    
                    # Задержка между сообщениями
                    time.sleep(MESSAGE_DELAY)
                else:
                    logger.error(f"Не удалось отправить уведомление о скидке: {title}")
            
            except Exception as e:
                logger.error(f"Ошибка обработки скидки {title}: {e}")
                continue
    
    except Exception as e:
        logger.error(f"Ошибка получения списка скидок: {e}")
    
    # === Обработка событий распродаж ===
    logger.info("Получение списка событий распродаж...")
    try:
        sale_events = scraper.get_sale_events()
        logger.info(f"Найдено {len(sale_events)} активных/предстоящих событий")
        
        for event in sale_events:
            event_name = event.get('event_name')
            
            if not event_name:
                logger.warning("Пропущено событие без названия")
                continue
            
            try:
                # Проверяем, отправляли ли уже
                if database.is_event_sent(event_name):
                    logger.debug(f"Событие уже отправлялось: {event_name}")
                    continue
                
                # Отправляем уведомление
                logger.info(f"Отправка уведомления о событии: {event_name}")
                success = telegram_client.send_sale_event_notification(
                    TELEGRAM_BOT_TOKEN,
                    TELEGRAM_CHAT_ID,
                    event
                )
                
                if success:
                    # Отмечаем как отправленное
                    database.mark_event_sent(event_name)
                    events_sent += 1
                    
                    # Задержка между сообщениями
                    time.sleep(MESSAGE_DELAY)
                else:
                    logger.error(f"Не удалось отправить уведомление о событии: {event_name}")
            
            except Exception as e:
                logger.error(f"Ошибка обработки события {event_name}: {e}")
                continue
    
    except Exception as e:
        logger.error(f"Ошибка получения списка событий: {e}")
    
    # === Периодическая очистка старых записей ===
    try:
        database.cleanup_old_records(days=90)
    except Exception as e:
        logger.warning(f"Ошибка очистки старых записей: {e}")
    
    logger.info(f"=== Проверка завершена. Отправлено: скидок - {deals_sent}, событий - {events_sent} ===")
    
    return deals_sent, events_sent


def run_single_check():
    """
    Выполняет одиночную проверку (для тестирования)
    """
    from config import validate_config
    
    # Проверяем конфигурацию
    validate_config()
    
    # Инициализируем БД
    database.init_db()
    
    # Запускаем проверку
    games, events = check_and_notify()
    
    return games, events


if __name__ == "__main__":
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=== Запуск одиночной проверки ===")
    try:
        games, events = run_single_check()
        print(f"\nРезультат: отправлено {games} игр и {events} событий")
    except Exception as e:
        print(f"Ошибка: {e}")
