# Task 1: Создать модуль парсинга SteamDB

## Файл
`scraper.py`

## Описание
Использовать `requests` + `BeautifulSoup` + `lxml` для парсинга SteamDB:
- `sales/?min_discount=80&min_rating=0&min_reviews=100` — бесплатные раздачи и раздачи со скидкой
- `sales/history/all/` — информация о текущих/предстоящих Steam Sale Events

## Требования
- Извлекать: название игры, app_id, ссылку на Steam, даты акции
- Реалистичный User-Agent (Chrome/Firefox)
- Случайные задержки 1-3 сек между запросами
- Retry-логика при ошибках (сетевых, таймаутах)

## Функции
- `get_free_games()` → список словарей с информацией об играх
- `get_sale_events()` → список словарей с информацией о распродажах
