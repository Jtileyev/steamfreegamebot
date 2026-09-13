import io
import logging
import socket
import threading
import time
import unittest
from unittest import mock

import requests

import telegram_client
from logging_setup import RedactingFormatter
from tests.helpers import TEST_TOKEN, TempDbTestCase, make_deal


def tg_response(json_data):
    resp = mock.Mock()
    resp.status_code = 200
    resp.json.return_value = json_data
    return resp


class EscapeTests(unittest.TestCase):
    def test_backslash_escaped_first(self):
        self.assertEqual(telegram_client.escape_markdown('a\\b.c'), 'a\\\\b\\.c')

    def test_all_special_chars(self):
        text = '_*[]()~`>#+-=|{}.!'
        escaped = telegram_client.escape_markdown(text)
        self.assertEqual(escaped, ''.join('\\' + c for c in text))

    def test_url_escape(self):
        self.assertEqual(telegram_client.escape_markdown_url('https://x/a)b\\c'), 'https://x/a\\)b\\\\c')


class FormatTests(unittest.TestCase):
    def test_deal_message(self):
        deal = make_deal('433340', discount=85, title='Tom & Jerry: C:\\Games (2020)!', review_count=65687)
        markdown, plain = telegram_client.format_deal_message(deal)
        self.assertIn('🔥🔥', markdown)
        self.assertIn('*Скидка \\-85% в Steam*', markdown)
        self.assertIn('*Tom & Jerry: C:\\\\Games \\(2020\\)\\!*', markdown)
        self.assertIn('💰 500,00₸ ~2 500,00₸~', markdown)
        self.assertIn('95% положительных из 65 687 отзывов', markdown)
        self.assertIn('[Открыть в Steam](https://store.steampowered.com/app/433340)', markdown)

        self.assertNotIn('\\', plain.replace('C:\\Games', ''))
        self.assertIn('Tom & Jerry: C:\\Games (2020)!', plain)
        self.assertIn('Скидка -85% в Steam', plain)
        self.assertIn('500,00₸ (было 2 500,00₸)', plain)

    def test_deal_message_without_optional_fields(self):
        deal = {'app_id': '1', 'title': 'X', 'discount': 70, 'steam_url': 'https://store.steampowered.com/app/1'}
        markdown, plain = telegram_client.format_deal_message(deal)
        self.assertNotIn('💰', markdown)
        self.assertNotIn('👍', plain)


@mock.patch('telegram_client.time.sleep')
class SendTests(TempDbTestCase):
    def test_plain_fallback_on_parse_error(self, sleep):
        responses = [
            tg_response({'ok': False, 'error_code': 400, 'description': "Bad Request: can't parse entities"}),
            tg_response({'ok': True}),
        ]
        with mock.patch('telegram_client.requests.post', side_effect=responses) as post:
            outcome = telegram_client.send_deal_notification(TEST_TOKEN, '42', make_deal('1', title='A.B'))
        self.assertEqual(outcome, telegram_client.SENT)
        first, second = (c.kwargs['json'] for c in post.call_args_list)
        self.assertEqual(first['parse_mode'], 'MarkdownV2')
        self.assertNotIn('parse_mode', second)
        self.assertIn('A.B', second['text'])
        self.assertNotIn('\\', second['text'])

    def test_network_error_does_not_leak_token(self, sleep):
        url = telegram_client.TELEGRAM_API_URL.format(token=TEST_TOKEN)
        error = requests.exceptions.ConnectionError(f"HTTPSConnectionPool: Max retries exceeded with url: {url}")
        with mock.patch('telegram_client.requests.post', side_effect=error):
            with self.assertLogs('telegram_client', level='ERROR') as logs:
                result = telegram_client.send_message(TEST_TOKEN, '42', 'hi')
        self.assertFalse(result['ok'])
        self.assertNotIn(TEST_TOKEN, result['description'])
        self.assertNotIn(TEST_TOKEN, '\n'.join(logs.output))
        self.assertIn('***', result['description'])

    def test_rate_limit_retry(self, sleep):
        responses = [
            tg_response({'ok': False, 'error_code': 429, 'description': 'Too Many Requests',
                         'parameters': {'retry_after': 3}}),
            tg_response({'ok': True}),
        ]
        with mock.patch('telegram_client.requests.post', side_effect=responses) as post:
            result = telegram_client.send_message(TEST_TOKEN, '42', 'hi')
        self.assertTrue(result['ok'])
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(3)

    def test_send_text_is_plain(self, sleep):
        with mock.patch('telegram_client.requests.post', return_value=tg_response({'ok': True})) as post:
            self.assertTrue(telegram_client.send_text(TEST_TOKEN, '42', 'a.b!'))
        payload = post.call_args.kwargs['json']
        self.assertNotIn('parse_mode', payload)
        self.assertEqual(payload['text'], 'a.b!')

    def test_failure(self, sleep):
        with mock.patch('telegram_client.requests.post',
                        return_value=tg_response({'ok': False, 'error_code': 403, 'description': 'Forbidden'})):
            outcome = telegram_client.send_deal_notification(TEST_TOKEN, '42', make_deal('1'))
        self.assertEqual(outcome, telegram_client.FAILED)

    def test_read_timeout_is_uncertain_and_not_retried(self, sleep):
        url = telegram_client.TELEGRAM_API_URL.format(token=TEST_TOKEN)
        error = requests.exceptions.ReadTimeout(f"Read timed out. (url: {url})")
        with mock.patch('telegram_client.requests.post', side_effect=error) as post:
            with self.assertLogs('telegram_client', level='ERROR') as logs:
                outcome = telegram_client.send_deal_notification(TEST_TOKEN, '42', make_deal('1'))
        self.assertEqual(outcome, telegram_client.UNCERTAIN)
        self.assertEqual(post.call_count, 1)
        self.assertNotIn(TEST_TOKEN, '\n'.join(logs.output))

    def test_connection_error_is_failure(self, sleep):
        error = requests.exceptions.ConnectTimeout('connect timeout')
        with mock.patch('telegram_client.requests.post', side_effect=error):
            outcome = telegram_client.send_deal_notification(TEST_TOKEN, '42', make_deal('1'))
        self.assertEqual(outcome, telegram_client.FAILED)


