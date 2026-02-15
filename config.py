"""
Модуль конфигурации - загрузка переменных окружения
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Database (SQLite)
DATABASE_PATH = os.environ.get('DATABASE_PATH', 'data/steam_bot.db')

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# Настройки скидок
MIN_DISCOUNT_PERCENT = int(os.environ.get('MIN_DISCOUNT_PERCENT', '70'))


def validate_config():
    """Проверяет наличие обязательных переменных окружения"""
    missing = []

    if not TELEGRAM_BOT_TOKEN:
        missing.append('TELEGRAM_BOT_TOKEN')
    if not TELEGRAM_CHAT_ID:
        missing.append('TELEGRAM_CHAT_ID')

    if missing:
        raise EnvironmentError(
            f"Отсутствуют обязательные переменные окружения: {', '.join(missing)}"
        )

    return True
