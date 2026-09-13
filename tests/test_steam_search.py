import re
import unittest
from unittest import mock

import requests

import config
import steam_search
from tests.helpers import TempDbTestCase, load_fixture, make_deal

FIXTURE_TOTAL = 2525


def row(item_key='App_100', app_id='100', title='Game', discount='80', review=True, tags='492,19'):
    review_html = (
        '<span class="search_review_summary positive" data-tooltip-html="Very Positive&lt;br&gt;'
        '91% of the 1,234 user reviews for this game are positive.&lt;br&gt;extra"></span>'
        if review else ''
    )
    return (
        f'<a href="https://store.steampowered.com/app/{app_id}/X/?snr=1" '
        f'data-ds-appid="{app_id}" data-ds-itemkey="{item_key}" data-ds-tagids="[{tags}]" class="search_result_row">'
        f'<span class="title">{title}</span>'
        f'<div class="search_released responsive_secondrow">\n 1 Aug, 2017 </div>'
        f'<div class="search_reviewscore responsive_secondrow">{review_html}</div>'
        f'<div class="search_price_discount_combined" data-price-final="112500">'
        f'<div class="discount_block" data-price-final="112500" data-bundlediscount="0" data-discount="{discount}">'
        f'<div class="discount_pct">-{discount}%</div><div class="discount_prices">'
        f'<div class="discount_original_price">4 500,00₸</div>'
        f'<div class="discount_final_price">1 125,00₸</div></div></div></div></a>'
    )


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.data = load_fixture('steam_search_kz.json')

    def test_live_fixture(self):
        html = self.data['results_html']
        games = steam_search.parse_results(html)
        self.assertEqual(len(steam_search.split_rows(html)), 100)
        self.assertEqual(len(games), 99)  # одна строка это пакет Sub_
        for game in games:
            self.assertTrue(game['app_id'].isdigit())
            self.assertTrue(game['title'])
            self.assertTrue(game['price_final'].endswith('₸'))
            self.assertGreater(game['review_count'], 0)
            self.assertLessEqual(len(game['tag_ids']), 7)

        slime = next(g for g in games if g['app_id'] == '433340')
        self.assertEqual(slime['title'], 'Slime Rancher')
        self.assertEqual(slime['discount'], 75)
        self.assertEqual(slime['price_final'], '1 125,00₸')
        self.assertEqual(slime['price_original'], '4 500,00₸')
        self.assertEqual(slime['price_final_minor'], 112500)
        self.assertEqual(slime['review_pct'], 98)
        self.assertEqual(slime['review_count'], 65687)
        self.assertEqual(slime['released'], '1 Aug, 2017')

    def test_live_fixture_selection(self):
        games = steam_search.parse_results(self.data['results_html'])
        deals = steam_search.select_deals(games, 70, 80, 200, [3799, 4085, 12095, 9130, 6650])
        self.assertEqual(len(deals), 24)
        discounts = [d['discount'] for d in deals]
        self.assertEqual(discounts, sorted(discounts, reverse=True))
        self.assertTrue(all(d['review_count'] >= 200 and d['review_pct'] >= 80 for d in deals))

    def test_attribute_order_does_not_break_split(self):
        html = self.data['results_html'].replace(
            '<a href="https://store.steampowered.com/', '<a class="row" href="https://store.steampowered.com/')
        self.assertEqual(len(steam_search.parse_results(html)), 99)

    def test_review_count_separator_variants(self):
        html = self.data['results_html']
        for sep in (' ', '.', '\u00a0', '\u202f'):
            changed = re.sub(r'(% of the )(\d{1,3}),(\d{3})', lambda m: m.group(1) + m.group(2) + sep + m.group(3), html)
            games = {g['app_id']: g for g in steam_search.parse_results(changed)}
            self.assertEqual(len(games), 99, repr(sep))
            self.assertEqual(games['433340']['review_count'], 65687, repr(sep))

    def test_row_fields(self):
        game = steam_search.parse_row(row(title='Tom &amp; Jerry&#39;s'))
        self.assertEqual(game['title'], "Tom & Jerry's")
        self.assertEqual(game['review_pct'], 91)
        self.assertEqual(game['review_count'], 1234)
        self.assertEqual(game['tag_ids'], [492, 19])
        self.assertEqual(game['steam_url'], 'https://store.steampowered.com/app/100')

    def test_package_row_skipped(self):
        self.assertIsNone(steam_search.parse_row(row(item_key='Sub_281610', app_id='1,2,3')))
        self.assertIsNone(steam_search.parse_row(row(item_key='Bundle_5')))

    def test_row_without_reviews_skipped(self):
        self.assertIsNone(steam_search.parse_row(row(review=False)))

    def test_empty_tags(self):
        self.assertEqual(steam_search.parse_row(row(tags=''))['tag_ids'], [])


