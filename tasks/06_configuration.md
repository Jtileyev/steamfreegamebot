# Task 6: Настроить конфигурацию и деплой

## Файлы для создания

### `config.py`
Загрузка переменных окружения через `python-dotenv`
- `DATABASE_URL` — Heroku Postgres connection string
- `TELEGRAM_BOT_TOKEN` — токен бота от @BotFather
- `TELEGRAM_CHAT_ID` — ID чата для уведомлений

### `Procfile`
```
clock: python clock.py
```

### `requirements.txt`
```
APScheduler>=3.10.0,<4.0.0
requests>=2.31.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
psycopg2-binary>=2.9.0
python-dotenv>=1.0.0
```

### `runtime.txt`
```
python-3.11.6
```

### `.env.example`
```
DATABASE_URL=postgresql://user:password@host:5432/dbname
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
```

### `.gitignore`
```
.env
*.pyc
__pycache__/
venv/
*.db
*.sqlite
```

## Инструкции по деплою (для README)

### Шаг 1: Создать Telegram бота
1. Написать @BotFather в Telegram
2. Выполнить `/newbot`
3. Сохранить токен

### Шаг 2: Получить Chat ID
1. Написать боту любое сообщение
2. Открыть `https://api.telegram.org/bot{TOKEN}/getUpdates`
3. Найти `chat.id` в JSON

### Шаг 3: Деплой на Heroku
```bash
heroku create your-steam-bot
heroku addons:create heroku-postgresql:essential-0
heroku config:set TELEGRAM_BOT_TOKEN=your_token
heroku config:set TELEGRAM_CHAT_ID=your_chat_id
git push heroku main
heroku ps:scale clock=1
heroku logs --tail
```
