"""
Модуль конфигурации - загрузка переменных окружения
"""
import os
from dotenv import load_dotenv

# Загрузка переменных из .env файла (для локальной разработки)
load_dotenv()

# Database
DATABASE_URL = os.environ.get('DATABASE_URL')

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# Настройки скидок
# Минимальный порог скидки для уведомления (в процентах)
# Например: 70 означает скидки от -70% и выше
MIN_DISCOUNT_PERCENT = int(os.environ.get('MIN_DISCOUNT_PERCENT', '70'))

# Проверка обязательных переменных
def validate_config():
    """Проверяет наличие всех необходимых переменных окружения"""
    missing = []
    
    if not DATABASE_URL:
        missing.append('DATABASE_URL')
    if not TELEGRAM_BOT_TOKEN:
        missing.append('TELEGRAM_BOT_TOKEN')
    if not TELEGRAM_CHAT_ID:
        missing.append('TELEGRAM_CHAT_ID')
    
    if missing:
        raise EnvironmentError(
            f"Отсутствуют обязательные переменные окружения: {', '.join(missing)}"
        )
    
    return True