class SelectTests(unittest.TestCase):
    def test_thresholds_are_inclusive(self):
        games = [
            make_deal('1', discount=69),
            make_deal('2', discount=70, review_pct=80, review_count=200),
            make_deal('3', discount=90, review_pct=79),
            make_deal('4', discount=90, review_count=199),
            make_deal('5', discount=95, tag_ids=[3799]),
        ]
        deals = steam_search.select_deals(games, 70, 80, 200, [3799])
        self.assertEqual([d['app_id'] for d in deals], ['2'])

    def test_duplicates_keep_max_discount(self):
        games = [make_deal('1', discount=75), make_deal('1', discount=85), make_deal('1', discount=80)]
        deals = steam_search.select_deals(games, 70, 0, 0)
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0]['discount'], 85)

    def test_sort_order(self):
        games = [make_deal('1', 75, review_pct=90), make_deal('2', 90), make_deal('3', 75, review_pct=99)]
        self.assertEqual([d['app_id'] for d in steam_search.select_deals(games, 70, 0, 0)], ['2', '3', '1'])


class BuildParamsTests(unittest.TestCase):
    def test_recommended_query(self):
        params = steam_search.build_params('kz', [3799, 4085])
        self.assertEqual(params['cc'], 'kz')
        self.assertEqual(params['untags'], '3799,4085')
        for key, value in {'specials': '1', 'category1': '998', 'sort_by': 'Reviews_DESC', 'start': '0',
                           'supportedlang': 'russian', 'l': 'en', 'json': '1', 'count': '100'}.items():
            self.assertEqual(params[key], value)

    def test_no_untags_when_empty(self):
        self.assertNotIn('untags', steam_search.build_params('kz', []))

    def test_start(self):
        self.assertEqual(steam_search.build_params('kz', [], start=200)['start'], '200')


def response(status=200, json_data=None, body=b''):
    resp = mock.Mock()
    resp.status_code = status
    resp.content = body
    if json_data is None:
        resp.json.side_effect = ValueError('not json')
    else:
        resp.json.return_value = json_data
    return resp


