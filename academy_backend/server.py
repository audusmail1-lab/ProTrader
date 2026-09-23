"""Local-first academy server. Run: python3 academy_backend/server.py.

Only explicitly allowed public assets are served. Database, credentials and full
lesson material stay outside that surface. Production requires HTTPS/reverse proxy.
"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import argparse, hashlib, hmac, json, os, re, secrets, sqlite3, threading, time
from mailer import SMTPConfig, safe_error
from welcome import acceptance_message
from invitations import class_message
import support
import teacher as teacher_dashboard
from telegram_bot import public_links
from contextlib import contextmanager
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
LESSONS = json.loads((ROOT / 'academy_backend/lessons.json').read_text())
PUBLIC = {'journey-videos.js','landing-assets/protrader-workspace.webp','posters/guide-0.jpg','posters/guide-1.jpg','captions/guide-0.vtt','captions/guide-1.vtt','teacher.js','teacher.css','support-chat.js','support-chat.css','homepage.js','homepage.css','landing-assets/barlow-400.woff2','landing-assets/barlow-500.woff2','landing-assets/barlow-700.woff2','landing-assets/barlow-condensed-600.woff2','landing-assets/landing-terminal-800.webp','landing-assets/landing-terminal.webp','styles.css','favicon.svg','live.js','live.css','public-content.js','public-intro.js','public-pages.js','video-player.js','video-library.js','intro-video.js','captions/intro.vtt','posters/intro-landscape.jpg','posters/intro-portrait.jpg'} | {f'captions/tutorial-{i}.vtt' for i in range(7)} | {f'posters/tutorial-{i}.jpg' for i in range(7)}
POLICY = json.loads((ROOT / 'academy_backend/public_policy.json').read_text())
EMAIL = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

class Academy:
    def __init__(self, directory, origin):
        self.directory = Path(directory); self.directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        self.dbfile = self.directory / 'academy.sqlite3'
        self.origin = origin.rstrip('/'); self.secure = self.origin.startswith('https://')
        self.lock = threading.Lock(); self.attempts = {}
        self.stop = threading.Event()
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,name TEXT NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'student',status TEXT NOT NULL DEFAULT 'pending',verified INTEGER NOT NULL DEFAULT 0,experience TEXT,difficulty TEXT,goal TEXT,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS progress(user_id INTEGER,lesson INTEGER,complete INTEGER DEFAULT 0,notes TEXT DEFAULT '',PRIMARY KEY(user_id,lesson));
            CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,lesson INTEGER NOT NULL,body TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS replies(id INTEGER PRIMARY KEY,question_id INTEGER NOT NULL,user_id INTEGER NOT NULL,body TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS mail(id INTEGER PRIMARY KEY,recipient TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,status TEXT DEFAULT 'queued',error TEXT DEFAULT '',created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL,kind TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor INTEGER,action TEXT,target INTEGER,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS agreements(user_id INTEGER PRIMARY KEY,version TEXT NOT NULL,adult INTEGER NOT NULL,accepted REAL NOT NULL);
            ''')
            support.initialize(db)
            columns = {r[1] for r in db.execute('PRAGMA table_info(mail)')}
            if 'delivery_key' not in columns:
                db.execute('ALTER TABLE mail ADD COLUMN delivery_key TEXT')
            if 'html_body' not in columns:
                db.execute("ALTER TABLE mail ADD COLUMN html_body TEXT NOT NULL DEFAULT ''")
            for row in db.execute('SELECT id FROM mail WHERE delivery_key IS NULL').fetchall():
                db.execute('UPDATE mail SET delivery_key=? WHERE id=?', (secrets.token_hex(20), row[0]))
            db.execute("UPDATE mail SET status='failed',error='Delivery interrupted. Check provider logs before retrying.' WHERE status='sending'")
        os.chmod(self.dbfile, 0o600)
        cfg = ROOT / 'academy.config.local.json'
        self.recipient = os.environ.get('ACADEMY_NOTIFICATION_RECIPIENT') or (json.loads(cfg.read_text()).get('notificationRecipient','') if cfg.exists() else '')
        self.mail_enabled = os.environ.get('ACADEMY_MAIL_ENABLED') == 'true'
        self.smtp = SMTPConfig.from_environment() if self.mail_enabled else None
        if self.mail_enabled and (not EMAIL.fullmatch(self.recipient) or not self.secure):
            raise ValueError('Email delivery requires a valid notification recipient and an HTTPS academy origin.')
        self.app_url = (os.environ.get('ACADEMY_APP_URL') or (json.loads(cfg.read_text()).get('appUrl','') if cfg.exists() else '')).strip()
        if self.app_url:
            target = urlsplit(self.app_url)
            if target.scheme != 'https' or not target.hostname or target.username or any(c in self.app_url for c in '\r\n'):
                raise ValueError('ACADEMY_APP_URL must be the verified HTTPS Pro Trader app URL.')
        self.policy = dict(POLICY)
        self.enrollment_open = os.environ.get('ACADEMY_ENROLLMENT_OPEN', 'true') == 'true'
        self.setup_file = self.directory / 'setup-token'
        if not self.has_admin() and not self.setup_file.exists():
            self.setup_file.write_text(secrets.token_urlsafe(32)); os.chmod(self.setup_file,0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.dbfile, timeout=20); db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()

    def has_admin(self):
        with self.db() as db: return bool(db.execute("SELECT 1 FROM users WHERE role='teacher'").fetchone())

    def applications_open(self):
        policy_ready = self.policy.get('published') is True and all(self.policy.get(k) for k in ('operatorName','operatorAddress','contactEmail','retentionApproved')) and self.policy.get('adultOnly') is True
        return bool(self.enrollment_open and policy_ready and self.has_admin())

    def limited(self, key, maximum=12, interval=900):
        with self.lock:
            now=time.time(); self.attempts={k:[t for t in v if now-t<interval] for k,v in self.attempts.items() if any(now-t<interval for t in v)}
            stamps=self.attempts.setdefault(key,[])
            if len(stamps)>=maximum: return True
            stamps.append(now); return False

    @staticmethod
    def digest(token): return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def password(value, stored=None):
        salt=bytes.fromhex(stored.split(':')[0]) if stored else secrets.token_bytes(16)
        result=salt.hex()+':'+hashlib.scrypt(value.encode(),salt=salt,n=16384,r=8,p=1).hex()
        return hmac.compare_digest(result,stored) if stored else result

    def enqueue(self,db,to,subject,body,html_body=''):
        if to: db.execute('INSERT INTO mail(recipient,subject,body,html_body,created,delivery_key) VALUES(?,?,?,?,?,?)',(to,subject,body,html_body,time.time(),secrets.token_hex(20)))

    def process_mail(self):
        if not self.mail_enabled: return
        with self.db() as db:
            rows=db.execute("SELECT * FROM mail WHERE status='queued' ORDER BY id LIMIT 10").fetchall()
        for row in rows:
            with self.db() as db:
                claimed=db.execute("UPDATE mail SET status='sending' WHERE id=? AND status='queued'",(row['id'],)).rowcount
            if not claimed: continue
            if row['subject']=='Reset your academy password' and time.time()-row['created']>1800:
                with self.db() as db: db.execute("UPDATE mail SET status='expired',body='',html_body='',error='Reset link expired. Request a new one.' WHERE id=?",(row['id'],))
                continue
            try:
                self.smtp.send(row)
                status,error='sent',''
            except Exception as exc:
                status,error='failed',safe_error(exc)
            with self.db() as db:
                db.execute("UPDATE mail SET status=?,error=?,body=CASE WHEN ?='sent' THEN '' ELSE body END,html_body=CASE WHEN ?='sent' THEN '' ELSE html_body END WHERE id=?",(status,error,status,status,row['id']))

    def send_loop(self):
        while not self.stop.wait(10):
            self.process_mail()

class APIError(Exception):
    def __init__(self,status,message): self.status=status; self.message=message

class Handler(BaseHTTPRequestHandler):
    api_error=APIError
    lesson_titles=[x['title'] for x in LESSONS]
    server_version='Academy'
    def log_message(self,*args): pass # Avoid recording personal data and reset links.
    @property
    def app(self): return self.server.app

    def output(self,data,status=200,content_type='application/json; charset=utf-8',cookie=None):
        payload=json.dumps(data).encode() if content_type.startswith('application/json') else data.encode() if isinstance(data,str) else data
        self.send_response(status); self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(payload))); self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; media-src 'self' https://d2ol7oe51mr4n9.cloudfront.net; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if cookie: self.send_header('Set-Cookie',cookie)
        self.end_headers(); self.wfile.write(payload)

    def read_json(self):
        if self.headers.get('Origin') != self.app.origin: raise APIError(403,'This request must come from the academy site.')
        if self.headers.get_content_type()!='application/json': raise APIError(415,'Use a JSON request.')
        try: size=int(self.headers.get('Content-Length','0'))
        except ValueError: raise APIError(400,'Invalid request size.')
        if size<1 or size>20000: raise APIError(413,'The request is too large or empty.')
        try: data=json.loads(self.rfile.read(size))
        except (ValueError,UnicodeDecodeError): raise APIError(400,'Invalid request.')
        if not isinstance(data,dict): raise APIError(400,'Invalid request.')
        return data

    def text(self,data,key,minimum=1,maximum=1000):
        value=data.get(key,'')
        if isinstance(value,str) and key!='password': value=value.strip()
        if not isinstance(value,str) or not minimum<=len(value)<=maximum: raise APIError(400,f'Please check {key.replace("_"," ")} ({minimum}–{maximum} characters).')
        return value

    def email(self,data):
        value=self.text(data,'email',3,254).lower()
        if not EMAIL.fullmatch(value): raise APIError(400,'Enter a valid email address.')
        return value

    def user(self,teacher=False,accepted=False):
        cookie=SimpleCookie()
        try: cookie.load(self.headers.get('Cookie','')); token=cookie.get('academy_session'); token=token.value if token else ''
        except Exception: token=''
        with self.app.db() as db: row=db.execute('SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>?',(self.app.digest(token),time.time())).fetchone()
        if not row: raise APIError(401,'Sign in to continue.')
        if teacher and row['role']!='teacher': raise APIError(403,'Instructor access is required.')
        if accepted and row['role']!='teacher' and (row['status']!='accepted' or not row['verified']): raise APIError(403,'Your instructor must approve and verify your application before classroom access.')
        return dict(row)

    def session(self,db,uid):
        raw=secrets.token_urlsafe(32); db.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
        db.execute('INSERT INTO sessions VALUES(?,?,?)',(self.app.digest(raw),uid,time.time()+86400))
        return f'academy_session={raw}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400'+('; Secure' if self.app.secure else '')

    @staticmethod
    def safe_user(user): return {key:user[key] for key in ('id','name','email','role','status','verified')}

    def do_GET(self):
        try:
            path=urlsplit(self.path).path
            if path=='/api/teacher-overview': return teacher_dashboard.route(self,path)
            if path in ('/api/support','/api/support-admin'): return support.route(self,path)
            if path=='/healthz':
                with self.app.db() as db: db.execute('SELECT 1').fetchone()
                return self.output({'ok':True})
            if path=='/api/session':
                try: user=self.safe_user(self.user())
                except APIError: user=None
                return self.output({'user':user,'setupRequired':not self.app.has_admin(),'appUrl':self.app.app_url,'enrollmentOpen':self.app.applications_open(),'policy':self.app.policy,'telegram':public_links()})
            if path=='/api/lessons': self.user(accepted=True); return self.output(LESSONS)
            if path=='/api/materials.js':
                self.user(accepted=True); return self.output((ROOT/'academy/practice.js').read_text(),content_type='text/javascript; charset=utf-8')
            if path=='/api/classroom':
                user=self.user(accepted=True)
                with self.app.db() as db:
                    progress=[dict(r) for r in db.execute('SELECT lesson,complete,notes FROM progress WHERE user_id=?',(user['id'],))]
                    schedule=json.loads((db.execute("SELECT value FROM settings WHERE key='schedule'").fetchone() or ['[]'])[0])
                return self.output({'progress':progress,'schedule':[s for s in schedule if s.get('status')!='cancelled']})
            if path=='/api/questions':
                user=self.user(accepted=True)
                with self.app.db() as db:
                    sql='SELECT q.*,u.name FROM questions q JOIN users u ON u.id=q.user_id'
                    rows=db.execute(sql+('' if user['role']=='teacher' else ' WHERE q.user_id=?')+' ORDER BY q.created DESC',() if user['role']=='teacher' else (user['id'],)).fetchall()
                    questions=[]
                    for row in rows:
                        q=dict(row);q['replies']=[dict(r) for r in db.execute('SELECT r.body,r.created,u.name FROM replies r JOIN users u ON u.id=r.user_id WHERE question_id=? ORDER BY r.created',(row['id'],))];questions.append(q)
                return self.output(questions)
            if path=='/api/admin':
                self.user(teacher=True)
                with self.app.db() as db:
                    students=[dict(r) for r in db.execute("SELECT u.id,u.name,u.email,u.status,u.verified,u.experience,u.difficulty,u.goal,u.created,a.version AS terms_version,a.adult AS adult_confirmed,a.accepted AS acknowledged_at FROM users u LEFT JOIN agreements a ON a.user_id=u.id WHERE u.role='student' ORDER BY u.created DESC")]
                    mail=[dict(r) for r in db.execute('SELECT id,recipient,subject,status,error,created FROM mail ORDER BY id DESC LIMIT 100')]
                return self.output({'students':students,'mail':mail,'mailEnabled':self.app.mail_enabled,'recipient':self.app.recipient})
            if path=='/':
                html=(ROOT/'academy/live.html').read_text()
                return self.output(html,content_type='text/html; charset=utf-8')
            name=path.removeprefix('/')
            if name in PUBLIC:
                mime='font/woff2' if name.endswith('.woff2') else 'image/webp' if name.endswith('.webp') else 'image/jpeg' if name.endswith('.jpg') else 'text/vtt' if name.endswith('.vtt') else 'text/javascript' if name.endswith('.js') else 'text/css' if name.endswith('.css') else 'image/svg+xml'
                return self.output((ROOT/'academy'/name).read_bytes(),content_type=mime if name.endswith(('.webp','.woff2')) else mime+'; charset=utf-8')
            raise APIError(404,'Not found.')
        except APIError as e: self.output({'error':e.message},e.status)
        except (BrokenPipeError,ConnectionResetError): pass
        except Exception: self.output({'error':'The server could not complete this request.'},500)

    def do_POST(self):
        try:
            data=self.read_json(); path=urlsplit(self.path).path; app=self.app
            if path in ('/api/class-save','/api/class-cancel'): return teacher_dashboard.route(self,path,data)
            if path.startswith('/api/support'): return support.route(self,path,data)
            if path in ('/api/setup','/api/register','/api/login','/api/reset-request','/api/reset'):
                identity = str(data.get('email','')).strip().lower()
                ip_limited = app.limited(self.client_address[0]+path, maximum=200)
                account_limited = app.limited(path+app.digest(identity), maximum=12)
                if ip_limited or account_limited: raise APIError(429,'Too many attempts. Please try again in 15 minutes.')
            if path in ('/api/setup','/api/register'):
                if path=='/api/register' and not app.applications_open(): raise APIError(403,'Applications are not open yet. You can explore the public introduction and videos.')
                email=self.email(data);name=self.text(data,'name',2,80);password=self.text(data,'password',12,128)
                teacher=path=='/api/setup'
                with app.lock:
                    if teacher:
                        if app.has_admin(): raise APIError(409,'An instructor account already exists.')
                        if not app.setup_file.exists() or not hmac.compare_digest(str(data.get('setup_token','')),app.setup_file.read_text()): raise APIError(403,'The instructor setup key is invalid.')
                    elif not app.has_admin(): raise APIError(409,'The instructor must finish setup before applications open.')
                    experience='' if teacher else self.text(data,'experience',2,80)
                    difficulty='' if teacher else self.text(data,'difficulty',2,500)
                    goal='' if teacher else self.text(data,'goal',10,1000)
                    if not teacher:
                        if data.get('adult') is not True: raise APIError(400,'You must confirm that you are at least 18 to apply.')
                        if data.get('consent') is not True or data.get('terms') is not True: raise APIError(400,'Read the Privacy Policy and agree to the Terms of Use before applying.')
                        if data.get('policyVersion') != app.policy['version']: raise APIError(409,'The academy terms have changed. Refresh this page and review the current terms before applying.')
                    try:
                        with app.db() as db:
                            uid=db.execute('INSERT INTO users(email,name,password,role,status,verified,experience,difficulty,goal,created) VALUES(?,?,?,?,?,?,?,?,?,?)',(email,name,app.password(password),'teacher' if teacher else 'student','accepted' if teacher else 'pending',1 if teacher else 0,experience,difficulty,goal,time.time())).lastrowid
                            cookie=self.session(db,uid)
                            if not teacher: db.execute('INSERT INTO agreements VALUES(?,?,?,?)',(uid,app.policy['version'],1,time.time()))
                            if not teacher: app.enqueue(db,app.recipient,'New academy application',f'A new application is ready for review. Sign in at {app.origin}/#teaching. Personal application details stay in your dashboard.')
                    except sqlite3.IntegrityError: raise APIError(409,'An account already uses that email. Sign in or request a password reset.')
                    if teacher: app.setup_file.unlink(missing_ok=True)
                return self.output({'ok':True,'message':'Instructor account created.' if teacher else 'Application saved. Your instructor will review and verify it.'},201,cookie=cookie)
            if path=='/api/login':
                email=self.email(data);password=self.text(data,'password',1,128)
                with app.db() as db:
                    user=db.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
                    valid=app.password(password,user['password']) if user else app.password(password,'00'*16+':'+'00'*64)
                    if not user or not valid: raise APIError(401,'Email or password is incorrect.')
                    cookie=self.session(db,user['id'])
                return self.output({'ok':True},cookie=cookie)
            if path=='/api/logout':
                cookie=SimpleCookie(self.headers.get('Cookie',''));raw=cookie.get('academy_session')
                if raw:
                    with app.db() as db: db.execute('DELETE FROM sessions WHERE token=?',(app.digest(raw.value),))
                return self.output({'ok':True},cookie='academy_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            if path=='/api/progress':
                user=self.user(accepted=True); lesson=data.get('lesson')
                if type(lesson)!=int or not 0<=lesson<7: raise APIError(400,'Choose a valid lesson.')
                notes=self.text(data,'notes',0,10000); complete=data.get('complete')
                if type(complete)!=bool: raise APIError(400,'Invalid progress value.')
                with app.db() as db: db.execute('INSERT INTO progress(user_id,lesson,complete,notes) VALUES(?,?,?,?) ON CONFLICT(user_id,lesson) DO UPDATE SET complete=excluded.complete,notes=excluded.notes',(user['id'],lesson,int(complete),notes))
                return self.output({'ok':True})
            if path=='/api/questions':
                user=self.user(accepted=True);body=self.text(data,'body',10,3000);lesson=data.get('lesson')
                if type(lesson)!=int or not 0<=lesson<7: raise APIError(400,'Choose a valid lesson.')
                if app.limited('question:'+str(user['id']),20,3600): raise APIError(429,'Please wait before adding more questions.')
                with app.db() as db:
                    db.execute('INSERT INTO questions(user_id,lesson,body,created) VALUES(?,?,?,?)',(user['id'],lesson,body,time.time()))
                    app.enqueue(db,app.recipient,'New academy question',f'A student question is ready in your private dashboard: {app.origin}/#questions')
                return self.output({'ok':True},201)
            if path=='/api/reply':
                user=self.user(teacher=True);body=self.text(data,'body',1,5000)
                with app.db() as db:
                    q=db.execute('SELECT q.id,u.email FROM questions q JOIN users u ON u.id=q.user_id WHERE q.id=?',(data.get('question'),)).fetchone()
                    if not q: raise APIError(404,'Question not found.')
                    db.execute('INSERT INTO replies(question_id,user_id,body,created) VALUES(?,?,?,?)',(q['id'],user['id'],body,time.time()))
                    app.enqueue(db,q['email'],'Your instructor replied',f'Your academy question has a new reply. Read it securely at {app.origin}/#questions')
                return self.output({'ok':True})
            if path=='/api/admission':
                user=self.user(teacher=True);status=data.get('status')
                if status not in ('pending','accepted','needs_information','declined'): raise APIError(400,'Choose a valid application status.')
                note=self.text(data,'note',0,2000)
                with app.db() as db:
                    student=db.execute("SELECT * FROM users WHERE id=? AND role='student'",(data.get('student'),)).fetchone()
                    if not student: raise APIError(404,'Application not found.')
                    verified=bool(student['verified']) or data.get('verified') is True
                    db.execute('BEGIN IMMEDIATE')
                    previous_note=db.execute('SELECT value FROM settings WHERE key=?',('application_note:'+str(student['id']),)).fetchone()
                    if status==student['status'] and verified==bool(student['verified']) and note==(json.loads(previous_note[0]) if previous_note else ''):
                        return self.output({'ok':True,'message':'This decision is already saved. No duplicate email was sent.'})
                    db.execute('UPDATE users SET status=?,verified=? WHERE id=?',(status,int(verified),student['id']))
                    db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('application_note:'+str(student['id']),json.dumps(note)))
                    db.execute('INSERT INTO audit(actor,action,target,created) VALUES(?,?,?,?)',(user['id'],'admission:'+status,student['id'],time.time()))
                    if status=='accepted' and not verified:
                        raw=secrets.token_urlsafe(32)
                        db.execute("DELETE FROM tokens WHERE user_id=? AND kind='verify'",(student['id'],))
                        db.execute('INSERT INTO tokens VALUES(?,?,?,?)',(app.digest(raw),student['id'],'verify',time.time()+86400))
                        app.enqueue(db,student['email'],'You are accepted — verify your academy email',f"Hello {student['name']},\nYour Academy application is accepted. Confirm ownership of this email address to open your classroom:\n{app.origin}/#verify/{raw}\nThis link expires in 24 hours.\n"+(note+'\n' if note else '')+'If you did not apply, ignore this email.')
                    elif status=='accepted':
                        subject,body,html_body=acceptance_message(student['name'],note,app.origin,app.app_url,app.policy.get('contactEmail',''))
                        app.enqueue(db,student['email'],subject,body,html_body)
                    else:
                        app.enqueue(db,student['email'],'Academy application update',f'Your application status is now {status.replace("_"," ")}. '+(note+'\n' if note else '')+f'Check your account at {app.origin}/#account')
                return self.output({'ok':True,'message':'Accepted. A verification link was emailed; classroom access opens after verification.' if status=='accepted' and not verified else 'Decision saved and email notification queued.'})
            if path=='/api/account':
                user=self.user()
                with app.db() as db: row=db.execute('SELECT value FROM settings WHERE key=?',('application_note:'+str(user['id']),)).fetchone()
                return self.output({'user':self.safe_user(user),'note':json.loads(row[0]) if row else '', 'application':{k:user[k] for k in ('experience','difficulty','goal')}})
            if path=='/api/application-update':
                user=self.user()
                if user['role']!='student' or user['status'] not in ('pending','needs_information'): raise APIError(403,'This application cannot be edited at its current stage.')
                goal=self.text(data,'goal',10,1000);difficulty=self.text(data,'difficulty',2,500)
                with app.db() as db:
                    db.execute("UPDATE users SET goal=?,difficulty=?,status='pending' WHERE id=?",(goal,difficulty,user['id']))
                    app.enqueue(db,app.recipient,'Academy application updated',f'An applicant has updated their information. Review it at {app.origin}/#teaching')
                return self.output({'ok':True})
            if path=='/api/schedule':
                self.user(teacher=True);sessions=data.get('sessions')
                if not isinstance(sessions,list) or len(sessions)>7: raise APIError(400,'Provide up to seven sessions.')
                clean=[]
                for item in sessions:
                    if not isinstance(item,dict) or type(item.get('lesson'))!=int or not 0<=item['lesson']<7: raise APIError(400,'Invalid lesson.')
                    when=self.text(item,'when',1,100);url=self.text(item,'url',1,1000)
                    if url and (urlsplit(url).scheme!='https' or not urlsplit(url).netloc): raise APIError(400,'Joining links must use HTTPS.')
                    if any(s['lesson']==item['lesson'] for s in clean): raise APIError(400,'Each lesson can appear only once in the schedule.')
                    clean.append({'lesson':item['lesson'],'when':when,'url':url})
                with app.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    previous=db.execute("SELECT value FROM settings WHERE key='schedule'").fetchone()
                    if previous and any('id' in x for x in json.loads(previous[0])): raise APIError(409,'Refresh the teacher dashboard to use the updated class scheduler.')
                    old={x['lesson']:x for x in json.loads(previous[0])} if previous else {}
                    new={x['lesson']:x for x in clean}
                    changes=[('updated' if x['lesson'] in old else 'scheduled',x) for x in clean if old.get(x['lesson'])!=x]
                    changes += [('cancelled',x) for key,x in old.items() if key not in new]
                    db.execute("INSERT INTO settings VALUES('schedule',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(clean),))
                    students=db.execute("SELECT email,name FROM users WHERE role='student' AND status='accepted' AND verified=1").fetchall()
                    for kind,session in changes:
                        title=LESSONS[session['lesson']]['title']
                        for student in students:
                            subject,body,html_body=class_message(student['name'],title,session['when'],session['url'],app.origin,kind)
                            app.enqueue(db,student['email'],subject,body,html_body)
                return self.output({'ok':True,'notifications':len(changes)*len(students)})
            if path=='/api/mail-test':
                self.user(teacher=True)
                if not app.mail_enabled: raise APIError(409,'Connect email delivery before sending a test.')
                if app.limited('mail-test',3,3600): raise APIError(429,'Please check the outbox before sending another test.')
                with app.db() as db: app.enqueue(db,app.recipient,'Academy email delivery test',f'This is an academy delivery test. Open your instructor dashboard at {app.origin}/#teaching. Receiving this message confirms delivery to this inbox.')
                return self.output({'ok':True,'message':'Test queued to your notification address. Check the outbox and your inbox.'})
            if path=='/api/mail-retry':
                self.user(teacher=True)
                with app.db() as db: db.execute("UPDATE mail SET status='queued',error='' WHERE id=? AND status='failed'",(data.get('id'),))
                return self.output({'ok':True})
            if path=='/api/verify-email':
                if app.limited('verify:'+self.client_address[0],40,900): raise APIError(429,'Please wait before trying another verification link.')
                raw=self.text(data,'token',20,200)
                with app.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    row=db.execute("SELECT * FROM tokens WHERE token=? AND kind='verify' AND expires>?",(app.digest(raw),time.time())).fetchone()
                    if not row: raise APIError(400,'This verification link is invalid or expired. Sign in and request a new one.')
                    db.execute('UPDATE users SET verified=1 WHERE id=?',(row['user_id'],))
                    db.execute("DELETE FROM tokens WHERE user_id=? AND kind='verify'",(row['user_id'],))
                return self.output({'ok':True,'message':'Email verified. Sign in to open your classroom if your application is accepted.'})
            if path=='/api/verification-request':
                user=self.user()
                if user['verified']: return self.output({'ok':True,'message':'Your email is already verified.'})
                if app.limited('verify-send:'+str(user['id']),3,3600): raise APIError(429,'A verification email was recently requested. Check your inbox and spam folder before trying again.')
                with app.db() as db:
                    raw=secrets.token_urlsafe(32)
                    db.execute("DELETE FROM tokens WHERE user_id=? AND kind='verify'",(user['id'],))
                    db.execute('INSERT INTO tokens VALUES(?,?,?,?)',(app.digest(raw),user['id'],'verify',time.time()+86400))
                    app.enqueue(db,user['email'],'Verify your academy email',f'Confirm your email address within 24 hours: {app.origin}/#verify/{raw}')
                return self.output({'ok':True,'message':'A new verification link has been queued to your registered email.'})
            if path=='/api/reset-request':
                email=self.email(data)
                with app.db() as db:
                    user=db.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()
                    if user:
                        raw=secrets.token_urlsafe(32); db.execute("DELETE FROM tokens WHERE user_id=? AND kind='reset'",(user['id'],))
                        db.execute('INSERT INTO tokens VALUES(?,?,?,?)',(app.digest(raw),user['id'],'reset',time.time()+1800))
                        app.enqueue(db,email,'Reset your academy password',f'Use this link within 30 minutes: {app.origin}/#reset/{raw}\nIf you did not request this, ignore this email.')
                return self.output({'ok':True,'message':'If an account matches, reset instructions have been queued. Delivery requires the instructor’s email service to be connected.'})
            if path=='/api/reset':
                raw=self.text(data,'token',20,200);password=self.text(data,'password',12,128)
                with app.db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    row=db.execute("SELECT * FROM tokens WHERE token=? AND kind='reset' AND expires>?",(app.digest(raw),time.time())).fetchone()
                    if not row: raise APIError(400,'This reset link is invalid or expired.')
                    db.execute('UPDATE users SET password=? WHERE id=?',(app.password(password),row['user_id']))
                    db.execute('DELETE FROM tokens WHERE user_id=?',(row['user_id'],));db.execute('DELETE FROM sessions WHERE user_id=?',(row['user_id'],))
                return self.output({'ok':True})
            raise APIError(404,'Not found.')
        except APIError as e: self.output({'error':e.message},e.status)
        except (BrokenPipeError,ConnectionResetError): pass
        except Exception: self.output({'error':'The server could not complete this request.'},500)

def make_server(directory,port=8743,origin=None):
    app=Academy(directory,origin or f'http://127.0.0.1:{port}')
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.app=app
    return server

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8743);parser.add_argument('--data',default=str(ROOT/'.academy-data'));args=parser.parse_args()
    server=make_server(args.data,args.port,os.environ.get('ACADEMY_ORIGIN'))
    threading.Thread(target=server.app.send_loop,daemon=True).start()
    print(f'Academy ready at {server.app.origin}. Local data: {server.app.directory}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: server.app.stop.set();server.server_close()
