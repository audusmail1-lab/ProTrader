"""Sign in to the PROTrader app with an Academy account.   python3 -m unittest test_app_sso"""
import http.client
import json
import secrets
import time
from urllib.parse import parse_qs, urlsplit

from app_sso import challenge_of
from test_server import AcademyTests


class AppSignInTests(AcademyTests):
    def raw(self, method, path, body=None, cookie=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        h = {'Cookie': cookie if cookie is not None else self.cookie}
        h.update(headers or {})
        conn.request(method, path, json.dumps(body) if body is not None else None, h)
        r = conn.getresponse()
        data = r.read()
        out = (r.status, r.getheader('Location'), r.getheader('Content-Type', ''), data)
        conn.close()
        return out

    def exchange(self, code, verifier):
        return self.raw('POST', '/api/app-exchange', {'code': code, 'verifier': verifier}, cookie='',
                        headers={'Content-Type': 'application/json'})

    def start(self, cookie):
        verifier = secrets.token_urlsafe(48)
        state = secrets.token_urlsafe(24)
        status, location, ctype, body = self.raw('GET', f'/app-login?state={state}&challenge={challenge_of(verifier)}', cookie=cookie)
        return status, location, body, state, verifier

    def test_incomplete_link_is_refused(self):
        status, _, _, _ = self.raw('GET', '/app-login?state=short&challenge=x')
        self.assertEqual(status, 400)

    def test_signed_out_browser_gets_the_sign_in_page(self):
        status, location, body, _, _ = self.start(cookie='')
        self.assertEqual(status, 200)
        self.assertIn(b'Sign in to PROTrader', body)
        self.assertIn(b'/app-login.js', body)
        self.assertEqual(self.raw('GET', '/app-login.js')[0], 200)

    def test_code_flow_returns_the_account_once(self):
        self.teacher(); uid = self.student(); self.approve(uid)
        status, location, _, state, verifier = self.start(cookie=self.student_cookie)
        self.assertEqual(status, 302)
        target = urlsplit(location)
        self.assertEqual(f'{target.scheme}://{target.netloc}{target.path}', 'https://app.example.com/auth/academy/callback')
        q = parse_qs(target.query)
        self.assertEqual(q['state'][0], state)
        code = q['code'][0]
        status, _, _, body = self.exchange(code, verifier)
        self.assertEqual(status, 200, body)
        user = json.loads(body)['user']
        self.assertEqual((user['id'], user['email'], user['role'], user['status'], bool(user['verified'])),
                         (uid, 'student@example.com', 'student', 'accepted', True))
        self.assertNotIn('password', user)
        self.assertEqual(self.exchange(code, verifier)[0], 400)            # single use

    def test_wrong_verifier_burns_the_code(self):
        self.teacher()
        _, location, _, _, verifier = self.start(cookie=self.teacher_cookie)
        code = parse_qs(urlsplit(location).query)['code'][0]
        self.assertEqual(self.exchange(code, secrets.token_urlsafe(48))[0], 400)
        self.assertEqual(self.exchange(code, verifier)[0], 400)

    def test_expired_code_is_refused(self):
        self.teacher()
        _, location, _, _, verifier = self.start(cookie=self.teacher_cookie)
        code = parse_qs(urlsplit(location).query)['code'][0]
        with self.server.app.db() as db:
            db.execute('UPDATE app_codes SET expires=?', (time.time() - 1,))
        self.assertEqual(self.exchange(code, verifier)[0], 400)

    def test_pending_applicant_is_reported_as_pending(self):
        self.teacher(); self.student('pending@example.com')
        _, location, _, _, verifier = self.start(cookie=self.student_cookie)
        code = parse_qs(urlsplit(location).query)['code'][0]
        user = json.loads(self.exchange(code, verifier)[3])['user']
        self.assertEqual((user['status'], bool(user['verified'])), ('pending', False))


# Only this file's tests: switch off the inherited AcademyTests cases here
# (they run in test_server), and hide the imported base from discovery.
for _name in dir(AcademyTests):
    if _name.startswith('test_') and _name not in AppSignInTests.__dict__:
        setattr(AppSignInTests, _name, None)
del AcademyTests
