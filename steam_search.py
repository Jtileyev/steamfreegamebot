"""
Источник скидок: поиск магазина Steam

Эндпоинт недокументирован. Параметры, ловушки и формат ответа описаны
в docs/02-steam-search-api.md.

За цикл загружается STEAM_MAX_PAGES страниц по 100 строк, отсортированных
по отзывам. Одна страница это только лучшие по отзывам ~4% скидок.
Контрольный запрос без фильтра языка делается по требованию вызывающего
(раз в сутки) и при резком изменении total_count: так распродажа отличается
от молча проигнорированного supportedlang.
"""
import html
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

import requests

import config

logger = logging.getLogger(__name__)

SEARCH_URL = "https://store.steampowered.com/search/results/"
HEADERS = {"User-Agent": "SteamDealsBot/2.0"}
REQUEST_TIMEOUT = 20
PAGE_SIZE = 100

# Временные ошибки (сеть, 429, 5xx, не-JSON) повторяются один раз после паузы
FETCH_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 60

# Пауза между запросами одного цикла: после ~3 запросов подряд Steam отвечает 429
PAGE_DELAY_SECONDS = 12

# Проверки правдоподобия выдачи
MIN_ROWS_FOR_MARKUP_CHECK = 10
# Допустимая нехватка строк на странице относительно total_count
ROW_SHORTFALL_TOLERANCE = 2
# Доля строк с отзывами, которая должна разобраться
MIN_PARSED_REVIEW_SHARE = 0.9
# Изменение total_count во столько раз относительно прошлого цикла вызывает контрольный запрос
TOTAL_COUNT_JUMP_RATIO = 1.6
# Если без фильтра языка total_count больше не более чем на эту долю, фильтр проигнорирован
LANGUAGE_FILTER_MIN_RATIO = 1.05
# Доля игр страницы, уже встреченных на прошлых страницах, при которой start считается проигнорированным
MAX_REPEATED_SHARE = 0.5

ROW_SPLIT = re.compile(r'(?=<a\s[^>]*?data-ds-itemkey=")')
ITEM_KEY = re.compile(r'data-ds-itemkey="(\w+?)_')
APP_ID = re.compile(r'data-ds-appid="(\d+)"')
TITLE = re.compile(r'<span class="title">(.*?)</span>', re.S)
DISCOUNT = re.compile(r'data-discount="(\d+)"')
PRICE_FINAL = re.compile(r'data-price-final="(\d+)"')
PRICE_FINAL_TEXT = re.compile(r'<div class="discount_final_price[^"]*">([^<]*)</div>')
PRICE_ORIGINAL_TEXT = re.compile(r'<div class="discount_original_price[^"]*">([^<]*)</div>')
TAG_IDS = re.compile(r'data-ds-tagids="\[([\d,]*)\]"')
RELEASED = re.compile(r'<div class="search_released[^"]*">\s*(.*?)\s*</div>', re.S)
REVIEW = re.compile(
    r'search_review_summary\s+(positive|mixed|negative)"\s+'
    r'data-tooltip-html="([^&"]+)&lt;br&gt;(\d{1,3})% of the (\d[\d,.\u00a0\u202f ]*) u'
)


class SourceError(Exception):
    """
    Источник недоступен или ответ не прошёл проверку. Это не пустая выдача.
    temporary=True означает, что повтор через минуту может помочь.
    """

    def __init__(self, message: str, temporary: bool = False):
        super().__init__(message)
        self.temporary = temporary


@dataclass
class SearchResult:
    total_count: int
    rows: int
    pages: int = 1
    games: List[Dict] = field(default_factory=list)
    deals: List[Dict] = field(default_factory=list)
    language_checked: bool = False


