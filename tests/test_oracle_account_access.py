"""Remote Oracle authorization stays disabled; explicit synthetic accounts only.

No real credentials, provider calls, browser or execution processes are used.
"""
import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import accounts
import oracle_api

ORIGIN = 'https://terminal.example.test'
CONFIG = {'ELEVENLABS_API_KEY': 'fictional-test-only',
          'ORACLE_ELEVENLABS_AGENT_ID': 'agent_fixture',
          'ORACLE_REMOTE_ENABLED': '1', 'ORACLE_PUBLIC_ORIGIN': ORIGIN,
          'ORACLE_ALLOWED_USER_IDS': '101,102'}
PNG = b'\x89PNG\r\n\x1a\n' + b'fictional-pixels'

def signed(conversation='conv_fixtureA'):
    suffix = '&conversation_id=' + conversation if conversation else ''
    return 'wss://api.elevenlabs.io/v1/convai/conversation?conversation_signature=fictional' + suffix


class OracleAccountAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, CONFIG, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        self.db = patch.object(accounts, 'DB_PATH', os.path.join(self.temp.name, 'accounts.db'))
        self.db.start(); self.addCleanup(self.db.stop)
        accounts.init()
        with accounts._db() as db:
            for uid in [101, 102, 103]:
                db.execute("INSERT INTO users(id,name,role,status,verified,created) VALUES(?,?,'student','accepted',1,?)", (uid, 'Fixture', time.time()))
                db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)', (accounts._digest('fixture-session-token-'+str(uid)), uid, time.time(), time.time()+3600, 'test'))
        app = FastAPI(); app.include_router(oracle_api.router); app.include_router(accounts.router)
        self.client = TestClient(app, base_url=ORIGIN, client=('192.0.2.10', 1234))
        self.client.cookies.set(accounts.SESSION_COOKIE, 'fixture-session-token-101')
        self.get = patch('oracle_api.requests.get', return_value=Mock(status_code=200, json=Mock(return_value={'signed_url': signed()}))).start()
        self.post = patch('oracle_api.requests.post', return_value=Mock(status_code=200, json=Mock(return_value={'file_id':'file_fixture'}))).start()
        self.addCleanup(patch.stopall)
        self.headers = {'Origin': ORIGIN, 'Sec-Fetch-Site': 'same-origin'}

    def session(self):
        return self.client.post('/api/oracle/conversation/session', headers=self.headers)

    def image(self, conv='conv_fixtureA'):
        return self.client.post('/api/oracle/conversation/'+conv+'/image', content=PNG, headers={**self.headers, 'Content-Type':'image/png'})

    def test_remote_disabled_by_default_even_for_signed_in_entitled_user(self):
        os.environ.pop('ORACLE_REMOTE_ENABLED')
        self.assertEqual(self.session().status_code,403)
        self.get.assert_not_called()
        os.environ['ORACLE_REMOTE_ENABLED']='1'; os.environ['PROTRADER_LOCAL_PREVIEW']='1'
        self.assertEqual(self.session().status_code,403)
        self.get.assert_not_called()

    def test_production_cannot_bypass_account_auth_by_forging_loopback_addresses(self):
        app=FastAPI();app.include_router(oracle_api.router)
        fake_local=TestClient(app,base_url='http://127.0.0.1:8020',client=('127.0.0.1',1234))
        # Even an apparent loopback request cannot use preview mode without its
        # explicit startup flag; reverse-proxy forwarded-address spoofing does
        # not turn a production process into a private local preview.
        result=fake_local.post('/api/oracle/conversation/session',headers={'Origin':'http://127.0.0.1:8020'})
        self.assertEqual(result.status_code,403);self.get.assert_not_called()

    def test_remote_needs_real_session_entitlement_and_exact_https_origin(self):
        self.client.cookies.clear()
        self.assertEqual(self.session().status_code,401)
        self.client.cookies.set(accounts.SESSION_COOKIE,'fixture-session-token-103')
        self.assertEqual(self.session().status_code,403)
        self.client.cookies.set(accounts.SESSION_COOKIE,'fixture-session-token-101')
        for change in [{'Origin':'https://evil.example'}, {'Sec-Fetch-Site':'cross-site'}]:
            r=self.client.post('/api/oracle/conversation/session',headers={**self.headers,**change})
            self.assertEqual(r.status_code,403)
        self.assertEqual(self.client.post('/api/oracle/conversation/session').status_code,403)
        self.get.assert_not_called()

    def test_status_does_not_consume_provider_or_expose_key_or_agent(self):
        r=self.client.get('/api/oracle/conversation/status')
        self.assertEqual(r.status_code,200);self.assertFalse(r.json()['local_preview_only'])
        self.assertEqual(r.json()['access_mode'],'entitled-account')
        self.assertNotIn('fictional-test-only',r.text);self.assertNotIn('agent_fixture',r.text)
        self.get.assert_not_called()

    def test_session_records_only_provider_owned_conversation_and_image_requires_same_account_and_login(self):
        r=self.session();self.assertEqual(r.status_code,200)
        with accounts._db() as db:
            row=db.execute('SELECT * FROM oracle_ownership').fetchone()
            self.assertEqual(row['user_id'],101);self.assertEqual(row['conversation_id'],'conv_fixtureA')
            self.assertNotIn('fixture-session-token',row['session_hash'])
        self.client.cookies.set(accounts.SESSION_COOKIE,'fixture-session-token-102')
        self.get.reset_mock();self.assertEqual(self.image().status_code,403);self.get.assert_not_called();self.post.assert_not_called()
        self.client.cookies.set(accounts.SESSION_COOKIE,'fixture-session-token-101')
        self.get.return_value=Mock(status_code=200,json=Mock(return_value={'conversation_id':'conv_fixtureA','agent_id':'agent_fixture','status':'in-progress'}))
        self.assertEqual(self.image().status_code,200)
        self.assertEqual(self.post.call_count,1)
        with accounts._db() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',(accounts._digest('another-fixture-session'),101,time.time(),time.time()+3600,'test'))
        self.client.cookies.set(accounts.SESSION_COOKIE,'another-fixture-session')
        self.assertEqual(self.image().status_code,403)

    def test_remote_provider_without_conversation_id_fails_closed_and_cannot_claim_another_id(self):
        self.get.return_value=Mock(status_code=200,json=Mock(return_value={'signed_url':signed(None)}))
        r=self.session();self.assertEqual(r.status_code,502);self.assertNotIn('signed_url',r.json())
        self.get.reset_mock();self.assertEqual(self.image('conv_somebodyElse').status_code,403);self.get.assert_not_called()

    def test_durable_per_user_limits_count_failed_attempts_and_do_not_block_another_account(self):
        self.get.return_value=Mock(status_code=503,json=Mock(return_value={}))
        for _ in range(6):self.assertEqual(self.session().status_code,502)
        self.get.reset_mock();self.assertEqual(self.session().status_code,429);self.get.assert_not_called()
        oracle_api._ORACLE_SESSION_REQUESTS.clear() # restarting local counters cannot bypass durable budget
        self.assertEqual(self.session().status_code,429)
        self.client.cookies.set(accounts.SESSION_COOKIE,'fixture-session-token-102')
        self.get.return_value=Mock(status_code=200,json=Mock(return_value={'signed_url':signed('conv_fixtureB')}))
        self.assertEqual(self.session().status_code,200)
        with accounts._db() as db:
            db.executemany('INSERT INTO oracle_attempts VALUES(?,?,?)',[(102,'session',time.time()-120)]*29)
        self.assertEqual(self.session().status_code,429)

    def test_account_logout_revokes_existing_remote_upload_access(self):
        self.assertEqual(self.session().status_code,200)
        self.assertEqual(self.client.post('/api/account/logout',headers=self.headers).status_code,200)
        self.get.reset_mock();self.assertEqual(self.image().status_code,401);self.get.assert_not_called()

    def test_remote_quota_reservation_is_atomic_across_parallel_requests(self):
        from concurrent.futures import ThreadPoolExecutor
        from fastapi import HTTPException
        principal={'local':False,'user_id':101,'session_hash':'fixture'}
        # Create the schema before the concurrent transaction race.
        with accounts._db() as db: oracle_api._remote_schema(db)
        def reserve(_):
            try:
                oracle_api._remote_quota(principal,'session')
                return 200
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(reserve,range(8)))
        self.assertEqual(results.count(200),6);self.assertEqual(results.count(429),2)

    def test_expired_or_reused_conversation_cannot_be_reassigned_or_uploaded(self):
        self.assertEqual(self.session().status_code,200)
        self.client.cookies.set(accounts.SESSION_COOKIE,'fixture-session-token-102')
        self.assertEqual(self.session().status_code,502)
        with accounts._db() as db:
            row=db.execute('SELECT * FROM oracle_ownership').fetchone()
            self.assertEqual(row['user_id'],101)
            db.execute('UPDATE oracle_ownership SET created=?',(time.time()-7201,))
        self.client.cookies.set(accounts.SESSION_COOKIE,'fixture-session-token-101')
        self.get.reset_mock();self.assertEqual(self.image().status_code,403);self.get.assert_not_called()

    def test_new_workspace_documents_are_versioned_and_account_isolated(self):
        for key in ['oracleAnalyst','oracleReviews','lessonPractice']:
            r=self.client.put('/api/account/workspace/'+key,json={'data':{'note':'student-101'},'version':0},headers=self.headers)
            self.assertEqual(r.status_code,200)
            stale=self.client.put('/api/account/workspace/'+key,json={'data':{},'version':0},headers=self.headers)
            self.assertEqual(stale.status_code,409)
        self.client.cookies.set(accounts.SESSION_COOKIE,'fixture-session-token-102')
        self.assertEqual(self.client.get('/api/account/workspace').json()['docs'],{})
        self.assertEqual(self.client.get('/api/account/workspace/oracleReviews/history').json().get('copies',[]),[])


if __name__ == '__main__':
    unittest.main()
