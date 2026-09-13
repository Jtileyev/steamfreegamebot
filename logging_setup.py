"""
Настройка логирования с вырезанием токена бота из любых записей
"""
import logging

import config


class RedactingFormatter(logging.Formatter):
    """Заменяет токен бота на *** в итоговой строке, включая traceback"""

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        token = config.TELEGRAM_BOT_TOKEN
        return text.replace(token, '***') if token else text


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    # Отключаем избыточное логирование сторонних библиотек.
    # urllib3 на уровне DEBUG пишет URL запроса вместе с токеном
    logging.getLogger('apscheduler').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
