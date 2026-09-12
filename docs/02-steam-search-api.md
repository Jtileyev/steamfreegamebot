# Поиск магазина Steam как источник скидок

Этот эндпоинт заменяет Reddit. Он недокументирован: это тот же запрос, который делает сама страница поиска магазина при прокрутке. Всё ниже установлено живыми запросами 12 сентября 2026 года. Параметры проверялись сравнением `total_count` с базовым запросом при изменении ровно одного параметра.

Базовые замеры сделаны с `cc=us`, итоговый запрос с `cc=kz`. Регион влияет на состав выдачи, поэтому абсолютные числа между ними не сравнимы.

## Рекомендованный запрос

```
https://store.steampowered.com/search/results/?query&start=0&count=100&infinite=1&json=1
  &cc=kz
  &l=en
  &specials=1
  &category1=998
  &sort_by=Reviews_DESC
  &supportedlang=russian
  &hidef2p=1
  &untags=3799,4085,12095,9130,6650
```

В коде это одна строка без переносов.

| Параметр | Зачем |
|---|---|
| `count=100` | Максимум за один запрос |
| `infinite=1&json=1` | Ответ в JSON вместо целой HTML-страницы |
| `cc=kz` | Регион магазина: цены в тенге и казахстанский ассортимент |
| `l=en` | Английские подписи. Парсер отзывов и дат рассчитан на них |
| `specials=1` | Только товары со скидкой |
| `category1=998` | Только игры, без DLC, саундтреков и программ |
| `sort_by=Reviews_DESC` | Лучшие отзывы первыми и скрытый отсев товаров без отзывов |
| `supportedlang=russian` | Только игры с поддержкой русского языка |
| `hidef2p=1` | Без free-to-play |
| `untags=...` | Без Visual Novel, Anime, Sexual Content, Hentai, Nudity |

| Замер итогового запроса | Значение |
|---|---|
| Код ответа, объём, время | 200, 244 КБ, 1.5 с |
| `total_count` | 2557 |
| Строк в ответе | 100, из них 1 пакет |
| Со скидкой от 70% | 26 |
| После гейта качества: от 80% положительных и от 200 отзывов | 24 |

## Формат ответа

```json
{
  "success": 1,
  "results_html": "\n<!-- List Items -->\n<a href=...>...</a> ... ",
  "total_count": 2557,
  "start": 0
}
```

Пустая выдача выглядит так, и это не ошибка:

```json
{"success":1,"results_html":"\n<!-- List Items -->\n<!-- End List Items -->\n","total_count":0,"start":-1}
```

Ответ при превышении лимита запросов: код 429 и тело длиной 24 байта, не JSON.

## Параметры фильтрации

### Тип контента: `category1`

| Значение | Что выбирает | `total_count` со `specials=1` |
|---|---|---|
| `998` | Игры | 6439 |
| `21` | DLC | 2078 |
| `990` | Саундтреки | 160 |
| `994` | Программы | 33 |
| `996` | **Всё подряд, выборка расширяется** | 8685 |
| `10`, `992`, `997` | Ничего, смысл определить не удалось | 0 |

Пересечение игр с саундтреками и программами пустое. С DLC пересекается один пакет. Значит `category1=998` сам по себе отсекает почти весь не-игровой контент.

Несколько значений через запятую работают как ИЛИ: `998,21` дал 8494.

> **Опасно.** `996` не выдаёт ошибку, а молча пропускает DLC. Проверяйте, что `total_count` попал в ожидаемый диапазон.

### Теги: `untags` и `tags`

| Параметр | Семантика нескольких значений | Замер |
|---|---|---|
| `untags=` | ИЛИ: убрать, если есть любой из тегов | `untags=3799` дал 5808 из 6439. Семь тегов дали 2626 |
| `tags=` | И: оставить, только если есть все теги | `tags=3799` дал 631, `tags=3799,9130` дал 98 |

Выразить «Action или RPG» одним запросом нельзя. Для отсева шлака нужен `untags`.

**Жанров как отдельного параметра больше нет.** Жанры это обычные теги. `category3` означает мультиплеерные возможности: Single-player, Multi-player, PvP, Co-op, Split Screen, Cross-Platform. Старый id жанра Action, отправленный в `category3`, возвращает ноль результатов.

Словарь всех тегов, 429 штук, 15 КБ. Его достаточно скачать один раз:

```
GET https://store.steampowered.com/tagdata/populartags/english
→ [{"tagid":492,"name":"Indie"}, ...]
```