class DeliveryClassificationTests(TempDbTestCase):
    """Настоящие локальные сокеты: запрос в Telegram не уходит"""

    def serve(self, handler):
        server = socket.socket()
        server.bind(('127.0.0.1', 0))
        server.listen(1)
        self.addCleanup(server.close)

        def run():
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                handler(conn)

        threading.Thread(target=run, daemon=True).start()
        return server.getsockname()[1]

    @staticmethod
    def read_request(conn):
        """Читает запрос целиком: заголовки и тело по Content-Length"""
        data = b''
        while b'\r\n\r\n' not in data:
            chunk = conn.recv(65536)
            if not chunk:
                return data
            data += chunk
        head, _, body = data.partition(b'\r\n\r\n')
        length = 0
        for line in head.split(b'\r\n')[1:]:
            name, _, value = line.partition(b':')
            if name.strip().lower() == b'content-length':
                length = int(value)
        while len(body) < length:
            chunk = conn.recv(65536)
            if not chunk:
                break
            body += chunk
        return head + b'\r\n\r\n' + body

    def post(self, url):
        with mock.patch.object(telegram_client, 'REQUEST_TIMEOUT', 0.5):
            return telegram_client._post(url, {'text': 'x'}, TEST_TOKEN)

    def test_tls_handshake_timeout_is_failure(self):
        port = self.serve(lambda conn: time.sleep(1.5))
        result = self.post(f'https://127.0.0.1:{port}/bot{TEST_TOKEN}/sendMessage')
        self.assertFalse(result['ok'])
        self.assertNotIn('uncertain', result)

    def test_response_timeout_is_uncertain(self):
        port = self.serve(lambda conn: (self.read_request(conn), time.sleep(1.5)))
        result = self.post(f'http://127.0.0.1:{port}/bot{TEST_TOKEN}/sendMessage')
        self.assertTrue(result.get('uncertain'))
        self.assertNotIn(TEST_TOKEN, result['description'])

    def test_disconnect_after_request_is_uncertain(self):
        port = self.serve(self.read_request)
        result = self.post(f'http://127.0.0.1:{port}/bot{TEST_TOKEN}/sendMessage')
        self.assertTrue(result.get('uncertain'))

    def test_body_timeout_after_headers_is_uncertain(self):
        def handler(conn):
            self.read_request(conn)
            conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{"ok"')
            time.sleep(1.5)

        result = self.post(f'http://127.0.0.1:{self.serve(handler)}/bot{TEST_TOKEN}/sendMessage')
        self.assertTrue(result.get('uncertain'))

    def test_truncated_body_is_uncertain(self):
        def handler(conn):
            self.read_request(conn)
            conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{"ok"')

        result = self.post(f'http://127.0.0.1:{self.serve(handler)}/bot{TEST_TOKEN}/sendMessage')
        self.assertTrue(result.get('uncertain'))

    def test_refused_connection_is_failure(self):
        probe = socket.socket()
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
        probe.close()
        result = self.post(f'https://127.0.0.1:{port}/bot{TEST_TOKEN}/sendMessage')
        self.assertFalse(result['ok'])
        self.assertNotIn('uncertain', result)


class RedactingFormatterTests(TempDbTestCase):
    def test_setup_logging_installs_redacting_formatter(self):
        import logging_setup
        root = logging.getLogger()
        saved_handlers, saved_level = root.handlers[:], root.level
        self.addCleanup(lambda: (root.handlers.__setitem__(slice(None), saved_handlers), root.setLevel(saved_level)))

        logging_setup.setup_logging()
        stream = io.StringIO()
        root.handlers[0].setStream(stream)
        logging.getLogger('any.module').error('url https://api.telegram.org/bot%s/sendMessage', TEST_TOKEN)
        self.assertIn('bot***/sendMessage', stream.getvalue())
        self.assertNotIn(TEST_TOKEN, stream.getvalue())
        self.assertEqual(logging.getLogger('urllib3').level, logging.WARNING)

    def test_token_removed_from_message_and_traceback(self):
        formatter = RedactingFormatter('%(message)s')
        try:
            raise RuntimeError(f'url with {TEST_TOKEN}')
        except RuntimeError:
            record = logging.LogRecord('x', logging.ERROR, __file__, 1, 'token %s', (TEST_TOKEN,), None)
            import sys
            record.exc_info = sys.exc_info()
        text = formatter.format(record)
        self.assertNotIn(TEST_TOKEN, text)
        self.assertIn('***', text)


if __name__ == '__main__':
    unittest.main()
