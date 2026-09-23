import unittest
import test_server

class TeacherTests(unittest.TestCase):
    setUp=test_server.AcademyTests.setUp
    tearDown=test_server.AcademyTests.tearDown
    request=test_server.AcademyTests.request
    teacher=test_server.AcademyTests.teacher
    student=test_server.AcademyTests.student
    approve=test_server.AcademyTests.approve

    def draft(self,cid='test-class-1'):
        return {'id':cid,'title':'Market structure clinic','lesson':None,'local':'2031-10-03T18:00','timezone':'Africa/Lagos','url':'https://example.com/join'}

    def test_repeat_sessions_invitations_updates_and_cancellation(self):
        self.teacher();uid=self.student();self.approve(uid)
        v=self.draft()
        self.assertEqual(self.request('/api/class-save',v,cookie=self.teacher_cookie)['notifications'],1)
        self.assertEqual(self.request('/api/class-save',v,cookie=self.teacher_cookie)['notifications'],0)
        v2=self.draft('test-class-2');v2['local']='2031-10-04T18:00'
        self.request('/api/class-save',v2,cookie=self.teacher_cookie)
        classes=self.request('/api/teacher-overview',cookie=self.teacher_cookie)['classes']
        self.assertEqual(len(classes),2)
        self.assertEqual(classes[0]['startsAt'],'2031-10-03T17:00:00+00:00')
        v['version']=1;v['title']='Updated clinic'
        self.assertEqual(self.request('/api/class-save',v,cookie=self.teacher_cookie)['notifications'],1)
        self.request('/api/class-cancel',{'id':v['id'],'version':1},409,cookie=self.teacher_cookie)
        self.assertEqual(self.request('/api/class-cancel',{'id':v['id'],'version':2},cookie=self.teacher_cookie)['notifications'],1)
        self.assertEqual(self.request('/api/class-cancel',{'id':v['id'],'version':2},cookie=self.teacher_cookie)['notifications'],0)
        self.assertEqual(len(self.request('/api/classroom')['schedule']),1)
        with self.server.app.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM class_mail').fetchone()[0],4)
            self.assertEqual(db.execute("SELECT count(*) FROM mail WHERE subject LIKE 'Academy class %'").fetchone()[0],4)

    def test_authorization_and_invalid_inputs_leave_schedule_unchanged(self):
        self.teacher();self.student()
        self.request('/api/teacher-overview',expected=403)
        self.request('/api/class-save',self.draft(),403)
        for changes in [{'timezone':'Invalid/Zone'},{'local':'2031-02-30T18:00'},{'url':'javascript:alert(1)'},{'local':'2020-01-01T18:00'},{'lesson':99}]:
            v=self.draft();v.update(changes)
            self.request('/api/class-save',v,400,cookie=self.teacher_cookie)
        self.assertEqual(self.request('/api/teacher-overview',cookie=self.teacher_cookie)['classes'],[])

    def test_legacy_schedule_can_be_edited_without_losing_other_classes(self):
        self.teacher()
        self.request('/api/schedule',{'sessions':[{'lesson':1,'when':'3 October 2031, 18:00 WAT','url':'https://example.com/join'}]},cookie=self.teacher_cookie)
        result=self.request('/api/teacher-overview',cookie=self.teacher_cookie)
        self.assertEqual(result['classes'][0]['id'],'legacy-1')
        v=self.draft('legacy-1');v.update(version=0,lesson=1)
        self.request('/api/class-save',v,cookie=self.teacher_cookie)
        self.request('/api/schedule',{'sessions':[]},409,cookie=self.teacher_cookie)
        self.assertEqual(len(self.request('/api/teacher-overview',cookie=self.teacher_cookie)['classes']),1)

    def test_overview_reports_real_action_counts_and_progress(self):
        self.teacher();uid=self.student()
        with self.server.app.db() as db:
            db.execute('INSERT INTO progress VALUES(?,?,?,?)',(uid,0,1,'Private practice note'))
            db.execute('INSERT INTO questions(user_id,lesson,body,created) VALUES(?,?,?,?)',(uid,0,'Help with the first lesson',1))
            db.execute("INSERT INTO support_threads(user_id,status,created,updated) VALUES(?,'waiting',1,1)",(uid,))
            db.execute("INSERT INTO mail(recipient,subject,body,status,created) VALUES('sample@example.invalid','Test failure','Body','failed',1)")
        result=self.request('/api/teacher-overview',cookie=self.teacher_cookie)
        self.assertEqual(result['students'][0]['completed'],1)
        self.assertNotIn('password',result['students'][0])
        self.assertEqual(result['questionsWaiting'],1)
        self.assertEqual(result['supportWaiting'],1)
        self.assertEqual(result['failed'],1)

    def test_dst_ambiguous_or_nonexistent_time_is_rejected(self):
        self.teacher()
        for local in ['2031-03-09T02:30','2031-11-02T01:30']:
            v=self.draft();v.update(local=local,timezone='America/New_York')
            self.request('/api/class-save',v,400,cookie=self.teacher_cookie)
