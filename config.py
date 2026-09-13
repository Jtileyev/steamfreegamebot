"""
Модуль конфигурации - загрузка переменных окружения

Значения читаются один раз при импорте. Пустое значение переменной
считается отсутствующим и заменяется значением по умолчанию. Ошибки
разбора не роняют импорт: они копятся и выводятся в validate_config().
"""
import os
import re
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

_errors: List[str] = []


def _get_str(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name, '').strip()
    return value or default


def _get_int(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = _get_str(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        _errors.append(f"{name}: ожидается целое число, получено {raw!r}")
        return default
    if not min_value <= value <= max_value:
        _errors.append(f"{name}: значение {value} вне диапазона {min_value}..{max_value}")
        return default
    return value


def _get_int_list(name: str, default: List[int]) -> List[int]:
    raw = _get_str(name)
    if raw is None:
        return list(default)
    if raw.lower() == 'none':
        return []  # явный отказ от исключений
    try:
        return [int(part) for part in raw.split(',') if part.strip()]
    except ValueError:
        _errors.append(f"{name}: ожидается список целых чисел через запятую или none, получено {raw!r}")
        return list(default)


# Database (SQLite)
DATABASE_PATH = _get_str('DATABASE_PATH', 'data/steam_bot.db')

# Telegram
TELEGRAM_BOT_TOKEN = _get_str('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = _get_str('TELEGRAM_CHAT_ID')

# Поиск Steam. Регион выбирается один раз: база отправленных привязана к нему
STEAM_CC = _get_str('STEAM_CC', 'kz').lower()
if not re.fullmatch(r'[a-z]{2}', STEAM_CC):
    _errors.append(f"STEAM_CC: ожидается двухбуквенный код страны, получено {STEAM_CC!r}")
    STEAM_CC = 'kz'

# Visual Novel, Anime, Sexual Content, Hentai, Nudity. Значение none отключает исключение
DEFAULT_EXCLUDE_TAG_IDS = [3799, 4085, 12095, 9130, 6650]
EXCLUDE_TAG_IDS = _get_int_list('EXCLUDE_TAG_IDS', DEFAULT_EXCLUDE_TAG_IDS)

# Пороги отбора
MIN_DISCOUNT_PERCENT = _get_int('MIN_DISCOUNT_PERCENT', 70, 1, 100)
MIN_REVIEW_PCT = _get_int('MIN_REVIEW_PCT', 80, 0, 100)
MIN_REVIEWS = _get_int('MIN_REVIEWS', 200, 0, 10_000_000)

# Сколько страниц по 100 строк загружать за цикл. Выдача отсортирована по отзывам:
# одна страница это лучшие ~4% скидок, и порог MIN_REVIEW_PCT ниже ~92% на ней не действует
STEAM_MAX_PAGES = _get_int('STEAM_MAX_PAGES', 1, 1, 30)

# Разумный диапазон total_count. Ловит пустой или сломанный ответ и сброс фильтра
# specials. Проигнорированный фильтр языка ловит контрольный запрос в steam_search
STEAM_TOTAL_COUNT_MIN = _get_int('STEAM_TOTAL_COUNT_MIN', 50, 0, 1_000_000)
STEAM_TOTAL_COUNT_MAX = _get_int('STEAM_TOTAL_COUNT_MAX', 12000, 1, 1_000_000)

# Расписание и доставка
CHECK_INTERVAL_HOURS = _get_int('CHECK_INTERVAL_HOURS', 12, 1, 168)
MAX_MESSAGES_PER_CYCLE = _get_int('MAX_MESSAGES_PER_CYCLE', 10, 1, 100)

# Через сколько дней отсутствия в выдаче запись о скидке удаляется
FORGET_AFTER_DAYS = _get_int('FORGET_AFTER_DAYS', 3, 1, 365)

# Через сколько часов без успешного цикла отправить предупреждение в Telegram
HEARTBEAT_HOURS = _get_int('HEARTBEAT_HOURS', 24, 1, 720)


def validate_config(require_telegram: bool = True):
    """Проверяет обязательные переменные и корректность значений"""
    problems = list(_errors)

    missing = []
    if require_telegram and not TELEGRAM_BOT_TOKEN:
        missing.append('TELEGRAM_BOT_TOKEN')
    if require_telegram and not TELEGRAM_CHAT_ID:
        missing.append('TELEGRAM_CHAT_ID')
    if missing:
        problems.append(f"Отсутствуют обязательные переменные окружения: {', '.join(missing)}")

    if STEAM_TOTAL_COUNT_MIN > STEAM_TOTAL_COUNT_MAX:
        problems.append(
            f"STEAM_TOTAL_COUNT_MIN ({STEAM_TOTAL_COUNT_MIN}) больше "
            f"STEAM_TOTAL_COUNT_MAX ({STEAM_TOTAL_COUNT_MAX})"
        )

    if FORGET_AFTER_DAYS * 24 <= CHECK_INTERVAL_HOURS:
        problems.append(
            f"FORGET_AFTER_DAYS ({FORGET_AFTER_DAYS} дн.) должен быть длиннее "
            f"CHECK_INTERVAL_HOURS ({CHECK_INTERVAL_HOURS} ч), иначе скидки забываются между циклами"
        )

    if problems:
        raise EnvironmentError('; '.join(problems))

    return True
