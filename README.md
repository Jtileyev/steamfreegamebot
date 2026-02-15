# Steam Deals Bot 🎮

Telegram-бот для отслеживания скидок на игры в Steam через Reddit r/steamdeals.

## Функции

- 🔥 Отслеживание скидок в Steam (настраиваемый порог, по умолчанию от -70%)
- 🎮 Отдельное отслеживание бесплатных раздач (-100%)
- 🏷️ Уведомления о Steam Sale Events
- 📊 Хранение истории в SQLite (без внешних зависимостей)
- 🔄 Умная дедупликация — повторная отправка при увеличении скидки или через N дней
- ⏰ Автоматическая проверка каждые 12 часов

## Технологии

- **Python 3.11** — основной язык
- **requests** — HTTP-запросы к Reddit RSS/JSON
- **lxml + xml.etree** — парсинг RSS feed
- **SQLite** — хранение истории уведомлений
- **APScheduler** — планировщик задач
- **Telegram Bot API** — отправка уведомлений

## Структура проекта

```
steam-deals-bot/
├── config.py              # Загрузка переменных окружения
├── scraper.py             # Парсинг r/steamdeals (RSS + JSON fallback)
├── database.py            # Работа с SQLite
├── telegram_client.py     # Отправка в Telegram
├── bot.py                 # Основная логика
├── clock.py               # Планировщик (точка входа)
├── requirements.txt       # Зависимости
├── steam-deals-bot.service # systemd unit-файл
├── .env.example           # Пример переменных окружения
└── data/
    └── steam_bot.db       # SQLite база (создаётся автоматически)
```

## Установка и запуск

### 1. Создать Telegram бота

1. Откройте [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot`, следуйте инструкциям
3. Сохраните токен бота

### 2. Получить Chat ID

1. Отправьте боту любое сообщение
2. Откройте в браузере:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
3. Найдите `"chat":{"id":123456789}` — это ваш Chat ID

### 3. Локальный запуск

```bash
git clone <repo-url>
cd steam-deals-bot

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Заполните .env своими данными

# Одиночная проверка (тест)
python3 bot.py

# Запуск с планировщиком (каждые 12 часов)
python3 clock.py
```

### 4. Деплой на сервер (systemd)

```bash
# Копируем проект
sudo mkdir -p /opt/steam-deals-bot
sudo cp -r . /opt/steam-deals-bot/

# Создаём пользователя для сервиса
sudo useradd -r -s /bin/false steam-bot
sudo chown -R steam-bot:steam-bot /opt/steam-deals-bot

# Заполняем .env
sudo cp /opt/steam-deals-bot/.env.example /opt/steam-deals-bot/.env
sudo nano /opt/steam-deals-bot/.env

# Устанавливаем зависимости
pip3 install -r /opt/steam-deals-bot/requirements.txt

# Устанавливаем и запускаем сервис
sudo cp /opt/steam-deals-bot/steam-deals-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable steam-deals-bot
sudo systemctl start steam-deals-bot
```

### Управление сервисом

```bash
sudo systemctl status steam-deals-bot    # Статус
sudo systemctl restart steam-deals-bot   # Перезапуск
sudo systemctl stop steam-deals-bot      # Остановка
sudo journalctl -u steam-deals-bot -f    # Логи в реальном времени
```

## Переменные окружения

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `DATABASE_PATH` | Путь к файлу SQLite | `data/steam_bot.db` |
| `TELEGRAM_BOT_TOKEN` | Токен бота от @BotFather | — (обязательно) |
| `TELEGRAM_CHAT_ID` | ID чата для уведомлений | — (обязательно) |
| `MIN_DISCOUNT_PERCENT` | Минимальный порог скидки (%) | `70` |

## Шаблоны сообщений

### Скидка на игру
```
🔥 Скидка -90% в Steam!

Название игры
🔗 Купить в Steam
👍 Reddit: 150
💬 Обсуждение
```

### Steam Sale Event
```
🔥 АКТИВНО СЕЙЧАС!
🏷️ Steam Sale Event

Название события
📅 даты проведения
🔗 Подробнее на SteamDB
```

## Разработка

```bash
# Одиночная проверка
python3 bot.py

# Тест скрапера
python3 scraper.py

# Тест форматирования сообщений
python3 telegram_client.py
```

## Лицензия

MIT License
