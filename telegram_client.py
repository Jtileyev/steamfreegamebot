"""
Модуль для отправки сообщений в Telegram

Токен бота входит в URL запроса, поэтому ни текст исключений requests,
ни URL не попадают в лог без вырезания токена.
"""
import http.client
import logging
import time
from typing import Dict, List, Optional, Tuple

import requests
import urllib3

logger = logging.getLogger(__name__)

# Telegram API endpoint
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
REQUEST_TIMEOUT = 30

# Сколько максимум ждать по retry_after из ответа 429
MAX_RETRY_AFTER_SECONDS = 60

# Результат отправки уведомления. UNCERTAIN: запрос ушёл, ответа нет,
# сообщение могло быть доставлено
SENT = 'sent'
FAILED = 'failed'
UNCERTAIN = 'uncertain'

# Спецсимволы MarkdownV2. Обратный слэш экранируется первым
MARKDOWN_V2_SPECIAL_CHARS = '\\_*[]()~`>#+-=|{}.!'


def redact(text: str, token: Optional[str]) -> str:
    """Вырезает токен бота из произвольного текста"""
    if not text or not token:
        return text
    return text.replace(token, '***')


def escape_markdown(text: str) -> str:
    """Экранирует спецсимволы для обычного текста в MarkdownV2"""
    if not text:
        return ""
    for char in MARKDOWN_V2_SPECIAL_CHARS:
        text = text.replace(char, f'\\{char}')
    return text


def escape_markdown_url(url: str) -> str:
    """Экранирует URL внутри (...) ссылки MarkdownV2"""
    return url.replace('\\', '\\\\').replace(')', '\\)')


def _exception_chain(error: BaseException) -> List[BaseException]:
    """Исключение и все вложенные: args, __cause__, __context__, reason у urllib3"""
    chain: List[BaseException] = []
    stack = [error]
    while stack and len(chain) < 20:
        current = stack.pop()
        if any(current is seen for seen in chain):
            continue
        chain.append(current)
        stack.extend(arg for arg in current.args if isinstance(arg, BaseException))
        for attr in ('__cause__', '__context__', 'reason'):
            nested = getattr(current, attr, None)
            if isinstance(nested, BaseException):
                stack.append(nested)
    return chain


def maybe_delivered(error: requests.exceptions.RequestException) -> bool:
    """
    Мог ли запрос дойти до Telegram. Да: таймаут ответа, разрыв после отправки
    или обрыв тела ответа. Нет: ошибка соединения или TLS-рукопожатия, запрос не ушёл.
    """
    chain = _exception_chain(error)
    if any('handshake' in str(exc).lower() for exc in chain):
        return False
    if isinstance(error, (requests.exceptions.ReadTimeout, requests.exceptions.ChunkedEncodingError,
                          requests.exceptions.ContentDecodingError)):
        return True
    return any(isinstance(exc, (http.client.RemoteDisconnected, urllib3.exceptions.ReadTimeoutError))
               for exc in chain)


def _post(url: str, payload: Dict, token: str) -> Dict:
    """Один запрос к Bot API. Сетевые ошибки превращаются в ответ с ok=False"""
    try:
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        error = f"{type(e).__name__}: {redact(str(e), token)}"
        if maybe_delivered(e):
            logger.error(f"Ответ Telegram не получен, сообщение могло быть доставлено: {error}")
            return {"ok": False, "uncertain": True, "description": error}
        logger.error(f"Ошибка сети при отправке в Telegram: {error}")
        return {"ok": False, "description": error}

    try:
        result = response.json()
    except ValueError:
        logger.error(f"Telegram ответил HTTP {response.status_code} без JSON")
        return {"ok": False, "error_code": response.status_code, "description": "ответ не JSON"}

    if not isinstance(result, dict):
        return {"ok": False, "error_code": response.status_code, "description": "неожиданный ответ"}
    return result


