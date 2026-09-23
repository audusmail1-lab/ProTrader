"""Teacher overview and individually versioned class scheduling."""
import json
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import urlsplit
from invitations import class_message


def schedule(db):
    row=db.execute("SELECT value FROM settings WHERE key='schedule'").fetchone()
    return [dict(s, id=s.get('id',f"legacy-{s['lesson']}"),version=s.get('version',0)) for s in json.loads(row[0] if row else '[]')]


def route(h,path,data=None):
    user=h.user(teacher=True);app=h.app;Error=h.api_error
    with app.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS class_mail(mail_id INTEGER PRIMARY KEY,class_id TEXT NOT NULL)')
        if path=='/api/teacher-overview' and data is None:
            students=[dict(r) for r in db.execute("SELECT id,name,email,status,verified,experience,difficulty,goal,created FROM users WHERE role='student' ORDER BY created DESC")]
            for s in students:
                s['completed']=db.execute('SELECT count(*) FROM progress WHERE user_id=? AND complete=1',(s['id'],)).fetchone()[0]
                note=db.execute('SELECT value FROM settings WHERE key=?',('application_note:'+str(s['id']),)).fetchone()
                s['note']=json.loads(note[0]) if note else ''
            questions=db.execute('SELECT count(*) FROM questions q WHERE NOT EXISTS(SELECT 1 FROM replies r WHERE r.question_id=q.id)').fetchone()[0]
            support=db.execute("SELECT count(*) FROM support_threads WHERE status='waiting'").fetchone()[0]
            mail=[dict(r) for r in db.execute('SELECT m.id,m.recipient,m.subject,m.status,m.error,m.created,c.class_id FROM mail m LEFT JOIN class_mail c ON c.mail_id=m.id ORDER BY m.id DESC LIMIT 200')]
            failed=db.execute("SELECT count(*) FROM mail WHERE status='failed'").fetchone()[0]
            return h.output({'students':students,'classes':schedule(db),'questionsWaiting':questions,'supportWaiting':support,'failed':failed,'mail':mail,'mailEnabled':app.mail_enabled})
        if path not in ('/api/class-save','/api/class-cancel') or data is None: raise Error(404,'Not found.')
        cid=h.text(data,'id',1,80)
        if not re.fullmatch(r'[A-Za-z0-9-]+',cid): raise Error(400,'Invalid class identifier.')
        db.execute('BEGIN IMMEDIATE')
        sessions=schedule(db);old=next((s for s in sessions if s['id']==cid),None)
        if path=='/api/class-cancel':
            if not old: raise Error(404,'Class not found.')
            if old.get('status')=='cancelled': return h.output({'ok':True,'notifications':0})
            candidate=dict(old,status='cancelled')
        else:
            title=h.text(data,'title',2,120);local=h.text(data,'local',16,16);zone=h.text(data,'timezone',1,80);url=h.text(data,'url',1,1000)
            parsed=urlsplit(url)
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or any(c.isspace() for c in url): raise Error(400,'Paste a valid HTTPS meeting link.')
            lesson=data.get('lesson')
            if lesson is not None and (type(lesson)!=int or not 0<=lesson<7): raise Error(400,'Choose a valid lesson or custom topic.')
            try:
                naive=datetime.strptime(local,'%Y-%m-%dT%H:%M');tz=ZoneInfo(zone);date=naive.replace(tzinfo=tz)
                if date.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)!=naive: raise ValueError()
                if date.utcoffset()!=naive.replace(tzinfo=tz,fold=1).utcoffset(): raise ValueError()
            except (ValueError,ZoneInfoNotFoundError): raise Error(400,'Choose a valid date, time and time zone. Avoid an ambiguous daylight-saving hour.')
            candidate={'id':cid,'title':title,'lesson':lesson,'local':local,'timezone':zone,'startsAt':date.astimezone(timezone.utc).isoformat(),'when':date.strftime('%d %B %Y, %H:%M')+' · '+zone+' (UTC'+date.strftime('%z')+')','url':url,'status':'scheduled'}
            if old and all(old.get(k)==v for k,v in candidate.items()): return h.output({'ok':True,'notifications':0})
            if not old and date.timestamp()<=time.time(): raise Error(400,'Choose a future date for a new class.')
            if old and old.get('status')=='cancelled': raise Error(409,'Create a new class instead of editing a cancelled session.')
        if old and data.get('version')!=old['version']: raise Error(409,'This class changed since you opened it. Refresh Classes before editing again.')
        candidate['version']=(old['version'] if old else 0)+1
        if old: sessions=[candidate if x['id']==cid else x for x in sessions]
        else: sessions.append(candidate)
        db.execute("INSERT INTO settings VALUES('schedule',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(sessions),))
        kind='cancelled' if path=='/api/class-cancel' else 'updated' if old else 'scheduled'
        title=candidate.get('title') or h.lesson_titles[candidate['lesson']]
        students=db.execute("SELECT name,email FROM users WHERE role='student' AND status='accepted' AND verified=1").fetchall()
        for student in students:
            subject,body,html=class_message(student['name'],title,candidate['when'],candidate['url'],app.origin,kind)
            app.enqueue(db,student['email'],subject,body,html)
            db.execute('INSERT INTO class_mail VALUES(last_insert_rowid(),?)',(cid,))
        db.execute('INSERT INTO audit(actor,action,target,created) VALUES(?,?,?,?)',(user['id'],'class:'+kind,cid,time.time()))
    return h.output({'ok':True,'notifications':len(students)})
