# Хостинг

## Решение

Бот переезжает на отдельный VPS. Нагрузка ничтожная: один HTTP-запрос к источнику и несколько сообщений в Telegram раз или два в сутки. Подойдёт минимальный тариф любого провайдера.

| Требование | Значение |
|---|---|
| Процессор и память | минимальные, процесс большую часть времени спит |
| Диск | десятки мегабайт: код, venv, база SQLite |
| Сеть | только исходящий HTTPS к Steam и `api.telegram.org` |
| Входящие порты | не нужны |
| Python | 3.10 или новее. В 3.12 `datetime.utcnow` помечен устаревшим, но работает |

## Почему не Vercel

Вариант переписать бота под бесплатный тариф Vercel Hobby рассматривался и был отклонён. Лимиты сверены с документацией Vercel 12 сентября 2026 года.

| Ограничение Hobby | Значение | Последствие для бота | Источник |
|---|---|---|---|
| Интервал cron | не чаще раза в сутки. Более частое выражение валит деплой | Проверка каждые 12 часов невозможна | [cron usage and pricing](https://vercel.com/docs/cron-jobs/usage-and-pricing) |
| Точность запуска | в пределах часа | неважно | там же |
| Число cron-задач | 100 на проект | неважно | там же |
| Доставка cron | best effort: запуск может пропасть без записи в логе или прийти дважды | Нужна идемпотентность | [managing cron jobs](https://vercel.com/docs/cron-jobs/manage-cron-jobs) |
| Повтор при сбое | Vercel не повторяет упавший запуск | Сутки потеряны | там же |
| Длительность функции | 300 секунд | хватает | [functions limitations](https://vercel.com/docs/functions/limitations) |
| Файловая система | только чтение, кроме временного `/tmp` до 500 МБ | SQLite не переживает запуск, нужна внешняя база | [functions runtimes](https://vercel.com/docs/functions/runtimes) |
| Использование | только личное некоммерческое. Партнёрские ссылки прямо названы коммерческим использованием | Монетизация канала потребует платного тарифа | [fair use guidelines](https://vercel.com/docs/limits/fair-use-guidelines) |

Технически Vercel возможен: суточного запуска хватает, потому что лента Reddit хранит около 69 часов истории, а поиск Steam отдаёт все текущие скидки сразу. Но переезд требует переписать планировщик и хранилище, добавить внешнюю базу и сторонний планировщик для второго запуска. На VPS текущий код работает почти как есть.

## Почему не GitHub Actions

Бот уже работал на GitHub Actions до коммита `03a11fa`, тогда база жила во внешнем PostgreSQL. Минимальный интервал cron 5 минут, но при высокой нагрузке запуски задерживаются, особенно в начало часа. На публичном репозитории расписание само отключается после 60 дней без активности. Источник: [events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows). Файловая система между запусками не сохраняется, базу пришлось бы хранить в отдельной ветке или внешнем сервисе.

## Что было сломано в прежнем systemd-юните

1. `ExecStart` указывал на `venv/bin/python3`, а каталога `venv` не существовало.
2. `User=steam-bot` указывал на несуществующего пользователя.
3. Каталог `data/` и файл базы принадлежали root. Сервисный пользователь не смог бы писать в базу, `init_db` упал бы.
4. При ошибке конфига или базы [clock.py](../clock.py#L52) выходит с кодом 0. `Restart=on-failure` такой выход не перезапускает, и сервис молча останавливается.

## Развёртывание на VPS

Пути ниже используют `/opt/steam-deals-bot`. Если выберете другой, замените везде, включая юнит.

### 1. Пользователь и код

Репозиторий приватный. Для клонирования на сервере нужен deploy key или SSH-ключ с доступом к репозиторию.

```bash
sudo useradd --system --home-dir /opt/steam-deals-bot --shell /usr/sbin/nologin steam-bot
sudo git clone git@github.com:Jtileyev/steamfreegamebot.git /opt/steam-deals-bot
cd /opt/steam-deals-bot
```

### 2. Окружение

```bash
sudo apt install -y python3-venv
sudo python3 -m venv venv
sudo venv/bin/pip install -r requirements.txt
```

### 3. Секреты и права

```bash
sudo cp .env.example .env
sudo nano .env

sudo chown root:steam-bot .env
sudo chmod 640 .env

sudo mkdir -p data
sudo chown steam-bot:steam-bot data
```

`.env` должен быть читаем для группы сервиса. systemd читает `EnvironmentFile` от root, но [config.py](../config.py#L7) дополнительно вызывает `load_dotenv()` уже от имени сервисного пользователя. Если файл недоступен, импорт упадёт с `PermissionError`.

Токен бота надо выпустить заново через @BotFather командой `/revoke`. Старый токен семь месяцев лежал в файле с правами 644 и мог попадать в логи при сетевых ошибках.

### 4. Юнит

`/etc/systemd/system/steam-deals-bot.service`:

```ini
[Unit]
Description=Steam Deals Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=steam-bot
Group=steam-bot
WorkingDirectory=/opt/steam-deals-bot
EnvironmentFile=/opt/steam-deals-bot/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/steam-deals-bot/venv/bin/python clock.py
Restart=on-failure
RestartSec=30

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/opt/steam-deals-bot/data

[Install]
WantedBy=multi-user.target
```

`Restart=on-failure` работает правильно только после исправления кода выхода в `clock.py`. До исправления поставьте `Restart=always`.

`ProtectSystem=strict` делает всю файловую систему доступной только на чтение, кроме `ReadWritePaths`. Если бот начнёт писать куда-то ещё, например в лог-файл, добавьте путь туда.

### 5. Запуск

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now steam-deals-bot
sudo systemctl status steam-deals-bot
sudo journalctl -u steam-deals-bot -f
```

### 6. Первый запуск

На пустой базе бот сразу отправит все подходящие скидки. На поиске Steam это около двух десятков сообщений за раз. Если это нежелательно, перед первым запуском нужен режим, который помечает текущие скидки отправленными без публикации. Такого режима пока нет, он в [04-roadmap.md](04-roadmap.md).

## Сеть

Reddit ограничивает запросы на один IP-адрес очень жёстко, а к адресам дата-центров относится хуже, чем к домашним. На VPS RSS-лента может отвечать 403 или 429 чаще, чем на старом сервере. Это ещё один довод за переход на поиск Steam.

Steam отвечает 429 после примерно трёх запросов подряд с интервалом в секунду. Бот делает один запрос за цикл и лимит не затрагивает. При ручной отладке делайте паузы между запросами.
