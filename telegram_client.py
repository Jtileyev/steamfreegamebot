"""
Модуль для отправки сообщений в Telegram
"""
import requests
import logging
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Telegram API endpoint
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

# Спецсимволы MarkdownV2, которые нужно экранировать
MARKDOWN_V2_SPECIAL_CHARS = r'_*[]()~`>#+-=|{}.!'


def escape_markdown(text: str) -> str:
    """
    Экранирует спецсимволы для MarkdownV2
    
    Args:
        text: текст для экранирования
    
    Returns:
        экранированный текст
    """
    if not text:
        return ""
    
    # Экранируем каждый спецсимвол
    for char in MARKDOWN_V2_SPECIAL_CHARS:
        text = text.replace(char, f'\\{char}')
    
    return text


def send_message(bot_token: str, chat_id: str, text: str, 
                 parse_mode: str = "MarkdownV2") -> Dict:
    """
    Отправляет сообщение через Telegram Bot API
    
    Args:
        bot_token: токен бота
        chat_id: ID чата для отправки
        text: текст сообщения
        parse_mode: режим форматирования (MarkdownV2, HTML, Markdown)
    
    Returns:
        ответ от Telegram API
    """
    url = TELEGRAM_API_URL.format(token=bot_token)
    
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": False
    }
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        result = response.json()
        
        if not result.get("ok"):
            logger.error(f"Ошибка Telegram API: {result.get('description')}")
            
            # Если ошибка в форматировании, пробуем отправить без parse_mode
            if "can't parse" in result.get("description", "").lower():
                logger.info("Повторная попытка отправки без форматирования")
                payload["parse_mode"] = None
                response = requests.post(url, json=payload, timeout=30)
                result = response.json()
        
        return result
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка отправки сообщения в Telegram: {e}")
        return {"ok": False, "error": str(e)}


def format_free_game_message(game_data: Dict) -> str:
    """
    Форматирует сообщение о бесплатной игре
    
    Args:
        game_data: словарь с данными об игре
            - title: название игры
            - steam_url: ссылка на Steam
            - end_date: дата окончания акции (опционально)
    
    Returns:
        отформатированное сообщение для Telegram
    """
    title = escape_markdown(game_data.get('title', 'Неизвестная игра'))
    steam_url = game_data.get('steam_url', '')
    end_date = game_data.get('end_date', '')
    
    message_parts = [
        "🎮 *Бесплатная игра в Steam\\!*",
        "",
        f"*{title}*",
        f"🔗 [Получить в Steam]({steam_url})"
    ]
    
    if end_date:
        end_date_escaped = escape_markdown(end_date)
        message_parts.append(f"⏰ До: {end_date_escaped}")
    
    return "\n".join(message_parts)


def format_deal_message(game_data: Dict) -> str:
    """
    Форматирует сообщение о скидке на игру
    
    Args:
        game_data: словарь с данными об игре
            - title: название игры
            - steam_url: ссылка на Steam
            - discount: размер скидки (-70%, -90% и т.д.)
            - reddit_score: рейтинг поста на Reddit (опционально)
            - reddit_url: ссылка на пост Reddit (опционально)
    
    Returns:
        отформатированное сообщение для Telegram
    """
    title = escape_markdown(game_data.get('title', 'Неизвестная игра'))
    steam_url = game_data.get('steam_url', '')
    discount = game_data.get('discount', 'Скидка')
    reddit_score = game_data.get('reddit_score', 0)
    reddit_url = game_data.get('reddit_url', '')
    
    # Экранируем скидку
    discount_escaped = escape_markdown(discount)
    
    # Определяем эмодзи в зависимости от размера скидки
    discount_num = 0
    match = re.search(r'(\d+)', discount)
    if match:
        discount_num = int(match.group(1))
    
    if discount_num >= 90:
        emoji = "🔥🔥🔥"
    elif discount_num >= 80:
        emoji = "🔥🔥"
    elif discount_num >= 70:
        emoji = "🔥"
    else:
        emoji = "💰"
    
    message_parts = [
        f"{emoji} *Скидка {discount_escaped} в Steam\\!*",
        "",
        f"*{title}*",
        f"🔗 [Купить в Steam]({steam_url})"
    ]
    
    # Добавляем рейтинг Reddit если он высокий
    if reddit_score and reddit_score > 50:
        message_parts.append(f"👍 Reddit: {reddit_score}")
    
    if reddit_url:
        message_parts.append(f"💬 [Обсуждение]({reddit_url})")
    
    return "\n".join(message_parts)


