"""Disposable browser QA only; never shares production data or sends email."""
import os,tempfile,time
from server import make_server
os.environ['ACADEMY_MAIL_ENABLED']='false'
os.environ['ACADEMY_NOTIFICATION_RECIPIENT']='teacher@example.com'
os.environ['ACADEMY_ENROLLMENT_OPEN']='true'
server=make_server(tempfile.mkdtemp(prefix='academy-qa-'),8744)
app=server.app
app.policy.update(published=True,operatorAddress="Sample address for local testing only")
with app.db() as db:
    for email,name,role,status,verified in [('teacher@example.com','Sample Instructor','teacher','accepted',1),('learner@example.com','Sample Learner','student','accepted',1),('pending@example.com','New Applicant','student','pending',0)]:
        db.execute('INSERT INTO users(email,name,password,role,status,verified,experience,difficulty,goal,created) VALUES(?,?,?,?,?,?,?,?,?,?)',(email,name,app.password('Local-QA-only-passphrase!'),role,status,verified,'Beginner','Chart reading','Understand a paper trade ticket.',time.time()))
app.mail_enabled=False
print('Disposable QA server ready; no emails will be sent.',flush=True)
server.serve_forever()
