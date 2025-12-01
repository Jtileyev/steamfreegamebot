# Task 2: Создать модуль БД

## Файл
`database.py`

## Описание
Подключение к Heroku Postgres через `psycopg2` и переменную окружения `DATABASE_URL`

## Таблицы
### `sent_games`
- `app_id` (PRIMARY KEY) — Steam App ID
- `title` — название игры
- `sent_at` — timestamp отправки

### `sent_events`
- `event_name` (PRIMARY KEY) — название события
- `sent_at` — timestamp отправки

## Функции
- `init_db()` — создание таблиц (CREATE TABLE IF NOT EXISTS)
- `is_game_sent(app_id)` → bool
- `mark_game_sent(app_id, title)` → void
- `is_event_sent(event_name)` → bool
- `mark_event_sent(event_name)` → void
- `get_connection()` — получение соединения с БД