@mock.patch('steam_search.time.sleep')
class GetDealsTests(TempDbTestCase):
    def setUp(self):
        super().setUp()
        self.data = load_fixture('steam_search_kz.json')

    def get(self, *responses):
        return mock.patch('steam_search.requests.get', side_effect=list(responses))

    def ok(self, **overrides):
        return response(json_data=dict(self.data, **overrides))

    def test_success(self, sleep):
        with self.get(self.ok()) as get:
            result = steam_search.get_deals(previous_total_count=FIXTURE_TOTAL)
        self.assertEqual(get.call_count, 1)
        self.assertEqual((result.total_count, result.rows, len(result.games), len(result.deals)),
                         (2525, 100, 99, 24))
        self.assertFalse(result.language_checked)
        sleep.assert_not_called()

    def test_config_reaches_request_and_selection(self, sleep):
        with mock.patch.object(config, 'STEAM_CC', 'us'), \
                mock.patch.object(config, 'EXCLUDE_TAG_IDS', [597]), \
                mock.patch.object(config, 'MIN_DISCOUNT_PERCENT', 85), \
                mock.patch.object(config, 'MIN_REVIEWS', 5000):
            with self.get(self.ok()) as get:
                result = steam_search.get_deals(previous_total_count=FIXTURE_TOTAL)
        params = get.call_args.kwargs['params']
        self.assertEqual((params['cc'], params['untags']), ('us', '597'))
        self.assertTrue(result.deals)
        self.assertTrue(all(d['discount'] >= 85 and d['review_count'] >= 5000 for d in result.deals))

    def test_review_pct_and_tag_exclusion_reach_selection(self, sleep):
        games = steam_search.parse_results(self.data['results_html'])
        tag = next(t for g in games if g['discount'] >= 70 for t in g['tag_ids'])
        with mock.patch.object(config, 'MIN_REVIEW_PCT', 97), mock.patch.object(config, 'EXCLUDE_TAG_IDS', [tag]):
            with self.get(self.ok()):
                result = steam_search.get_deals(previous_total_count=FIXTURE_TOTAL)
        self.assertTrue(result.deals)
        self.assertTrue(all(d['review_pct'] >= 97 and tag not in d['tag_ids'] for d in result.deals))

    def test_delays_are_sane(self, sleep):
        self.assertGreaterEqual(steam_search.PAGE_DELAY_SECONDS, 10)
        self.assertGreaterEqual(steam_search.RETRY_DELAY_SECONDS, 30)
        self.assertGreaterEqual(steam_search.FETCH_ATTEMPTS, 2)

    def test_429_is_error_not_empty(self, sleep):
        with self.get(*[response(429, body=b'x' * 24)] * 2) as get:
            with self.assertRaisesRegex(steam_search.SourceError, '429'):
                steam_search.get_deals(previous_total_count=FIXTURE_TOTAL)
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(steam_search.RETRY_DELAY_SECONDS)

    def test_retry_then_success(self, sleep):
        with self.get(response(429), self.ok()):
            result = steam_search.get_deals(previous_total_count=FIXTURE_TOTAL)
        self.assertEqual(len(result.deals), 24)
        sleep.assert_called_once_with(steam_search.RETRY_DELAY_SECONDS)

    def test_permanent_errors_not_retried(self, sleep):
        for resp in (response(404, json_data={}), response(json_data={'success': 2})):
            with self.get(resp) as get:
                with self.assertRaises(steam_search.SourceError):
                    steam_search.get_deals(previous_total_count=FIXTURE_TOTAL)
            self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()

    def test_non_json(self, sleep):
        with self.get(*[response(200, body=b'<html>')] * 2):
            with self.assertRaisesRegex(steam_search.SourceError, 'не JSON'):
                steam_search.get_deals(previous_total_count=FIXTURE_TOTAL)

    def test_server_error(self, sleep):
        with self.get(*[response(503, json_data={})] * 2):
            with self.assertRaisesRegex(steam_search.SourceError, '503'):
                steam_search.get_deals(previous_total_count=FIXTURE_TOTAL)

    def test_network_error(self, sleep):
        error = requests.exceptions.ConnectionError('boom')
        with mock.patch('steam_search.requests.get', side_effect=error):
            with self.assertRaisesRegex(steam_search.SourceError, 'ConnectionError'):
                steam_search.get_deals(previous_total_count=FIXTURE_TOTAL)

    def test_success_flag(self, sleep):
        with self.get(self.ok(success=2)):
            with self.assertRaisesRegex(steam_search.SourceError, 'success'):
                steam_search.get_deals(previous_total_count=FIXTURE_TOTAL)

    def test_total_count_above_range(self, sleep):
        with self.get(self.ok(total_count=16724)):
            with self.assertRaisesRegex(steam_search.SourceError, 'total_count=16724'):
                steam_search.get_deals(previous_total_count=FIXTURE_TOTAL)

    def test_total_count_below_range(self, sleep):
        empty = {'success': 1, 'results_html': '\n<!-- List Items -->\n<!-- End List Items -->\n',
                 'total_count': 0, 'start': -1}
        with self.get(response(json_data=empty)):
            with self.assertRaisesRegex(steam_search.SourceError, 'total_count=0'):
                steam_search.get_deals(previous_total_count=FIXTURE_TOTAL)

    def assert_markup_error(self, results_html, pattern):
        with self.get(self.ok(results_html=results_html)):
            with self.assertRaisesRegex(steam_search.SourceError, pattern):
                steam_search.get_deals(previous_total_count=FIXTURE_TOTAL)

    def test_empty_list_with_total_in_range(self, sleep):
        self.assert_markup_error('\n<!-- List Items -->\n<!-- End List Items -->\n', 'разметка')

    def test_row_anchor_changed(self, sleep):
        html = self.data['results_html'].replace('data-ds-itemkey=', 'data-ds-item-key=')
        self.assert_markup_error(html, 'разметка')

    def test_review_markup_changed(self, sleep):
        html = self.data['results_html'].replace('search_review_summary', 'review_summary_v2')
        self.assert_markup_error(html, 'разметка')

    def test_partial_parse_failure(self, sleep):
        html = self.data['results_html'].replace('% of the ', '% из ', 60)
        self.assert_markup_error(html, 'разобрано')

    def test_rows_not_split(self, sleep):
        html = self.data['results_html'].replace('<a href=', '<div href=')
        self.assert_markup_error(html, 'не разделяются')

    def test_review_tooltip_partly_changed(self, sleep):
        html = self.data['results_html'].replace('% of the ', '% из ', 20)
        self.assert_markup_error(html, 'строк с отзывами')

    def test_specials_ignored(self, sleep):
        html = self.data['results_html'].replace('data-discount="', 'data-discount="0" data-x="')
        self.assert_markup_error(html, 'specials')


