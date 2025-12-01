# Task 4: Создать основную логику

## Файл
`bot.py`

## Описание
Объединение всех модулей: парсинг → фильтрация → отправка → сохранение

## Главная функция
`check_and_notify()` — выполнение полного цикла проверки и уведомлений

## Алгоритм
1. Вызвать `scraper.get_free_games()` и `scraper.get_sale_events()`
2. Для каждой игры:
   - Проверить `database.is_game_sent(app_id)`
   - Если нет → форматировать сообщение → отправить в Telegram
   - Сохранить `database.mark_game_sent(app_id, title)`
3. Для каждого события:
   - Проверить `database.is_event_sent(event_name)`
   - Если нет → форматировать сообщение → отправить в Telegram
   - Сохранить `database.mark_event_sent(event_name)`

## Требования
- Логирование через `logging` (INFO, ERROR уровни)
- Обработка исключений (сеть, БД, Telegram API)
- Graceful degradation — продолжать работу при частичных сбоях
