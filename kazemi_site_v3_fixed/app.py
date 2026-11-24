import os, sys, sqlite3, secrets, io, csv, time, json, re
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
        con.execute('''CREATE TABLE IF NOT EXISTS blocks (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}', sort_order INTEGER NOT NULL DEFAULT 0, is_visible INTEGER NOT NULL DEFAULT 1)''')
        # Publish an initial editorial library once; existing posts are never overwritten.
        seed_articles = [('راهنمای جامع اجرای سنگ لاشه', 'rahnamaye-ejra-sang-lashe', 'مراحل انتخاب سنگ، زیرسازی، چیدمان، نصب و بندکشی', 'دیوار باغ، نمای ویلا و محوطه', 'هماهنگی اندازه قطعات و تکیه\u200cگاه پایدار', 'پیش از اجرا نمونه چیدمان بسازید و روش مهار را مشخص کنید'), ('سنگ مالون چیست و چه تفاوتی با سنگ لاشه دارد؟', 'fargh-sang-malon-lashe', 'تفاوت فرم طبیعی، میزان تراش و کاربرد سنگ مالون و لاشه', 'دیوارچینی، نما و عناصر محوطه', 'نام تجاری به\u200cتنهایی مشخصات فنی را روشن نمی\u200cکند', 'در سفارش ضخامت، میزان تراش و نمونه محموله را ثبت کنید'), ('فروش سنگ لاشه؛ نکات مهم پیش از خرید', 'kharid-foroosh-sang-lashe', 'ارزیابی کیفیت محموله، هزینه حمل، شکستگی و مقدار سفارش', 'تأمین سنگ برای پروژه\u200cهای ساختمانی و محوطه', 'مقایسه صرف قیمت هر تن می\u200cتواند گمراه\u200cکننده باشد', 'هزینه سنگ قابل استفاده، بارگیری و حمل را یکجا مقایسه کنید'), ('سنگ ورقه\u200cای برای کف حیاط و محوطه', 'sang-varaghei-kaf-hayat', 'ویژگی\u200cهای سنگ تخت، ضخامت، زبری و روش نصب', 'حیاط، مسیر باغ و محوطه ویلا', 'لغزندگی، اختلاف ارتفاع و نشست زیرکار', 'نمونه را در حالت خیس ببینید و شیب تخلیه آب را اجرا کنید'), ('اجرای نمای ساختمان با سنگ لاشه', 'ejraye-namay-sakhteman-sang-lashe', 'طراحی نما، وزن سنگ، زیرسازی و مهار ایمن', 'نمای بیرونی ساختمان و ویلا', 'وزن زیاد و خطر جداشدن سنگ از نما', 'جزئیات مهار و ظرفیت بستر باید توسط متخصص بررسی شود'), ('محوطه\u200cسازی باغ و ویلا با سنگ طبیعی', 'mohavate-sazi-bagh-ba-sang', 'ترکیب مسیر سنگی، دیوار، لبه باغچه و آبنما', 'باغ، ویلا و فضای سبز', 'نبود طرح یکپارچه و جمع\u200cشدن آب', 'مسیر حرکت، زهکشی و هماهنگی رنگ\u200cها را از ابتدا طراحی کنید'), ('سنگ کوهی، مالون و ورقه\u200cای؛ کدام را بخریم؟', 'moghayese-sang-kohi-malon-varaghei', 'مقایسه ویژگی\u200cهای ظاهری و کاربردی انواع سنگ طبیعی', 'کف، دیوار و نما', 'تفاوت کیفیت محصولات با نام مشابه', 'نمونه واقعی، ضخامت و کاربرد نهایی را مبنای انتخاب قرار دهید'), ('اجرای دیوار باغ با سنگ مالون', 'divar-bagh-sang-malon', 'نکات پی\u200cسازی، رج\u200cبندی، درپوش و زهکشی', 'دیوار محوطه و دیوار باغ', 'اشتباه گرفتن دیوار تزئینی با دیوار حائل', 'در دیوار نگهدارنده خاک، طراحی سازه\u200cای و زهکشی ضروری است'), ('سنگ\u200cکاری آبنما و آبشار سنگی', 'sang-kari-abnama-abshar', 'انتخاب سنگ، آب\u200cبندی، پمپ و مسیر گردش آب', 'آبنما و آبشار محوطه', 'نشتی، رسوب و دسترسی دشوار به تجهیزات', 'آب\u200cبندی را مستقل از سنگ\u200cکاری آزمایش کنید'), ('سنگ قلوه\u200cای و رودخانه\u200cای در طراحی محوطه', 'sang-gholvei-rudkhane-mohavate', 'کاربرد قلوه\u200cسنگ در نوارهای تزئینی و اطراف آبنما', 'محوطه، باغچه و حاشیه آبنما', 'حرکت سنگ\u200cهای گرد در مسیرهای پرتردد', 'برای مسیر عبور، بستر و تثبیت متناسب طراحی کنید'), ('کف\u200cسازی سنگی حیاط؛ شیب\u200cبندی و زهکشی', 'kaf-sazi-sangi-hayat', 'زیرسازی، تراکم، شیب و جلوگیری از لق\u200cشدن', 'حیاط، پارکینگ و مسیر پیاده', 'تجمع آب و نشست قطعات', 'بارگذاری و شیب تخلیه را پیش از نصب تعیین کنید'), ('قیمت اجرای سنگ لاشه چگونه محاسبه می\u200cشود؟', 'ghimat-ejra-sang-lashe', 'عوامل مؤثر بر مصالح، حمل، زیرسازی و دستمزد', 'برآورد پروژه سنگ\u200cکاری', 'اعلام قیمت بدون اندازه\u200cگیری و شناخت زیرکار', 'شرح خدمات و واحد اندازه\u200cگیری را در پیش\u200cفاکتور بنویسید'), ('نمای ویلایی با سنگ طبیعی؛ ترکیب با چوب و آجر', 'namaye-vilayi-sang-tabiyee', 'ایده\u200cهای ترکیب سنگ با چوب، آجر و بتن', 'نمای ویلا و ورودی ساختمان', 'ناهماهنگی رنگ و اتصال نامناسب متریال\u200cها', 'پیش از اجرا یک نمونه در مقیاس واقعی بسازید'), ('اجرای پله و مسیر سنگی در باغ', 'pelle-masiri-sangi-bagh', 'ابعاد پله، پاگرد، اصطکاک و تخلیه آب', 'مسیرهای شیب\u200cدار و باغ', 'پله\u200cهای ناهم\u200cاندازه و سطح لغزنده', 'ارتفاع و عمق پله\u200cها را یکنواخت و ایمن اجرا کنید'), ('بندکشی سنگ لاشه؛ رنگ ملات و اجرای تمیز', 'bandkeshi-sang-lashe', 'انتخاب رنگ بند، آماده\u200cسازی درز و پاک\u200cکردن ملات', 'نما و دیوار سنگی', 'ترک، حفره و لکه ملات روی سنگ', 'ابتدا نمونه بندکشی را روی چند قطعه آزمایش کنید'), ('نگهداری و شست\u200cوشوی نمای سنگی', 'negahdari-shosteshooye-namay-sangi', 'تمیزکاری، شوره\u200cزدگی و پیشگیری از نفوذ رطوبت', 'نمای سنگی و دیوار محوطه', 'استفاده از شوینده اسیدی یا پاک\u200cکردن بدون رفع علت', 'منبع رطوبت را پیدا کنید و شوینده را ابتدا روی نقطه پنهان بیازمایید'), ('انتخاب سنگ برای آب\u200cوهوای سرد و پرباران', 'entekhab-sang-sarma-barani', 'جذب آب، یخ\u200cزدگی و جزئیات تخلیه آب', 'فضاهای بیرونی در اقلیم سرد یا مرطوب', 'آب محبوس در بندها و پشت سنگ', 'مشخصات فنی و سازگاری ملات و سنگ را بررسی کنید'), ('سنگ کوبیک در محوطه\u200cسازی و کف\u200cسازی', 'sang-koobik-kaf-sazi', 'الگوی چیدمان، ضخامت و مهار قطعات', 'مسیر، حیاط و فضاهای پرتردد', 'حرکت قطعات و نشست بستر', 'زیرسازی و مهار لبه\u200cها را بر اساس بار طراحی کنید'), ('چطور مقدار سنگ موردنیاز پروژه را برآورد کنیم؟', 'baravord-meghdar-sang-proje', 'اندازه\u200cگیری سطوح، محاسبه پرت و واحد خرید', 'خرید سنگ برای پروژه', 'اشتباه گرفتن تن، مترمربع و مترمکعب', 'هر سطح و نوع سنگ را جداگانه متره کنید'), ('اشتباهات رایج در اجرای سنگ لاشه', 'eshtebahat-ejra-sang-lashe', 'خطاهای انتخاب، زیرسازی، نصب و کنترل کیفیت', 'تمام پروژه\u200cهای سنگ لاشه', 'پوشاندن ایرادهای زیرکار با سنگ\u200cکاری نهایی', 'مراحل پنهان را پیش از پوشانده\u200cشدن کنترل و مستندسازی کنید')]
        for title, slug, focus, usage, risk, advice in seed_articles:
            if con.execute('SELECT 1 FROM blog_posts WHERE slug=?', (slug,)).fetchone():
                continue
            excerpt = f'{focus}؛ نکات انتخاب و اجرای درست برای {usage}.'
            content = f'''
<h2>مقدمه</h2>
<p>{title} از موضوعات مهم در انتخاب و اجرای سنگ طبیعی است. نتیجه ماندگار تنها به ظاهر سنگ وابسته نیست؛ شناخت محل مصرف، کیفیت مصالح، آماده‌سازی بستر و اجرای درست در کنار هم اهمیت دارند. در این راهنما نکته‌هایی را مرور می‌کنیم که پیش از خرید یا شروع کار باید در نظر گرفته شوند تا تصمیم‌گیری بر اساس نیاز واقعی پروژه باشد.</p>
<h2>انتخاب مصالح و بررسی شرایط پروژه</h2>
<p>{focus}. این موضوع برای کاربردهایی مانند {usage} اهمیت ویژه‌ای دارد. پیش از سفارش، نمونه واقعی سنگ را از نظر رنگ، بافت، ضخامت، سلامت لبه‌ها و یکنواختی بررسی کنید. شرایط اقلیمی، میزان رفت‌وآمد، تماس با آب و بار وارد بر سطح نیز باید در انتخاب لحاظ شود. نام تجاری یا عکس اینترنتی به‌تنهایی مشخصات فنی یک محموله را اثبات نمی‌کند؛ از فروشنده اطلاعات دقیق همان محصول را بخواهید.</p>
<h2>نکات اجرایی و خطاهای قابل پیشگیری</h2>
<p>در زمان اجرا، بستر باید متناسب با نوع کار آماده و پایدار شود. تراز، شاقول، شیب‌بندی و مسیر خروج آب را پیش از نصب مشخص کنید. قطعات باید به شکلی چیده شوند که تکیه‌گاه کافی داشته باشند و بندها بدون حفره و با نظم قابل قبول تکمیل شوند. یکی از ریسک‌های مهم این کار، {risk} است؛ بنابراین مراحل زیرکار و جزئیات اتصال را پیش از پوشانده‌شدن کنترل کنید. در نماهای مرتفع، دیوارهای حائل و سطوحی که بار قابل توجه دارند، بررسی فنی و اجرای مهار متناسب ضروری است.</p>
<h2>کنترل کیفیت و نگهداری</h2>
<p>{advice}. در پایان کار، سطح از نظر لق‌شدن، اختلاف ارتفاع، ترک، بندهای ناقص و مسیر تخلیه آب بررسی شود. برای نظافت نیز از مواد شیمیایی ناشناخته یا ابزار خشن استفاده نکنید؛ روش تمیزکاری باید با جنس و پرداخت سنگ سازگار باشد. ثبت عکس از مراحل اجرا و نگهداری مشخصات سنگ مصرفی، در تعمیرات آینده کمک‌کننده است.</p>
<h2>پیش از سفارش چه اطلاعاتی آماده کنیم؟</h2>
<p>ابعاد تقریبی، عکس واضح از محل، نوع کاربری، شهر و شرایط دسترسی کارگاه را آماده کنید. سپس درباره نوع سنگ، مقدار و واحد فروش، هزینه حمل، زیرسازی، روش نصب، بندکشی، زمان‌بندی و موارد خارج از تعهد سؤال کنید. برآورد دقیق قیمت بدون اندازه‌گیری و شناخت شرایط محل ممکن نیست؛ قیمت روز را هنگام سفارش از فروشنده و مجری استعلام کنید.</p>
<p><strong>پیمانکاری کاظمی</strong> برای بررسی نیاز پروژه و انتخاب روش مناسب سنگ‌کاری، آماده دریافت توضیحات و تصاویر محل اجراست.</p>
'''
            meta = f'{title}؛ راهنمای انتخاب مصالح، نکات اجرا و کنترل کیفیت برای {usage}.'
            con.execute('INSERT INTO blog_posts(title,slug,excerpt,content,image,meta_description,is_published) VALUES(?,?,?,?,?,?,1)',
                        (title, slug, excerpt, content, '', meta[:160]))

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
    return render_template('admin_dashboard.html', settings=get_settings(), projects=projects, messages=messages, total_projects=total_projects, total_messages=total_messages, latest_message=latest_message, categories=categories, pages=pages, blog_posts=blog_posts)

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
