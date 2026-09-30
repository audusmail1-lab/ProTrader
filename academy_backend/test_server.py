import http.client
import gzip
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
from server import make_server,Academy
from welcome import WELCOME_SUBJECT

class AcademyTests(unittest.TestCase):
    def setUp(self):
        environment=patch.dict(os.environ,{'ACADEMY_MAIL_ENABLED':'false','ACADEMY_ENROLLMENT_OPEN':'true','ACADEMY_NOTIFICATION_RECIPIENT':'teacher@example.com','ACADEMY_APP_URL':'https://app.example.com'})
        environment.start();self.addCleanup(environment.stop)
        self.tmp=tempfile.TemporaryDirectory()
        self.server=make_server(self.tmp.name,0)
        self.server.app.policy.update(published=True,operatorName='Sample Operator',operatorAddress='Sample business address',contactEmail='teacher@example.com',adultOnly=True,retentionApproved=True)
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
        self.request('/api/register',{'name':'Sample Learner','email':email,'password':self.password,'experience':'Beginner','difficulty':'Reading charts','goal':'Learn to explain a fictional ticket.','consent':True,'terms':True,'adult':True,'policyVersion':self.server.app.policy['version']},201)
        self.student_cookie=self.cookie
        return self.request('/api/session')['user']['id']
    def approve(self,uid):
        self.request('/api/admission',{'student':uid,'status':'accepted','verified':True,'note':'Welcome to the class.'},cookie=self.teacher_cookie)

    def test_alex_audio_policy_allows_only_pinned_safari_resampler(self):
        resampler='https://cdn.jsdelivr.net/npm/@alexanderolsen/libsamplerate-js@2.1.2/dist/libsamplerate.worklet.js'
        for path in ('/', '/classroom'):
            with self.subTest(path=path):
                conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
                conn.request('GET',path)
                response=conn.getresponse()
                response.read()
                policy={part.split()[0]:part.split()[1:] for part in response.getheader('Content-Security-Policy').split(';') if part.strip()}
                conn.close()
                self.assertEqual(response.status,200)
                # Modern browsers use script-src; pre-fix Safari uses worker-src.
                for directive in ('script-src','worker-src'):
                    self.assertIn(resampler,policy[directive])
                    self.assertIn('blob:',policy[directive])
                    for overly_broad in ('*','https:', 'https://cdn.jsdelivr.net', 'https://*.jsdelivr.net', 'data:', "'unsafe-eval'", "'unsafe-inline'"):
                        self.assertNotIn(overly_broad,policy[directive])
                self.assertIn('wss://*.elevenlabs.io',policy['connect-src'])
                self.assertIn('wss://*.livekit.cloud',policy['connect-src'])
                self.assertEqual(policy['frame-ancestors'],["'none'"])
                self.assertEqual(policy['base-uri'],["'self'"])
                self.assertEqual(policy['form-action'],["'self'"])

    def test_motion_assets_use_exact_public_paths_and_correct_types(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            allowed={f'posters/motion-{i}.jpg':'image/jpeg' for i in range(10)}
            allowed.update({f'captions/motion-{i}.vtt':'text/vtt; charset=utf-8' for i in range(10)})
            blocked=('posters/motion-10.jpg','captions/motion-10.vtt','posters/motion-0.jpg.bak','captions/motion-0.json')
            for name in (*allowed,*blocked):
                asset=root/'academy'/name
                asset.parent.mkdir(parents=True,exist_ok=True)
                asset.write_bytes(b'WEBVTT\n\n' if name.endswith('.vtt') else b'test asset')
            # Keep the real allowlist: files merely existing must not expose them.
            with patch('server.ROOT',root):
                for name,mime in allowed.items():
                    with self.subTest(name=name):
                        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
                        conn.request('GET','/'+name)
                        response=conn.getresponse();body=response.read()
                        self.assertEqual(response.status,200)
                        self.assertEqual(response.getheader('Content-Type'),mime)
                        self.assertEqual(response.getheader('Cache-Control'),'no-cache')
                        self.assertEqual(body,(root/'academy'/name).read_bytes())
                        self.assertTrue(response.getheader('ETag'))
                        conn.close()
                for name in (*blocked,'posters/../posters/motion-0.jpg','captions/%2e%2e/captions/motion-0.vtt'):
                    with self.subTest(blocked=name):
                        self.request('/'+name,expected=404)

    def test_film_media_policy_allows_the_exact_distribution_on_both_pages(self):
        for path in ('/','/classroom'):
            with self.subTest(path=path):
                conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
                conn.request('GET',path)
                response=conn.getresponse();html=response.read().decode()
                directives={part.split()[0]:part.split()[1:] for part in response.getheader('Content-Security-Policy').split(';') if part.strip()}
                self.assertEqual(response.status,200)
                self.assertIn('https://d2ol7oe51mr4n9.cloudfront.net',directives['media-src'])
                self.assertIn("'self'",directives['media-src'])
                self.assertIn("'self'",directives['img-src'])
                for broad in ('*','https:','https://*.cloudfront.net'):
                    self.assertNotIn(broad,directives['media-src'])
                self.assertNotIn('content-security-policy',html.lower())
                conn.close()

    def test_recovery_copy_is_private_and_visitor_facing(self):
        self.teacher();self.student()
        known=self.request('/api/reset-request',{'email':'student@example.com'})
        unknown=self.request('/api/reset-request',{'email':'unknown@example.com'})
        self.assertEqual(known,unknown)
        self.assertIn('Check your inbox and spam folder.',known['message'])
        for term in ('instructor','service','connected','queued'):
            self.assertNotIn(term,known['message'])

    def test_public_assets_revalidate_across_encodings_and_file_edits(self):
        def fetch(headers):
            conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
            conn.request('GET','/cinematic/cache-test.js',headers=headers)
            response=conn.getresponse();body=response.read()
            result=response.status,dict(response.getheaders()),body
            conn.close();return result
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);asset=root/'academy/cinematic/cache-test.js'
            asset.parent.mkdir(parents=True)
            original=b'export const version = 1;\n'
            asset.write_bytes(original)
            compressed=gzip.compress(original,mtime=0)
            asset.with_suffix('.js.gz').write_bytes(compressed)
            with patch('server.ROOT',root),patch('server.PUBLIC',{'cinematic/cache-test.js'}):
                status,headers,body=fetch({})
                self.assertEqual((status,body),(200,original))
                self.assertEqual(headers['Content-Type'],'text/javascript; charset=utf-8')
                self.assertEqual(headers['Cache-Control'],'no-cache')
                self.assertEqual(headers['Vary'],'Accept-Encoding')
                plain_tag=headers['ETag']
                status,headers,body=fetch({'If-None-Match':'"different", W/'+plain_tag})
                self.assertEqual((status,body),(304,b''))
                self.assertEqual(headers['ETag'],plain_tag)
                self.assertNotIn('Content-Length',headers)
                status,headers,body=fetch({'Accept-Encoding':'gzip','If-None-Match':plain_tag})
                self.assertEqual((status,body),(200,compressed))
                self.assertEqual(headers['Content-Encoding'],'gzip')
                gzip_tag=headers['ETag']
                self.assertNotEqual(gzip_tag,plain_tag)
                status,headers,body=fetch({'Accept-Encoding':'gzip','If-None-Match':gzip_tag})
                self.assertEqual((status,body),(304,b''))
                self.assertEqual(headers['Vary'],'Accept-Encoding')
                status,headers,body=fetch({'Accept-Encoding':'gzip;q=0','If-None-Match':gzip_tag})
                self.assertEqual((status,body),(200,original))
                self.assertNotIn('Content-Encoding',headers)
                asset.write_bytes(b'export const version = 2;\n')
                os.utime(asset.with_suffix('.js.gz'),(0,0))
                status,headers,body=fetch({'If-None-Match':plain_tag})
                self.assertEqual((status,body),(200,b'export const version = 2;\n'))
                self.assertNotEqual(headers['ETag'],plain_tag)
                status,headers,body=fetch({'Accept-Encoding':'gzip','If-None-Match':gzip_tag})
                self.assertEqual((status,body),(200,b'export const version = 2;\n'))
                self.assertNotIn('Content-Encoding',headers)

    def test_documents_and_private_responses_cannot_use_asset_cache(self):
        for path,status in [('/',200),('/classroom',200),('/api/session',200),('/api/support',200),('/api/classroom',401),('/api/materials.js',401),('/not-public.js',404)]:
            with self.subTest(path=path):
                conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
                conn.request('GET',path,headers={'If-None-Match':'*'})
                response=conn.getresponse();response.read();conn.close()
                self.assertEqual(response.status,status)
                self.assertEqual(response.getheader('Cache-Control'),'no-store')
                self.assertIsNone(response.getheader('ETag'))

    def test_acceptance_verification_and_repeat_saves(self):
        self.teacher();uid=self.student()
        payload={'student':uid,'status':'accepted'}
        self.request('/api/admission',payload,cookie=self.teacher_cookie)
        self.request('/api/admission',payload,cookie=self.teacher_cookie)
        self.request('/api/classroom',expected=403)
        with self.server.app.db() as db:
            rows=db.execute("SELECT body FROM mail WHERE recipient='student@example.com'").fetchall()
            self.assertEqual(len(rows),1)
        token=rows[0]['body'].split('/#verify/')[1].split()[0]
        self.request('/api/verify-email',{'token':token})
        self.request('/api/classroom')
        self.request('/api/verify-email',{'token':token},400)
        self.assertTrue(self.request('/api/session')['user']['verified'])

    def test_schedule_changes_notify_only_eligible_students_once(self):
        self.teacher();uid=self.student();self.approve(uid)
        other=self.student('pending@example.com')
        schedule={'sessions':[{'lesson':1,'when':'3 October 2026 at 18:00 WAT','url':'https://example.com/class'}]}
        self.assertEqual(self.request('/api/schedule',schedule,cookie=self.teacher_cookie)['notifications'],1)
        self.assertEqual(self.request('/api/schedule',schedule,cookie=self.teacher_cookie)['notifications'],0)
        schedule['sessions'][0]['when']='4 October 2026 at 18:00 WAT'
        self.assertEqual(self.request('/api/schedule',schedule,cookie=self.teacher_cookie)['notifications'],1)
        self.assertEqual(self.request('/api/schedule',{'sessions':[]},cookie=self.teacher_cookie)['notifications'],1)
        with self.server.app.db() as db:
            rows=db.execute("SELECT recipient,body,html_body FROM mail WHERE subject LIKE 'Academy class %'").fetchall()
            self.assertEqual(len(rows),3)
            self.assertTrue(all(r['recipient']=='student@example.com' for r in rows))
            self.assertIn('Read and annotate a chart',rows[0]['body'])
            self.assertIn('18:00 WAT',rows[0]['body'])
            self.assertIn('Join class →',rows[0]['html_body'])
            self.assertIn('https://example.com/class',rows[0]['html_body'])
            self.assertIn('Your class has an update.',rows[1]['html_body'])
            self.assertNotIn('https://example.com/class',rows[2]['html_body'])
            self.assertNotIn('Join class →',rows[2]['html_body'])

    def test_schedule_requires_link_and_teacher_without_partial_saves(self):
        self.teacher();self.student()
        valid={'sessions':[{'lesson':0,'when':'3 October 2026 at 18:00 WAT','url':'https://example.com/join'}]}
        self.request('/api/schedule',valid,403)
        invalid={'sessions':[valid['sessions'][0],{'lesson':1,'when':'4 October 2026 at 18:00 WAT','url':''}]}
        self.request('/api/schedule',invalid,400,cookie=self.teacher_cookie)
        with self.server.app.db() as db:
            self.assertIsNone(db.execute("SELECT value FROM settings WHERE key='schedule'").fetchone())
            self.assertEqual(db.execute("SELECT count(*) FROM mail WHERE subject LIKE 'Academy class %'").fetchone()[0],0)


    def test_many_students_can_be_accepted_without_manual_verification(self):
        self.teacher()
        with self.server.app.db() as db:
            ids=[db.execute("INSERT INTO users(email,name,password,role,status,verified,created) VALUES(?,?,?,'student','pending',0,?)",(f'learner{i}@example.com','Learner','unused',time.time())).lastrowid for i in range(25)]
        for uid in ids:
            self.request('/api/admission',{'student':uid,'status':'accepted'},cookie=self.teacher_cookie)
        with self.server.app.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users WHERE role='student' AND status='accepted'").fetchone()[0],25)
            self.assertEqual(db.execute("SELECT count(*) FROM users WHERE role='student' AND verified=1").fetchone()[0],0)

    def test_application_availability_matches_server_gate(self):
        self.assertFalse(self.request('/api/session')['enrollmentOpen'])
        self.teacher()
        self.assertTrue(self.request('/api/session')['enrollmentOpen'])
        self.server.app.enrollment_open=False
        self.assertFalse(self.request('/api/session')['enrollmentOpen'])
        self.request('/api/register',{'name':'Sample Learner','email':'closed@example.com','password':self.password,'experience':'Beginner','difficulty':'Reading charts','goal':'Learn to explain a fictional ticket.','consent':True,'terms':True,'adult':True,'policyVersion':self.server.app.policy['version']},403)
        with self.server.app.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users WHERE role='student'").fetchone()[0],0)
    def test_application_requires_current_terms_and_adult_confirmation(self):
        self.teacher()
        application={'name':'Sample Learner','email':'adult@example.com','password':self.password,'experience':'Beginner','difficulty':'Reading charts','goal':'Learn to explain a fictional ticket.','consent':True,'terms':True,'adult':True,'policyVersion':self.server.app.policy['version']}
        for field in ['consent','terms','adult']:
            self.request('/api/register',{**application,field:False},400)
        self.request('/api/register',{**application,'policyVersion':'old-version'},409)
        with self.server.app.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users WHERE role='student'").fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM agreements').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM mail').fetchone()[0],0)
        self.request('/api/register',application,201)
        uid=self.request('/api/session')['user']['id']
        with self.server.app.db() as db:
            agreement=db.execute('SELECT * FROM agreements WHERE user_id=?',(uid,)).fetchone()
            self.assertEqual(agreement['version'],self.server.app.policy['version'])
            self.assertEqual(agreement['adult'],1)
            self.assertLess(abs(agreement['accepted']-time.time()),10)
    def test_incomplete_policy_cannot_open_applications(self):
        self.teacher()
        for field,missing in [('published',False),('operatorAddress',''),('retentionApproved',False)]:
            original=self.server.app.policy[field]
            self.server.app.policy[field]=missing
            self.assertFalse(self.request('/api/session')['enrollmentOpen'])
            self.request('/api/register',{},403)
            self.server.app.policy[field]=original
        self.assertTrue(self.request('/api/session')['enrollmentOpen'])
    def test_student_workflow_queues_notifications_to_the_right_recipient(self):
        self.teacher();uid=self.student();self.approve(uid)
        self.request('/api/questions',{'lesson':2,'body':'Why did the example loss change with size?'},201)
        question=self.request('/api/questions')[0]
        self.request('/api/reply',{'question':question['id'],'body':'Each additional unit has the same price difference.'},cookie=self.teacher_cookie)
        self.request('/api/reset-request',{'email':'student@example.com'})
        app=self.server.app
        with app.db() as db:
            rows=db.execute('SELECT recipient,subject,body,html_body FROM mail ORDER BY id').fetchall()
        self.assertEqual([(r['recipient'],r['subject']) for r in rows],[
            ('teacher@example.com','New academy application'),
            ('student@example.com',WELCOME_SUBJECT),
            ('teacher@example.com','New academy question'),
            ('student@example.com','Your instructor replied'),
            ('student@example.com','Reset your academy password'),
        ])
        self.assertNotIn('Learn to explain a fictional ticket.',rows[0]['body'])
        self.assertIn('Hello Sample Learner,',rows[1]['body'])
        self.assertIn('Welcome to the class.',rows[1]['body'])
        self.assertIn(self.origin+'/#classroom',rows[1]['body'])
        self.assertIn('https://app.example.com',rows[1]['html_body'])
        self.assertIn('A note from your instructor',rows[1]['html_body'])
        self.assertEqual(self.request('/api/account',{})['note'],'Welcome to the class.')
        self.assertNotIn('Why did the example loss change',rows[2]['body'])
        self.assertNotIn('Each additional unit',rows[3]['body'])
        self.assertIn(self.origin+'/#reset/',rows[4]['body'])
        app.smtp=MagicMock();app.mail_enabled=True
        app.process_mail()
        self.assertEqual(app.smtp.send.call_count,5)
        with app.db() as db:
            self.assertEqual([tuple(r) for r in db.execute('SELECT status,body,html_body FROM mail')],[('sent','','')]*5)
    def test_public_captions_do_not_expand_private_asset_access(self):
        for i in range(7):
            self.assertTrue(self.request(f'/captions/tutorial-{i}.vtt').startswith('WEBVTT\n'))
        self.assertTrue(self.request('/captions/intro.vtt').startswith('WEBVTT\n'))
        self.assertIn('introVideo', self.request('/intro-video.js'))
        self.assertIn('createVideoPlayer',self.request('/video-player.js'))
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        conn.request('GET','/posters/tutorial-6.jpg')
        poster=conn.getresponse()
        self.assertEqual(poster.status,200)
        self.assertTrue(poster.getheader('Content-Type').startswith('image/jpeg'))
        self.assertTrue(poster.read().startswith(b'\xff\xd8'))
        conn.close()
        for name in ['intro-landscape.jpg', 'intro-portrait.jpg']:
            conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
            conn.request('GET','/posters/'+name)
            response=conn.getresponse()
            self.assertEqual(response.status,200)
            self.assertTrue(response.getheader('Content-Type').startswith('image/jpeg'))
            self.assertTrue(response.read().startswith(b'\xff\xd8'))
            conn.close()
        for path in ['/captions/tutorial-7.vtt','/captions/../practice.js',
                     '/captions/%2e%2e/academy.sqlite3','/captions/production-review.zip',
                     '/posters/tutorial-7.jpg','/posters/../academy.sqlite3',
                     '/intro/voice-jobs.json','/posters/intro-source.zip']:
            self.request(path,expected=404)
        self.request('/api/materials.js',expected=401)

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
        self.request('/api/admission',{'student':uid,'status':'accepted'},cookie=self.teacher_cookie)
        self.request('/api/classroom',expected=403)
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