| Тег | id | | Тег | id |
|---|---|---|---|---|
| Visual Novel | 3799 | | Action | 19 |
| Anime | 4085 | | Adventure | 21 |
| Sexual Content | 12095 | | RPG | 122 |
| Hentai | 9130 | | Strategy | 9 |
| Nudity | 6650 | | Indie | 492 |
| Casual | 597 | | Simulation | 599 |
| Early Access | 493 | | Horror | 1667 |
| Free to Play | 113 | | Puzzle | 1664 |

Состав выдачи без исключений: из 100 строк базового запроса 27 помечены Anime, 27 Visual Novel, 26 Casual, 8 Sexual Content.

Два наблюдения, которые стоит учесть:

- **Casual исключать не рекомендуется.** Он уносит нормальные игры, например A Good Snowman Is Hard To Build.
- **Исключение Early Access протекает.** Две строки с тегом 493 прошли `untags=493`. Если это важно, проверяйте тег на клиенте.

### Сортировка: `sort_by`

| Значение | `total_count` | Что получается |
|---|---|---|
| `Reviews_DESC` | 6439 | Лучшие отзывы первыми. Ни одной строки без отзывов на 350 проверенных |
| по умолчанию | 8536 | Популярное и узнаваемое, но без гарантии наличия отзывов |
| `Released_DESC` | 8515 | Новинки. 80 строк из 100 без единого отзыва |
| `Price_ASC` | 8536 | Самое дешёвое. Среди первых 25 строк шесть разных SKU игры Barro по минимальной цене |
| `Price_DESC` | 8536 | Самое дорогое с неглубокими скидками. У 4 строк нет цены вообще |

**`Reviews_DESC` работает скрытым фильтром качества.** Разница в 2097 позиций это товары без отзывов, то есть ассет-флипы и мусор. Поведение недокументированное, Valve может его изменить.

**Сортировки по размеру скидки не существует.** `Discount_DESC` и любое неизвестное значение молча откатываются на сортировку по умолчанию: ответ совпадает байт в байт с заведомо битым значением `_ASC`.

### Язык: `supportedlang` и `l`

| Параметр | Фильтрует | Эффект |
|---|---|---|
| `supportedlang=russian` | да | 6439 в 2992. Из 100 строк заменились 53 |
| `l=russian` | нет | Названия игр остаются латиницей. Переводятся подписи отзывов и даты, от которых зависит парсер |

Используйте `supportedlang=russian` и `l=en`. Разницу между полной локализацией и только субтитрами этот параметр не различает.

### Регион: `cc`

`cc` меняет не только валюту, но и состав магазина. При одинаковых остальных параметрах `cc=us` дал 6439, `cc=ru` дал 6072. В российском регионе нет части игр Capcom, например Resident Evil 2.

`cc` также меняет формат даты при `l=en`: `Jul 29, 2019` для `us` и `20 Oct, 2022` для `kz`.

Выберите регион один раз и не меняйте. База отправленных привязана к региону, и смена выглядит как поток дублей.

### Цена: `maxprice`

- Фильтрует цену **после** скидки, в основных единицах валюты региона. `cc=us&maxprice=10` дал 5645 и только цены до $9.99.
- Значение должно входить в сетку цен региона. `cc=kz&maxprice=10` молча проигнорирован.
- `maxprice=free` вместе со `specials=1` 12 сентября дал ноль. Проверить на дне с активной раздачей.
- `minprice` и `min_price` не существуют.

Фильтр по цене удобнее делать на клиенте по атрибуту `data-price-final`.

### Платформа: `os`

`os=mac` и `os=linux` работают. Список через запятую не работает: `os=mac,linux` возвращает ровно то же, что `os=mac`.

### Прочее

| Параметр | Поведение |
|---|---|
| `hidef2p=1` | Работает, но эффект мал: 6439 в 6427 |
| `count` | Максимум 100. Значения до 20 округляются до 25, 200 даёт 100 |
| `start` | Невыровненное значение игнорируется: `start=20&count=25` вернул первую страницу. Глубокая постраничная выборка не проверена |
| `deck_compatibility` | Не проверялся |

## Чего нет среди параметров

Проверены все очевидные имена, ни одно не подействовало. Всё это делается на клиенте.

| Нужно | Проверенные имена | Замена на клиенте |
|---|---|---|
| Минимальная скидка | `discount`, `mindiscount`, `min_discount`, `discount_pct`, `maxdiscount` | `data-discount` |
| Минимальный рейтинг и число отзывов | `review_score`, `reviewscore`, `review_ratio`, `min_reviews`, `minreviews`, `reviews` | подсказка отзывов в строке |
| Минимальная цена | `minprice`, `min_price` | `data-price-final` |
| Исключение пакетов | нет параметра | `data-ds-itemkey` |
| Исключение предзаказов | нет параметра | дата в `search_released` |

