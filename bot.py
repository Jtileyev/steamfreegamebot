"""
Основная логика бота: один цикл проверки скидок

Цикл: запрос к поиску Steam, отбор по порогам, сравнение с известными
скидками, отправка в Telegram не больше MAX_MESSAGES_PER_CYCLE сообщений,
удаление записей о скидках, которые пропали из выдачи.
"""
import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import config
import database
import steam_search
import telegram_client
from logging_setup import setup_logging

logger = logging.getLogger(__name__)

# Задержка между отправками сообщений (секунды)
MESSAGE_DELAY = 2

# Сколько символов текста ошибки попадает в предупреждение heartbeat
MAX_ERROR_TEXT = 500

# Допуск heartbeat: циклы идут строго по расписанию, и порог, кратный интервалу,
# не должен зависеть от миллисекунд задержки запуска
HEARTBEAT_SLACK_HOURS = 0.25

# Как часто проверять, что Steam не игнорирует фильтр языка
LANGUAGE_CHECK_HOURS = 24


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Отсчёт heartbeat, пока в базе нет ни одного успешного цикла
_PROCESS_STARTED_AT = _now()

# Копия состояния heartbeat на случай, если база недоступна
_memory_state: Dict[str, Optional[datetime]] = {
    database.META_LAST_SUCCESS: None,
    database.META_ALERT_SENT: None,
}
# Ключи, чья последняя запись в базу не удалась: для них верна копия в памяти
_unsynced: Set[str] = set()


@dataclass
class CycleStats:
    # ok, source_error, telegram_error, error, locked
    status: str = 'ok'
    error: Optional[str] = None
    started_at: datetime = field(default_factory=_now)
    pages: int = 0
    total_count: int = 0
    parsed: int = 0
    selected: int = 0
    known: int = 0
    sent: int = 0
    uncertain: int = 0
    deferred: int = 0
    failed: int = 0
    seeded: int = 0
    forgotten: int = 0

    @property
    def ok(self) -> bool:
        return self.status == 'ok'

    def summary(self) -> str:
        text = (
            f"Итог цикла [{self.status}]: разобрано {self.parsed} из выдачи {self.total_count} "
            f"(страниц {self.pages}), прошло фильтр {self.selected}, отправлено {self.sent}, "
            f"уже известно {self.known}, отложено {self.deferred}, помечено без отправки {self.seeded}, "
            f"забыто {self.forgotten}, ошибок отправки {self.failed}, доставка неизвестна {self.uncertain}"
        )
        if self.error:
            text += f". Ошибка: {self.error}"
        return text


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        logger.warning(f"Некорректная метка времени в базе: {value!r}")
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def selection_fingerprint() -> str:
    """Настройки, от которых зависит состав отобранных скидок"""
    return json.dumps({
        'cc': config.STEAM_CC,
        'pages': config.STEAM_MAX_PAGES,
        'min_discount': config.MIN_DISCOUNT_PERCENT,
        'min_review_pct': config.MIN_REVIEW_PCT,
        'min_reviews': config.MIN_REVIEWS,
        'exclude_tags': sorted(config.EXCLUDE_TAG_IDS),
    }, sort_keys=True)


def previously_selected_ids(games: List[Dict], stored_selection: Optional[str]) -> Optional[Set[str]]:
    """
    app_id скидок, которые прошли бы прежние настройки отбора на той же выдаче.
    None, если сравнить нельзя: настройки не сохранены или сменился регион.
    """
    try:
        old = json.loads(stored_selection) if stored_selection else None
        if not isinstance(old, dict) or old.get('cc') != config.STEAM_CC:
            return None
        visible = [g for g in games if g.get('page', 0) < int(old['pages'])]
        deals = steam_search.select_deals(
            visible,
            min_discount=int(old['min_discount']),
            min_review_pct=int(old['min_review_pct']),
            min_reviews=int(old['min_reviews']),
            exclude_tags=[int(t) for t in old['exclude_tags']],
        )
    except (KeyError, TypeError, ValueError):
        return None
    return {d['app_id'] for d in deals}


def _send_service_message(text: str) -> bool:
    text = telegram_client.redact(text, config.TELEGRAM_BOT_TOKEN)
    ok = telegram_client.send_text(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, text)
    if not ok:
        logger.error("Не удалось отправить служебное сообщение в Telegram")
    return ok