def build_params(cc: str, exclude_tag_ids: Iterable[int], start: int = 0) -> Dict[str, str]:
    """Рекомендованный запрос из справочника"""
    params = {
        'query': '',
        'start': str(start),
        'count': str(PAGE_SIZE),
        'infinite': '1',
        'json': '1',
        'cc': cc,
        'l': 'en',
        'specials': '1',
        'category1': '998',
        'sort_by': 'Reviews_DESC',
        'supportedlang': 'russian',
        'hidef2p': '1',
    }
    tag_ids = ','.join(str(t) for t in exclude_tag_ids)
    if tag_ids:
        params['untags'] = tag_ids
    return params


def _fetch_once(params: Dict[str, str]) -> Dict:
    try:
        response = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise SourceError(f"сетевая ошибка: {type(e).__name__}: {e}", temporary=True) from e

    if response.status_code == 429:
        raise SourceError("Steam ограничил частоту запросов (HTTP 429)", temporary=True)
    if response.status_code != 200:
        raise SourceError(f"Steam ответил HTTP {response.status_code}",
                          temporary=response.status_code >= 500)

    try:
        data = response.json()
    except ValueError as e:
        raise SourceError(f"ответ Steam не JSON ({len(response.content)} байт)", temporary=True) from e

    if not isinstance(data, dict) or data.get('success') != 1:
        raise SourceError("ответ Steam без success=1")
    if not isinstance(data.get('results_html'), str):
        raise SourceError("в ответе Steam нет results_html")
    if not isinstance(data.get('total_count'), int):
        raise SourceError("в ответе Steam нет total_count")

    return data


def fetch_search(params: Dict[str, str], attempts: int = FETCH_ATTEMPTS,
                 retry_delay: float = RETRY_DELAY_SECONDS) -> Dict:
    """Загружает страницу поиска. Бросает SourceError, если ответ не получен"""
    for attempt in range(1, attempts + 1):
        try:
            return _fetch_once(params)
        except SourceError as e:
            if not e.temporary or attempt == attempts:
                raise
            logger.warning(f"Попытка {attempt}/{attempts} запроса к Steam не удалась: {e}. "
                           f"Повтор через {retry_delay:g} с")
            time.sleep(retry_delay)
    raise SourceError("запрос к Steam не выполнялся")  # attempts < 1


def split_rows(results_html: str) -> List[str]:
    return ROW_SPLIT.split(results_html)[1:]


def parse_row(row: str) -> Optional[Dict]:
    """Разбирает одну строку выдачи. Пакеты и строки без скидки или без отзывов отбрасываются"""
    key = ITEM_KEY.search(row)
    if not key or key.group(1) != 'App':
        return None  # Sub_/Bundle_: data-ds-appid там список через запятую

    app_id, title, discount = APP_ID.search(row), TITLE.search(row), DISCOUNT.search(row)
    if not (app_id and title and discount):
        return None

    review = REVIEW.search(row)
    if not review:
        return None  # нет ни одного отзыва: главный признак шлака

    price = PRICE_FINAL.search(row)
    price_text = PRICE_FINAL_TEXT.search(row)
    original_text = PRICE_ORIGINAL_TEXT.search(row)
    tags = TAG_IDS.search(row)
    released = RELEASED.search(row)

    return {
        'app_id': app_id.group(1),
        'title': html.unescape(title.group(1)).strip(),
        'discount': int(discount.group(1)),
        'price_final_minor': int(price.group(1)) if price else None,
        'price_final': html.unescape(price_text.group(1)).strip() if price_text else None,
        'price_original': html.unescape(original_text.group(1)).strip() if original_text else None,
        'review_label': html.unescape(review.group(2)).strip(),
        'review_pct': int(review.group(3)),
        'review_count': int(re.sub(r'\D', '', review.group(4))),
        'tag_ids': [int(t) for t in tags.group(1).split(',') if t] if tags else [],
        'released': released.group(1).strip() if released else None,
        'steam_url': f"https://store.steampowered.com/app/{app_id.group(1)}",
    }


def parse_results(results_html: str, page: int = 0) -> List[Dict]:
    games = []
    for row in split_rows(results_html):
        game = parse_row(row)
        if game and game['title']:
            game['page'] = page
            games.append(game)
    return games