## Ловушки

- **Неизвестный параметр молча игнорируется** с кодом 200 и прежним `total_count`. Опечатка выглядит как работающий фильтр. Любой новый параметр проверяйте сравнением с базовым запросом.
- **`total_count` зависит от сортировки**, а не только от фильтров. Не сравнивайте замеры с разными `sort_by`.
- **Строки-пакеты ломают наивный парсер.** У пакета `data-ds-itemkey="Sub_281610"`, а `data-ds-appid` содержит список app id через запятую.
- **`data-ds-tagids` обрезан до 7 тегов** в каждой строке. Фильтровать теги полностью на клиенте нельзя: 17 из 100 строк, которые сервер отнёс к тегу, не показывают его среди своих семи.
- **Хэш ответа не годится для обнаружения изменений.** Счётчики отзывов меняются между запросами. Ключ изменения это app id вместе со скидкой.
- **Подписи отзывов не годятся как гейт.** Mostly Positive при 74% всё ещё имеет класс `positive`.
- **Steam ограничивает частоту.** После примерно трёх запросов подряд с интервалом в секунду приходит 429. Один или два запроса в сутки лимит не затрагивают.

## Устройство строки ответа

Реальная строка, сокращена только картинка и обработчики мыши:

```html
<a href="https://store.steampowered.com/app/646570/Slay_the_Spire/?snr=1_7_7_2300_150_1"
   data-ds-appid="646570" data-ds-itemkey="App_646570"
   data-ds-tagids="[1091588,1666,791774,1716,32322,1677,9]" ...
   class="search_result_row ds_collapse_flag ">
  <div class="search_name ellipsis">
    <span class="title">Slay the Spire</span>
  </div>
  <div class="search_platforms">
    <span class="platform_img win"></span><span class="platform_img mac"></span><span class="platform_img linux"></span>
  </div>
  <div class="search_released responsive_secondrow">Jan 23, 2019</div>
  <div class="search_reviewscore responsive_secondrow">
    <span class="search_review_summary positive"
          data-tooltip-html="Overwhelmingly Positive&lt;br&gt;97% of the 76,885 user reviews for this game are positive.&lt;br&gt;..."></span>
  </div>
  <div class="search_price_discount_combined responsive_secondrow" data-price-final="624">
    <div class="discount_block search_discount_block" data-price-final="624" data-bundlediscount="0"
         data-discount="75" role="link" aria-label="75% off. $24.99 normally, discounted to $6.24">
      <div class="discount_pct">-75%</div>
      <div class="discount_prices">
        <div class="discount_original_price">$24.99</div>
        <div class="discount_final_price">$6.24</div>
      </div>
    </div>
  </div>
</a>
```

| Что | Откуда |
|---|---|
| app id | `data-ds-appid` |
| Тип строки | `data-ds-itemkey`: `App_`, `Sub_` или `Bundle_` |
| Название | `<span class="title">` |
| Скидка в процентах | `data-discount` |
| Цена со скидкой | `data-price-final`, в минимальных единицах валюты: центах или тиынах |
| Процент положительных и число отзывов | `data-tooltip-html` у `search_review_summary` |
| Теги | `data-ds-tagids`, первые 7 |
| Платформы | классы `platform_img` |
| Дата выхода | `search_released`, формат зависит от `cc` |

У строки без отзывов контейнер `search_reviewscore` есть, а `span` внутри нет. Это главный признак шлака.

Подсказка отзывов закодирована HTML-сущностями: перевод строки лежит как текст `&lt;br&gt;`. У 59 строк из 100 после основной фразы дописано ещё одно предложение, поэтому регулярку нельзя привязывать к концу атрибута. Число отзывов приходит с запятыми.

## Эталонный парсер

Проверен на трёх сохранённых ответах. Итоговый запрос: 99 игр разобрано, 24 отобрано. Базовый запрос с `cc=us`: 99 и 19. Сортировка по дате выхода: из 100 строк разобрано 20, остальные без отзывов, отобрано 0.

