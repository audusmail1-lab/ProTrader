"""Same-site support conversations. Guest capabilities are opaque HttpOnly cookies."""
import json
import secrets
import time
import re
import support_ai
from http.cookies import SimpleCookie


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS support_threads(id INTEGER PRIMARY KEY,user_id INTEGER,guest_hash TEXT,status TEXT NOT NULL DEFAULT 'waiting',created REAL NOT NULL,updated REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS support_messages(id INTEGER PRIMARY KEY,thread_id INTEGER NOT NULL,role TEXT NOT NULL,body TEXT NOT NULL,created REAL NOT NULL,client_id TEXT,UNIQUE(thread_id,client_id));
    CREATE INDEX IF NOT EXISTS support_owner ON support_threads(user_id,updated);
    CREATE INDEX IF NOT EXISTS support_guest ON support_threads(guest_hash);
    ''')
    db.execute("UPDATE support_threads SET status='waiting' WHERE status='assistant_pending'")


def route(h, path, data=None):
    APIError=h.api_error
    app=h.app
    def user_optional():
        try: return h.user()
        except APIError as exc:
            if exc.status!=401: raise
            return None
    user=user_optional()
    if path.startswith('/api/support-admin'):
        user=h.user(teacher=True)
        if data is None:
            with app.db() as db:
                rows=db.execute("SELECT t.id,t.status,t.created,t.updated,u.name FROM support_threads t LEFT JOIN users u ON u.id=t.user_id ORDER BY t.updated DESC LIMIT 100").fetchall()
            return h.output({'threads':[dict(r) for r in rows]})
        tid=data.get('thread')
        if type(tid)!=int: raise APIError(400,'Choose a conversation.')
        with app.db() as db:
            thread=db.execute('SELECT * FROM support_threads WHERE id=?',(tid,)).fetchone()
            if not thread: raise APIError(404,'Conversation not found.')
            if path=='/api/support-admin-thread':
                messages=db.execute('SELECT id,role,body,created FROM support_messages WHERE thread_id=? ORDER BY id',(tid,)).fetchall()
                return h.output({'thread':tid,'status':thread['status'],'messages':[dict(m) for m in messages]})
            if path=='/api/support-admin-reply':
                body=h.text(data,'body',1,3000);key=h.text(data,'clientId',10,100)
                db.execute('BEGIN IMMEDIATE')
                inserted=db.execute("INSERT OR IGNORE INTO support_messages(thread_id,role,body,created,client_id) VALUES(?,'human',?,?,?)",(tid,body,time.time(),key)).rowcount
                if inserted:
                    db.execute("UPDATE support_threads SET status='human',updated=? WHERE id=?",(time.time(),tid))
                    if thread['user_id']:
                        recipient=db.execute('SELECT email,verified FROM users WHERE id=?',(thread['user_id'],)).fetchone()
                        if recipient and recipient['verified']: app.enqueue(db,recipient['email'],'Your Academy support reply',f'A human support reply is ready. Open the support chat at {app.origin}/#account')
                return h.output({'ok':True})
            if path=='/api/support-admin-close':
                db.execute("UPDATE support_threads SET status='closed',updated=? WHERE id=?",(time.time(),tid))
                return h.output({'ok':True})
        raise APIError(404,'Not found.')
    if path not in ('/api/support','/api/support-message'): raise APIError(404,'Not found.')
    jar=SimpleCookie()
    try: jar.load(h.headers.get('Cookie',''))
    except Exception: pass
    raw=jar.get('academy_support');raw=raw.value if raw else ''
    guest_hash=app.digest(raw) if raw else ''
    ai_request=False;tid=None
    with app.db() as db:
        thread=db.execute('SELECT * FROM support_threads WHERE user_id=? ORDER BY updated DESC LIMIT 1',(user['id'],)).fetchone() if user else None
        if not thread and guest_hash:
            thread=db.execute('SELECT * FROM support_threads WHERE guest_hash=? AND user_id IS NULL AND updated>? ORDER BY updated DESC LIMIT 1',(guest_hash,time.time()-604800)).fetchone()
        cookie=None
        if data is not None:
            body=h.text(data,'body',1,3000);key=h.text(data,'clientId',10,100)
            if app.limited('support-ip:'+h.client_address[0],60,3600): raise APIError(429,'Please wait before sending more messages.')
            identity=str(user['id']) if user else guest_hash or h.client_address[0]
            if app.limited('support-user:'+identity,30,3600): raise APIError(429,'Please wait before sending more messages.')
            db.execute('BEGIN IMMEDIATE')
            if not thread:
                raw=secrets.token_urlsafe(32)
                tid=db.execute('INSERT INTO support_threads(user_id,guest_hash,created,updated) VALUES(?,?,?,?)',(user['id'] if user else None,app.digest(raw),time.time(),time.time())).lastrowid
                cookie=f'academy_support={raw}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800'+('; Secure' if app.secure else '')
            else:
                tid=thread['id']
                if user and not thread['user_id']: db.execute('UPDATE support_threads SET user_id=?,guest_hash=NULL WHERE id=?',(user['id'],tid))
            count=db.execute('SELECT count(*) FROM support_messages WHERE thread_id=?',(tid,)).fetchone()[0]
            if count>=500: raise APIError(400,'This conversation is full. Contact the Academy using the Contact page.')
            inserted=db.execute("INSERT OR IGNORE INTO support_messages(thread_id,role,body,created,client_id) VALUES(?,'visitor',?,?,?)",(tid,body,time.time(),key)).rowcount
            if inserted:
                wants_human=data.get('human') is True or bool(re.search(r'\b(human|person|agent|complaint|refund|hacked|cannot log|can.t log|locked out)\b',body,re.I))
                ai_request=(support_ai.available() and data.get('aiConsent') is True and not wants_human and (not thread or thread['status'] in ('ai','closed')))
                if ai_request and app.limited('support-ai-global',300,86400): ai_request=False
                mode='assistant_pending' if ai_request else 'waiting'
                if not ai_request and (not thread or thread['status'] not in ('waiting','human')):
                    db.execute("INSERT INTO support_messages(thread_id,role,body,created) VALUES(?,'system',?,?)",(tid,'Your message is saved for a human support agent. Replies appear here; an agent may not be online now. Signed-in users with verified email also receive reply notifications.',time.time()))
                    app.enqueue(db,app.recipient,'New Academy support conversation',f'A support conversation needs a human reply. Open {app.origin}/#support-inbox')
                if not ai_request and thread and thread['status']=='human': app.enqueue(db,app.recipient,'Academy support follow-up',f'A conversation has a new message: {app.origin}/#support-inbox')
                db.execute('UPDATE support_threads SET status=?,updated=? WHERE id=?',(mode,time.time(),tid))
            thread=db.execute('SELECT * FROM support_threads WHERE id=?',(tid,)).fetchone()
        messages=db.execute('SELECT id,role,body,created FROM support_messages WHERE thread_id=? ORDER BY id',(thread['id'],)).fetchall() if thread else []
    if ai_request:
        try: answer,escalate=support_ai.answer([dict(m) for m in messages],app.applications_open())
        except Exception:
            answer='The AI assistant is unavailable right now. Your message has been saved for a human to reply here.';escalate=True
        with app.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT * FROM support_threads WHERE id=?',(tid,)).fetchone()
            if current['status']=='assistant_pending':
                db.execute("INSERT INTO support_messages(thread_id,role,body,created) VALUES(?,'assistant',?,?)",(tid,answer,time.time()))
                db.execute('UPDATE support_threads SET status=?,updated=? WHERE id=?',('waiting' if escalate else 'ai',time.time(),tid))
                if escalate: app.enqueue(db,app.recipient,'Academy support needs a human',f'An AI conversation needs your reply: {app.origin}/#support-inbox')
            thread=db.execute('SELECT * FROM support_threads WHERE id=?',(tid,)).fetchone()
            messages=db.execute('SELECT id,role,body,created FROM support_messages WHERE thread_id=? ORDER BY id',(tid,)).fetchall()
    return h.output({'aiAvailable':support_ai.available(),'thread':thread['id'] if thread else None,'status':thread['status'] if thread else 'new','messages':[dict(m) for m in messages]},cookie=cookie)
