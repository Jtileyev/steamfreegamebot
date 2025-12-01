# Task 5: Создать планировщик

## Файл
`clock.py`

## Описание
Использование APScheduler для запуска задачи каждые 12 часов

## Требования
- `BlockingScheduler` из `apscheduler.schedulers.blocking`
- Интервал: `hours=12`
- Немедленный запуск при старте приложения
- Timezone: UTC

## Структура
```python
from apscheduler.schedulers.blocking import BlockingScheduler
from bot import check_and_notify
from database import init_db
import logging

# Настройка логирования
# Инициализация БД
# Создание scheduler
# Добавление job с интервалом 12 часов
# Запуск scheduler
```

## Логирование
- INFO: старт планировщика, выполнение задачи
- ERROR: критические ошибки