def send_message(bot_token: str, chat_id: str, text: str,
                 parse_mode: Optional[str] = "MarkdownV2",
                 plain_text: Optional[str] = None) -> Dict:
    """
    Отправляет сообщение через Telegram Bot API

    Args:
        bot_token: токен бота
        chat_id: ID чата для отправки
        text: текст сообщения
        parse_mode: режим форматирования или None для простого текста
        plain_text: текст без разметки на случай, если Telegram не разобрал форматирование

    Returns:
        ответ Telegram API; при сетевой ошибке {"ok": False, "description": ...};
        при таймауте ответа дополнительно "uncertain": True
    """
    url = TELEGRAM_API_URL.format(token=bot_token)

    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    result = _post(url, payload, bot_token)
    if result.get("uncertain"):
        return result  # повтор мог бы продублировать доставленное сообщение

    # Лимит частоты: подождать сколько просит Telegram и повторить один раз
    if not result.get("ok") and result.get("error_code") == 429:
        retry_after = (result.get("parameters") or {}).get("retry_after", 1)
        if isinstance(retry_after, int) and 0 < retry_after <= MAX_RETRY_AFTER_SECONDS:
            logger.warning(f"Telegram просит подождать {retry_after} с перед повтором")
            time.sleep(retry_after)
            result = _post(url, payload, bot_token)

    if not result.get("ok"):
        description = result.get("description", "")
        logger.error(f"Ошибка Telegram API: {redact(description, bot_token)}")

        # Разметка не разобралась: отправляем заранее собранный простой текст
        if parse_mode and plain_text and "can't parse" in description.lower():
            logger.info("Повторная отправка без форматирования")
            plain_payload = {k: v for k, v in payload.items() if k != "parse_mode"}
            plain_payload["text"] = plain_text
            result = _post(url, plain_payload, bot_token)
            if not result.get("ok"):
                logger.error(f"Ошибка Telegram API: {redact(result.get('description', ''), bot_token)}")

    return result


def _format_count(value: int) -> str:
    return f"{value:,}".replace(',', ' ')


def _discount_emoji(discount: int) -> str:
    if discount >= 90:
        return "🔥🔥🔥"
    if discount >= 80:
        return "🔥🔥"
    if discount >= 70:
        return "🔥"
    return "💰"


def format_deal_message(deal: Dict) -> Tuple[str, str]:
    """
    Форматирует сообщение о скидке

    Args:
        deal: скидка из steam_search: title, steam_url, discount, price_final,
            price_original, review_pct, review_count

    Returns:
        (текст MarkdownV2, тот же текст без разметки)
    """
    title = deal.get('title') or 'Неизвестная игра'
    steam_url = deal.get('steam_url', '')
    discount = int(deal.get('discount') or 0)
    price_final = deal.get('price_final')
    price_original = deal.get('price_original')
    review_pct = deal.get('review_pct')
    review_count = deal.get('review_count')

    emoji = _discount_emoji(discount)

    md = [f"{emoji} *Скидка {escape_markdown(f'-{discount}%')} в Steam*", "", f"*{escape_markdown(title)}*"]
    plain = [f"{emoji} Скидка -{discount}% в Steam", "", title]

    if price_final:
        if price_original:
            md.append(f"💰 {escape_markdown(price_final)} ~{escape_markdown(price_original)}~")
            plain.append(f"💰 {price_final} (было {price_original})")
        else:
            md.append(f"💰 {escape_markdown(price_final)}")
            plain.append(f"💰 {price_final}")

    if review_pct is not None and review_count:
        reviews = f"{review_pct}% положительных из {_format_count(review_count)} отзывов"
        md.append(f"👍 {escape_markdown(reviews)}")
        plain.append(f"👍 {reviews}")

    if steam_url:
        md.append(f"🔗 [Открыть в Steam]({escape_markdown_url(steam_url)})")
        plain.append(f"🔗 {steam_url}")

    return "\n".join(md), "\n".join(plain)


def send_deal_notification(bot_token: str, chat_id: str, deal: Dict) -> str:
    """
    Отправляет уведомление о скидке

    Returns:
        SENT, FAILED или UNCERTAIN, если ответ не получен и доставка неизвестна
    """
    text, plain = format_deal_message(deal)
    result = send_message(bot_token, chat_id, text, plain_text=plain)

    if result.get("ok"):
        logger.info(f"Уведомление о скидке '{deal.get('title')}' отправлено")
        return SENT
    if result.get("uncertain"):
        logger.warning(f"Доставка уведомления о скидке '{deal.get('title')}' неизвестна")
        return UNCERTAIN

    logger.error(f"Не удалось отправить уведомление о скидке '{deal.get('title')}'")
    return FAILED


def send_text(bot_token: str, chat_id: str, text: str) -> bool:
    """Отправляет служебное сообщение простым текстом"""
    result = send_message(bot_token, chat_id, text, parse_mode=None)
    return bool(result.get("ok"))


if __name__ == "__main__":
    # Предпросмотр форматирования без отправки
    test_deal = {
        'title': 'Test Game: The Adventure! (C:\\Games) & Co.',
        'steam_url': 'https://store.steampowered.com/app/12345',
        'discount': 85,
        'price_final': '675,00₸',
        'price_original': '4 500,00₸',
        'review_pct': 96,
        'review_count': 12345,
    }
    markdown, plain_text = format_deal_message(test_deal)
    print(markdown)
    print()
    print(plain_text)