@mock.patch('steam_search.time.sleep')
class LanguageCheckTests(TempDbTestCase):
    def setUp(self):
        super().setUp()
        self.data = load_fixture('steam_search_kz.json')

    def control(self, total):
        return response(json_data=dict(self.data, total_count=total))

    def test_first_cycle_checks_language_filter(self, sleep):
        with mock.patch('steam_search.requests.get',
                        side_effect=[response(json_data=self.data), self.control(5044)]) as get:
            result = steam_search.get_deals(previous_total_count=None)
        self.assertTrue(result.language_checked)
        self.assertEqual(get.call_count, 2)
        self.assertNotIn('supportedlang', get.call_args_list[1].kwargs['params'])
        sleep.assert_called_once_with(steam_search.PAGE_DELAY_SECONDS)

    def test_ignored_language_filter_is_error(self, sleep):
        with mock.patch('steam_search.requests.get',
                        side_effect=[response(json_data=self.data), self.control(2525)]):
            with self.assertRaisesRegex(steam_search.SourceError, 'supportedlang'):
                steam_search.get_deals(previous_total_count=None)

    def test_jump_triggers_check(self, sleep):
        with mock.patch('steam_search.requests.get',
                        side_effect=[response(json_data=self.data), self.control(2600)]):
            with self.assertRaisesRegex(steam_search.SourceError, 'supportedlang'):
                steam_search.get_deals(previous_total_count=1000)

    def test_sharp_drop_triggers_check(self, sleep):
        with mock.patch('steam_search.requests.get',
                        side_effect=[response(json_data=self.data), self.control(2530)]):
            with self.assertRaisesRegex(steam_search.SourceError, 'supportedlang'):
                steam_search.get_deals(previous_total_count=9000)

    def test_forced_check(self, sleep):
        with mock.patch('steam_search.requests.get',
                        side_effect=[response(json_data=self.data), self.control(5044)]) as get:
            result = steam_search.get_deals(previous_total_count=2525, check_language=True)
        self.assertTrue(result.language_checked)
        self.assertEqual(get.call_count, 2)

    def test_small_growth_does_not_trigger_check(self, sleep):
        with mock.patch('steam_search.requests.get', side_effect=[response(json_data=self.data)]) as get:
            steam_search.get_deals(previous_total_count=2000)
        self.assertEqual(get.call_count, 1)


