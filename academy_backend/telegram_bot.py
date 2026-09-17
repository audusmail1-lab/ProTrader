"""Private-chat onboarding bot, opt-in on the Academy's existing paid process.

No bot token, incoming message or Telegram request URL is written to logs.
Polling keeps credentials out of public URLs and needs no extra hosting service.
"""
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
import json
import logging
import os
import re
import sqlite3
import threading
import time

LOG = logging.getLogger('academy.telegram')
ROOT = Path(__file__).resolve().parent.parent
COPY = json.loads((ROOT / 'telegram_setup/copy.json').read_text())
WEBSITE = 'https://protraderacademy.company'
APP = 'https://app.protraderacademy.company'
EMAIL = 'support@protraderacademy.company'
SUPPORT_URL = 'https://t.me/protrader_support_bot'
CATEGORIES = {'app': 'PROTrader app', 'account': 'Academy account', 'learning': 'Learning / enrollment', 'general': 'General question'}


class TelegramError(Exception):
    def __init__(self, code=0, retry_after=0):
        self.code, self.retry_after = code, retry_after
        super().__init__(f'Telegram request failed ({code})')


class TelegramAPI:
    def __init__(self, token):
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{30,}', token):
            raise ValueError('Invalid Telegram token format; check the private Render setting.')
        self._token = token

    def __call__(self, method, **payload):
        request = Request(f'https://api.telegram.org/bot{self._token}/{method}',
                          data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=40) as response:
                result = json.load(response)
        except HTTPError as exc:
            delay = 0
            try:
                delay = int(json.loads(exc.read()).get('parameters', {}).get('retry_after', 0))
            except (ValueError, TypeError):
                pass
            raise TelegramError(exc.code, delay) from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise TelegramError() from None
        if not result.get('ok'):
            raise TelegramError(result.get('error_code', 0))
        return result.get('result')


def telegram_link(value):
    value = value.strip()
    if not value:
        return ''
    p = urlsplit(value)
    if p.scheme != 'https' or p.netloc != 't.me' or not re.fullmatch(r'/[A-Za-z0-9_+\-]+', p.path) or p.query or p.fragment:
        raise ValueError('Telegram public links must be direct https://t.me/ links.')
    return value


def public_links():
    """Only an explicit launch switch exposes the verified public destinations."""
    if any(os.environ.get(key) != 'true' for key in ('ACADEMY_TELEGRAM_ENABLED', 'ACADEMY_TELEGRAM_PUBLIC')):
        return {}
    try:
        links = {'support': SUPPORT_URL,
                 'community': telegram_link(os.environ.get('ACADEMY_TELEGRAM_COMMUNITY_URL', '')),
                 'updates': telegram_link(os.environ.get('ACADEMY_TELEGRAM_UPDATES_URL', ''))}
    except ValueError:
        return {}
    return links if all(links.values()) else {}


