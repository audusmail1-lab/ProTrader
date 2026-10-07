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

    def test_password_reset_revokes_only_that_accounts_pending_codes(self):
        self.teacher()
        _, teacher_location, _, _, teacher_verifier = self.start(cookie=self.teacher_cookie)
        teacher_code = parse_qs(urlsplit(teacher_location).query)['code'][0]
        uid = self.student(); self.approve(uid)
        _, location, _, _, verifier = self.start(cookie=self.student_cookie)
        code = parse_qs(urlsplit(location).query)['code'][0]
        self.request('/api/reset-request', {'email': 'student@example.com'})
        with self.server.app.db() as db:
            body = db.execute("SELECT body FROM mail WHERE subject='Reset your academy password' AND recipient=?", ('student@example.com',)).fetchone()[0]
        token = body.split('#reset/')[1].split('\n')[0]
        new_password = 'A-changed-test-only-password!'
        self.request('/api/reset', {'token': token, 'password': new_password})
        self.request('/api/classroom', expected=401, cookie=self.student_cookie)
        self.assertEqual(self.exchange(code, verifier)[0], 400)
        self.assertEqual(self.exchange(teacher_code, teacher_verifier)[0], 200)
        self.request('/api/login', {'email': 'student@example.com', 'password': new_password})
        _, fresh_location, _, _, fresh_verifier = self.start(cookie=self.cookie)
        fresh_code = parse_qs(urlsplit(fresh_location).query)['code'][0]
        self.assertEqual(self.exchange(fresh_code, fresh_verifier)[0], 200)

    def test_exchange_rejects_non_object_json(self):
        for payload in ([], [{}], 'invalid', 42, True, None):
            with self.subTest(payload=payload):
                conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
                try:
                    conn.request('POST', '/api/app-exchange', json.dumps(payload), {'Content-Type': 'application/json'})
                    response = conn.getresponse()
                    body = json.loads(response.read())
                    self.assertEqual(response.status, 400, body)
                    self.assertEqual(body, {'error': 'Invalid request.'})
                finally:
                    conn.close()

    def test_pending_applicant_is_reported_as_pending(self):
        self.teacher(); self.student('pending@example.com')
        _, location, _, _, verifier = self.start(cookie=self.student_cookie)
        code = parse_qs(urlsplit(location).query)['code'][0]
        user = json.loads(self.exchange(code, verifier)[3])['user']
        self.assertEqual((user['status'], bool(user['verified'])), ('pending', False))

    def test_add_account_always_asks_for_a_sign_in(self):
        self.teacher()
        verifier = secrets.token_urlsafe(48)
        path = f'/app-login?state={secrets.token_urlsafe(24)}&challenge={challenge_of(verifier)}'
        self.assertEqual(self.raw('GET', path, cookie=self.teacher_cookie)[0], 302)
        status, _, _, body = self.raw('GET', path + '&prompt=login', cookie=self.teacher_cookie)
        self.assertEqual(status, 200)
        self.assertIn(b'Add another account', body)

    def test_production_wsgi_passes_the_query_string(self):
        from io import BytesIO
        from production import wsgi_app
        verifier = secrets.token_urlsafe(48)
        env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/app-login', 'QUERY_STRING': f'state={secrets.token_urlsafe(24)}&challenge={challenge_of(verifier)}',
               'REMOTE_ADDR': '127.0.0.1', 'wsgi.input': BytesIO()}
        seen = {}
        body = b''.join(wsgi_app(self.server.app)(env, lambda status, headers: seen.update(status=status)))
        self.assertTrue(seen['status'].startswith('200'), (seen, body[:200]))
        self.assertIn(b'Sign in to PROTrader', body)


# Only this file's tests: switch off the inherited AcademyTests cases here
# (they run in test_server), and hide the imported base from discovery.
for _name in dir(AcademyTests):
    if _name.startswith('test_') and _name not in AppSignInTests.__dict__:
        setattr(AppSignInTests, _name, None)
del AcademyTests
