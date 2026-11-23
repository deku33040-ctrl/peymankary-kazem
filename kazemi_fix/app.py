import os, sqlite3, secrets, io, csv, time, json, re, hashlib, hmac
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_file
try:
    from werkzeug.security import check_password_hash, generate_password_hash
except ImportError:
    # Compatibility fallback for damaged/mismatched Werkzeug security exports.
    # Keeps Werkzeug-compatible PBKDF2 hashes and verifies older scrypt hashes.
    def generate_password_hash(password, method='pbkdf2:sha256:600000', salt_length=16):
        if not method.startswith('pbkdf2:sha256:'):
            method = 'pbkdf2:sha256:600000'
        iterations = int(method.rsplit(':', 1)[1])
        salt = secrets.token_hex(salt_length)
        digest = hashlib.pbkdf2_hmac('sha256', str(password).encode(), salt.encode(), iterations).hex()
        return f'pbkdf2:sha256:{iterations}${salt}${digest}'

    def check_password_hash(pwhash, password):
        try:
            method, salt, expected = str(pwhash).split('$', 2)
            if method.startswith('pbkdf2:sha256:'):
                iterations = int(method.rsplit(':', 1)[1])
                actual = hashlib.pbkdf2_hmac('sha256', str(password).encode(), salt.encode(), iterations).hex()
            elif method.startswith('scrypt:'):
                _, n, r, p = method.split(':')
                actual = hashlib.scrypt(str(password).encode(), salt=salt.encode(), n=int(n), r=int(r), p=int(p)).hex()
            else:
                return False
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError, MemoryError):
            return False
from werkzeug.utils import secure_filename

BASE = Path(__file__).resolve().parent
DB = BASE / 'kazemi.db'
UPLOAD_DIR = BASE / 'static' / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
LOGIN_ATTEMPTS = {}

