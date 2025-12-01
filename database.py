"""
Модуль работы с базой данных PostgreSQL
Поддерживает: Neon, Supabase, Railway, ElephantSQL, Render и другие
"""
import psycopg2
from psycopg2 import sql, extensions
from contextlib import contextmanager
import logging
from datetime import datetime
from typing import Optional

from config import DATABASE_URL

logger = logging.getLogger(__name__)


def get_connection():
    """
    Создает и возвращает соединение с базой данных
    
    Returns:
        psycopg2 connection object
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except psycopg2.Error as e:
        logger.error(f"Ошибка подключения к базе данных: {e}")
        raise


@contextmanager
def get_db_cursor():
    """
    Контекстный менеджер для работы с курсором базы данных
    Автоматически управляет соединением и транзакциями
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        logger.error(f"Ошибка базы данных: {e}")
        raise
    finally:
        if conn:
            conn.close()


def init_db():
    """
    Инициализирует базу данных - создает необходимые таблицы
    """
    logger.info("Инициализация базы данных...")
    
    create_sent_games_table = """
    CREATE TABLE IF NOT EXISTS sent_games (
        app_id VARCHAR(20) PRIMARY KEY,
        title VARCHAR(500) NOT NULL,
        discount INTEGER DEFAULT 0,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    
    # Миграция: добавляем колонку discount если её нет
    add_discount_column = """
    ALTER TABLE sent_games ADD COLUMN IF NOT EXISTS discount INTEGER DEFAULT 0;
    """
    
    create_sent_events_table = """
    CREATE TABLE IF NOT EXISTS sent_events (
        event_name VARCHAR(500) PRIMARY KEY,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    
    try:
        with get_db_cursor() as cursor:
            cursor.execute(create_sent_games_table)
            cursor.execute(add_discount_column)
            cursor.execute(create_sent_events_table)
            logger.info("Таблицы успешно созданы или уже существуют")
    except psycopg2.Error as e:
        logger.error(f"Ошибка создания таблиц: {e}")
        raise


def is_game_sent(app_id: str) -> bool:
    """
    Проверяет, было ли уведомление об игре уже отправлено
    (устаревшая функция, используйте should_notify_deal)
    
    Args:
        app_id: Steam App ID игры
    
    Returns:
        True если уведомление уже отправлялось, False иначе
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM sent_games WHERE app_id = %s",
                (app_id,)
            )
            result = cursor.fetchone()
            return result is not None
    except psycopg2.Error as e:
        logger.error(f"Ошибка проверки отправки игры {app_id}: {e}")
        return False


def get_sent_game_info(app_id: str) -> Optional[tuple]:
    """
    Получает информацию о ранее отправленной игре
    
    Args:
        app_id: Steam App ID игры
    
    Returns:
        Кортеж (discount, sent_at) или None если не найдено
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT discount, sent_at FROM sent_games WHERE app_id = %s",
                (app_id,)
            )
            return cursor.fetchone()
    except psycopg2.Error as e:
        logger.error(f"Ошибка получения информации об игре {app_id}: {e}")
        return None


def should_notify_deal(app_id: str, new_discount: int, days_threshold: int = 7) -> bool:
    """
    Определяет, нужно ли отправлять уведомление о скидке
    
    Логика:
    - Если игра не отправлялась - отправить
    - Если скидка увеличилась (была -70%, стала -90%) - отправить
    - Если прошло больше days_threshold дней - отправить
    - Иначе - не отправлять
    
    Args:
        app_id: Steam App ID игры
        new_discount: новый размер скидки (число, например 90 для -90%)
        days_threshold: через сколько дней можно отправить повторно
    
    Returns:
        True если нужно отправить уведомление
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT discount, sent_at FROM sent_games WHERE app_id = %s
                """,
                (app_id,)
            )
            result = cursor.fetchone()
            
            if result is None:
                # Игра не отправлялась - отправить
                return True
            
            old_discount, sent_at = result
            old_discount = old_discount or 0
            
            # Проверяем, прошло ли достаточно дней
            from datetime import timedelta
            days_passed = (datetime.utcnow() - sent_at).days
            if days_passed >= days_threshold:
                logger.debug(f"Игра {app_id}: прошло {days_passed} дней, отправляем повторно")
                return True
            
            # Проверяем, увеличилась ли скидка
            if new_discount > old_discount:
                logger.debug(f"Игра {app_id}: скидка увеличилась {old_discount}% -> {new_discount}%")
                return True
            
            return False
            
    except psycopg2.Error as e:
        logger.error(f"Ошибка проверки скидки для {app_id}: {e}")
        return False