def check_page(results_html: str, games: List[Dict], expected_rows: int) -> None:
    """
    Проверяет, что страница разобрана правдоподобно. Бросает SourceError,
    если строк меньше, чем обещает total_count, разметка изменилась или
    Steam проигнорировал specials.
    """
    item_rows = results_html.count('data-ds-itemkey="')
    rows = split_rows(results_html)
    app_rows = [row for row in rows if 'data-ds-itemkey="App_' in row]

    if item_rows < expected_rows - ROW_SHORTFALL_TOLERANCE:
        raise SourceError(f"в выдаче {item_rows} строк при ожидаемых {expected_rows}: "
                          f"Steam урезал страницу или изменилась разметка")
    if len(rows) < item_rows:
        raise SourceError(f"строки выдачи не разделяются: найдено {len(rows)} из {item_rows}, "
                          f"разметка Steam изменилась")
    if len(app_rows) < MIN_ROWS_FOR_MARKUP_CHECK:
        return

    without_discount = sum(
        1 for row in app_rows
        if not (m := DISCOUNT.search(row)) or int(m.group(1)) == 0
    )
    if without_discount > len(app_rows) // 2:
        raise SourceError(f"{without_discount} из {len(app_rows)} игр в выдаче без скидки: "
                          f"Steam проигнорировал фильтр specials")
    if len(games) < len(app_rows) // 2:
        raise SourceError(f"разобрано {len(games)} из {len(app_rows)} строк выдачи: "
                          f"разметка Steam изменилась")

    review_rows = sum(1 for row in app_rows if 'search_review_summary' in row)
    if review_rows >= MIN_ROWS_FOR_MARKUP_CHECK and len(games) < review_rows * MIN_PARSED_REVIEW_SHARE:
        raise SourceError(f"разобрано {len(games)} из {review_rows} строк с отзывами: "
                          f"разметка Steam изменилась")


def select_deals(games: List[Dict], min_discount: int = 70,
                 min_review_pct: int = 80, min_reviews: int = 200,
                 exclude_tags: Optional[Iterable[int]] = None) -> List[Dict]:
    """
    Клиентские фильтры, которых нет среди параметров Steam.
    Одна игра встречается один раз, лучшие скидки первыми.
    """
    exclude = set(exclude_tags or ())
    selected: Dict[str, Dict] = {}
    for game in games:
        if (game['discount'] >= min_discount
                and game['review_pct'] >= min_review_pct
                and game['review_count'] >= min_reviews
                and not exclude.intersection(game['tag_ids'])):
            previous = selected.get(game['app_id'])
            if previous is None or game['discount'] > previous['discount']:
                selected[game['app_id']] = game
    return sorted(
        selected.values(),
        key=lambda g: (-g['discount'], -g['review_pct'], -g['review_count'], g['app_id']),
    )


def check_language_filter(params: Dict[str, str], total_count: int) -> None:
    """
    Контрольный запрос без supportedlang. Если выдача почти не выросла,
    Steam игнорирует фильтр языка и в рассылку попадут игры без русского.
    """
    control = {k: v for k, v in params.items() if k != 'supportedlang'}
    time.sleep(PAGE_DELAY_SECONDS)
    control_total = fetch_search(control)['total_count']
    logger.info(f"Контроль фильтра языка: total_count {total_count} с фильтром, {control_total} без него")
    if control_total <= total_count * LANGUAGE_FILTER_MIN_RATIO:
        raise SourceError(
            f"Steam игнорирует фильтр supportedlang: total_count {total_count} с фильтром "
            f"и {control_total} без него"
        )


def _total_count_changed(total_count: int, previous: int) -> bool:
    return (total_count > previous * TOTAL_COUNT_JUMP_RATIO
            or total_count * TOTAL_COUNT_JUMP_RATIO < previous)


