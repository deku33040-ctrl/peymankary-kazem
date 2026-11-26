import os, sys, sqlite3, secrets, io, csv, time, json, re, urllib.request, urllib.error, html
from datetime import timedelta
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_file, g
from werkzeug.middleware.proxy_fix import ProxyFix
from markupsafe import Markup, escape
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import bleach
import helpers as H

BASE = Path(__file__).resolve().parent
DB = Path(os.environ.get('KAZEMI_DB') or BASE / 'kazemi.db')
UPLOAD_DIR = BASE / 'static' / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
FONT_ALLOWED = {'woff2','woff','ttf','otf'}
FONT_DIR = BASE / 'static' / 'fonts'
FONT_DIR.mkdir(parents=True, exist_ok=True)
app = Flask(__name__)
if os.environ.get('TRUST_PROXY') == '1':  # فقط پشت nginx/میزبان معتبر فعال شود تا IP واقعی کاربر دیده شود
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
def load_secret_key():
    configured = os.environ.get('SECRET_KEY')
    if configured:
        return configured
    key_file = BASE / '.kazemi_secret_key'
    try:
        if key_file.exists():
            return key_file.read_text(encoding='utf-8').strip()
        value = secrets.token_urlsafe(48)
        key_file.write_text(value, encoding='utf-8')
        try: key_file.chmod(0o600)
        except OSError: pass
        return value
    except OSError:
        return secrets.token_urlsafe(48)

app.secret_key = load_secret_key()
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE') == '1',
                  PERMANENT_SESSION_LIFETIME=timedelta(hours=12))
LOGIN_ATTEMPTS = {}
CONTACT_HITS = {}

DEFAULTS = {
 'company':'پیمانکاری کاظمی', 'slogan':'سنگ‌کاری • نما • اجرای ساختمان',
 'heroText':'پیمانکاری کاظمی؛ همراه مطمئن شما در اجرای سنگ‌کاری، نمای ساختمان و پروژه‌های ساختمانی، از ایده تا تحویل نهایی.',
 'aboutText':'در پیمانکاری کاظمی، هر پروژه با شناخت نیاز کارفرما، انتخاب مصالح مناسب و برنامه‌ریزی دقیق آغاز می‌شود. هدف ما اجرای تمیز، اصولی و ماندگار است.',
 'quote':'اعتماد با حرف ساخته نمی‌شود؛ با کیفیت کار، ماندگار می‌شود.',
 'experience':'۱۰+', 'projectsCount':'۷۰+', 'phone':'', 'telegram':'', 'address':'',
 'seo_title':'پیمانکاری کاظمی | سنگ‌کاری و اجرای ساختمان',
 'seo_description':'اجرای تخصصی سنگ‌کاری، نمای ساختمان، بازسازی و پیمانکاری ساختمان در ایران.', 'accent_color':'#c7a46b', 'home_projects_limit':'12', 'seo_city':'', 'visual_layout':'{}', 'custom_font':'', 'about_bg_image':'', 'statement_bg_image':'', 'maker_text':'MADE BY DEKU', 'maker_url':'#',
 'whatsapp':'', 'instagram':'', 'email':'', 'country_code':'', 'logo_letter':'K', 'header_cta_text':'تماس و مشاوره',
 'footer_text':'', 'float_enabled':'1'
}

class Conn(sqlite3.Connection):
    """with db() as con: ... هم commit می‌کند و هم اتصال را می‌بندد."""
    def __exit__(self, *exc):
        try: return super().__exit__(*exc)
        finally: self.close()

def db():
    con = sqlite3.connect(DB, factory=Conn, timeout=10)
    con.row_factory = sqlite3.Row
    return con

def seed_blocks(con):
    """اولین اجرا: چیدمان قبلی و «بخش‌های اختصاصی» قدیمی به بلوک تبدیل می‌شوند."""
    if con.execute('SELECT 1 FROM blocks LIMIT 1').fetchone(): return
    try: old = json.loads(con.execute("SELECT value FROM settings WHERE key='visual_layout'").fetchone()[0] or '{}')
    except (TypeError, ValueError): old = {}
    names = {'home':'hero','about':'about','services':'services','projects':'projects','statement':'statement','contact':'contact'}
    seq = [names[k] for k in old.get('order', []) if k in names] or [n for n in H.DEFAULT_ORDER if n != 'blog']
    seq += [n for n in H.DEFAULT_ORDER if n not in seq and n != 'blog']
    seq.insert(seq.index('projects')+1 if 'projects' in seq else len(seq), 'blog')
    hidden = {names[k] for k in old.get('hidden', []) if k in names}
    rows = [(t, {}, 0 if t in hidden else 1) for t in seq]
    legacy = [(r['title'], r['content'], r['is_visible']) for r in con.execute('SELECT * FROM home_sections ORDER BY sort_order,id')]
    at = rows.index(next(r for r in rows if r[0] == 'statement')) if any(r[0] == 'statement' for r in rows) else len(rows)
    rows[at:at] = [('text', {'title': t, 'body': c, 'bg': 'light'}, v) for t, c, v in legacy]
    for i, (t, d, v) in enumerate(rows):
        con.execute('INSERT INTO blocks(type,data,sort_order,is_visible) VALUES(?,?,?,?)', (t, json.dumps(H.clean_block(t, d), ensure_ascii=False), i, v))