```python
import re
from typing import List, Dict, Optional

ROW_SPLIT = re.compile(r'(?=<a href="https://store\.steampowered\.com/(?:app|sub|bundle)/)')
ITEM_KEY = re.compile(r'data-ds-itemkey="(\w+)_')
APP_ID = re.compile(r'data-ds-appid="(\d+)"')
TITLE = re.compile(r'<span class="title">(.*?)</span>', re.S)
DISCOUNT = re.compile(r'data-discount="(\d+)"')
PRICE_FINAL = re.compile(r'data-price-final="(\d+)"')
TAG_IDS = re.compile(r'data-ds-tagids="\[([\d,]*)\]"')
RELEASED = re.compile(r'<div class="search_released[^"]*">\s*(.*?)\s*</div>', re.S)
REVIEW = re.compile(
    r'search_review_summary\s+(positive|mixed|negative)"\s+'
    r'data-tooltip-html="([^&"]+)&lt;br&gt;(\d{1,3})% of the ([\d,]+) u'
)


def parse_results(results_html: str) -> List[Dict]:
    """Разбирает results_html. Пакеты и строки без скидки или без отзывов отбрасываются."""
    games = []
    for row in ROW_SPLIT.split(results_html)[1:]:
        key = ITEM_KEY.search(row)
        if not key or key.group(1) != 'App':
            continue  # Sub_/Bundle_: data-ds-appid там список через запятую
        app_id, title, discount = APP_ID.search(row), TITLE.search(row), DISCOUNT.search(row)
        if not (app_id and title and discount):
            continue
        review = REVIEW.search(row)
        if not review:
            continue  # нет ни одного отзыва: главный признак шлака
        price = PRICE_FINAL.search(row)
        tags = TAG_IDS.search(row)
        released = RELEASED.search(row)
        games.append({
            'app_id': app_id.group(1),
            'title': title.group(1).strip(),
            'discount': int(discount.group(1)),
            'price_final_minor': int(price.group(1)) if price else None,
            'review_label': review.group(2),
            'review_pct': int(review.group(3)),
            'review_count': int(review.group(4).replace(',', '')),
            'tag_ids': [int(t) for t in tags.group(1).split(',') if t] if tags else [],
            'released': released.group(1).strip() if released else None,
            'steam_url': f"https://store.steampowered.com/app/{app_id.group(1)}",
        })
    return games


def select_deals(games: List[Dict], min_discount: int = 70,
                 min_review_pct: int = 80, min_reviews: int = 200,
                 exclude_tags: Optional[set] = None) -> List[Dict]:
    """Клиентские фильтры, которых нет среди параметров Steam."""
    exclude_tags = exclude_tags or set()
    return sorted(
        (g for g in games
         if g['discount'] >= min_discount
         and g['review_pct'] >= min_review_pct
         and g['review_count'] >= min_reviews
         and not exclude_tags.intersection(g['tag_ids'])),
        key=lambda g: -g['discount'],
    )
```

Название приходит с HTML-сущностями, например `&amp;`. Перед отправкой в Telegram его нужно пропустить через `html.unescape`, а затем экранировать для MarkdownV2.

Получение ответа:

```python
import requests

resp = requests.get(STEAM_SEARCH_URL, timeout=20,
                    headers={'User-Agent': 'SteamDealsBot/2.0'})
if resp.status_code == 429:
    ...  # повторить позже, это не пустая выдача
resp.raise_for_status()
data = resp.json()
deals = select_deals(parse_results(data['results_html']))
```

## Гейт качества

Пороги по умолчанию: скидка от 70%, от 80% положительных отзывов, от 200 отзывов. На итоговом запросе гейт убрал 2 из 26 кандидатов:

| Игра | Скидка | Положительных | Отзывов |
|---|---|---|---|
| Rising Storm Game of the Year Edition | 90% | 98% | 86 |
| CPU Invaders - 3i Atlas | 90% | 98% | 82 |

Обе прошли бы при пороге от 50 отзывов. Это редакционный выбор.

При `sort_by=Reviews_DESC` гейт почти ничего не режет, потому что сортировка уже вывела лучшее вперёд. Его настоящая ценность в защите на случай смены сортировки.

## Что учесть в логике дедупликации

Скидка в Steam обычно держится несколько дней или недель и всё это время присутствует в выдаче. С Reddit пост уходил из ленты сам. Текущее правило «повторить через 7 дней» при Steam-источнике будет повторять одну и ту же распродажу каждую неделю.

Разумный ключ дедупликации: app id вместе с процентом скидки. Повторная отправка только при изменении скидки. Дата окончания скидки в строке поиска отсутствует. Эндпоинт `api/featuredcategories` отдаёт поле `discount_expiration`, но для этого бота он не проверялся.
