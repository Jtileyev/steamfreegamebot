"""
Модуль получения информации о скидках на игры в Steam
Использует Reddit r/steamdeals RSS feed (более надёжный для серверов)
"""
import requests
import time
import random
import logging
import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# RSS feed более надёжен для серверов (меньше блокировок)
REDDIT_RSS_URL = "https://www.reddit.com/r/steamdeals/.rss"
# Fallback на old.reddit (иногда работает лучше)
REDDIT_OLD_URL = "https://old.reddit.com/r/steamdeals/.json"

# Настройки
MAX_RETRIES = 3
RETRY_DELAY = 5

# User-Agent - имитируем RSS reader
HEADERS_RSS = {
    "User-Agent": "SteamDealsBot/1.0 (RSS Reader; +https://github.com/steam-deals-bot)",
    "Accept": "application/rss+xml, application/xml, text/xml",
}

HEADERS_JSON = {
    "User-Agent": "SteamDealsBot/1.0 (by /u/steam_deals_notifier)",
    "Accept": "application/json",
}


def random_delay():
    """Случайная задержка между запросами"""
    time.sleep(random.uniform(2, 4))


def fetch_rss_feed(url: str, retries: int = MAX_RETRIES) -> Optional[str]:
    """
    Загружает RSS feed
    """
    for attempt in range(retries):
        try:
            random_delay()
            response = requests.get(url, headers=HEADERS_RSS, timeout=30)
            response.raise_for_status()
            return response.text
            
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP ошибка {response.status_code}: {e}")
        except Exception as e:
            logger.warning(f"Попытка {attempt + 1}/{retries} RSS не удалась: {e}")
        
        if attempt < retries - 1:
            time.sleep(RETRY_DELAY)
    
    return None


def fetch_reddit_json(url: str, retries: int = MAX_RETRIES) -> Optional[Dict]:
    """
    Загружает JSON с Reddit API (fallback)
    """
    for attempt in range(retries):
        try:
            random_delay()
            response = requests.get(url, headers=HEADERS_JSON, timeout=30)
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:  # Rate limited
                logger.warning(f"Reddit rate limit, ожидание 60 сек...")
                time.sleep(60)
            else:
                logger.warning(f"HTTP ошибка {response.status_code}: {e}")
        except Exception as e:
            logger.warning(f"Попытка {attempt + 1}/{retries} JSON не удалась: {e}")
        
        if attempt < retries - 1:
            time.sleep(RETRY_DELAY)
    
    logger.error(f"Не удалось загрузить: {url}")
    return None


