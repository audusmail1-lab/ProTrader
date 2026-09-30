import json
import os
import unittest
import http.client
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch,MagicMock
import test_server as fixtures
import support_ai

class SupportTests(unittest.TestCase):
    setUp=fixtures.AcademyTests.setUp
    tearDown=fixtures.AcademyTests.tearDown
    request=fixtures.AcademyTests.request
    teacher=fixtures.AcademyTests.teacher
    student=fixtures.AcademyTests.student
    approve=fixtures.AcademyTests.approve

    def test_guest_preflight_cookie_survives_lost_first_post_response(self):
        result=self.request('/api/support',cookie='')
        guest=self.cookie
        self.assertIsNone(result['thread'])
        self.assertEqual(result['messages'],[])
        with self.server.app.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM support_threads').fetchone()[0],0)
        # Keep the already-received cookie and ignore all response state from the
        # first write, as happens when a mobile connection drops after saving.
        message={'body':'Please help me find my next lesson.','clientId':'first-send-lost-response','human':True}
        self.request('/api/support-message',message,cookie=guest)
        result=self.request('/api/support-message',message,cookie=guest)
        self.assertEqual(len([m for m in result['messages'] if m['role']=='visitor']),1)
        with self.server.app.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM support_threads').fetchone()[0],1)

    def test_guest_preflight_is_signed_private_and_survives_restart(self):
        self.server.app.secure=True
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        conn.request('GET','/api/support',headers={'Cookie':'academy_support=client-chosen-identity'})
        response=conn.getresponse();result=json.loads(response.read());cookie=response.getheader('Set-Cookie');conn.close()
        self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Strict',cookie);self.assertIn('Secure',cookie)
        self.assertNotIn('client-chosen-identity',cookie)
        self.assertEqual(set(result),{'aiAvailable','thread','status','messages'})
        guest=cookie.split(';')[0]
        # A fresh server instance must verify the same pending identity.
        self.server.app=fixtures.Academy(self.tmp.name,self.origin)
        message={'body':'Please explain how lessons work.','clientId':'identity-after-restart','human':True}
        result=self.request('/api/support-message',message,cookie=guest)
        self.assertEqual(self.request('/api/support',cookie=guest)['thread'],result['thread'])
        token=guest.split('=',1)[1]
        forged=guest[:-1]+('0' if guest[-1]!='0' else '1')
        self.assertEqual(self.request('/api/support',cookie=forged)['messages'],[])
        self.assertNotEqual(self.cookie,forged)
        with self.server.app.db() as db:
            self.assertEqual(db.execute('SELECT guest_hash FROM support_threads').fetchone()[0],self.server.app.digest(token))

    def test_parallel_first_sends_share_preissued_identity(self):
        self.request('/api/support',cookie='');guest=self.cookie
        body=json.dumps({'body':'I need help with the classroom.','clientId':'parallel-first-message','human':True})
        def send(_):
            conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
            conn.request('POST','/api/support-message',body,{'Cookie':guest,'Content-Type':'application/json','Origin':self.origin})
            response=conn.getresponse();result=json.loads(response.read());conn.close()
            return response.status,result
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(send,range(2)))
        self.assertEqual([status for status,_ in results],[200,200])
        self.assertEqual(results[0][1]['thread'],results[1][1]['thread'])
        with self.server.app.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM support_threads').fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM support_messages WHERE role='visitor'").fetchone()[0],1)

    def test_guest_isolation_and_human_reply_and_retry(self):
        self.teacher();teacher=self.teacher_cookie
        message={'body':'I need help with the introduction.','clientId':'unique-client-key-1','human':True}
        result=self.request('/api/support-message',message,cookie='')
        guest=self.cookie;tid=result['thread']
        self.assertEqual(result['status'],'waiting')
        self.request('/api/support-message',message,cookie=guest)
        self.assertEqual(self.request('/api/support',cookie='')['messages'],[])
        self.request('/api/support-admin',expected=401,cookie=guest)
        self.request('/api/support-admin-thread',{'thread':tid},401,cookie=guest)
        reply={'thread':tid,'body':'Open the introduction from the home page.','clientId':'unique-reply-key-1'}
        self.request('/api/support-admin-reply',reply,cookie=teacher)
        self.request('/api/support-admin-reply',reply,cookie=teacher)
        result=self.request('/api/support',cookie=guest)
        self.assertEqual(len([m for m in result['messages'] if m['role']=='visitor']),1)
        self.assertEqual(len([m for m in result['messages'] if m['role']=='human']),1)
        self.assertEqual(result['messages'][-1]['body'],reply['body'])
        self.request('/api/support-admin-close',{'thread':tid},cookie=teacher)
        self.assertEqual(self.request('/api/support',cookie=guest)['status'],'closed')

    def test_student_isolation_and_reply_notifications(self):
        self.teacher();uid=self.student();self.approve(uid);student=self.student_cookie
        result=self.request('/api/support-message',{'body':'Where are my classes?','clientId':'student-support-1'})
        self.cookie=student
        self.student('another@example.com')
        self.assertEqual(self.request('/api/support')['messages'],[])
        self.request('/api/support-admin',expected=403)
        self.request('/api/support-admin-reply',{'thread':result['thread'],'body':'Open your classroom.','clientId':'reply-to-student-1'},cookie=self.teacher_cookie)
        with self.server.app.db() as db:
            row=db.execute("SELECT recipient,body FROM mail WHERE subject='Your Academy support reply'").fetchone()
            self.assertEqual(row['recipient'],'student@example.com')
            self.assertNotIn('Where are my classes?',row['body'])
        self.assertEqual(self.request('/api/support',cookie=student)['messages'][-1]['role'],'human')

    @patch('support_ai.available',return_value=True)
    @patch('support_ai.answer',return_value=('Open /#library for the guides.',False))
    def test_ai_consent_handoff_and_no_duplicate_ai(self,answer,available):
        self.teacher()
        body={'body':'Where are the public videos?','clientId':'ai-consent-message-1','aiConsent':True}
        result=self.request('/api/support-message',body,cookie='');guest=self.cookie
        self.assertEqual(result['status'],'ai');self.assertEqual(answer.call_count,1)
        self.request('/api/support-message',body,cookie=guest);self.assertEqual(answer.call_count,1)
        self.request('/api/support-message',{'body':'A human please','human':True,'aiConsent':True,'clientId':'ai-handoff-message-1'},cookie=guest)
        self.request('/api/support-message',{'body':'Are the guides public?','aiConsent':True,'clientId':'after-human-message-1'},cookie=guest)
        self.assertEqual(answer.call_count,1)
        self.request('/api/support-message',{'body':'Where are the public videos?','clientId':'no-ai-consent-1'},cookie='')
        self.assertEqual(answer.call_count,1)

    @patch('support_ai.available',return_value=True)
    @patch('support_ai.answer',side_effect=TimeoutError)
    def test_ai_failure_saves_message_and_escalates(self,answer,available):
        self.teacher()
        result=self.request('/api/support-message',{'body':'How do lessons work?','clientId':'ai-failure-message-1','aiConsent':True},cookie='')
        self.assertEqual(result['status'],'waiting')
        self.assertIn('human',result['messages'][-1]['body'])
        with self.server.app.db() as db:
            self.assertIsNotNone(db.execute("SELECT id FROM mail WHERE subject='Academy support needs a human'").fetchone())

    def test_ai_request_bounded_and_does_not_store_response(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'answer':'Open /#library.','escalate':False})}]}]}).encode()
        with patch.dict(os.environ,{'ACADEMY_SUPPORT_OPENAI_API_KEY':'test-placeholder'}),patch('support_ai.urlopen',return_value=response) as request:
            self.assertEqual(support_ai.answer([{'role':'visitor','body':'Where are videos?'}],True),('Open /#library.',False))
            payload=json.loads(request.call_args.args[0].data)
            self.assertFalse(payload['store']);self.assertEqual(payload['max_output_tokens'],450)
            self.assertNotIn('tools',payload);self.assertEqual(request.call_args.kwargs['timeout'],12)
            self.assertIn('same account and maintain separate sessions',payload['instructions'])
            self.assertIn('not your password or password hash',payload['instructions'])
            self.assertNotIn('accounts are separate',payload['instructions'])