DEFAULTS = {
 'company':'پیمانکاری کاظمی', 'slogan':'سنگ‌کاری • نما • اجرای ساختمان',
 'heroText':'پیمانکاری کاظمی؛ همراه مطمئن شما در اجرای سنگ‌کاری، نمای ساختمان و پروژه‌های ساختمانی، از ایده تا تحویل نهایی.',
 'aboutText':'در پیمانکاری کاظمی، هر پروژه با شناخت نیاز کارفرما، انتخاب مصالح مناسب و برنامه‌ریزی دقیق آغاز می‌شود. هدف ما اجرای تمیز، اصولی و ماندگار است.',
 'quote':'اعتماد با حرف ساخته نمی‌شود؛ با کیفیت کار، ماندگار می‌شود.',
 'experience':'۱۰+', 'projectsCount':'۷۰+', 'phone':'', 'address':'',
 'seo_title':'پیمانکاری کاظمی | سنگ‌کاری و اجرای ساختمان',
 'seo_description':'اجرای تخصصی سنگ‌کاری، نمای ساختمان، بازسازی و پیمانکاری ساختمان در ایران.', 'accent_color':'#c7a46b', 'home_projects_limit':'12', 'seo_city':'', 'visual_layout':'{}'
}

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        con.execute('''CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, category TEXT NOT NULL, description TEXT DEFAULT '', image TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_favorite INTEGER NOT NULL DEFAULT 0)''')
        cols = [r['name'] for r in con.execute('PRAGMA table_info(projects)')]
        if 'is_favorite' not in cols:
            con.execute('ALTER TABLE projects ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0')
        con.execute('''CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, service TEXT, message TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        con.execute('''CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)''')
        for k,v in DEFAULTS.items():
            con.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',(k,v))
        if not con.execute('SELECT id FROM admins LIMIT 1').fetchone():
            username = os.environ.get('ADMIN_USERNAME', 'admin')
            password = os.environ.get('ADMIN_PASSWORD', 'Kazemi-Change-This-2026!')
            con.execute('INSERT INTO admins(username,password_hash) VALUES(?,?)',(username,generate_password_hash(password)))

init_db()

@app.context_processor
def inject_csrf():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return {'csrf_token': session['csrf_token']}

def valid_csrf():
    return secrets.compare_digest(str(session.get('csrf_token', '')), str(request.form.get('csrf_token', '')))

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if 'admin_id' not in session:
            return redirect(url_for('admin_login', next=request.path))
        if request.method == 'POST' and not valid_csrf():
            abort(400, description='درخواست نامعتبر است؛ صفحه را تازه‌سازی کنید.')
        return fn(*args, **kwargs)
    return wrapped

def get_settings():
    with db() as con:
        values = dict(DEFAULTS)
        values.update({r['key']:r['value'] for r in con.execute('SELECT key,value FROM settings')})
        return values

@app.get('/')
def home():
    
    settings = get_settings()
    try: layout = json.loads(settings.get('visual_layout', '{}'))
    except (TypeError, ValueError): layout = {}
    return render_template('index.html', settings=settings, layout=layout)

@app.get('/project/<int:pid>')
def project_detail(pid):
    with db() as con:
        project = con.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
    if not project: abort(404)
    return render_template('project_detail.html', project=project, settings=get_settings())

@app.get('/robots.txt')
def robots():
    return app.response_class('User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: ' + request.url_root.rstrip('/') + '/sitemap.xml\n', mimetype='text/plain')

@app.get('/sitemap.xml')
def sitemap():
    from xml.sax.saxutils import escape
    with db() as con:
        ids = [r['id'] for r in con.execute('SELECT id FROM projects ORDER BY id DESC')]
    root = request.url_root.rstrip('/')
    urls = [f'<url><loc>{escape(root)}/</loc></url>'] + [f'<url><loc>{escape(root)}/project/{pid}</loc></url>' for pid in ids]
    return app.response_class('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(urls) + '</urlset>', mimetype='application/xml')

@app.get('/api/public')
def public_data():
    with db() as con:
        projects = [dict(r) for r in con.execute('SELECT id,title,category,description,image,is_favorite FROM projects ORDER BY is_favorite DESC, id DESC')]
    return jsonify({'settings':get_settings(),'projects':projects})

@app.post('/api/contact')
def contact():
    data = request.get_json(silent=True) or request.form
    name = str(data.get('name','')).strip()[:120]
    phone = str(data.get('phone','')).strip()[:40]
    service = str(data.get('service','')).strip()[:120]
    message = str(data.get('message','')).strip()[:3000]
    if not name or not phone:
        return jsonify({'ok':False,'error':'نام و شماره تماس الزامی است.'}), 400
    with db() as con:
        con.execute('INSERT INTO messages(name,phone,service,message) VALUES(?,?,?,?)',(name,phone,service,message))
    return jsonify({'ok':True,'message':'درخواست شما ثبت شد. با شما تماس می‌گیریم.'})

@app.route('/admin/login', methods=['GET','POST'])
def admin_login():
    if request.method == 'POST':
        if not valid_csrf(): abort(400, description='درخواست نامعتبر است؛ صفحه را تازه‌سازی کنید.')
        ip = request.remote_addr or 'unknown'
        attempts, started = LOGIN_ATTEMPTS.get(ip, (0, time.time()))
        if time.time() - started > 600: attempts, started = 0, time.time()
        if attempts >= 8:
            flash('تلاش‌های ورود زیاد است؛ ۱۰ دقیقه دیگر امتحان کنید.','error')
            return render_template('admin_login.html'), 429
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        with db() as con:
            user = con.execute('SELECT * FROM admins WHERE username=?',(username,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            LOGIN_ATTEMPTS.pop(ip, None)
            session.clear(); session['admin_id'] = user['id']; session['admin_name'] = user['username']; session['csrf_token'] = secrets.token_urlsafe(32)
            return redirect(url_for('admin_dashboard'))
        LOGIN_ATTEMPTS[ip] = (attempts + 1, started)
        flash('نام کاربری یا رمز عبور اشتباه است.','error')
    return render_template('admin_login.html')

@app.post('/admin/logout')
@admin_required
def admin_logout():
    session.clear(); return redirect(url_for('admin_login'))

@app.get('/admin')
@admin_required
def admin_dashboard():
    with db() as con:
        projects = con.execute('SELECT * FROM projects ORDER BY id DESC').fetchall()
        messages = con.execute('SELECT * FROM messages ORDER BY id DESC LIMIT 100').fetchall()
    with db() as con:
        total_projects = con.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
        total_messages = con.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
        latest_message = con.execute('SELECT MAX(created_at) FROM messages').fetchone()[0]
    return render_template('admin_dashboard.html', settings=get_settings(), projects=projects, messages=messages, total_projects=total_projects, total_messages=total_messages, latest_message=latest_message)


@app.get('/admin/builder')
@admin_required
def visual_builder():
    settings = get_settings()
    try: layout = json.loads(settings.get('visual_layout', '{}'))
    except (TypeError, ValueError): layout = {}
    return render_template('admin_builder.html', settings=settings, layout=layout)

@app.post('/admin/builder')
@admin_required
def save_visual_builder():
    allowed_sections = {'home','about','services','projects','statement','contact'}
    default_order = ['home','about','services','projects','statement','contact']
    order = [x for x in request.form.getlist('section_order') if x in allowed_sections]
    order = list(dict.fromkeys(order))
    order += [x for x in default_order if x not in order]
    hidden = [x for x in request.form.getlist('hidden_sections') if x in allowed_sections]
    transition = request.form.get('transition', 'fade-up')
    if transition not in {'none','fade','fade-up','slide-left','slide-right','zoom','flip','blur'}: transition = 'fade-up'
    try: duration = max(100, min(3000, int(request.form.get('duration','650'))))
    except (ValueError, TypeError): duration = 650
    try: delay = max(0, min(1500, int(request.form.get('delay','0'))))
    except (ValueError, TypeError): delay = 0
    try: radius = max(0, min(48, int(request.form.get('radius','14'))))
    except (ValueError, TypeError): radius = 14
    try: spacing = max(40, min(180, int(request.form.get('spacing','105'))))
    except (ValueError, TypeError): spacing = 105
    def color(name, fallback):
        value = request.form.get(name, fallback).strip()
        return value if re.fullmatch(r'#[0-9a-fA-F]{6}', value) else fallback
    accent = color('accent', '#c7a46b')
    background = color('background', '#111512')
    font = request.form.get('font', 'Tahoma').strip()
    if font not in {'Tahoma','Arial','Vazirmatn','sans-serif'}: font = 'Tahoma'
    easing = request.form.get('easing', 'ease')
    if easing not in {'linear','ease','ease-in','ease-out','ease-in-out','cubic-bezier(.2,.8,.2,1)'}: easing = 'ease'
    config = {'order':order, 'hidden':hidden, 'transition':transition, 'duration':duration,
              'delay':delay, 'accent':accent, 'background':background, 'radius':radius,
              'spacing':spacing, 'font':font, 'easing':easing}
    with db() as con:
        con.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', ('visual_layout', json.dumps(config, ensure_ascii=False)))
    flash('تنظیمات طراحی ذخیره و روی سایت اعمال شد.','success')
    return redirect(url_for('visual_builder'))

@app.post('/admin/settings')
@admin_required
def save_settings():
    with db() as con:
        for key in DEFAULTS:
            if key in request.form:
                value = request.form.get(key, '').strip()[:2000]
                con.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,value))
    flash('تنظیمات سایت ذخیره شد.','success')
    return redirect(url_for('admin_dashboard')+'#settings')

def save_upload(file):
    if not file or not file.filename: return ''
    filename = secure_filename(file.filename)
    if '.' not in filename or filename.rsplit('.',1)[1].lower() not in ALLOWED:
        raise ValueError('فرمت تصویر باید JPG، PNG، WEBP یا GIF باشد.')
    ext = filename.rsplit('.',1)[1].lower()
    name = secrets.token_hex(12)+'.'+ext
    file.save(UPLOAD_DIR/name)
    return '/static/uploads/'+name

@app.post('/admin/projects/add')
@admin_required
def add_project():
    title=request.form.get('title','').strip(); category=request.form.get('category','').strip(); description=request.form.get('description','').strip()
    if not title or not category:
        flash('عنوان و دسته‌بندی پروژه الزامی است.','error'); return redirect(url_for('admin_dashboard')+'#projects')
    try: image=save_upload(request.files.get('image'))
    except ValueError as e:
        flash(str(e),'error'); return redirect(url_for('admin_dashboard')+'#projects')
    with db() as con: con.execute('INSERT INTO projects(title,category,description,image) VALUES(?,?,?,?)',(title,category,description,image))
    flash('نمونه‌کار اضافه شد.','success'); return redirect(url_for('admin_dashboard')+'#projects')

@app.post('/admin/projects/<int:pid>/edit')
@admin_required
def edit_project(pid):
    title=request.form.get('title','').strip(); category=request.form.get('category','').strip(); description=request.form.get('description','').strip()
    try: image=save_upload(request.files.get('image'))
    except ValueError as e:
        flash(str(e),'error'); return redirect(url_for('admin_dashboard')+'#projects')
    with db() as con:
        old=con.execute('SELECT image FROM projects WHERE id=?',(pid,)).fetchone()
        if not old: abort(404)
        if image:
            con.execute('UPDATE projects SET title=?,category=?,description=?,image=? WHERE id=?',(title,category,description,image,pid))
        else:
            con.execute('UPDATE projects SET title=?,category=?,description=? WHERE id=?',(title,category,description,pid))
    flash('نمونه‌کار ویرایش شد.','success'); return redirect(url_for('admin_dashboard')+'#projects')

@app.post('/admin/projects/<int:pid>/delete')
@admin_required
def delete_project(pid):
    with db() as con:
        row=con.execute('SELECT image FROM projects WHERE id=?',(pid,)).fetchone()
        if row:
            con.execute('DELETE FROM projects WHERE id=?',(pid,))
            if row['image'].startswith('/static/uploads/'):
                try: (BASE / row['image'].lstrip('/')).unlink(missing_ok=True)
                except OSError: pass
    flash('نمونه‌کار حذف شد.','success'); return redirect(url_for('admin_dashboard')+'#projects')

@app.post('/admin/projects/<int:pid>/favorite')
@admin_required
def toggle_favorite(pid):
    with db() as con:
        row = con.execute('SELECT is_favorite FROM projects WHERE id=?', (pid,)).fetchone()
        if not row: abort(404)
        con.execute('UPDATE projects SET is_favorite=? WHERE id=?', (0 if row['is_favorite'] else 1, pid))
    flash('وضعیت محبوبیت نمونه‌کار تغییر کرد.', 'success')
    return redirect(url_for('admin_dashboard') + '#projects')

@app.post('/admin/messages/<int:mid>/delete')
@admin_required
def delete_message(mid):
    with db() as con: con.execute('DELETE FROM messages WHERE id=?',(mid,))
    flash('پیام حذف شد.','success'); return redirect(url_for('admin_dashboard')+'#messages')

@app.post('/admin/password')
@admin_required
def change_password():
    current=request.form.get('current',''); new=request.form.get('new','')
    with db() as con:
        user=con.execute('SELECT * FROM admins WHERE id=?',(session['admin_id'],)).fetchone()
        if not user or not check_password_hash(user['password_hash'],current):
            flash('رمز فعلی صحیح نیست.','error')
        elif len(new)<12:
            flash('رمز جدید باید حداقل ۱۲ نویسه باشد.','error')
        else:
            con.execute('UPDATE admins SET password_hash=? WHERE id=?',(generate_password_hash(new),session['admin_id']))
            flash('رمز عبور تغییر کرد.','success')
    return redirect(url_for('admin_dashboard')+'#password')

@app.get('/admin/export/messages.csv')
@admin_required
def export_messages():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['نام', 'تلفن', 'موضوع', 'پیام', 'تاریخ'])
    with db() as con:
        for row in con.execute('SELECT name,phone,service,message,created_at FROM messages ORDER BY id DESC'):
            writer.writerow(list(row))
    data = ('\ufeff' + output.getvalue()).encode('utf-8')
    return send_file(io.BytesIO(data), mimetype='text/csv; charset=utf-8', as_attachment=True, download_name='kazemi-messages.csv')

@app.get('/admin/backup')
@admin_required
def backup_database():
    if not DB.exists(): abort(404)
    return send_file(DB, mimetype='application/x-sqlite3', as_attachment=True, download_name='kazemi-backup.sqlite3')

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