@mock.patch('steam_search.time.sleep')
class PaginationTests(TempDbTestCase):
    def setUp(self):
        super().setUp()
        self.data = load_fixture('steam_search_kz.json')

    def page(self, suffix, total=5000, rows=None):
        """Страница фикстуры с другими app id, чтобы страницы не совпадали"""
        html = self.data['results_html']
        if rows is not None:
            html = ''.join(steam_search.split_rows(html)[:rows])
        html = html.replace('data-ds-appid="', f'data-ds-appid="{suffix}')
        return response(json_data=dict(self.data, results_html=html, total_count=total))

    def test_pages_are_merged(self, sleep):
        with mock.patch.object(config, 'STEAM_MAX_PAGES', 3), \
                mock.patch('steam_search.requests.get',
                           side_effect=[self.page('1'), self.page('2'), self.page('3')]) as get:
            result = steam_search.get_deals(previous_total_count=5000)
        self.assertEqual(result.pages, 3)
        self.assertEqual(len(result.games), 99 * 3)
        self.assertEqual(len(result.deals), 24 * 3)
        self.assertEqual([c.kwargs['params']['start'] for c in get.call_args_list], ['0', '100', '200'])
        self.assertEqual(sleep.call_count, 2)

    def test_short_page_stops(self, sleep):
        with mock.patch.object(config, 'STEAM_MAX_PAGES', 5), \
                mock.patch('steam_search.requests.get',
                           side_effect=[self.page('1', total=140), self.page('2', total=140, rows=40)]) as get:
            result = steam_search.get_deals(previous_total_count=140)
        self.assertEqual((get.call_count, result.pages), (2, 2))

    def test_stops_at_total_count(self, sleep):
        with mock.patch.object(config, 'STEAM_MAX_PAGES', 5), \
                mock.patch('steam_search.requests.get', side_effect=[self.page('1', total=100)]) as get:
            result = steam_search.get_deals(previous_total_count=100)
        self.assertEqual((get.call_count, result.pages), (1, 1))

    def test_capped_page_is_error(self, sleep):
        with mock.patch.object(config, 'STEAM_MAX_PAGES', 5), \
                mock.patch('steam_search.requests.get', side_effect=[self.page('1', rows=50)]):
            with self.assertRaisesRegex(steam_search.SourceError, 'урезал'):
                steam_search.get_deals(previous_total_count=5000)

    def test_capped_middle_page_is_error(self, sleep):
        with mock.patch.object(config, 'STEAM_MAX_PAGES', 5), \
                mock.patch('steam_search.requests.get', side_effect=[self.page('1'), self.page('2', rows=60)]):
            with self.assertRaisesRegex(steam_search.SourceError, 'урезал'):
                steam_search.get_deals(previous_total_count=5000)

    def test_total_shrinks_between_pages(self, sleep):
        pages = [self.page('1', total=205), self.page('2', total=150, rows=50)]
        with mock.patch.object(config, 'STEAM_MAX_PAGES', 5), mock.patch('steam_search.requests.get', side_effect=pages):
            result = steam_search.get_deals(previous_total_count=205)
        self.assertEqual((result.pages, result.rows), (2, 150))

    def test_deals_end_before_next_page(self, sleep):
        empty = response(json_data=dict(self.data, results_html='', total_count=90, start=89))
        with mock.patch.object(config, 'STEAM_MAX_PAGES', 5), \
                mock.patch('steam_search.requests.get', side_effect=[self.page('1', total=105), empty]):
            result = steam_search.get_deals(previous_total_count=105)
        self.assertEqual(result.pages, 1)

    def test_collapsed_total_on_later_page_is_error(self, sleep):
        empty = {'success': 1, 'results_html': '\n<!-- List Items -->\n<!-- End List Items -->\n',
                 'total_count': 0, 'start': -1}
        for later in (response(json_data=empty), self.page('2', total=250)):
            with mock.patch.object(config, 'STEAM_MAX_PAGES', 5), \
                    mock.patch('steam_search.requests.get', side_effect=[self.page('1', total=2527), later]):
                with self.assertRaisesRegex(steam_search.SourceError, 'неправдоподобна'):
                    steam_search.get_deals(previous_total_count=2527)

    def test_repeated_page_is_error(self, sleep):
        with mock.patch.object(config, 'STEAM_MAX_PAGES', 3), \
                mock.patch('steam_search.requests.get', side_effect=[self.page('1'), self.page('1')]):
            with self.assertRaisesRegex(steam_search.SourceError, 'start'):
                steam_search.get_deals(previous_total_count=5000)

    def test_games_remember_page(self, sleep):
        with mock.patch.object(config, 'STEAM_MAX_PAGES', 2), \
                mock.patch('steam_search.requests.get', side_effect=[self.page('1'), self.page('2')]):
            result = steam_search.get_deals(previous_total_count=5000)
        self.assertEqual({g['page'] for g in result.games}, {0, 1})

    def test_later_page_total_jump_is_error(self, sleep):
        with mock.patch.object(config, 'STEAM_MAX_PAGES', 5), \
                mock.patch('steam_search.requests.get', side_effect=[self.page('1'), self.page('2', total=9000)]):
            with self.assertRaisesRegex(steam_search.SourceError, 'странице 2'):
                steam_search.get_deals(previous_total_count=5000)

    def test_failed_page_fails_cycle(self, sleep):
        with mock.patch.object(config, 'STEAM_MAX_PAGES', 3), \
                mock.patch('steam_search.requests.get',
                           side_effect=[self.page('1'), response(404, json_data={})]):
            with self.assertRaises(steam_search.SourceError):
                steam_search.get_deals(previous_total_count=5000)


if __name__ == '__main__':
    unittest.main()