def init_db():
    with db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        con.execute('''CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, category TEXT NOT NULL, description TEXT DEFAULT '', image TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_favorite INTEGER NOT NULL DEFAULT 0)''')
        cols = [r['name'] for r in con.execute('PRAGMA table_info(projects)')]
        if 'is_favorite' not in cols:
            con.execute('ALTER TABLE projects ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0')
        con.execute('''CREATE TABLE IF NOT EXISTS service_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL UNIQUE, slug TEXT NOT NULL UNIQUE, description TEXT DEFAULT '')''')
        con.execute('''CREATE TABLE IF NOT EXISTS home_sections (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT DEFAULT '', is_visible INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0)''')
        con.execute('''CREATE TABLE IF NOT EXISTS custom_pages (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, slug TEXT NOT NULL UNIQUE, content TEXT DEFAULT '', meta_description TEXT DEFAULT '', is_published INTEGER NOT NULL DEFAULT 1)''')
        defaults = [
            ('نمای سنگ ساختمان','nemaye-sang-sakhteman','اجرای تخصصی نمای سنگ ساختمان با دقت در انتخاب مصالح و جزئیات نصب.'),
            ('سنگ لاشه','sang-lashe','طراحی و اجرای سنگ لاشه برای فضاهای ساختمانی و محوطه.'),
            ('اجرای سنگ لاشه','ejraye-sang-lashe','اجرای اصولی سنگ لاشه با توجه به طرح و شرایط پروژه.'),
            ('سنگ‌کاری آبنما','sang-kari-abnama','اجرای سنگ‌کاری آبنما و جزئیات سنگی محوطه.')
        ]
        for title, slug, desc in defaults:
            con.execute('INSERT OR IGNORE INTO service_categories(title,slug,description) VALUES(?,?,?)',(title,slug,desc))
        # Migrate the earlier misspelled service label without losing linked projects.
        old_service = con.execute("SELECT id FROM service_categories WHERE title='سنگ کاری ابنما'").fetchone()
        correct_service = con.execute("SELECT id FROM service_categories WHERE title='سنگ‌کاری آبنما'").fetchone()
        if old_service:
            if correct_service:
                con.execute("UPDATE projects SET category='سنگ‌کاری آبنما' WHERE category='سنگ کاری ابنما'")
                con.execute("DELETE FROM service_categories WHERE id=?", (old_service['id'],))
            else:
                con.execute("UPDATE service_categories SET title='سنگ‌کاری آبنما',slug='sang-kari-abnama' WHERE id=?", (old_service['id'],))
                con.execute("UPDATE projects SET category='سنگ‌کاری آبنما' WHERE category='سنگ کاری ابنما'")
        con.execute('''CREATE TABLE IF NOT EXISTS blog_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            excerpt TEXT DEFAULT '',
            content TEXT NOT NULL,
            image TEXT DEFAULT '',
            meta_description TEXT DEFAULT '',
            is_published INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        con.execute('''CREATE TABLE IF NOT EXISTS ai_generated_posts (
            post_id INTEGER PRIMARY KEY,
            topic TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(post_id) REFERENCES blog_posts(id) ON DELETE CASCADE
        )''')
        con.execute('''CREATE TABLE IF NOT EXISTS blocks (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}', sort_order INTEGER NOT NULL DEFAULT 0, is_visible INTEGER NOT NULL DEFAULT 1)''')
        con.execute('''CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, service TEXT, message TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        con.execute('''CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)''')
        for k,v in DEFAULTS.items():
            con.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',(k,v))
        seed_blocks(con)
        if not con.execute('SELECT id FROM admins LIMIT 1').fetchone():
            username = os.environ.get('ADMIN_USERNAME', 'admin')
            password = os.environ.get('ADMIN_PASSWORD')
            if not password:  # رمز پیش‌فرض ثابت در کد نداریم؛ رمز تصادفی ساخته و یک‌بار نمایش داده می‌شود
                password = secrets.token_urlsafe(12)
                print(f'\n*** رمز اولیه مدیر ***\n  نام کاربری: {username}\n  رمز عبور: {password}\n  (فوراً از پنل تغییر دهید؛ در صورت فراموشی: python app.py reset-admin)\n', flush=True)
            con.execute('INSERT INTO admins(username,password_hash) VALUES(?,?)',(username,generate_password_hash(password)))

init_db()

@app.context_processor
def inject_csrf():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return {'csrf_token': session['csrf_token']}

def valid_csrf():
    sent = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token', '')
    return secrets.compare_digest(str(session.get('csrf_token', '')), str(sent))

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
    if 'settings' not in g:
        with db() as con:
            values = dict(DEFAULTS)
            values.update({r['key']:r['value'] for r in con.execute('SELECT key,value FROM settings')})
        g.settings = values
    return g.settings

def get_layout(settings=None):
    try: raw = json.loads((settings or get_settings()).get('visual_layout') or '{}')
    except (TypeError, ValueError): raw = {}
    return H.clean_appearance(raw)

def load_blocks(con, only_visible=False):
    out = []
    for r in con.execute('SELECT * FROM blocks ORDER BY sort_order,id'):
        if r['type'] not in H.BLOCK_TYPES or (only_visible and not r['is_visible']): continue
        try: data = json.loads(r['data'] or '{}')
        except ValueError: data = {}
        out.append({'id': r['id'], 'type': r['type'], 'visible': bool(r['is_visible']), 'data': H.fill_defaults(r['type'], data)})
    return out

@app.context_processor
def inject_site():
    settings = get_settings()
    with db() as con:
        nav_pages = con.execute('SELECT title,slug FROM custom_pages WHERE is_published=1 ORDER BY id').fetchall()
    return {'settings': settings, 'layout': get_layout(settings), 'links': H.contact_links(settings), 'nav_pages': nav_pages, 'year': time.strftime('%Y')}

@app.template_filter('fa_date')
def fa_date_filter(value): return H.jalali(value)

@app.template_filter('nl2br')
def nl2br_filter(value): return Markup('<br>').join(escape(line) for line in str(value or '').split('\n'))

@app.template_filter('rich')
def rich_filter(value):
    """متن امن عنوان: خط جدید = <br> و *کلمه* = برجسته."""
    html = str(nl2br_filter(value))
    return Markup(re.sub(r'\*([^*<]+)\*', r'<em>\1</em>', html))

@app.after_request
def security_headers(resp):
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    resp.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    if request.path.startswith('/admin'): resp.headers['Cache-Control'] = 'no-store'
    return resp

@app.get('/')
def home():
    settings = get_settings()
    try: limit = max(3, min(60, int(settings.get('home_projects_limit') or 12)))
    except ValueError: limit = 12
    with db() as con:
        categories = con.execute('SELECT * FROM service_categories ORDER BY id').fetchall()
        projects = con.execute('SELECT * FROM projects ORDER BY is_favorite DESC,id DESC LIMIT ?', (limit,)).fetchall()
        blog_posts = con.execute('SELECT id,title,slug,excerpt,image,created_at FROM blog_posts WHERE is_published=1 ORDER BY created_at DESC,id DESC LIMIT 3').fetchall()
        blocks = load_blocks(con, only_visible=True)
    return render_template('index.html', blocks=blocks, categories=categories, projects=projects, blog_posts=blog_posts)

@app.get('/service/<slug>')
def service_detail(slug):
    with db() as con:
        category = con.execute('SELECT * FROM service_categories WHERE slug=?',(slug,)).fetchone()
        if not category: abort(404)
        projects = con.execute('SELECT * FROM projects WHERE category=? ORDER BY is_favorite DESC,id DESC',(category['title'],)).fetchall()
    return render_template('service_detail.html', category=category, projects=projects, settings=get_settings())

@app.get('/page/<slug>')
def custom_page(slug):
    with db() as con:
        page = con.execute('SELECT * FROM custom_pages WHERE slug=? AND is_published=1',(slug,)).fetchone()
    if not page: abort(404)
    return render_template('custom_page.html', page=page, settings=get_settings())

@app.get('/project/<int:pid>')
def project_detail(pid):
    with db() as con:
        project = con.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
    if not project: abort(404)
    return render_template('project_detail.html', project=project, settings=get_settings())

@app.get('/blog')
def blog_index():
    page = max(1, request.args.get('page', 1, type=int))
    per_page = 9
    with db() as con:
        total = con.execute('SELECT COUNT(*) FROM blog_posts WHERE is_published=1').fetchone()[0]
        posts = con.execute('SELECT * FROM blog_posts WHERE is_published=1 ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?', (per_page, (page-1)*per_page)).fetchall()
    return render_template('blog_index.html', posts=posts, page=page, pages=max(1,(total+per_page-1)//per_page), settings=get_settings())

@app.get('/blog/<slug>')
def blog_detail(slug):
    with db() as con:
        post = con.execute('SELECT * FROM blog_posts WHERE slug=? AND is_published=1', (slug,)).fetchone()
    if not post: abort(404)
    return render_template('blog_detail.html', post=post, settings=get_settings())

@app.get('/robots.txt')
def robots():
    return app.response_class('User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: ' + request.url_root.rstrip('/') + '/sitemap.xml\n', mimetype='text/plain')

@app.get('/sitemap.xml')
def sitemap():
    from xml.sax.saxutils import escape
    with db() as con:
        ids = [r['id'] for r in con.execute('SELECT id FROM projects ORDER BY id DESC')]
    root = request.url_root.rstrip('/')
    with db() as con:
        slugs=[r['slug'] for r in con.execute('SELECT slug FROM service_categories')]
        page_slugs=[r['slug'] for r in con.execute('SELECT slug FROM custom_pages WHERE is_published=1')]
        blog_slugs=[r['slug'] for r in con.execute('SELECT slug FROM blog_posts WHERE is_published=1')]
    urls = [f'<url><loc>{escape(root)}/</loc></url>', f'<url><loc>{escape(root)}/blog</loc></url>'] + [f'<url><loc>{escape(root)}/project/{pid}</loc></url>' for pid in ids] + [f'<url><loc>{escape(root)}/service/{escape(slug)}</loc></url>' for slug in slugs] + [f'<url><loc>{escape(root)}/page/{escape(slug)}</loc></url>' for slug in page_slugs] + [f'<url><loc>{escape(root)}/blog/{escape(slug)}</loc></url>' for slug in blog_slugs]
    return app.response_class('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(urls) + '</urlset>', mimetype='application/xml')

@app.get('/api/public')
def public_data():
    with db() as con:
        projects = [dict(r) for r in con.execute('SELECT id,title,category,description,image,is_favorite FROM projects ORDER BY is_favorite DESC, id DESC')]
    with db() as con:
        categories = [dict(r) for r in con.execute('SELECT title,slug,description FROM service_categories ORDER BY id')]
    public = {k: v for k, v in get_settings().items() if k in ('company','slogan','phone','whatsapp','telegram','instagram','email','address')}
    return jsonify({'settings':public,'links':H.contact_links(get_settings()),'projects':projects,'categories':categories})

@app.post('/api/contact')
def contact():
    ip = request.remote_addr or 'unknown'
    hits = [t for t in CONTACT_HITS.get(ip, []) if time.time() - t < 3600]
    if len(hits) >= 5:
        return jsonify({'ok':False,'error':'تعداد درخواست‌ها زیاد است؛ کمی بعد دوباره تلاش کنید.'}), 429
    data = request.get_json(silent=True) or request.form
    if str(data.get('website','')).strip():  # honeypot: فقط ربات‌ها این فیلد پنهان را پر می‌کنند
        return jsonify({'ok':True,'message':'درخواست شما ثبت شد. با شما تماس می‌گیریم.'})
    CONTACT_HITS[ip] = hits + [time.time()]
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
            session.clear(); session.permanent = True; session['admin_id'] = user['id']; session['admin_name'] = user['username']; session['csrf_token'] = secrets.token_urlsafe(32)
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
        total_projects = con.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
        total_messages = con.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
        latest_message = con.execute('SELECT MAX(created_at) FROM messages').fetchone()[0]
        categories = con.execute('SELECT * FROM service_categories ORDER BY id').fetchall()
        pages = con.execute('SELECT * FROM custom_pages ORDER BY id DESC').fetchall()
        blog_posts = con.execute('SELECT * FROM blog_posts ORDER BY created_at DESC,id DESC').fetchall()
    ai_enabled = bool(os.environ.get('OPENAI_API_KEY', '').strip())
    with db() as con:
        ai_draft_count = con.execute('''SELECT COUNT(*) FROM ai_generated_posts a
            JOIN blog_posts b ON b.id=a.post_id WHERE b.is_published=0''').fetchone()[0]
    return render_template('admin_dashboard.html', settings=get_settings(), projects=projects, messages=messages, total_projects=total_projects, total_messages=total_messages, latest_message=latest_message, categories=categories, pages=pages, blog_posts=blog_posts, ai_enabled=ai_enabled, ai_draft_count=ai_draft_count)

@app.get('/admin/builder')
@admin_required
def visual_builder():
    settings = get_settings()
    with db() as con: blocks = load_blocks(con)
    state = {'blocks': blocks, 'appearance': get_layout(settings),
             'settings': {k: settings.get(k, '') for k in H.SETTING_FIELDS}}
    return render_template('admin_builder.html', state=state, schema=H.public_schema())

@app.post('/admin/builder/save')
@admin_required
def save_visual_builder():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict): return jsonify({'ok': False, 'error': 'داده نامعتبر است.'}), 400
    blocks = H.clean_blocks(payload.get('blocks'))
    settings = H.clean_settings(payload.get('settings'))
    appearance = H.clean_appearance(payload.get('appearance'))
    settings['accent_color'] = appearance['accent']
    settings['visual_layout'] = json.dumps(appearance, ensure_ascii=False)
    with db() as con:
        con.execute('DELETE FROM blocks')
        for i, b in enumerate(blocks):
            con.execute('INSERT INTO blocks(type,data,sort_order,is_visible) VALUES(?,?,?,?)', (b['type'], json.dumps(b['data'], ensure_ascii=False), i, 1 if b['visible'] else 0))
        for k, v in settings.items():
            con.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (k, str(v)))
    return jsonify({'ok': True, 'blocks': len(blocks)})

@app.post('/admin/builder/links')
@admin_required
def builder_links():
    """پیش‌نمایش لینک‌های تماس با همان منطقی که سایت استفاده می‌کند."""
    merged = dict(get_settings()); merged.update(H.clean_settings((request.get_json(silent=True) or {}).get('settings')))
    return jsonify(H.contact_links(merged))

def make_slug(value):
    value = re.sub(r'[^\w\u0600-\u06FF-]+', '-', value.strip().lower()).strip('-')
    return value[:70] or secrets.token_hex(4)

@app.post('/admin/categories/add')
@admin_required
def add_category():
    title=request.form.get('title','').strip()[:120]
    description=request.form.get('description','').strip()[:1000]
    if not title:
        flash('عنوان خدمت الزامی است.','error')
        return redirect(url_for('admin_dashboard')+'#categories')
    slug=make_slug(request.form.get('slug') or title)
    try:
        with db() as con: con.execute('INSERT INTO service_categories(title,slug,description) VALUES(?,?,?)',(title,slug,description))
        flash('عنوان خدمت و صفحه اختصاصی آن ساخته شد.','success')
    except sqlite3.IntegrityError:
        flash('عنوان یا نشانی این خدمت قبلاً ثبت شده است.','error')
    return redirect(url_for('admin_dashboard')+'#categories')

@app.post('/admin/categories/<int:cid>/delete')
@admin_required
def delete_category(cid):
    with db() as con:
        row=con.execute('SELECT title FROM service_categories WHERE id=?',(cid,)).fetchone()
        if row:
            con.execute('DELETE FROM service_categories WHERE id=?',(cid,))
    flash('خدمت حذف شد؛ نمونه‌کارهای قبلی حذف نمی‌شوند.','success')
    return redirect(url_for('admin_dashboard')+'#categories')

@app.post('/admin/pages/add')
@admin_required
def add_page():
    title=request.form.get('title','').strip()[:160]
    content=request.form.get('content','').strip()[:12000]
    slug=make_slug(request.form.get('slug') or title)
    if not title or not content:
        flash('عنوان و محتوای صفحه الزامی است.','error')
        return redirect(url_for('admin_dashboard')+'#pages')
    try:
        with db() as con: con.execute('INSERT INTO custom_pages(title,slug,content,meta_description) VALUES(?,?,?,?)',(title,slug,content,request.form.get('meta_description','').strip()[:300]))
        flash('صفحه جدید ساخته شد.','success')
    except sqlite3.IntegrityError:
        flash('این نشانی صفحه قبلاً استفاده شده است.','error')
    return redirect(url_for('admin_dashboard')+'#pages')

@app.post('/admin/pages/<int:pid>/delete')
@admin_required
def delete_page(pid):
    with db() as con: con.execute('DELETE FROM custom_pages WHERE id=?',(pid,))
    flash('صفحه حذف شد.','success')
    return redirect(url_for('admin_dashboard')+'#pages')



def clean_rich_html(value):
    allowed_tags = {'p','br','strong','b','em','i','u','h2','h3','h4','ul','ol','li','blockquote','a','img','hr'}
    allowed_attrs = {'a':['href','title','target','rel'], 'img':['src','alt','title','width','height']}
    cleaned = bleach.clean(value or '', tags=allowed_tags, attributes=allowed_attrs,
                           protocols={'http','https','mailto'}, strip=True)
    def safe_rel(attrs, new=False):
        if (None, 'href') in attrs:
            attrs[(None, 'rel')] = 'noopener noreferrer nofollow'
        return attrs
    return bleach.linkifier.Linker(callbacks=[safe_rel]).linkify(cleaned)

@app.post('/admin/upload-image')
@app.post('/admin/blog/inline-image')
@admin_required
def upload_blog_inline_image():
    f = request.files.get('image')
    try:
        url = save_upload(f)
    except ValueError as e:
        return jsonify({'error':str(e)}), 400
    if not url:
        return jsonify({'error':'فایلی انتخاب نشده است.'}), 400
    return jsonify({'url':url})

def unique_blog_slug(raw, exclude_id=None):
    base = make_slug(raw)
    candidate = base
    n = 2
    with db() as con:
        while True:
            row = con.execute('SELECT id FROM blog_posts WHERE slug=?', (candidate,)).fetchone()
            if not row or (exclude_id is not None and row['id'] == exclude_id):
                return candidate
            candidate = f'{base}-{n}'
            n += 1

@app.get('/admin/blog/new')
@admin_required
def new_blog_post():
    return render_template('admin_post_editor.html', post=None, action=url_for('add_blog_post'))

@app.get('/admin/blog/<int:post_id>/edit')
@admin_required
def blog_post_editor(post_id):
    with db() as con:
        post = con.execute('SELECT * FROM blog_posts WHERE id=?', (post_id,)).fetchone()
    if not post: abort(404)
    return render_template('admin_post_editor.html', post=post, action=url_for('edit_blog_post', post_id=post_id))

@app.post('/admin/blog/add')
@admin_required
def add_blog_post():
    title = request.form.get('title','').strip()[:180]
    content = clean_rich_html(request.form.get('content','').strip()[:50000])
    excerpt = request.form.get('excerpt','').strip()[:500]
    meta = request.form.get('meta_description','').strip()[:300]
    slug = unique_blog_slug(request.form.get('slug') or title)
    published = 1 if request.form.get('is_published') in ('on','1','true') else 0
    if not title or not content:
        flash('عنوان و متن مقاله الزامی است.','error')
        return redirect(url_for('new_blog_post'))
    try:
        image = save_upload(request.files.get('image'))
    except ValueError as e:
        flash(str(e),'error')
        return redirect(url_for('new_blog_post'))
    with db() as con:
        con.execute('INSERT INTO blog_posts(title,slug,excerpt,content,image,meta_description,is_published) VALUES(?,?,?,?,?,?,?)',
                    (title,slug,excerpt,content,image,meta,published))
    flash('مقاله با موفقیت ذخیره شد.','success')
    return redirect(url_for('admin_dashboard')+'#blog')

@app.post('/admin/blog/<int:post_id>/edit')
@admin_required
def edit_blog_post(post_id):
    title = request.form.get('title','').strip()[:180]
    content = clean_rich_html(request.form.get('content','').strip()[:50000])
    excerpt = request.form.get('excerpt','').strip()[:500]
    meta = request.form.get('meta_description','').strip()[:300]
    published = 1 if request.form.get('is_published') in ('on','1','true') else 0
    if not title or not content:
        flash('عنوان و متن مقاله الزامی است.','error')
        return redirect(url_for('blog_post_editor', post_id=post_id))
    try:
        image = save_upload(request.files.get('image'))
    except ValueError as e:
        flash(str(e),'error')
        return redirect(url_for('blog_post_editor', post_id=post_id))
    with db() as con:
        old = con.execute('SELECT id,image FROM blog_posts WHERE id=?',(post_id,)).fetchone()
        if not old: abort(404)
        slug = unique_blog_slug(request.form.get('slug') or title, exclude_id=post_id)
        if image:
            con.execute('UPDATE blog_posts SET title=?,slug=?,excerpt=?,content=?,image=?,meta_description=?,is_published=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                        (title,slug,excerpt,content,image,meta,published,post_id))
            delete_upload(old['image'])
        else:
            con.execute('UPDATE blog_posts SET title=?,slug=?,excerpt=?,content=?,meta_description=?,is_published=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                        (title,slug,excerpt,content,meta,published,post_id))
    flash('مقاله ویرایش شد.','success')
    return redirect(url_for('admin_dashboard')+'#blog')

@app.post('/admin/blog/<int:post_id>/delete')
@admin_required
def delete_blog_post(post_id):
    with db() as con:
        row = con.execute('SELECT image FROM blog_posts WHERE id=?',(post_id,)).fetchone()
        if row:
            con.execute('DELETE FROM blog_posts WHERE id=?',(post_id,))
            if row['image'] and row['image'].startswith('/static/uploads/'):
                try: (BASE / row['image'].lstrip('/')).unlink(missing_ok=True)
                except OSError: pass
    flash('مقاله حذف شد.','success')
    return redirect(url_for('admin_dashboard')+'#blog')



def _openai_response_text(payload):
    if isinstance(payload.get('output_text'), str) and payload['output_text'].strip():
        return payload['output_text'].strip()
    chunks = []
    for item in payload.get('output', []):
        if item.get('type') != 'message':
            continue
        for part in item.get('content', []):
            if part.get('type') in ('output_text', 'text') and part.get('text'):
                chunks.append(part['text'])
    return "\n".join(chunks).strip()


def _ai_plaintext_html(value):
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', str(value or '').strip()) if p.strip()]
    return ''.join('<p>' + html.escape(p).replace('\n', '<br>') + '</p>' for p in paragraphs)


def generate_ai_posts(count=1, topic='همه موضوعات', publish=False):
    api_key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('کلید OPENAI_API_KEY در Secrets سرور تنظیم نشده است.')
    try:
        count = max(1, min(50, int(count)))
    except (TypeError, ValueError):
        count = 1

    company = get_settings().get('company') or 'سنگ لاشه کاظمی'
    phone = get_settings().get('phone') or '09965470626'
    topic = str(topic or 'همه موضوعات').strip()[:120]
    model = os.environ.get('OPENAI_MODEL', 'gpt-4.1-mini').strip() or 'gpt-4.1-mini'

    system_text = (
        'تو نویسنده و ویراستار فارسی‌زبان متخصص محتوای کاربردی درباره سنگ طبیعی، سنگ لاشه، '
        'فروش مصالح و اجرای سنگ‌کاری هستی. فقط خروجی JSON معتبر بده؛ هیچ متن اضافه یا Markdown fence ننویس. '
        'اطلاعات تجاری ساختگی ممنوع است: قیمت قطعی، موجودی، آدرس، شهر، سابقه، تعداد پروژه، تضمین، '
        'تجربه مشتری و پروژه انجام‌شده را جعل نکن. هرجا قیمت یا موجودی مطرح است، بگو برای استعلام تماس بگیرند. '
        'مطالب واقع‌گرایانه، مفید، غیرتکراری و به زبان فارسی روان باشند. از ادعاهای مطلق و keyword stuffing دوری کن.'
    )
    user_text = f'''برای کسب‌وکار «{company}» با شماره تماس «{phone}» دقیقاً {count} محتوای تازه تولید کن.
