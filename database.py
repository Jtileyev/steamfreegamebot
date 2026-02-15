"""
Модуль работы с базой данных SQLite
"""
import sqlite3
import os
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from config import DATABASE_PATH

logger = logging.getLogger(__name__)


def get_connection():
    """Создает соединение с SQLite"""
    os.makedirs(os.path.dirname(DATABASE_PATH) if os.path.dirname(DATABASE_PATH) else '.', exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db_cursor():
    """Контекстный менеджер для работы с курсором"""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except sqlite3.Error as e:
        if conn:
            conn.rollback()
        logger.error(f"Ошибка базы данных: {e}")
        raise
    finally:
        if conn:
            conn.close()


def init_db():
    """Создает таблицы"""
    logger.info("Инициализация базы данных SQLite...")

    create_sent_games = """
    CREATE TABLE IF NOT EXISTS sent_games (
        app_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        discount INTEGER DEFAULT 0,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    create_sent_events = """
    CREATE TABLE IF NOT EXISTS sent_events (
        event_name TEXT PRIMARY KEY,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    try:
        with get_db_cursor() as cursor:
            cursor.execute(create_sent_games)
            cursor.execute(create_sent_events)
            logger.info("Таблицы созданы или уже существуют")
    except sqlite3.Error as e:
        logger.error(f"Ошибка создания таблиц: {e}")
        raise


def is_game_sent(app_id: str) -> bool:
    """Проверяет, отправлялось ли уведомление об игре"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT 1 FROM sent_games WHERE app_id = ?", (app_id,))
            return cursor.fetchone() is not None
    except sqlite3.Error as e:
        logger.error(f"Ошибка проверки игры {app_id}: {e}")
        return False


def should_notify_deal(app_id: str, new_discount: int, days_threshold: int = 7) -> bool:
    """
    Нужно ли отправлять уведомление:
    - Игра не отправлялась — да
    - Скидка увеличилась — да
    - Прошло больше days_threshold дней — да
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT discount, sent_at FROM sent_games WHERE app_id = ?",
                (app_id,)
            )
            result = cursor.fetchone()

            if result is None:
                return True

            old_discount = result['discount'] or 0
            sent_at = datetime.fromisoformat(result['sent_at']) if isinstance(result['sent_at'], str) else result['sent_at']

            days_passed = (datetime.utcnow() - sent_at).days
            if days_passed >= days_threshold:
                return True

            if new_discount > old_discount:
                return True

            return False

    except sqlite3.Error as e:
        logger.error(f"Ошибка проверки скидки для {app_id}: {e}")
        return False


def mark_game_sent(app_id: str, title: str, discount: int = 0) -> None:
    """Отмечает игру как отправленную"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sent_games (app_id, title, discount, sent_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(app_id) DO UPDATE SET
                    title = excluded.title,
                    discount = excluded.discount,
                    sent_at = excluded.sent_at
                """,
                (app_id, title, discount, datetime.utcnow().isoformat())
            )
    except sqlite3.Error as e:
        logger.error(f"Ошибка отметки игры {app_id}: {e}")
        raise


def is_event_sent(event_name: str) -> bool:
    """Проверяет, отправлялось ли событие"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT 1 FROM sent_events WHERE event_name = ?", (event_name,))
            return cursor.fetchone() is not None
    except sqlite3.Error as e:
        logger.error(f"Ошибка проверки события '{event_name}': {e}")
        return False


def mark_event_sent(event_name: str) -> None:
    """Отмечает событие как отправленное"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sent_events (event_name, sent_at)
                VALUES (?, ?)
                ON CONFLICT(event_name) DO NOTHING
                """,
                (event_name, datetime.utcnow().isoformat())
            )
    except sqlite3.Error as e:
        logger.error(f"Ошибка отметки события '{event_name}': {e}")
        raise


def cleanup_old_records(days: int = 90) -> int:
    """Удаляет записи старше указанного количества дней"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "DELETE FROM sent_games WHERE sent_at < datetime('now', ?)",
                (f'-{days} days',)
            )
            games_deleted = cursor.rowcount

            cursor.execute(
                "DELETE FROM sent_events WHERE sent_at < datetime('now', ?)",
                (f'-{days} days',)
            )
            events_deleted = cursor.rowcount

            total = games_deleted + events_deleted
            if total > 0:
                logger.info(f"Удалено {total} старых записей (игр: {games_deleted}, событий: {events_deleted})")
            return total
    except sqlite3.Error as e:
        logger.error(f"Ошибка очистки старых записей: {e}")
        return 0