class SupportBot:
    def __init__(self, directory, api, owner_id, *, public=False, community='', updates='', clock=time.time):
        if not isinstance(owner_id, int) or owner_id <= 0:
            raise ValueError('A verified private owner chat ID is required.')
        self.api, self.owner, self.public, self.clock = api, owner_id, public, clock
        self.links = {'communityUrl': telegram_link(community), 'updatesUrl': telegram_link(updates),
                      'supportUrl': SUPPORT_URL}
        folder = Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        self.path = folder / 'telegram.sqlite3'
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS updates(id INTEGER PRIMARY KEY, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS drafts(chat INTEGER PRIMARY KEY, step TEXT NOT NULL, data TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY, chat INTEGER NOT NULL, data TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created REAL NOT NULL, closed REAL);
                CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, method TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0, due REAL NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS limits(chat INTEGER PRIMARY KEY, window REAL NOT NULL, count INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS outbox_due ON outbox(status,due);
            ''')
        os.chmod(self.path, 0o600)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def buttons(*rows):
        return {'inline_keyboard': list(rows)}

    @staticmethod
    def button(text, callback):
        return {'text': text, 'callback_data': callback}

    def menu(self):
        return self.buttons(
            [{'text': 'Open App', 'url': APP}, {'text': 'Join Academy', 'url': WEBSITE + '/#enroll'}],
            [self.button('Get Support', 'support')],
            [({'text': 'Join Community', 'url': self.links['communityUrl']} if self.links['communityUrl'] else self.button('Join Community', 'community')),
             ({'text': 'Get Updates', 'url': self.links['updatesUrl']} if self.links['updatesUrl'] else self.button('Get Updates', 'updates'))],
            [self.button('FAQ', 'faq'), self.button('Contact the team', 'contact')])

    def queue(self, db, method, **payload):
        db.execute('INSERT INTO outbox(method,payload,due,created) VALUES(?,?,?,?)',
                   (method, json.dumps(payload), self.clock(), self.clock()))

    def say(self, db, chat, text, markup=None):
        payload = {'chat_id': chat, 'text': text, 'link_preview_options': {'is_disabled': True}}
        if markup:
            payload['reply_markup'] = markup
        self.queue(db, 'sendMessage', **payload)

    def draft(self, db, chat, step, data):
        db.execute('INSERT OR REPLACE INTO drafts VALUES(?,?,?,?)', (chat, step, json.dumps(data), self.clock()))

    def cancel(self, db, chat):
        db.execute('DELETE FROM drafts WHERE chat=?', (chat,))

    def support_intro(self, db, chat):
        self.cancel(db, chat)
        self.say(db, chat, 'Private support for Pro Trader Academy and PROTrader.\n\nWe will collect your name, Telegram chat ID, issue category, device and description; a cropped screenshot is optional. Your request goes to the academy operator. We aim to reply within 1–2 business days.\n\nDo not send passwords, codes, broker keys, financial documents or sensitive personal details. This is support, not trading advice.\nPrivacy: ' + WEBSITE + '/#privacy\n\nBegin when you are ready. /cancel stops an unfinished request.',
                 self.buttons([self.button('Begin support request', 'begin')], [self.button('Cancel', 'cancel')]))

    def review(self, db, chat, data):
        self.draft(db, chat, 'review', data)
        self.say(db, chat, 'Review before sending\n\n' + self.summary(data) + '\n\nSend this to the academy support team?',
                 self.buttons([self.button('Send request', 'submit')], [self.button('Start again', 'begin'), self.button('Cancel', 'cancel')]))

    @staticmethod
    def summary(data):
        return '\n'.join([f"Name: {data.get('name', '')}", f"Category: {data.get('category', '')}",
                          f"Device / browser: {data.get('device', '')}", f"Issue: {data.get('description', '')}",
                          'Screenshot: ' + ('attached' if data.get('photo') else 'none')])

    def command(self, db, chat, command, text):
        if command in ('reply', 'close', 'tickets'):
            if chat != self.owner:
                self.say(db, chat, 'Use /support to contact the academy team.')
                return
            if command == 'tickets':
                rows = db.execute("SELECT id,data FROM tickets WHERE status='open' ORDER BY id DESC LIMIT 20").fetchall()
                self.say(db, chat, '\n'.join(f"#{r['id']} — {json.loads(r['data']).get('category', '')}" for r in rows) or 'No open support tickets.')
                return
            parts = text.split(maxsplit=2)
            ticket = db.execute('SELECT * FROM tickets WHERE id=?', (int(parts[1]),)).fetchone() if len(parts) > 1 and parts[1].isdigit() else None
            if not ticket or ticket['status'] != 'open':
                self.say(db, chat, 'Open ticket not found. Use /tickets.')
                return
            if command == 'close':
                db.execute("UPDATE tickets SET status='closed',closed=? WHERE id=?", (self.clock(), ticket['id']))
                self.say(db, chat, f"Ticket #{ticket['id']} closed.")
            elif len(parts) != 3 or not 1 <= len(parts[2]) <= 3000:
                self.say(db, chat, 'Use /reply TICKET_NUMBER your reply (up to 3,000 characters).')
            else:
                self.say(db, ticket['chat'], f"Pro Trader Academy support · #{ticket['id']}\n\n{parts[2]}\n\nFor a follow-up, use /support and mention this ticket number.")
                self.say(db, chat, f"Reply for #{ticket['id']} queued. Check /delivery if a recipient has blocked the bot.")
            return
        if command == 'delivery' and chat == self.owner:
            counts = db.execute('SELECT status,count(*) AS n FROM outbox GROUP BY status').fetchall()
            self.say(db, chat, 'Delivery queue: ' + ', '.join(f"{r['status']}={r['n']}" for r in counts))
            return
        if command in ('start', 'help'):
            self.cancel(db, chat)
            self.say(db, chat, 'Welcome to Pro Trader Academy.\n\nOpen PROTrader, explore the free 18+ academy, or get help below. Start with paper practice. Educational only, not financial advice. Trading involves risk.\n\nUse /cancel to stop an unfinished support request.', self.menu())
        elif command == 'support':
            self.support_intro(db, chat)
        elif command == 'cancel':
            self.cancel(db, chat)
            self.say(db, chat, 'Unfinished support request cancelled. Already-sent requests remain with the team; email ' + EMAIL + ' for data requests.', self.menu())
        elif command == 'contact':
            self.say(db, chat, 'Contact the academy team\n\nEmail: ' + EMAIL + '\nSupport hours: Monday–Friday, 09:00–17:00 WAT (UTC+1). We aim to reply within 1–2 business days.\n\nFor lesson questions, use Questions & replies in the Academy. For account help, send a private support request.', self.buttons([self.button('Send support request', 'support')]))
        elif command in COPY['quickReplies']:
            if command in ('community', 'updates') and not self.links[command + 'Url']:
                self.say(db, chat, 'The official ' + command + ' link is being prepared. Please check ' + WEBSITE + '/#contact for the verified link.', self.menu())
            else:
                self.say(db, chat, COPY['quickReplies'][command].format(**self.links), self.menu())
        else:
            self.say(db, chat, 'Choose a menu option or use /support for a private request.', self.menu())

    def process(self, update):
        update_id = update.get('update_id')
        if not isinstance(update_id, int):
            return
        callback = update.get('callback_query')
        message = callback.get('message', {}) if callback else update.get('message', {})
        chat_info = message.get('chat', {})
        actor = (callback or message).get('from', {})
        chat = chat_info.get('id')
        with self.db() as db:
            offset = db.execute("SELECT value FROM meta WHERE key='offset'").fetchone()
            if offset and update_id < offset['value']:
                return
            if db.execute('SELECT 1 FROM updates WHERE id=?', (update_id,)).fetchone():
                return
            db.execute('INSERT INTO updates VALUES(?,?)', (update_id, self.clock()))
            db.execute("INSERT INTO meta VALUES('offset',?) ON CONFLICT(key) DO UPDATE SET value=max(value,excluded.value)", (update_id + 1,))
            # Never collect group messages or accept an owner command from a group.
            if chat_info.get('type') != 'private' or not isinstance(chat, int) or chat != actor.get('id') or actor.get('is_bot'):
                return
            if callback and isinstance(callback.get('id'), str):
                self.queue(db, 'answerCallbackQuery', callback_query_id=callback['id'])
            limit = db.execute('SELECT * FROM limits WHERE chat=?', (chat,)).fetchone()
            count = limit['count'] + 1 if limit and self.clock() - limit['window'] < 60 else 1
            window = limit['window'] if count > 1 else self.clock()
            db.execute('INSERT OR REPLACE INTO limits VALUES(?,?,?)', (chat, window, count))
            if count > 20:
                if count == 21:
                    self.say(db, chat, 'Please wait a minute before sending more messages.')
                return
            if not self.public and chat != self.owner:
                if count == 1:
                    self.say(db, chat, 'This bot is being prepared. For support, email ' + EMAIL + '.')
                return
            text = str(message.get('text', '')).strip()
            action = callback.get('data', '') if callback else ''
            if text.startswith('/') and not callback:
                self.command(db, chat, text.split()[0][1:].split('@')[0].lower(), text)
                return
            if action in ('support', 'faq', 'contact', 'community', 'updates', 'cancel'):
                self.command(db, chat, action, '')
                return
            if action == 'begin':
                self.draft(db, chat, 'name', {})
                self.say(db, chat, '1/4 · What name should our support team use? (80 characters maximum)')
                return
            row = db.execute('SELECT * FROM drafts WHERE chat=?', (chat,)).fetchone()
            if not row or self.clock() - row['updated'] > 86400:
                self.cancel(db, chat)
                self.say(db, chat, 'Choose Get Support to begin a private request.', self.menu())
                return
            data, step = json.loads(row['data']), row['step']
            if step == 'name' and not callback and 1 <= len(text) <= 80:
                data['name'] = text
                self.draft(db, chat, 'category', data)
                self.say(db, chat, '2/4 · What do you need help with?', self.buttons(*[[self.button(label, 'category:' + key)] for key, label in CATEGORIES.items()]))
            elif step == 'category' and action.startswith('category:') and action[9:] in CATEGORIES:
                data['category'] = CATEGORIES[action[9:]]
                self.draft(db, chat, 'device', data)
                self.say(db, chat, '3/4 · Which device and browser are you using? For example: iPhone / Safari, Android / Chrome, or Windows / Chrome. You may say “not relevant”. (160 characters maximum)')
            elif step == 'device' and not callback and 1 <= len(text) <= 160:
                data['device'] = text
                self.draft(db, chat, 'description', data)
                self.say(db, chat, '4/4 · Briefly describe the issue: what did you expect, and what happened? (10–1,500 characters)')
            elif step == 'description' and not callback and 10 <= len(text) <= 1500:
                data['description'] = text
                self.draft(db, chat, 'photo', data)
                self.say(db, chat, 'Optional: send one screenshot as a photo, or tap Skip. Crop out names, balances, account IDs, passwords and other private details.', self.buttons([self.button('Skip screenshot', 'skip')]))
            elif step == 'photo' and action == 'skip':
                self.review(db, chat, data)
            elif step == 'photo' and not callback and message.get('photo'):
                photo = message['photo'][-1]
                if not isinstance(photo.get('file_id'), str) or len(photo['file_id']) > 500 or photo.get('file_size', 0) > 10_000_000:
                    self.say(db, chat, 'Please send a smaller cropped photo, or tap Skip.', self.buttons([self.button('Skip screenshot', 'skip')]))
                else:
                    data['photo'] = photo['file_id']
                    self.review(db, chat, data)
            elif step == 'review' and action == 'submit':
                ticket = db.execute('INSERT INTO tickets(chat,data,created) VALUES(?,?,?)', (chat, json.dumps(data), self.clock())).lastrowid
                self.cancel(db, chat)
                self.say(db, self.owner, f'New support request #{ticket}\n\n' + self.summary(data) + f'\n\nReply: /reply {ticket} your message\nClose: /close {ticket}')
                if data.get('photo'):
                    self.queue(db, 'sendPhoto', chat_id=self.owner, photo=data['photo'], caption=f'Support request #{ticket} · optional screenshot')
                self.say(db, chat, f'Request #{ticket} saved and queued for our support team. We aim to reply within 1–2 business days. Replies will arrive in this chat. If you need another way to reach us, email {EMAIL}.', self.menu())
            elif step == 'review':
                self.say(db, chat, 'Use Send request, Start again or Cancel on the review message.')
            else:
                self.say(db, chat, 'Please answer the current step within its stated limit, or use /cancel to stop. Photos are accepted only at the screenshot step.')

    def flush(self):
        # A crash after Telegram accepts a message but before this commit can repeat
        # an acknowledgment. Requests themselves are idempotent by update ID.
        with self.db() as db:
            rows = db.execute("SELECT * FROM outbox WHERE status='queued' AND due<=? ORDER BY id LIMIT 25", (self.clock(),)).fetchall()
        for row in rows:
            try:
                self.api(row['method'], **json.loads(row['payload']))
            except TelegramError as exc:
                failed = exc.code in (400, 401, 403, 404) or row['attempts'] >= 7
                with self.db() as db:
                    db.execute('UPDATE outbox SET status=?,attempts=attempts+1,due=? WHERE id=?',
                               ('failed' if failed else 'queued', self.clock() + max(exc.retry_after, min(3600, 5 * 2 ** row['attempts'])), row['id']))
                LOG.warning('Telegram delivery issue: code=%s, outbox_id=%s', exc.code, row['id'])
            else:
                with self.db() as db:
                    db.execute("UPDATE outbox SET status='sent',payload='{}' WHERE id=?", (row['id'],))

    def cleanup(self):
        now = self.clock()
        with self.db() as db:
            db.execute('DELETE FROM drafts WHERE updated<?', (now - 86400,))
            db.execute('DELETE FROM limits WHERE window<?', (now - 86400,))
            db.execute('DELETE FROM updates WHERE created<?', (now - 7 * 86400,))
            db.execute("DELETE FROM tickets WHERE status='closed' AND closed<?", (now - 365 * 86400,))
            db.execute("DELETE FROM outbox WHERE status='sent' AND created<?", (now - 30 * 86400,))
            db.execute("UPDATE outbox SET payload='{}' WHERE status='failed' AND created<?", (now - 7 * 86400,))

    def run(self, stop):
        last_cleanup = 0
        while not stop.is_set():
            try:
                self.flush()
                if self.clock() - last_cleanup >= 3600:
                    self.cleanup()
                    last_cleanup = self.clock()
                with self.db() as db:
                    row = db.execute("SELECT value FROM meta WHERE key='offset'").fetchone()
                updates = self.api('getUpdates', offset=row['value'] if row else 0, timeout=20, limit=50, allowed_updates=['message', 'callback_query'])
                for update in updates:
                    self.process(update)
                self.flush()
            except TelegramError as exc:
                LOG.warning('Telegram connection issue: code=%s', exc.code)
                if exc.code in (401, 409):
                    LOG.error('Telegram worker stopped. Check the token and ensure exactly one polling worker, with no webhook.')
                    return
                stop.wait(max(10, min(exc.retry_after, 300)))
            except Exception:
                # Exception details can contain user data; don't include them.
                LOG.error('Telegram worker encountered an internal error; delivery will retry.')
                stop.wait(20)


def start_bot(directory, stop):
    if os.environ.get('ACADEMY_TELEGRAM_ENABLED') != 'true':
        return None
    try:
        api = TelegramAPI(os.environ.get('ACADEMY_TELEGRAM_BOT_TOKEN', ''))
        bot = SupportBot(directory, api, int(os.environ.get('ACADEMY_TELEGRAM_OWNER_ID', '0')),
                         public=os.environ.get('ACADEMY_TELEGRAM_PUBLIC') == 'true',
                         community=os.environ.get('ACADEMY_TELEGRAM_COMMUNITY_URL', ''),
                         updates=os.environ.get('ACADEMY_TELEGRAM_UPDATES_URL', ''))
    except (ValueError, OSError):
        LOG.error('Telegram is enabled but its private configuration is incomplete; worker not started.')
        return None
    thread = threading.Thread(target=bot.run, args=(stop,), daemon=True, name='academy-telegram')
    thread.start()
    return thread