موضوع محوری: {topic}
موضوعات مجاز و مرتبط: معرفی و فروش سنگ لاشه، کاربردها، تفاوت انواع سنگ، نکات انتخاب و خرید،
حمل و نگهداری، آماده‌سازی زیرکار، اصول کلی اجرای سنگ لاشه، دیوارچینی و محوطه‌سازی سنگی،
پرسش‌های متداول مشتریان و دعوت محترمانه به تماس.
ترکیب محتواها را متنوع کن: مقاله آموزشی نسبتاً کامل، پست کوتاه شبکه اجتماعی، معرفی خدمت و محتوای پرسش‌وپاسخ.
هر محتوا باید مستقل و واقعاً متفاوت باشد. از تکرار عنوان و متن پرهیز کن.
هر مورد باید این فیلدها را داشته باشد:
- title: عنوان فارسی جذاب و دقیق (حداکثر ۱۲۰ نویسه)
- excerpt: خلاصه ۱ تا ۲ جمله‌ای
- content: متن فارسی مفید، برای مقاله ۳ تا ۵ پاراگراف و برای پست کوتاه حداقل ۱ پاراگراف؛ در انتها دعوت به تماس و شماره {phone} را طبیعی بیاور.
- meta_description: توضیح سئوی طبیعی حداکثر ۱۵۰ نویسه
برای شماره تماس از همین شماره استفاده کن و هیچ شماره دیگری نساز.
خروجی دقیقاً به این شکل باشد:
{{"items":[{{"title":"...","excerpt":"...","content":"...","meta_description":"..."}}]}}
تعداد items باید دقیقاً {count} باشد.'''
    body = {
        'model': model,
        'input': [
            {'role': 'system', 'content': [{'type': 'input_text', 'text': system_text}]},
            {'role': 'user', 'content': [{'type': 'input_text', 'text': user_text}]}
        ],
        'max_output_tokens': min(20000, max(2500, count * 360))
    }
    req = urllib.request.Request(
        'https://api.openai.com/v1/responses',
        data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
        headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as response:
            result = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')[:1200]
        raise RuntimeError('خطا از سرویس OpenAI: ' + detail)
    except urllib.error.URLError as exc:
        raise RuntimeError('ارتباط با سرویس OpenAI برقرار نشد: ' + str(exc.reason))

    text_out = _openai_response_text(result)
    if text_out.startswith('```'):
        text_out = re.sub(r'^```(?:json)?\s*|\s*```$', '', text_out, flags=re.I)
    try:
        parsed = json.loads(text_out)
        items = parsed.get('items', []) if isinstance(parsed, dict) else parsed
    except (ValueError, TypeError):
        match = re.search(r'\{.*\}', text_out, flags=re.S)
        if not match:
            raise RuntimeError('پاسخ هوش مصنوعی قابل خواندن نبود؛ دوباره تلاش کن.')
        try:
            items = json.loads(match.group(0)).get('items', [])
        except (ValueError, AttributeError):
            raise RuntimeError('ساختار پاسخ هوش مصنوعی معتبر نبود.')

    if not isinstance(items, list) or not items:
        raise RuntimeError('هوش مصنوعی محتوایی برنگرداند.')
    created, seen_titles = [], set()
    for item in items[:count]:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title', '')).strip()[:180]
        excerpt = str(item.get('excerpt', '')).strip()[:500]
        content = _ai_plaintext_html(item.get('content', ''))[:50000]
        meta = str(item.get('meta_description', '')).strip()[:300]
        if not title or not content or title in seen_titles:
            continue
        seen_titles.add(title)
        slug = unique_blog_slug(title)
        with db() as con:
            cur = con.execute(
                'INSERT INTO blog_posts(title,slug,excerpt,content,meta_description,is_published) VALUES(?,?,?,?,?,?)',
                (title, slug, excerpt, content, meta, 1 if publish else 0)
            )
            post_id = cur.lastrowid
            con.execute('INSERT INTO ai_generated_posts(post_id,topic) VALUES(?,?)', (post_id, topic))
        created.append({'id': post_id, 'title': title, 'published': bool(publish)})
    if not created:
        raise RuntimeError('هیچ محتوای قابل ذخیره‌ای در پاسخ تولیدشده وجود نداشت.')
    return created


@app.post('/admin/ai/generate')
@admin_required
def admin_ai_generate():
    data = request.get_json(silent=True) or {}
    try:
        created = generate_ai_posts(count=data.get('count', 1),
                                    topic=data.get('topic', 'همه موضوعات'),
                                    publish=False)
        return jsonify({'ok': True, 'created': created, 'count': len(created),
                        'message': f'{len(created)} محتوا به‌صورت پیش‌نویس ذخیره شد.'})
    except RuntimeError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 503
    except Exception:
        app.logger.exception('AI content generation failed')
        return jsonify({'ok': False, 'error': 'خطای غیرمنتظره هنگام تولید محتوا رخ داد.'}), 500


@app.post('/admin/ai/publish')
@admin_required
def admin_ai_publish():
    with db() as con:
        rows = con.execute('''SELECT b.id FROM ai_generated_posts a
            JOIN blog_posts b ON b.id=a.post_id WHERE b.is_published=0 ORDER BY b.id''').fetchall()
        if rows:
            con.executemany('UPDATE blog_posts SET is_published=1,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                            [(r['id'],) for r in rows])
    flash(f'{len(rows)} محتوای هوش مصنوعی منتشر شد.' if rows else 'پیش‌نویس هوش مصنوعی برای انتشار وجود ندارد.',
          'success' if rows else 'error')
    return redirect(url_for('admin_dashboard') + '#ai-content')

@app.post('/admin/site-image/<field>')
@admin_required
def upload_site_image(field):
    if field not in {'about_bg_image','statement_bg_image'}: abort(404)
    try:
        image = save_upload(request.files.get('image'))
    except ValueError as e:
        flash(str(e),'error')
        return redirect(url_for('admin_dashboard')+'#settings')
    if not image:
        flash('فایل تصویر انتخاب نشده است.','error')
    else:
        with db() as con:
            con.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(field,image))
        flash('تصویر پس‌زمینه ذخیره شد.','success')
    return redirect(url_for('admin_dashboard')+'#settings')

@app.post('/admin/font')
@admin_required
def upload_font():
    f = request.files.get('font_file')
    if not f or not f.filename:
        flash('ابتدا فایل فونت را انتخاب کنید.','error')
        return redirect(url_for('admin_dashboard')+'#settings')
    ext = f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else ''
    if ext not in FONT_ALLOWED:
        flash('فرمت فونت باید WOFF2، WOFF، TTF یا OTF باشد.','error')
        return redirect(url_for('admin_dashboard')+'#settings')
    name = secrets.token_hex(12)+'.'+ext
    f.save(FONT_DIR/name)
    with db() as con:
        con.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('custom_font','/static/fonts/'+name))
    flash('فونت بارگذاری و برای سایت انتخاب شد.','success')
    return redirect(url_for('admin_dashboard')+'#settings')

@app.post('/admin/settings')
@admin_required
def save_settings():
    cleaned = H.clean_settings({k: v for k, v in request.form.items() if k != 'csrf_token'})
    if 'accent_color' in request.form and re.fullmatch(r'#[0-9a-fA-F]{6}', request.form['accent_color'].strip()):
        cleaned['accent_color'] = request.form['accent_color'].strip()
    with db() as con:
        for key, value in cleaned.items():
            con.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value)))
    flash('تنظیمات سایت ذخیره شد.','success')
    return redirect(url_for('admin_dashboard')+'#settings')

def delete_upload(url):
    if url and url.startswith('/static/uploads/'):
        try: (BASE / url.lstrip('/')).unlink(missing_ok=True)
        except OSError: pass

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
    title=request.form.get('title','').strip()[:200]; category=request.form.get('category','').strip(); description=request.form.get('description','').strip()[:3000]
    if not title or not category:
        flash('عنوان و دسته‌بندی پروژه الزامی است.','error'); return redirect(url_for('admin_dashboard')+'#projects')
    try: image=save_upload(request.files.get('image'))
    except ValueError as e:
        flash(str(e),'error'); return redirect(url_for('admin_dashboard')+'#projects')
    with db() as con:
        old=con.execute('SELECT image FROM projects WHERE id=?',(pid,)).fetchone()
        if not old: abort(404)
        if image:
            con.execute('UPDATE projects SET title=?,category=?,description=?,image=? WHERE id=?',(title,category,description,image,pid))
            delete_upload(old['image'])
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
    if len(sys.argv) > 1 and sys.argv[1] == 'reset-admin':
        import getpass
        user = input('نام کاربری مدیر [admin]: ').strip() or 'admin'
        pw = getpass.getpass('رمز جدید (حداقل ۱۲ نویسه): ')
        if len(pw) < 12: sys.exit('رمز کوتاه است.')
        with db() as con:
            con.execute('DELETE FROM admins WHERE username=?', (user,))
            con.execute('INSERT INTO admins(username,password_hash) VALUES(?,?)', (user, generate_password_hash(pw)))
        sys.exit('رمز مدیر تغییر کرد.')
    app.run(host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT', 5000)), debug=False)
