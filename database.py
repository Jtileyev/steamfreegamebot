"""
Модуль работы с базой данных SQLite

Таблица sent_games хранит известные скидки: отправленные и помеченные без
отправки при первом запуске. Ключ повтора это app id вместе со скидкой.
Время хранится в UTC в формате SQLite 'YYYY-MM-DD HH:MM:SS'.

Ошибки SQLite не глушатся: сломанная база должна выглядеть как ошибка цикла,
а не как тихая неделя.
"""
import fcntl
import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Dict, Iterable, Iterator, Optional, Tuple
from urllib.parse import quote

import config

logger = logging.getLogger(__name__)

# Ожидание блокировки SQLite, секунды
BUSY_TIMEOUT = 30

# Ключи таблицы meta
META_INITIALIZED = 'initialized_at'
META_LAST_SUCCESS = 'last_success_at'
META_ALERT_SENT = 'alert_sent_at'
META_LAST_TOTAL_COUNT = 'last_total_count'
META_LANGUAGE_CHECKED_AT = 'language_checked_at'
META_SELECTION = 'selection'


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    """Создает соединение с SQLite"""
    _ensure_parent_dir(config.DATABASE_PATH)
    conn = sqlite3.connect(config.DATABASE_PATH, timeout=BUSY_TIMEOUT)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db_cursor() -> Iterator[sqlite3.Cursor]:
    """Контекстный менеджер: одна транзакция на блок"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Создает таблицы и приводит старую схему к текущей"""
    logger.info("Инициализация базы данных SQLite...")

    with get_db_cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sent_games (
                app_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                discount INTEGER DEFAULT 0,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Миграция со схемы коммита 03a11fa: не было last_seen_at
        columns = {row['name'] for row in cursor.execute("PRAGMA table_info(sent_games)")}
        if 'last_seen_at' not in columns:
            logger.info("Миграция: добавляется колонка sent_games.last_seen_at")
            cursor.execute("ALTER TABLE sent_games ADD COLUMN last_seen_at TIMESTAMP")
        cursor.execute("UPDATE sent_games SET last_seen_at = sent_at WHERE last_seen_at IS NULL")

        # События распродаж больше не отслеживаются
        cursor.execute("DROP TABLE IF EXISTS sent_events")

    logger.info("Таблицы созданы или уже существуют")


def load_known_deals() -> Dict[str, Dict]:
    """Все известные скидки: app_id -> {title, discount, sent_at, last_seen_at}"""
    with get_db_cursor() as cursor:
        cursor.execute("SELECT app_id, title, discount, sent_at, last_seen_at FROM sent_games")
        return {row['app_id']: dict(row) for row in cursor.fetchall()}


def should_notify(known: Optional[Dict], discount: int) -> bool:
    """Отправлять, если скидка новая или её процент изменился"""
    if known is None:
        return True
    return (known.get('discount') or 0) != discount


def touch_seen(app_ids: Iterable[str]) -> int:
    """Отмечает известные скидки как присутствующие в текущей выдаче"""
    ids = list(app_ids)
    if not ids:
        return 0
    with get_db_cursor() as cursor:
        cursor.executemany(
            "UPDATE sent_games SET last_seen_at = datetime('now') WHERE app_id = ?",
            [(app_id,) for app_id in ids],
        )
        return cursor.rowcount


def remember_deals(deals: Iterable[Dict]) -> None:
    """Записывает скидки как известные одной транзакцией"""
    rows = [(d['app_id'], d['title'], d['discount']) for d in deals]
    if not rows:
        return
    with get_db_cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO sent_games (app_id, title, discount, sent_at, last_seen_at)
            VALUES (?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(app_id) DO UPDATE SET
                title = excluded.title,
                discount = excluded.discount,
                sent_at = excluded.sent_at,
                last_seen_at = excluded.last_seen_at
            """,
            rows,
        )


def reserve_deal(deal: Dict) -> None:
    """Резервирует скидку до отправки: сбой записи не приведёт к дублю"""
    remember_deals([deal])


def restore_deal(app_id: str, previous: Optional[Dict]) -> None:
    """Откатывает резерв после неудачной отправки"""
    with get_db_cursor() as cursor:
        if previous is None:
            cursor.execute("DELETE FROM sent_games WHERE app_id = ?", (app_id,))
        else:
            cursor.execute(
                """
                UPDATE sent_games
                SET title = ?, discount = ?, sent_at = ?, last_seen_at = datetime('now')
                WHERE app_id = ?
                """,
                (previous['title'], previous['discount'], previous['sent_at'], app_id),
            )


def forget_missing(days: int) -> int:
    """Удаляет скидки, которых нет в выдаче дольше days дней"""
    with get_db_cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM sent_games
            WHERE datetime(COALESCE(last_seen_at, sent_at)) < datetime('now', ?)
               OR datetime(COALESCE(last_seen_at, sent_at)) IS NULL
            """,
            (f'-{int(days)} days',),
        )
        return cursor.rowcount


def get_meta(key: str) -> Optional[str]:
    with get_db_cursor() as cursor:
        cursor.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row['value'] if row else None


def set_meta(key: str, value: str) -> None:
    with get_db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def delete_meta(key: str) -> None:
    with get_db_cursor() as cursor:
        cursor.execute("DELETE FROM meta WHERE key = ?", (key,))


@contextmanager
def cycle_lock() -> Iterator[bool]:
    """
    Межпроцессная блокировка цикла проверки.

    Возвращает True, если блокировка взята, и False, если цикл уже идёт
    в другом процессе, например ручной запуск рядом с сервисом.

    flock не требует права записи, поэтому файл открывается только на чтение:
    файл, созданный ручным запуском от root, не ломает сервис. Симлинк вместо
    файла не открывается. Права меняются только у только что созданного файла.
    """
    lock_path = f"{config.DATABASE_PATH}.lock"
    _ensure_parent_dir(lock_path)
    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        fd = os.open(lock_path, flags | os.O_CREAT | os.O_EXCL, 0o644)
        os.fchmod(fd, 0o644)  # umask запускающего не должен закрыть файл от сервиса
    except FileExistsError:
        fd = os.open(lock_path, flags)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def peek_state() -> Tuple[Dict[str, str], Dict[str, int]]:
    """
    Состояние базы без записи и без миграции, для --dry-run.

    Returns:
        (meta: ключ -> значение, app_id -> процент скидки)
    """
    if not os.path.exists(config.DATABASE_PATH):
        return {}, {}
    uri = f"file:{quote(os.path.abspath(config.DATABASE_PATH))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        meta: Dict[str, str] = {}
        if 'meta' in tables:
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        known: Dict[str, int] = {}
        if 'sent_games' in tables:
            known = {row[0]: row[1] or 0 for row in conn.execute("SELECT app_id, discount FROM sent_games")}
        return meta, known
    finally:
        conn.close()