def mark_game_sent(app_id: str, title: str, discount: int = 0) -> None:
    """
    Отмечает игру как отправленную
    
    Args:
        app_id: Steam App ID игры
        title: название игры
        discount: размер скидки (число, например 90 для -90%)
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sent_games (app_id, title, discount, sent_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (app_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    discount = EXCLUDED.discount,
                    sent_at = EXCLUDED.sent_at
                """,
                (app_id, title, discount, datetime.utcnow())
            )
            logger.debug(f"Игра отмечена как отправленная: {title} ({app_id}) скидка -{discount}%")
    except psycopg2.Error as e:
        logger.error(f"Ошибка отметки игры как отправленной {app_id}: {e}")
        raise


def is_event_sent(event_name: str) -> bool:
    """
    Проверяет, было ли уведомление о событии уже отправлено
    
    Args:
        event_name: название события распродажи
    
    Returns:
        True если уведомление уже отправлялось, False иначе
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM sent_events WHERE event_name = %s",
                (event_name,)
            )
            result = cursor.fetchone()
            return result is not None
    except psycopg2.Error as e:
        logger.error(f"Ошибка проверки отправки события '{event_name}': {e}")
        return False


def mark_event_sent(event_name: str) -> None:
    """
    Отмечает событие как отправленное
    
    Args:
        event_name: название события распродажи
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sent_events (event_name, sent_at)
                VALUES (%s, %s)
                ON CONFLICT (event_name) DO NOTHING
                """,
                (event_name, datetime.utcnow())
            )
            logger.debug(f"Событие отмечено как отправленное: {event_name}")
    except psycopg2.Error as e:
        logger.error(f"Ошибка отметки события как отправленного '{event_name}': {e}")
        raise


def cleanup_old_records(days: int = 90) -> int:
    """
    Удаляет старые записи из базы данных (старше указанного количества дней)
    
    Args:
        days: количество дней, записи старше которых будут удалены
    
    Returns:
        количество удаленных записей
    """
    try:
        with get_db_cursor() as cursor:
            # Удаляем старые игры
            cursor.execute(
                """
                DELETE FROM sent_games 
                WHERE sent_at < CURRENT_TIMESTAMP - INTERVAL '%s days'
                """,
                (days,)
            )
            games_deleted = cursor.rowcount
            
            # Удаляем старые события
            cursor.execute(
                """
                DELETE FROM sent_events 
                WHERE sent_at < CURRENT_TIMESTAMP - INTERVAL '%s days'
                """,
                (days,)
            )
            events_deleted = cursor.rowcount
            
            total_deleted = games_deleted + events_deleted
            if total_deleted > 0:
                logger.info(f"Удалено {total_deleted} старых записей "
                          f"(игр: {games_deleted}, событий: {events_deleted})")
            return total_deleted
    except psycopg2.Error as e:
        logger.error(f"Ошибка очистки старых записей: {e}")
        return 0


if __name__ == "__main__":
    # Тестовый запуск
    logging.basicConfig(level=logging.DEBUG)
    
    print("=== Тестирование модуля базы данных ===\n")
    
    # Инициализация
    init_db()
    print("База данных инициализирована")
    
    # Тест проверки игры
    test_app_id = "test_123"
    test_title = "Test Game"
    
    print(f"\nПроверка игры {test_app_id}: {is_game_sent(test_app_id)}")
    
    # Отмечаем как отправленную
    mark_game_sent(test_app_id, test_title)
    print(f"Игра отмечена как отправленная")
    
    # Проверяем снова
    print(f"Проверка игры {test_app_id}: {is_game_sent(test_app_id)}")
