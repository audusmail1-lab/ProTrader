import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
from server import make_server,Academy

class AcademyTests(unittest.TestCase):
    def setUp(self):
        environment=patch.dict(os.environ,{'ACADEMY_MAIL_ENABLED':'false','ACADEMY_ENROLLMENT_OPEN':'true','ACADEMY_NOTIFICATION_RECIPIENT':'teacher@example.com','ACADEMY_APP_URL':'https://app.example.com'})
        environment.start();self.addCleanup(environment.stop)
        self.tmp=tempfile.TemporaryDirectory()
        self.server=make_server(self.tmp.name,0)
        self.port=self.server.server_address[1]
        self.origin=f'http://127.0.0.1:{self.port}'
        self.server.app.origin=self.origin
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.cookie=''
        self.password='Test-only-long-password-173!'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.tmp.cleanup()
    def request(self,path,data=None,expected=200,origin=None,cookie=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        headers={'Cookie':self.cookie if cookie is None else cookie}
        if data is not None: headers.update({'Content-Type':'application/json','Origin':origin or self.origin})
        conn.request('GET' if data is None else 'POST',path,json.dumps(data) if data is not None else None,headers)
        response=conn.getresponse();raw=response.read();ctype=response.getheader('Content-Type','')
        body=json.loads(raw) if ctype.startswith('application/json') else raw.decode()
        self.assertEqual(response.status,expected,(path,body))
        new_cookie=response.getheader('Set-Cookie')
        if new_cookie: self.cookie=new_cookie.split(';')[0]
        conn.close();return body
    def teacher(self):
        token=self.server.app.setup_file.read_text()
        self.request('/api/setup',{'name':'Sample Instructor','email':'teacher@example.com','password':self.password,'setup_token':token},201)
        self.teacher_cookie=self.cookie
    def student(self,email='student@example.com'):
        self.request('/api/register',{'name':'Sample Learner','email':email,'password':self.password,'experience':'Beginner','difficulty':'Reading charts','goal':'Learn to explain a fictional ticket.','consent':True},201)
        self.student_cookie=self.cookie
        return self.request('/api/session')['user']['id']
    def approve(self,uid):
        self.request('/api/admission',{'student':uid,'status':'accepted','verified':True,'note':'Welcome to the class.'},cookie=self.teacher_cookie)
    def test_application_availability_matches_server_gate(self):
        self.assertFalse(self.request('/api/session')['enrollmentOpen'])
        self.teacher()
        self.assertTrue(self.request('/api/session')['enrollmentOpen'])
        self.server.app.enrollment_open=False
        self.assertFalse(self.request('/api/session')['enrollmentOpen'])
        self.request('/api/register',{'name':'Sample Learner','email':'closed@example.com','password':self.password,'experience':'Beginner','difficulty':'Reading charts','goal':'Learn to explain a fictional ticket.','consent':True},403)
        with self.server.app.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users WHERE role='student'").fetchone()[0],0)
    def test_student_workflow_queues_notifications_to_the_right_recipient(self):
        self.teacher();uid=self.student();self.approve(uid)
        self.request('/api/questions',{'lesson':2,'body':'Why did the example loss change with size?'},201)
        question=self.request('/api/questions')[0]
        self.request('/api/reply',{'question':question['id'],'body':'Each additional unit has the same price difference.'},cookie=self.teacher_cookie)
        self.request('/api/reset-request',{'email':'student@example.com'})
        app=self.server.app
        with app.db() as db:
            rows=db.execute('SELECT recipient,subject,body FROM mail ORDER BY id').fetchall()
        self.assertEqual([(r['recipient'],r['subject']) for r in rows],[
            ('teacher@example.com','New academy application'),
            ('student@example.com','Academy application update'),
            ('teacher@example.com','New academy question'),
            ('student@example.com','Your instructor replied'),
            ('student@example.com','Reset your academy password'),
        ])
        self.assertNotIn('Learn to explain a fictional ticket.',rows[0]['body'])
        self.assertNotIn('Why did the example loss change',rows[2]['body'])
        self.assertNotIn('Each additional unit',rows[3]['body'])
        self.assertIn(self.origin+'/#reset/',rows[4]['body'])
        app.smtp=MagicMock();app.mail_enabled=True
        app.process_mail()
        self.assertEqual(app.smtp.send.call_count,5)
        with app.db() as db:
            self.assertEqual([tuple(r) for r in db.execute('SELECT status,body FROM mail')],[('sent','')]*5)
    def test_setup_auth_and_private_assets(self):
        self.request('/api/lessons',expected=401)
        self.request('/api/materials.js',expected=401)
        for path in ['/content.js','/practice.js','/app.js','/academy.config.local.json','/../.academy-data/academy.sqlite3','/README.md']:
            self.request(path,expected=404)
        self.teacher()
        self.request('/api/setup',{'name':'Another teacher','email':'other@example.com','password':self.password,'setup_token':'wrong'},409)
        uid=self.student()
        self.request('/api/admin',expected=403)
        self.request('/api/classroom',expected=403)
        self.request('/api/admission',{'student':uid,'status':'accepted','verified':True},403)
        self.request('/api/admission',{'student':uid,'status':'accepted'},400,cookie=self.teacher_cookie)
        self.approve(uid)
        self.assertEqual(len(self.request('/api/lessons')),7)
        self.assertIn('export function practice',self.request('/api/materials.js'))
        self.request('/api/progress',{'lesson':0,'complete':True,'notes':'hello'},403,origin='https://attacker.invalid')
    def test_persistent_progress_questions_and_isolation(self):
        self.teacher();uid=self.student();self.approve(uid)
        self.request('/api/progress',{'lesson':1,'complete':True,'notes':'My chart explanation'})
        self.request('/api/questions',{'lesson':1,'body':'How should I explain this candle?'},201)
        q=self.request('/api/questions')[0]
        self.request('/api/reply',{'question':q['id'],'body':'Start with open and close.'},403)
        self.request('/api/reply',{'question':q['id'],'body':'Start with open and close.'},cookie=self.teacher_cookie)
        self.assertEqual(self.request('/api/questions')[0]['replies'][0]['body'],'Start with open and close.')
        self.request('/api/schedule',{'sessions':[{'lesson':1,'when':'Confirmed sample time WAT','url':'javascript:alert(1)'}]},400,cookie=self.teacher_cookie)
        self.request('/api/schedule',{'sessions':[{'lesson':1,'when':'Confirmed sample time WAT','url':'https://example.com/class'}]},cookie=self.teacher_cookie)
        self.assertEqual(self.request('/api/classroom')['progress'][0]['notes'],'My chart explanation')
        uid2=self.student('second@example.com');self.approve(uid2)
        self.assertEqual(self.request('/api/questions'),[])
        self.assertEqual(self.request('/api/classroom')['progress'],[])
        persisted=Academy(self.tmp.name,self.origin)
        with persisted.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM replies').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT notes FROM progress WHERE user_id=?',(uid,)).fetchone()[0],'My chart explanation')
    def test_recovery_revokes_sessions_and_token_is_single_use(self):
        self.teacher();uid=self.student();self.approve(uid)
        self.request('/api/reset-request',{'email':'student@example.com'})
        with self.server.app.db() as db:
            body=db.execute("SELECT body FROM mail WHERE subject='Reset your academy password'").fetchone()[0]
        token=body.split('#reset/')[1].split('\n')[0]
        self.request('/api/reset',{'token':token,'password':'A-different-long-password!'})
        self.request('/api/classroom',expected=401)
        self.request('/api/reset',{'token':token,'password':'Yet-another-long-password!'},400)
        self.request('/api/login',{'email':'student@example.com','password':self.password},401)
        self.request('/api/login',{'email':'student@example.com','password':'A-different-long-password!'})
        self.assertEqual(self.request('/api/session')['user']['id'],uid)
        self.request('/api/logout',{})
        self.request('/api/classroom',expected=401)
    def test_application_resubmission_and_validation(self):
        self.teacher();uid=self.student()
        self.request('/api/admission',{'student':uid,'status':'needs_information','note':'Please explain your goal.'},cookie=self.teacher_cookie)
        self.assertEqual(self.request('/api/account',{})['note'],'Please explain your goal.')
        self.request('/api/application-update',{'goal':'I want to learn chart reading first.','difficulty':'Complete beginner'})
        self.assertEqual(self.request('/api/session')['user']['status'],'pending')
        self.approve(uid)
        self.request('/api/application-update',{'goal':'I want to learn chart reading first.','difficulty':'Complete beginner'},403)
        self.request('/api/progress',{'lesson':99,'notes':'','complete':True},400)
        self.request('/api/questions',{'lesson':0,'body':'short'},400)
        with self.server.app.db() as db:
            pw=db.execute('SELECT password FROM users WHERE id=?',(uid,)).fetchone()[0]
            self.assertNotIn(self.password,pw)
            self.assertTrue(self.server.app.password(self.password,pw))

if __name__=='__main__': unittest.main(verbosity=2)
