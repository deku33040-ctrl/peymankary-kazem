import os, sqlite3, secrets, io, csv, time, json, re
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_file
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import bleach

BASE = Path(__file__).resolve().parent
DB = BASE / 'kazemi.db'
UPLOAD_DIR = BASE / 'static' / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
FONT_ALLOWED = {'woff2','woff','ttf','otf'}
FONT_DIR = BASE / 'static' / 'fonts'
FONT_DIR.mkdir(parents=True, exist_ok=True)
app = Flask(__name__)
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
    except OSError as exc:
        # A random key per worker/restart invalidates every login session.
        # On read-only or multi-worker hosts, configure SECRET_KEY explicitly.
        raise RuntimeError(
            'SECRET_KEY must be set in the hosting environment when the app '
            'cannot persist .kazemi_secret_key.'
        ) from exc

app.secret_key = load_secret_key()
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
LOGIN_ATTEMPTS = {}

DEFAULTS = {
 'company':'پیمانکاری کاظمی', 'slogan':'سنگ‌کاری • نما • اجرای ساختمان',
 'heroText':'پیمانکاری کاظمی؛ همراه مطمئن شما در اجرای سنگ‌کاری، نمای ساختمان و پروژه‌های ساختمانی، از ایده تا تحویل نهایی.',
 'aboutText':'در پیمانکاری کاظمی، هر پروژه با شناخت نیاز کارفرما، انتخاب مصالح مناسب و برنامه‌ریزی دقیق آغاز می‌شود. هدف ما اجرای تمیز، اصولی و ماندگار است.',
 'quote':'اعتماد با حرف ساخته نمی‌شود؛ با کیفیت کار، ماندگار می‌شود.',
 'experience':'۱۰+', 'projectsCount':'۷۰+', 'phone':'', 'telegram':'', 'address':'',
 'seo_title':'پیمانکاری کاظمی | سنگ‌کاری و اجرای ساختمان',
 'seo_description':'اجرای تخصصی سنگ‌کاری، نمای ساختمان، بازسازی و پیمانکاری ساختمان در ایران.', 'accent_color':'#c7a46b', 'home_projects_limit':'12', 'seo_city':'', 'visual_layout':'{}', 'custom_font':'', 'about_bg_image':'', 'statement_bg_image':'', 'maker_text':'MADE BY DEKU', 'maker_url':'#'
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
        con.execute('''CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, service TEXT, message TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        con.execute('''CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)''')
        for k,v in DEFAULTS.items():
            con.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',(k,v))
        # Always ensure a known bootstrap admin exists. Environment variables
        # can override these credentials on the hosting platform.
        username = (os.environ.get('ADMIN_USERNAME') or 'admin').strip()[:80]
        password = os.environ.get('ADMIN_PASSWORD') or 'Kazemi-Change-This-2026!'
        if not username:
            username = 'admin'
        password_hash = generate_password_hash(password)
        con.execute(
            '''INSERT INTO admins(username,password_hash) VALUES(?,?)
               ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash''',
            (username, password_hash)
        )

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
    with db() as con:
        categories = con.execute('SELECT * FROM service_categories ORDER BY id').fetchall()
        projects = con.execute('SELECT * FROM projects ORDER BY is_favorite DESC,id DESC LIMIT 60').fetchall()
        pages = con.execute('SELECT title,slug FROM custom_pages WHERE is_published=1 ORDER BY id DESC').fetchall()
        home_sections = con.execute('SELECT * FROM home_sections WHERE is_visible=1 ORDER BY sort_order,id').fetchall()
        blog_posts = con.execute('SELECT id,title,slug,excerpt,image,created_at FROM blog_posts WHERE is_published=1 ORDER BY created_at DESC,id DESC LIMIT 3').fetchall()
    return render_template('index.html', settings=settings, layout=layout, categories=categories, projects=projects, pages=pages, home_sections=home_sections, blog_posts=blog_posts)

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
    return jsonify({'settings':get_settings(),'projects':projects,'categories':categories})

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
        total_projects = con.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
        total_messages = con.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
        latest_message = con.execute('SELECT MAX(created_at) FROM messages').fetchone()[0]
        categories = con.execute('SELECT * FROM service_categories ORDER BY id').fetchall()
        pages = con.execute('SELECT * FROM custom_pages ORDER BY id DESC').fetchall()
        home_sections = con.execute('SELECT * FROM home_sections ORDER BY sort_order,id').fetchall()
        blog_posts = con.execute('SELECT * FROM blog_posts ORDER BY created_at DESC,id DESC').fetchall()
    return render_template('admin_dashboard.html', settings=get_settings(), projects=projects, messages=messages, total_projects=total_projects, total_messages=total_messages, latest_message=latest_message, categories=categories, pages=pages, home_sections=home_sections, blog_posts=blog_posts)

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
    order = request.form.getlist('section_order')
    order = [x for x in order if x in allowed_sections]
    order = list(dict.fromkeys(order))
    order += [x for x in ['home','about','services','projects','statement','contact'] if x not in order]
    hidden = [x for x in request.form.getlist('hidden_sections') if x in allowed_sections]
    transition = request.form.get('transition', 'fade-up')
    if transition not in {'none','fade','fade-up','slide-left','zoom','flip','blur'}: transition = 'fade-up'
    try: duration = max(100, min(2000, int(request.form.get('duration','650'))))
    except ValueError: duration = 650
    accent = request.form.get('accent', '#c7a46b').strip()
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', accent): accent = '#c7a46b'
    try: radius = max(0, min(40, int(request.form.get('radius','14'))))
    except ValueError: radius = 14
    font = request.form.get('font', 'Tahoma').strip()
    if font not in {'Tahoma','Arial','Vazirmatn','sans-serif'}: font = 'Tahoma'
    hover = request.form.get('hover_effect','zoom')
    if hover not in {'none','zoom','lift','tilt'}: hover='zoom'
    gallery = request.form.get('gallery_layout','grid')
    if gallery not in {'grid','masonry','slider'}: gallery='grid'
    title_style = request.form.get('title_style','classic')
    if title_style not in {'classic','underline','center'}: title_style='classic'
    config = {'order':order, 'hidden':hidden, 'transition':transition, 'duration':duration, 'accent':accent, 'radius':radius, 'font':font, 'hover_effect':hover, 'gallery_layout':gallery, 'title_style':title_style}
    with db() as con:
        con.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', ('visual_layout', json.dumps(config, ensure_ascii=False)))
    flash('چیدمان و ظاهر سایت ذخیره شد.','success')
    return redirect(url_for('visual_builder'))

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

@app.post('/admin/sections/add')
@admin_required
def add_home_section():
    title=request.form.get('title','').strip()[:160]
    content=request.form.get('content','').strip()[:5000]
    if not title or not content:
        flash('عنوان و متن بخش الزامی است.','error')
    else:
        with db() as con:
            next_order=con.execute('SELECT COALESCE(MAX(sort_order),0)+1 FROM home_sections').fetchone()[0]
            con.execute('INSERT INTO home_sections(title,content,sort_order) VALUES(?,?,?)',(title,content,next_order))
        flash('بخش جدید به صفحه اصلی اضافه شد.','success')
    return redirect(url_for('admin_dashboard')+'#sections')

@app.post('/admin/sections/<int:sid>/delete')
@admin_required
def delete_home_section(sid):
    with db() as con: con.execute('DELETE FROM home_sections WHERE id=?',(sid,))
    flash('بخش صفحه اصلی حذف شد.','success')
    return redirect(url_for('admin_dashboard')+'#sections')

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
    return bleach.linkifier.Linker().linkify(cleaned)

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
        old = con.execute('SELECT id FROM blog_posts WHERE id=?',(post_id,)).fetchone()
        if not old: abort(404)
        slug = unique_blog_slug(request.form.get('slug') or title, exclude_id=post_id)
        if image:
            con.execute('UPDATE blog_posts SET title=?,slug=?,excerpt=?,content=?,image=?,meta_description=?,is_published=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                        (title,slug,excerpt,content,image,meta,published,post_id))
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