def run_cycle(stats: CycleStats) -> CycleStats:
    """
    Один цикл без блокировки и heartbeat. Счётчики пишутся в stats по ходу,
    чтобы итог был виден и после исключения.

    Недоступность Steam возвращается статусом source_error. Ошибки базы
    пробрасываются наружу: сломанная база это ошибка цикла.
    """
    logger.info(
        f"=== Начало проверки скидок: регион {config.STEAM_CC}, страниц до {config.STEAM_MAX_PAGES}, "
        f"скидка от {config.MIN_DISCOUNT_PERCENT}%, отзывов от {config.MIN_REVIEWS} "
        f"и от {config.MIN_REVIEW_PCT}% положительных ==="
    )

    previous_total = _parse_int(database.get_meta(database.META_LAST_TOTAL_COUNT))
    last_language_check = _parse_time(database.get_meta(database.META_LANGUAGE_CHECKED_AT))
    check_language = (last_language_check is None or _hours_between(stats.started_at, last_language_check)
                      >= LANGUAGE_CHECK_HOURS - HEARTBEAT_SLACK_HOURS)
    try:
        result = steam_search.get_deals(previous_total_count=previous_total, check_language=check_language)
    except steam_search.SourceError as e:
        stats.status = 'source_error'
        stats.error = str(e)
        logger.error(f"Источник скидок недоступен: {e}")
        return stats

    stats.pages = result.pages
    stats.total_count = result.total_count
    stats.parsed = len(result.games)
    stats.selected = len(result.deals)
    deals = result.deals
    database.set_meta(database.META_LAST_TOTAL_COUNT, str(result.total_count))
    if result.language_checked:
        database.set_meta(database.META_LANGUAGE_CHECKED_AT, stats.started_at.isoformat(timespec='seconds'))

    known = database.load_known_deals()
    database.touch_seen(d['app_id'] for d in deals if d['app_id'] in known)

    pending = [d for d in deals if database.should_notify(known.get(d['app_id']), d['discount'])]
    initialized = database.get_meta(database.META_INITIALIZED) is not None
    selection = selection_fingerprint()
    stored_selection = database.get_meta(database.META_SELECTION)

    if not initialized:
        # Первый запуск: запомнить текущие скидки, не публикуя их
        database.remember_deals(deals)
        database.set_meta(database.META_SELECTION, selection)
        database.set_meta(database.META_INITIALIZED, _now().isoformat(timespec='seconds'))
        stats.seeded = len(pending)
        logger.info(f"Первый запуск: {len(deals)} текущих скидок помечены известными без отправки")
        _send_service_message(
            f"✅ Бот скидок Steam запущен. Сейчас подходящих скидок: {len(deals)}. "
            f"Они отмечены как известные, уведомления будут приходить о новых и изменившихся скидках."
        )
    else:
        stats.known = len(deals) - len(pending)

        if stored_selection != selection:
            # Смена настроек отбора: скидки, которые подходят только под новые настройки,
            # не рассылаются, иначе в чат уйдут десятки старых скидок
            old_ids = previously_selected_ids(result.games, stored_selection)
            newly_eligible = [d for d in pending if old_ids is None or d['app_id'] not in old_ids]
            database.remember_deals(newly_eligible)
            database.set_meta(database.META_SELECTION, selection)
            stats.seeded = len(newly_eligible)
            seeded_ids = {d['app_id'] for d in newly_eligible}
            pending = [d for d in pending if d['app_id'] not in seeded_ids]
            logger.info(f"Настройки отбора изменились: {stats.seeded} скидок, подходящих только под новые "
                        f"настройки, помечены известными без отправки")
            if stats.seeded:
                _send_service_message(
                    f"⚙️ Настройки отбора изменились. Скидок, которые подходят только под новые настройки: "
                    f"{stats.seeded}. Они отмечены как известные без отправки."
                )

        to_send = pending[:config.MAX_MESSAGES_PER_CYCLE]
        stats.deferred = len(pending) - len(to_send)
        if not pending:
            logger.info("Новых скидок нет")
        if stats.deferred:
            logger.info(f"Лимит {config.MAX_MESSAGES_PER_CYCLE} сообщений за цикл: "
                        f"{stats.deferred} скидок перенесены на следующий цикл")

        for index, deal in enumerate(to_send):
            if index:
                time.sleep(MESSAGE_DELAY)

            previous = known.get(deal['app_id'])
            # Резерв до отправки: если запись упадёт, сообщение не уйдёт и дубля не будет
            database.reserve_deal(deal)

            logger.info(f"Отправка уведомления: {deal['title']} ({deal['app_id']}) -{deal['discount']}%")
            outcome = telegram_client.send_deal_notification(
                config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, deal
            )
            if outcome == telegram_client.SENT:
                stats.sent += 1
            elif outcome == telegram_client.UNCERTAIN:
                # Сообщение могло дойти: резерв остаётся, повтора не будет. Остальные
                # переносятся, чтобы зависший Telegram не съел все скидки цикла
                stats.uncertain += 1
                rest = len(to_send) - index - 1
                if rest:
                    stats.deferred += rest
                    logger.warning(f"Доставка неизвестна, {rest} скидок перенесены на следующий цикл")
                break
            else:
                stats.failed += 1
                database.restore_deal(deal['app_id'], previous)

        if not stats.sent and (stats.failed or stats.uncertain):
            stats.status = 'telegram_error'
            stats.error = (f"ни одно сообщение не подтверждено: ошибок {stats.failed}, "
                           f"доставка неизвестна {stats.uncertain}")

    stats.forgotten = database.forget_missing(config.FORGET_AFTER_DAYS)
    if stats.forgotten:
        logger.info(f"Забыто {stats.forgotten} скидок, которых нет в выдаче дольше {config.FORGET_AFTER_DAYS} дн.")

    return stats