def format_sale_event_message(event_data: Dict) -> str:
    """
    Форматирует сообщение о Steam Sale Event
    
    Args:
        event_data: словарь с данными о событии
            - event_name: название события
            - start_date: дата начала
            - end_date: дата окончания
            - steamdb_url: ссылка на SteamDB
    
    Returns:
        отформатированное сообщение для Telegram
    """
    event_name = escape_markdown(event_data.get('event_name', 'Неизвестное событие'))
    start_date = event_data.get('start_date', '')
    end_date = event_data.get('end_date', '')
    steamdb_url = event_data.get('steamdb_url', '')
    
    # Формируем строку с датами
    dates_str = ""
    if start_date and end_date:
        start_escaped = escape_markdown(start_date)
        end_escaped = escape_markdown(end_date)
        dates_str = f"{start_escaped} \\- {end_escaped}"
    elif start_date:
        dates_str = escape_markdown(start_date)
    elif end_date:
        dates_str = f"До {escape_markdown(end_date)}"
    
    message_parts = [
        "🏷️ *Steam Sale Event*",
        "",
        f"*{event_name}*"
    ]
    
    if dates_str:
        message_parts.append(f"📅 {dates_str}")
    
    if steamdb_url:
        message_parts.append(f"🔗 [Подробнее на SteamDB]({steamdb_url})")
    
    # Если событие активно
    if event_data.get('is_active'):
        message_parts.insert(0, "🔥 *АКТИВНО СЕЙЧАС\\!*")
    
    return "\n".join(message_parts)


def send_free_game_notification(bot_token: str, chat_id: str, 
                                game_data: Dict) -> bool:
    """
    Отправляет уведомление о бесплатной игре
    
    Args:
        bot_token: токен бота
        chat_id: ID чата
        game_data: данные об игре
    
    Returns:
        True если отправка успешна, False иначе
    """
    message = format_free_game_message(game_data)
    result = send_message(bot_token, chat_id, message)
    
    if result.get("ok"):
        logger.info(f"Уведомление об игре '{game_data.get('title')}' отправлено")
        return True
    else:
        logger.error(f"Не удалось отправить уведомление об игре: {result}")
        return False


def send_sale_event_notification(bot_token: str, chat_id: str, 
                                 event_data: Dict) -> bool:
    """
    Отправляет уведомление о распродаже
    
    Args:
        bot_token: токен бота
        chat_id: ID чата
        event_data: данные о событии
    
    Returns:
        True если отправка успешна, False иначе
    """
    message = format_sale_event_message(event_data)
    result = send_message(bot_token, chat_id, message)
    
    if result.get("ok"):
        logger.info(f"Уведомление о событии '{event_data.get('event_name')}' отправлено")
        return True
    else:
        logger.error(f"Не удалось отправить уведомление о событии: {result}")
        return False


def send_deal_notification(bot_token: str, chat_id: str, 
                           game_data: Dict) -> bool:
    """
    Отправляет уведомление о скидке
    
    Args:
        bot_token: токен бота
        chat_id: ID чата
        game_data: данные об игре со скидкой
    
    Returns:
        True если отправка успешна, False иначе
    """
    message = format_deal_message(game_data)
    result = send_message(bot_token, chat_id, message)
    
    if result.get("ok"):
        logger.info(f"Уведомление о скидке '{game_data.get('title')}' отправлено")
        return True
    else:
        logger.error(f"Не удалось отправить уведомление о скидке: {result}")
        return False


if __name__ == "__main__":
    # Тестовый запуск
    logging.basicConfig(level=logging.DEBUG)
    
    print("=== Тестирование форматирования сообщений ===\n")
    
    # Тестовые данные
    test_game = {
        'title': 'Test Game: The Adventure!',
        'steam_url': 'https://store.steampowered.com/app/12345',
        'end_date': '15 Dec 2024'
    }
    
    test_event = {
        'event_name': 'Steam Winter Sale 2024',
        'start_date': '19 Dec 2024',
        'end_date': '2 Jan 2025',
        'steamdb_url': 'https://steamdb.info/sales/winter-sale-2024/',
        'is_active': True
    }
    
    print("Сообщение о бесплатной игре:")
    print(format_free_game_message(test_game))
    print()
    
    print("Сообщение о распродаже:")
    print(format_sale_event_message(test_event))
