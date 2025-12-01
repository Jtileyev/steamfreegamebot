# Task 3: Создать модуль Telegram

## Файл
`telegram_client.py`

## Описание
Отправка сообщений в Telegram Bot API с форматированием MarkdownV2

## Требования
- API endpoint: `https://api.telegram.org/bot{token}/sendMessage`
- Параметры: `chat_id`, `text`, `parse_mode=MarkdownV2`
- Экранирование спецсимволов MarkdownV2: `_*[]()~`>#+-=|{}.!`

## Шаблоны сообщений

### Бесплатная игра
```
🎮 **Бесплатная игра в Steam!**

**{название игры}**
🔗 [Получить в Steam]({ссылка})
⏰ До: {дата окончания}
```

### Steam Sale Event
```
🏷️ **Steam Sale Event**

**{название события}**
📅 {даты проведения}
🔗 [Подробнее на SteamDB]({ссылка})
```

## Функции
- `escape_markdown(text)` → escaped text
- `send_message(bot_token, chat_id, text)` → response
- `format_free_game_message(game_data)` → formatted text
- `format_sale_event_message(event_data)` → formatted text