def _read_state_time(key: str) -> Optional[datetime]:
    """
    Время из meta. Копия в памяти используется, если база не читается или
    последняя запись этого ключа в базу не удалась
    """
    if key in _unsynced:
        return _memory_state.get(key)
    try:
        return _parse_time(database.get_meta(key))
    except Exception as e:
        logger.warning(f"Не удалось прочитать {key} из базы: {type(e).__name__}: {e}")
        return _memory_state.get(key)


def _write_state_time(key: str, value: Optional[datetime]) -> None:
    _memory_state[key] = value
    try:
        if value is None:
            database.delete_meta(key)
        else:
            database.set_meta(key, value.isoformat(timespec='seconds'))
        _unsynced.discard(key)
    except Exception as e:
        _unsynced.add(key)
        logger.warning(f"Не удалось записать {key} в базу: {type(e).__name__}: {e}")


def _flush_unsynced() -> None:
    """Повторяет несохранённые записи состояния, чтобы база сошлась с памятью"""
    for key in list(_unsynced):
        _write_state_time(key, _memory_state.get(key))


def _hours_between(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 3600


def update_heartbeat(stats: CycleStats, now: Optional[datetime] = None) -> None:
    """
    Предупреждает в Telegram, если успешного цикла не было дольше HEARTBEAT_HOURS.
    Предупреждение повторяется не чаще раза в HEARTBEAT_HOURS. После
    восстановления приходит одно сообщение об этом.

    Время отсчитывается от начала циклов: они идут по расписанию, и
    длительность цикла не сдвигает момент предупреждения.
    """
    now = now or stats.started_at
    _flush_unsynced()

    if stats.ok:
        alert_was_sent = _read_state_time(database.META_ALERT_SENT) is not None
        _write_state_time(database.META_LAST_SUCCESS, now)
        if alert_was_sent:
            _write_state_time(database.META_ALERT_SENT, None)
            _send_service_message("✅ Проверка скидок Steam снова работает.")
        return

    threshold = config.HEARTBEAT_HOURS - HEARTBEAT_SLACK_HOURS
    last_success = _read_state_time(database.META_LAST_SUCCESS) or _PROCESS_STARTED_AT
    hours_without_success = _hours_between(now, last_success)
    if hours_without_success < threshold:
        return

    alert_sent = _read_state_time(database.META_ALERT_SENT)
    if alert_sent and _hours_between(now, alert_sent) < threshold:
        return

    error = telegram_client.redact(stats.error or stats.status, config.TELEGRAM_BOT_TOKEN)[:MAX_ERROR_TEXT]
    logger.error(f"Heartbeat: успешного цикла не было {hours_without_success:.0f} ч")
    if _send_service_message(
        f"⚠️ Бот скидок Steam не может завершить проверку уже {hours_without_success:.0f} ч.\n"
        f"Последняя ошибка: {error}"
    ):
        _write_state_time(database.META_ALERT_SENT, now)


def check_and_notify() -> CycleStats:
    """
    Полный цикл: межпроцессная блокировка, проверка, итог в лог, heartbeat.
    Не бросает исключений.
    """
    stats = CycleStats()
    try:
        with database.cycle_lock() as acquired:
            if not acquired:
                stats.status = 'locked'
                stats.error = "цикл уже выполняется другим процессом"
            else:
                try:
                    run_cycle(stats)
                except Exception as e:
                    logger.error(f"Ошибка цикла проверки: {type(e).__name__}: {e}", exc_info=True)
                    stats.status = 'error'
                    stats.error = f"{type(e).__name__}: {e}"
    except Exception as e:
        logger.error(f"Не удалось взять блокировку цикла: {type(e).__name__}: {e}", exc_info=True)
        stats.status = 'error'
        stats.error = f"блокировка: {type(e).__name__}: {e}"

    if stats.ok:
        logger.info(stats.summary())
    elif stats.status == 'locked':
        logger.warning(stats.summary())
    else:
        logger.error(stats.summary())

    try:
        update_heartbeat(stats)
    except Exception as e:
        logger.error(f"Ошибка heartbeat: {type(e).__name__}: {e}", exc_info=True)

    return stats


def dry_run() -> int:
    """Показывает, что было бы отправлено, без Telegram и без записи в базу"""
    try:
        config.validate_config(require_telegram=False)
    except EnvironmentError as e:
        print(f"Ошибка конфигурации: {e}")
        return 1

    meta: Optional[Dict[str, str]]
    try:
        meta, known = database.peek_state()
    except Exception as e:
        print(f"База не прочитана ({type(e).__name__}: {e})")
        meta, known = None, {}

    try:
        result = steam_search.get_deals(previous_total_count=None, check_language=True)
    except steam_search.SourceError as e:
        print(f"Источник недоступен: {e}")
        return 1

    initialized = meta is not None and database.META_INITIALIZED in meta
    pending_ids = {
        d['app_id'] for d in result.deals
        if initialized and (d['app_id'] not in known or known[d['app_id']] != d['discount'])
    }
    seeded_ids: Set[str] = set()
    selection_changed = initialized and meta.get(database.META_SELECTION) != selection_fingerprint()
    if selection_changed:
        old_ids = previously_selected_ids(result.games, meta.get(database.META_SELECTION))
        seeded_ids = {app_id for app_id in pending_ids if old_ids is None or app_id not in old_ids}
        pending_ids -= seeded_ids

    print(f"total_count={result.total_count}, страниц {result.pages}, разобрано {len(result.games)}, "
          f"прошло фильтр {len(result.deals)}, контроль фильтра языка: "
          f"{'пройден' if result.language_checked else 'не делался'}")
    if meta is None:
        print("Состояние базы неизвестно, отметки NEW не ставятся")
    elif not initialized:
        print("Первый запуск: цикл пометит все эти скидки известными и ничего не отправит")
    else:
        if selection_changed:
            print(f"Настройки отбора изменились: {len(seeded_ids)} скидок, подходящих только под новые "
                  f"настройки, будут помечены известными без отправки")
        print(f"К отправке {len(pending_ids)}, за цикл не больше {config.MAX_MESSAGES_PER_CYCLE}")

    for deal in result.deals:
        mark = 'NEW' if deal['app_id'] in pending_ids else '   '
        print(f"  {mark} -{deal['discount']}%  {deal['price_final'] or '?':>12}  "
              f"{deal['review_pct']}% из {deal['review_count']}  {deal['title']} ({deal['app_id']})")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Одиночная проверка скидок Steam")
    parser.add_argument('--dry-run', action='store_true',
                        help="показать отобранные скидки без отправки в Telegram и записи в базу")
    args = parser.parse_args(argv)

    setup_logging()

    if args.dry_run:
        return dry_run()

    try:
        config.validate_config()
        database.init_db()
    except Exception as e:
        logger.error(f"Ошибка запуска: {type(e).__name__}: {e}")
        return 1

    stats = check_and_notify()
    return 0 if stats.ok else 1


if __name__ == "__main__":
    sys.exit(main())
