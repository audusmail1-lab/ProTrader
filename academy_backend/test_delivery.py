import json
from io import BytesIO
import os
from pathlib import Path
import smtplib
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from backup import backup
from mailer import SMTPConfig
from production import wsgi_app
from server import Academy

SMTP_ENV = {
    'ACADEMY_SMTP_HOST': 'smtp.resend.com', 'ACADEMY_SMTP_USER': 'resend',
    'ACADEMY_SMTP_PASSWORD': 'fake-test-secret', 'ACADEMY_SMTP_FROM': 'Academy <academy@example.com>',
    'ACADEMY_SMTP_PORT': '587', 'ACADEMY_SMTP_SECURITY': 'starttls',
    'ACADEMY_MAIL_ENABLED': 'true', 'ACADEMY_NOTIFICATION_RECIPIENT': 'owner@example.com',
}

class DeliveryTests(unittest.TestCase):
    def test_transport_upgrades_before_credentials_and_stable_identity(self):
        with patch.dict(os.environ, SMTP_ENV), patch('mailer.smtplib.SMTP') as smtp:
            connection = smtp.return_value
            connection.__enter__.return_value = connection
            connection.send_message.return_value = {}
            cfg = SMTPConfig.from_environment()
            row = {'recipient':'student@example.com','subject':'Test','body':'Example','delivery_key':'stable-123'}
            cfg.send(row); cfg.send(row)
            names = [call[0] for call in connection.method_calls]
            self.assertLess(names.index('starttls'), names.index('login'))
            messages = [call.args[0] for call in connection.send_message.call_args_list]
            self.assertEqual(messages[0]['Message-ID'], messages[1]['Message-ID'])
            self.assertEqual(messages[0]['Resend-Idempotency-Key'], 'academy/stable-123')
            connection.noop.return_value = (250,b'OK')
            cfg.check()
            self.assertEqual(connection.send_message.call_count, 2)  # check sends nothing

    def test_no_plaintext_or_missing_config(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError): SMTPConfig.from_environment()
        with patch.dict(os.environ, {**SMTP_ENV,'ACADEMY_SMTP_SECURITY':'none'}):
            with self.assertRaises(ValueError): SMTPConfig.from_environment()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, SMTP_ENV):
            with self.assertRaises(ValueError): Academy(directory,'http://127.0.0.1:1234')

    def test_queue_success_failure_expiry_disabled_and_backup(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, SMTP_ENV):
            app = Academy(directory,'https://academy.example.com')
            app.smtp = MagicMock()
            with app.db() as db:
                app.enqueue(db,'student@example.com','Update','Private text')
                app.enqueue(db,'student@example.com','Reset your academy password','Expired token')
                db.execute("UPDATE mail SET created=? WHERE subject='Reset your academy password'",(time.time()-1900,))
            app.process_mail()
            self.assertEqual(app.smtp.send.call_count,1)
            with app.db() as db:
                rows = db.execute('SELECT status,body FROM mail ORDER BY id').fetchall()
            self.assertEqual([tuple(r) for r in rows],[('sent',''),('expired','')])
            app.smtp.send.side_effect = smtplib.SMTPAuthenticationError(535,b'fake-test-secret')
            with app.db() as db: app.enqueue(db,'student@example.com','Another update','Body')
            app.process_mail()
            with app.db() as db:
                row = db.execute('SELECT status,error FROM mail ORDER BY id DESC LIMIT 1').fetchone()
            self.assertEqual(row['status'],'failed')
            self.assertNotIn('fake-test-secret',row['error'])
            app.mail_enabled = False
            with app.db() as db: app.enqueue(db,'student@example.com','Disabled','Body')
            app.process_mail()
            self.assertEqual(app.smtp.send.call_count,2)
            target = Path(directory)/'backup.sqlite3'
            backup(app.dbfile,target)
            self.assertEqual(target.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError): backup(app.dbfile,target)

    def test_wsgi_setup_session_secure_cookie_origin_and_health(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'ACADEMY_MAIL_ENABLED':'false','ACADEMY_ENROLLMENT_OPEN':'false'}):
            app = Academy(directory,'https://academy.example.com')
            wsgi = wsgi_app(app)
            def request(path, payload=None, cookie='', origin='https://academy.example.com', method=None):
                raw = json.dumps(payload).encode() if payload is not None else b''
                env = {'PATH_INFO':path,'REQUEST_METHOD':method or ('POST' if payload is not None else 'GET'),
                       'REMOTE_ADDR':'127.0.0.1','wsgi.input':BytesIO(raw), 'CONTENT_TYPE':'application/json',
                       'CONTENT_LENGTH':str(len(raw)),'HTTP_ORIGIN':origin,'HTTP_COOKIE':cookie}
                response = {}
                body = b''.join(wsgi(env,lambda status,headers:response.update(status=status,headers=dict(headers))))
                return response, body
            response, body = request('/healthz')
            self.assertEqual(response['status'],'200 OK')
            response, body = request('/api/setup',{'name':'Instructor','email':'teacher@example.com','password':'fake-test-password-123','setup_token':app.setup_file.read_text()})
            self.assertEqual(response['status'],'201 Created')
            cookie = response['headers']['Set-Cookie']
            self.assertIn('Secure',cookie)
            response, body = request('/api/admin',cookie=cookie)
            self.assertEqual(response['status'],'200 OK')
            response, body = request('/api/register',{})
            self.assertEqual(response['status'],'403 Forbidden')
            response, body = request('/api/mail-test',{},cookie=cookie)
            self.assertEqual(response['status'],'409 Conflict')
            response, body = request('/api/logout',{},cookie=cookie,origin='https://evil.example')
            self.assertEqual(response['status'],'403 Forbidden')
            response, body = request('/healthz',method='HEAD')
            self.assertEqual(body,b'')
            response, body = request('/healthz',method='DELETE')
            self.assertEqual(response['status'],'405 Method Not Allowed')

class ProductionSocketTests(unittest.TestCase):
    def test_waitress_serves_same_routes_and_rejects_large_requests(self):
        try:
            from waitress import create_server
        except ImportError:
            self.skipTest('Install academy_backend/requirements.txt to test production HTTP serving.')
        import http.client
        import threading
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'ACADEMY_MAIL_ENABLED':'false','ACADEMY_APP_URL':'https://app.example.com'}):
            app = Academy(directory, 'https://academy.example.com')
            server = create_server(wsgi_app(app), host='127.0.0.1', port=0, max_request_body_size=20000)
            stopping = threading.Event()
            errors = []
            def run_server():
                try: server.run()
                except OSError as exc:
                    # Closing the fixture's listening socket can interrupt select().
                    if not stopping.is_set(): errors.append(exc)
            thread = threading.Thread(target=run_server, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection('127.0.0.1', server.effective_port, timeout=5)
                conn.request('GET','/api/session')
                response = conn.getresponse()
                self.assertEqual(response.status,200)
                self.assertEqual(json.loads(response.read())['appUrl'],'https://app.example.com')
                conn.request('GET','/api/lessons')
                response=conn.getresponse();response.read()
                self.assertEqual(response.status,401)
                conn.request('POST','/api/login',b'x'*21000,{'Content-Type':'application/json','Origin':app.origin})
                response=conn.getresponse();response.read()
                self.assertEqual(response.status,413)
                conn.close()
            finally:
                stopping.set()
                server.close()
                server.task_dispatcher.shutdown()
                thread.join(timeout=3)
                self.assertEqual(errors, [])