def extract_discount_from_title(title: str) -> Optional[str]:
    """
    Извлекает размер скидки из заголовка поста
    Примеры: "Save 70% on...", "80% off", "-90%"
    """
    # Паттерны для извлечения скидки
    patterns = [
        r'Save\s+(\d+)%',           # "Save 70%"
        r'(\d+)%\s*off',            # "70% off"
        r'-(\d+)%',                  # "-70%"
        r'(\d+)\s*percent',          # "70 percent"
        r'\((\d+)%\)',               # "(70%)"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return f"-{match.group(1)}%"
    
    return None


def extract_steam_app_id(url: str) -> Optional[str]:
    """
    Извлекает Steam App ID из URL
    """
    # Паттерны для Steam URLs
    patterns = [
        r'store\.steampowered\.com/app/(\d+)',
        r'steampowered\.com/app/(\d+)',
        r'/app/(\d+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None


def clean_game_title(title: str) -> str:
    """
    Очищает название игры от служебных частей
    "Save 70% on The Witcher 3: Wild Hunt on Steam" -> "The Witcher 3: Wild Hunt"
    """
    # Удаляем "Save X% on " в начале
    title = re.sub(r'^Save\s+\d+%\s+on\s+', '', title, flags=re.IGNORECASE)
    
    # Удаляем " on Steam" в конце
    title = re.sub(r'\s+on\s+Steam\s*$', '', title, flags=re.IGNORECASE)
    
    # Удаляем другие суффиксы
    title = re.sub(r'\s*\|\s*Steam\s*$', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s*-\s*Steam\s*$', '', title, flags=re.IGNORECASE)
    
    return title.strip()


def get_deals_from_steamdeals(limit: int = 100) -> List[Dict]:
    """
    Получает список скидок из r/steamdeals
    Сначала пробует RSS (надёжнее), затем JSON API
    
    Args:
        limit: Максимальное количество постов для загрузки
    
    Returns:
        Список словарей с информацией об играх
    """
    games = []
    
    # Метод 1: RSS feed (более надёжный для серверов)
    logger.info(f"Попытка загрузки через RSS feed...")
    rss_data = fetch_rss_feed(REDDIT_RSS_URL)
    
    if rss_data:
        games = parse_rss_feed(rss_data, limit)
        if games:
            logger.info(f"RSS: Найдено {len(games)} скидок")
            return games
    
    # Метод 2: old.reddit JSON (fallback)
    logger.info(f"RSS не удался, пробуем old.reddit JSON...")
    url = f"{REDDIT_OLD_URL}?limit={limit}"
    data = fetch_reddit_json(url)
    
    if data and 'data' in data:
        games = parse_json_response(data, limit)
        if games:
            logger.info(f"JSON: Найдено {len(games)} скидок")
            return games
    
    logger.warning("Не удалось получить данные ни через RSS, ни через JSON")
    return games


def parse_rss_feed(rss_text: str, limit: int) -> List[Dict]:
    """
    Парсит RSS feed r/steamdeals
    """
    games = []
    
    try:
        # Reddit RSS использует Atom namespace
        namespaces = {
            'atom': 'http://www.w3.org/2005/Atom',
            'media': 'http://search.yahoo.com/mrss/'
        }
        
        root = ET.fromstring(rss_text)
        entries = root.findall('.//atom:entry', namespaces)
        
        logger.info(f"RSS: Получено {len(entries)} записей")
        
        for entry in entries[:limit]:
            try:
                title = entry.find('atom:title', namespaces)
                link = entry.find('atom:link', namespaces)
                content = entry.find('atom:content', namespaces)
                
                title_text = title.text if title is not None else ''
                reddit_url = link.get('href') if link is not None else ''
                content_html = content.text if content is not None else ''
                
                # Извлекаем Steam URL из контента
                steam_url = extract_steam_url_from_html(content_html)
                if not steam_url:
                    continue
                
                app_id = extract_steam_app_id(steam_url)
                if not app_id:
                    continue
                
                discount = extract_discount_from_title(title_text)
                if not discount:
                    discount = "Скидка"
                
                game_title = clean_game_title(title_text)
                if not game_title:
                    game_title = title_text
                
                game = {
                    'app_id': app_id,
                    'title': game_title,
                    'steam_url': f"https://store.steampowered.com/app/{app_id}",
                    'discount': discount,
                    'end_date': None,
                    'reddit_score': 0,
                    'reddit_url': reddit_url,
                    'created_utc': 0,
                }
                
                if not any(g['app_id'] == app_id for g in games):
                    games.append(game)
                    logger.debug(f"RSS: {game_title} ({discount})")
                    
            except Exception as e:
                logger.debug(f"Ошибка парсинга RSS entry: {e}")
                continue
                
    except ET.ParseError as e:
        logger.error(f"Ошибка парсинга RSS XML: {e}")
    except Exception as e:
        logger.error(f"Ошибка обработки RSS: {e}")
    
    return games


def extract_steam_url_from_html(html: str) -> Optional[str]:
    """
    Извлекает Steam URL из HTML контента RSS
    """
    patterns = [
        r'href="(https?://store\.steampowered\.com/app/\d+[^"]*)"',
        r'(https?://store\.steampowered\.com/app/\d+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    
    return None


def parse_json_response(data: Dict, limit: int) -> List[Dict]:
    """
    Парсит JSON ответ от Reddit API
    """
    games = []
    posts = data.get('data', {}).get('children', [])
    
    logger.info(f"JSON: Получено {len(posts)} постов")
    
    for post_wrapper in posts[:limit]:
        try:
            post = post_wrapper.get('data', {})
            
            title = post.get('title', '')
            url = post.get('url', '')
            score = post.get('score', 0)
            created_utc = post.get('created_utc', 0)
            permalink = post.get('permalink', '')
            
            # Проверяем, что это ссылка на Steam
            if 'steampowered.com' not in url and 'steam://' not in url:
                continue
            
            # Извлекаем app_id
            app_id = extract_steam_app_id(url)
            if not app_id:
                continue
            
            # Извлекаем скидку
            discount = extract_discount_from_title(title)
            if not discount:
                discount = "Скидка"  # Если не удалось определить
            
            # Очищаем название
            game_title = clean_game_title(title)
            if not game_title:
                game_title = title
            
            game = {
                'app_id': app_id,
                'title': game_title,
                'steam_url': f"https://store.steampowered.com/app/{app_id}",
                'discount': discount,
                'end_date': None,
                'reddit_score': score,
                'reddit_url': f"https://reddit.com{permalink}",
                'created_utc': created_utc,
            }
            
            # Проверяем на дубликаты (по app_id)
            if not any(g['app_id'] == app_id for g in games):
                games.append(game)
                logger.debug(f"JSON: {game_title} ({discount})")
        
        except Exception as e:
            logger.warning(f"Ошибка парсинга поста Reddit: {e}")
            continue
    
    # Сортируем по популярности (score)
    games.sort(key=lambda x: x.get('reddit_score', 0), reverse=True)
    
    return games


def get_free_games() -> List[Dict]:
    """
    Получает список БЕСПЛАТНЫХ игр (100% скидка) из r/steamdeals
    
    Returns:
        Список словарей с информацией об играх:
        - app_id: Steam App ID
        - title: название игры
        - steam_url: ссылка на Steam
        - discount: размер скидки
        - end_date: дата окончания акции (если доступна)
    """
    all_deals = get_deals_from_steamdeals(limit=100)
    
    # Фильтруем только 100% скидки (бесплатные игры)
    free_games = [
        game for game in all_deals 
        if game.get('discount') == '-100%'
    ]
    
    logger.info(f"Из {len(all_deals)} скидок найдено {len(free_games)} бесплатных игр")
    return free_games


def get_all_deals(min_discount: int = 50) -> List[Dict]:
    """
    Получает все скидки с минимальным порогом
    
    Args:
        min_discount: Минимальный размер скидки в процентах (например, 50 для -50% и выше)
    
    Returns:
        Список скидок, отфильтрованных по порогу
    """
    all_deals = get_deals_from_steamdeals(limit=100)
    
    filtered_deals = []
    for game in all_deals:
        discount_str = game.get('discount', '')
        # Извлекаем число из "-70%"
        match = re.search(r'-?(\d+)%', discount_str)
        if match:
            discount_value = int(match.group(1))
            if discount_value >= min_discount:
                filtered_deals.append(game)
        else:
            # Если скидка не определена, пропускаем или включаем по желанию
            pass
    
    logger.info(f"Найдено {len(filtered_deals)} скидок от -{min_discount}%")
    return filtered_deals


def get_sale_events() -> List[Dict]:
    """
    Получает информацию о Steam Sale Events
    (Упрощённая версия - проверяем посты о распродажах)
    
    Returns:
        Список словарей с информацией о распродажах
    """
    events = []
    
    # Можно расширить, парсить посты о глобальных распродажах
    # Пока возвращаем пустой список - основной фокус на скидках
    
    logger.info("Проверка событий распродаж (не реализовано для Reddit источника)")
    return events


if __name__ == "__main__":
    # Тестовый запуск
    logging.basicConfig(level=logging.INFO)
    
    print("=== Тестирование парсера r/steamdeals ===\n")
    
    print("1. Получение всех скидок...")
    deals = get_deals_from_steamdeals(limit=50)
    print(f"\nНайдено {len(deals)} скидок:")
    for deal in deals[:15]:
        print(f"  [{deal['discount']}] {deal['title']}")
        print(f"       Steam: {deal['steam_url']}")
        print(f"       Reddit score: {deal.get('reddit_score', 'N/A')}")
        print()
    
    print("\n2. Получение только бесплатных игр (-100%)...")
    free = get_free_games()
    print(f"Найдено {len(free)} бесплатных игр:")
    for game in free[:5]:
        print(f"  - {game['title']}")
    
    print("\n3. Получение крупных скидок (от -70%)...")
    big_deals = get_all_deals(min_discount=70)
    print(f"Найдено {len(big_deals)} скидок от -70%:")
    for deal in big_deals[:10]:
        print(f"  [{deal['discount']}] {deal['title']}")
