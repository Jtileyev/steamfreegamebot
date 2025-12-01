# Steam Free Game Bot 🎮

Telegram-бот для отслеживания бесплатных игр и распродаж в Steam.

## Функции

- 🎮 Отслеживание бесплатных раздач игр в Steam (скидка 100%)
- 🏷️ Уведомления о Steam Sale Events
- 📊 Хранение истории отправленных уведомлений в PostgreSQL
- ⏰ Автоматическая проверка каждые 12 часов

## Технологии

- **Python 3.11** - основной язык
- **BeautifulSoup4 + lxml** - парсинг SteamDB
- **psycopg2** - работа с PostgreSQL
- **APScheduler** - планировщик задач
- **Telegram Bot API** - отправка уведомлений

## Структура проекта

```
steam_free_game_bot/
├── config.py           # Загрузка переменных окружения
├── scraper.py          # Парсинг SteamDB
├── database.py         # Работа с PostgreSQL
├── telegram_client.py  # Отправка в Telegram
├── bot.py              # Основная логика
├── clock.py            # Планировщик (точка входа)
├── requirements.txt    # Зависимости
├── Procfile           # Конфиг для Heroku
├── runtime.txt        # Версия Python
└── .env.example       # Пример переменных окружения
```

## Установка и запуск

### Шаг 1: Создать Telegram бота

1. Откройте [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте команду `/newbot`
3. Следуйте инструкциям и сохраните токен бота

### Шаг 2: Получить Chat ID

1. Отправьте боту любое сообщение
2. Откройте в браузере:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
3. Найдите `"chat":{"id":123456789}` в JSON-ответе
4. Сохраните этот ID

### Шаг 3: Локальный запуск

```bash
# Клонируйте репозиторий
git clone <repo-url>
cd steam_free_game_bot

# Создайте виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate     # Windows

# Установите зависимости
pip install -r requirements.txt

# Скопируйте и заполните .env
cp .env.example .env
# Отредактируйте .env с вашими данными

# Запустите
python clock.py
```

### Шаг 4: Настройка базы данных

1. Создайте бесплатную PostgreSQL базу данных на одном из провайдеров (рекомендуется [Neon](https://neon.tech))
2. Скопируйте connection string
3. Добавьте его в переменную `DATABASE_URL`

### Шаг 5: Деплой на Heroku

```bash
# Установите Heroku CLI и авторизуйтесь
heroku login

# Создайте приложение
heroku create your-steam-bot-name

# Установите переменные окружения
heroku config:set DATABASE_URL="postgresql://user:pass@host/dbname?sslmode=require"
heroku config:set TELEGRAM_BOT_TOKEN=your_token_here
heroku config:set TELEGRAM_CHAT_ID=your_chat_id_here

# Деплой
git push heroku main

# Запустите worker
heroku ps:scale clock=1

# Просмотр логов
heroku logs --tail
```

### Альтернатива: Деплой на Railway

```bash
# Railway автоматически создаст PostgreSQL
railway login
railway init
railway add postgresql
railway up
```

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `DATABASE_URL` | PostgreSQL connection string (см. примеры ниже) |
| `TELEGRAM_BOT_TOKEN` | Токен бота от @BotFather |
| `TELEGRAM_CHAT_ID` | ID чата для отправки уведомлений |

### Бесплатные облачные PostgreSQL провайдеры

| Провайдер | Бесплатный план | Формат URL |
|-----------|-----------------|------------|
| [Neon](https://neon.tech) | 0.5 GB | `postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require` |
| [Supabase](https://supabase.com) | 500 MB | `postgresql://postgres:pass@db.xxx.supabase.co:5432/postgres` |
| [Railway](https://railway.app) | $5 кредит | `postgresql://postgres:pass@xxx.railway.app:5432/railway` |
| [ElephantSQL](https://elephantsql.com) | 20 MB | `postgresql://user:pass@xxx.db.elephantsql.com/dbname` |
| [Render](https://render.com) | 90 дней | `postgresql://user:pass@xxx.oregon-postgres.render.com/dbname` |

## Шаблоны сообщений

### Бесплатная игра
```
🎮 Бесплатная игра в Steam!

**Название игры**
🔗 Получить в Steam
⏰ До: дата окончания
```

### Steam Sale Event
```
🔥 АКТИВНО СЕЙЧАС!
🏷️ Steam Sale Event

**Название события**
📅 даты проведения
🔗 Подробнее на SteamDB
```

## Разработка

```bash
# Запуск одиночной проверки (для тестирования)
python bot.py

# Тест парсера
python scraper.py

# Тест базы данных
python database.py

# Тест форматирования сообщений
python telegram_client.py
```

## Лицензия

MIT License
