import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backup import backup

from telegram_bot import SupportBot, TelegramAPI, TelegramError, telegram_link, start_bot, public_links


class TelegramFlowTests(unittest.TestCase):
    def test_public_links_require_explicit_launch_and_never_expose_secrets(self):
        settings = {'ACADEMY_TELEGRAM_ENABLED': 'true', 'ACADEMY_TELEGRAM_PUBLIC': 'false',
                    'ACADEMY_TELEGRAM_BOT_TOKEN': 'test-secret', 'ACADEMY_TELEGRAM_OWNER_ID': '123',
                    'ACADEMY_TELEGRAM_COMMUNITY_URL': 'https://t.me/examplecommunity',
                    'ACADEMY_TELEGRAM_UPDATES_URL': 'https://t.me/exampleupdates'}
        with patch.dict('os.environ', settings, clear=True):
            self.assertEqual(public_links(), {})
        settings['ACADEMY_TELEGRAM_PUBLIC'] = 'true'
        with patch.dict('os.environ', settings, clear=True):
            self.assertEqual(set(public_links()), {'support', 'community', 'updates'})
            self.assertNotIn('test-secret', json.dumps(public_links()))
            self.assertNotIn('123', json.dumps(public_links()))
        settings['ACADEMY_TELEGRAM_COMMUNITY_URL'] = 'https://untrusted.example/'
        with patch.dict('os.environ', settings, clear=True):
            self.assertEqual(public_links(), {})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 2_000_000_000
        self.sent = []
        self.bot = SupportBot(self.temp.name, self.api, 123, public=True, clock=lambda: self.now)
        self.n = 0

    def api(self, method, **payload):
        self.sent.append((method, payload))
        return {'message_id': len(self.sent)}

    def update(self, text='', action=None, chat=456, kind='private', photo=None):
        self.n += 1
        message = {'chat': {'id': chat, 'type': kind}, 'from': {'id': chat}, 'text': text}
        if photo:
            message['photo'] = [{'file_id': photo, 'file_size': 100}]
        update = {'update_id': self.n, 'message': message}
        if action:
            update = {'update_id': self.n, 'callback_query': {'id': str(self.n), 'from': {'id': chat}, 'message': message, 'data': action}}
        self.bot.process(update)
        return update

    def complete(self, photo=False):
        self.update('/support')
        self.update(action='begin')
        self.update('Test Learner')
        self.update(action='category:app')
        self.update('Android / Chrome')
        self.update('Expected the chart to load; it stays blank.')
        self.update(photo='TEST_PHOTO_ID') if photo else self.update(action='skip')
        return self.update(action='submit')

    def test_full_support_flow_persists_and_submits_once(self):
        self.update(action='begin')
        self.update('Test Learner')
        self.bot = SupportBot(self.temp.name, self.api, 123, public=True, clock=lambda: self.now)
        self.update(action='category:account')
        self.update('iPhone / Safari')
        self.update('I need help finding my application status.')
        self.update(action='skip')
        duplicate = self.update(action='submit')
        self.bot.process(duplicate)
        self.update(action='submit')
        with self.bot.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tickets').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM drafts').fetchone()[0], 0)
        self.bot.flush()
        owner_requests = [p for m, p in self.sent if m == 'sendMessage' and p['chat_id'] == 123 and 'New support request' in p['text']]
        self.assertEqual(len(owner_requests), 1)

    def test_consistent_database_export_restores_ticket_and_delivery_state(self):
        self.complete()
        self.bot.flush()
        restored_directory = Path(self.temp.name) / 'isolated-restore'
        restored_directory.mkdir(mode=0o700)
        backup(self.bot.path, restored_directory / 'telegram.sqlite3')
        restored = SupportBot(restored_directory, self.api, 123, public=False, clock=lambda: self.now)
        with restored.db() as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            ticket = db.execute('SELECT * FROM tickets').fetchone()
            self.assertEqual(ticket['chat'], 456)
            self.assertEqual(json.loads(ticket['data'])['name'], 'Test Learner')
            self.assertEqual(db.execute("SELECT count(*) FROM outbox WHERE status='queued'").fetchone()[0], 0)
        self.sent.clear()
        restored.flush()
        self.assertEqual(self.sent, [])  # a restore does not resend successful messages

    def test_photo_is_forwarded_only_after_confirmation(self):
        self.complete(photo=True)
        with self.bot.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM outbox WHERE method='sendPhoto'").fetchone()[0], 1)
        self.bot.flush()
        photos = [p for m, p in self.sent if m == 'sendPhoto']
        self.assertEqual(photos, [{'chat_id': 123, 'photo': 'TEST_PHOTO_ID', 'caption': 'Support request #1 · optional screenshot'}])

    def test_owner_only_replies_and_group_messages_ignored(self):
        self.complete()
        self.bot.flush()
        self.sent.clear()
        self.update('/reply 1 An unauthorized reply', chat=999)
        self.update('/reply 1 A group reply', chat=123, kind='supergroup')
        self.update('/reply 1 Please reopen the app in Chrome.', chat=123)
        self.bot.flush()
        replies = [p['text'] for m, p in self.sent if m == 'sendMessage' and p['chat_id'] == 456]
        self.assertEqual(len(replies), 1)
        self.assertIn('Please reopen the app in Chrome.', replies[0])
        self.assertNotIn('unauthorized', replies[0])

    def test_cancel_and_expired_drafts_do_not_create_tickets(self):
        self.update(action='begin')
        self.update('Example')
        self.update('/cancel')
        self.update(action='submit')
        self.update(action='begin')
        self.now += 86401
        self.update('Late reply')
        with self.bot.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tickets').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM drafts').fetchone()[0], 0)

    def test_invalid_category_and_too_long_values_cannot_advance(self):
        self.update(action='begin')
        self.update('x' * 81)
        with self.bot.db() as db:
            self.assertEqual(db.execute('SELECT step FROM drafts').fetchone()[0], 'name')
        self.update('Learner')
        self.update(action='category:admin')
        with self.bot.db() as db:
            self.assertEqual(db.execute('SELECT step FROM drafts').fetchone()[0], 'category')

    def test_delivery_retry_and_payload_clearing(self):
        self.update('/app')
        calls = []
        def failing(method, **payload):
            calls.append(method)
            raise TelegramError(429, 30)
        self.bot.api = failing
        self.bot.flush()
        self.assertEqual(len(calls), 1)
        self.bot.flush()
        self.assertEqual(len(calls), 1)
        self.now += 31
        self.bot.api = self.api
        self.bot.flush()
        with self.bot.db() as db:
            row = db.execute('SELECT status,payload FROM outbox').fetchone()
            self.assertEqual(tuple(row), ('sent', '{}'))

    def test_preview_only_owner_and_rate_limit(self):
        self.bot.public = False
        self.update('/support')
        self.update(action='begin')
        self.update('/start', chat=123)
        with self.bot.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM drafts').fetchone()[0], 0)
        self.bot.flush()
        self.assertTrue(any('reply_markup' in p for m, p in self.sent if p.get('chat_id') == 123))
        self.bot.public = True
        for _ in range(25):
            self.update('/start', chat=999)
        self.bot.flush()
        responses = [p for m, p in self.sent if m == 'sendMessage' and p['chat_id'] == 999]
        self.assertEqual(len(responses), 21)

    def test_closed_ticket_retention_and_replay_after_cleanup(self):
        duplicate = self.complete()
        self.update('/close 1', chat=123)
        self.now += 366 * 86400
        self.bot.cleanup()
        self.bot.process(duplicate)
        with self.bot.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tickets').fetchone()[0], 0)
        self.assertEqual(self.bot.path.stat().st_mode & 0o777, 0o600)

    def test_safe_configuration_and_disabled_by_default(self):
        for value in ['http://t.me/example', 'https://t.me@evil.example/a', 'https://t.me/a?secret=1', 'javascript:alert(1)']:
            with self.assertRaises(ValueError):
                telegram_link(value)
        self.assertEqual(telegram_link('https://t.me/protraderacademy_bot'), 'https://t.me/protraderacademy_bot')
        with self.assertRaises(ValueError):
            TelegramAPI('not-a-token')
        with patch.dict('os.environ', {}, clear=True):
            self.assertIsNone(start_bot(self.temp.name, None))


if __name__ == '__main__':
    unittest.main()