def get_deals(previous_total_count: Optional[int] = None, check_language: bool = False,
              max_pages: Optional[int] = None) -> SearchResult:
    """
    Один цикл получения скидок с настройками из config.

    Args:
        previous_total_count: total_count прошлого успешного цикла. Если его нет
            или выдача изменилась в TOTAL_COUNT_JUMP_RATIO раз, делается
            контрольный запрос без фильтра языка.
        check_language: сделать контрольный запрос в любом случае.
        max_pages: сколько страниц загружать, по умолчанию STEAM_MAX_PAGES.

    Бросает SourceError, если Steam недоступен или ответ выглядит неправдоподобно.
    Частичный результат не возвращается: сбой любой страницы это сбой цикла.
    """
    max_pages = max_pages or config.STEAM_MAX_PAGES
    games: List[Dict] = []
    total_count = 0
    rows = 0
    pages = 0
    language_checked = False

    for page in range(max_pages):
        start = page * PAGE_SIZE
        if page:
            time.sleep(PAGE_DELAY_SECONDS)

        params = build_params(config.STEAM_CC, config.EXCLUDE_TAG_IDS, start=start)
        data = fetch_search(params)
        results_html = data['results_html']
        page_total = data['total_count']

        if page == 0:
            total_count = page_total
            if not config.STEAM_TOTAL_COUNT_MIN <= total_count <= config.STEAM_TOTAL_COUNT_MAX:
                raise SourceError(
                    f"total_count={total_count} вне ожидаемого диапазона "
                    f"{config.STEAM_TOTAL_COUNT_MIN}..{config.STEAM_TOTAL_COUNT_MAX}: "
                    f"возможно, Steam проигнорировал фильтр"
                )
        elif page_total <= 0 or _total_count_changed(page_total, total_count):
            raise SourceError(
                f"total_count на странице {page + 1} равен {page_total} при {total_count} на первой: "
                f"выдача Steam неправдоподобна"
            )
        elif start >= page_total:
            if total_count - page_total > PAGE_SIZE:
                raise SourceError(
                    f"total_count на странице {page + 1} упал до {page_total} при {total_count} на первой: "
                    f"выдача Steam неправдоподобна"
                )
            break  # скидки закончились между запросами

        page_games = parse_results(results_html, page=page)
        page_rows = len(split_rows(results_html))
        check_page(results_html, page_games, expected_rows=min(PAGE_SIZE, page_total - start))

        if page and page_games:
            seen = {g['app_id'] for g in games}
            repeated = sum(1 for g in page_games if g['app_id'] in seen)
            if repeated > len(page_games) * MAX_REPEATED_SHARE:
                raise SourceError(f"на странице {page + 1} повторяются {repeated} из {len(page_games)} игр "
                                  f"прошлых страниц: Steam проигнорировал start")

        if page == 0 and (check_language or previous_total_count is None
                          or _total_count_changed(total_count, previous_total_count)):
            check_language_filter(params, total_count)
            language_checked = True

        games.extend(page_games)
        rows += page_rows
        pages += 1

        if start + page_rows >= page_total:
            break

    deals = select_deals(
        games,
        min_discount=config.MIN_DISCOUNT_PERCENT,
        min_review_pct=config.MIN_REVIEW_PCT,
        min_reviews=config.MIN_REVIEWS,
        exclude_tags=config.EXCLUDE_TAG_IDS,
    )
    return SearchResult(total_count=total_count, rows=rows, pages=pages, games=games,
                        deals=deals, language_checked=language_checked)


if __name__ == "__main__":
    # Ручная проверка источника без Telegram и базы
    logging.basicConfig(level=logging.INFO)
    result = get_deals()
    print(f"total_count={result.total_count}, страниц={result.pages}, строк={result.rows}, "
          f"разобрано={len(result.games)}, отобрано={len(result.deals)}")
    for deal in result.deals:
        print(f"  -{deal['discount']}%  {deal['price_final'] or '?':>12}  "
              f"{deal['review_pct']}%/{deal['review_count']}  {deal['title']}  ({deal['app_id']})")
