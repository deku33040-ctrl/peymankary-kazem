"""توابع خالص (بدون وابستگی به Flask): لینک‌های تماس، تاریخ شمسی و اسکیمای بلوک‌های صفحه‌ساز."""
import re
from urllib.parse import urlparse

_FA = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
_PERSIAN_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
UPLOAD_PREFIX = '/static/uploads/'


def digits(value):
    return re.sub(r'\D', '', str(value or '').translate(_FA))


def _host(url):
    try:
        return (urlparse(url).hostname or '').lower().removeprefix('www.')
    except ValueError:
        return ''


def safe_url(value, allow_relative=True):
    """فقط آدرس‌های امن؛ جلوی javascript: و آدرس‌های مشابه را می‌گیرد."""
    v = str(value or '').strip()[:500]
    if not v or re.search(r'[\s<>"\']', v):
        return ''
    if v.startswith('//'):
        return ''
    if allow_relative and (v[0] in '#/'):
        return v
    if v.startswith(('https://', 'http://', 'tel:', 'mailto:')):
        return v
    return ''


def normalize_number(raw, country_code=''):
    """شماره را به قالب بین‌المللی (فقط ارقام) تبدیل می‌کند. ارقام فارسی هم پذیرفته می‌شود."""
    raw = str(raw or '').translate(_FA).strip()
    d, cc = digits(raw), digits(country_code)
    if not d:
        return ''
    if raw.startswith('+'):
        return d
    if d.startswith('00'):
        return d[2:]
    if cc and d.startswith('0'):
        return cc + d[1:]
    return d


def _handle(raw, hosts):
    """نام کاربری یا آدرس کامل شبکه اجتماعی -> (نام کاربری | '')."""
    raw = str(raw or '').strip()
    if not raw:
        return ''
    if re.match(r'^[\w.-]+\.\w+/', raw) and not raw.startswith('http'):
        raw = 'https://' + raw
    if raw.startswith(('http://', 'https://')):
        if _host(raw) not in hosts:
            return ''
        path = urlparse(raw).path.strip('/').split('/')[0]
        return path if re.fullmatch(r'\+?[\w.]{3,64}', path) else ''
    raw = raw.lstrip('@')
    return raw if re.fullmatch(r'[A-Za-z][\w.]{2,63}', raw) else ''


def contact_links(s):
    """از تنظیمات، لینک‌های آماده و امن تماس را می‌سازد (هر مقدار خالی = موجود نیست)."""
    cc = s.get('country_code', '')
    phone = normalize_number(s.get('phone'), cc)
    out = {'tel': '+' + phone if phone else '', 'whatsapp': '', 'telegram': '', 'instagram': '', 'email': ''}
    out['tel_href'] = 'tel:' + out['tel'] if phone else ''

    wa_raw = str(s.get('whatsapp') or '').strip()
    # Prefer the native WhatsApp URI so a phone with WhatsApp installed opens the app.
    # If the setting contains a wa.me URL, extract its phone number before building the URI.
    if wa_raw.startswith(('https://wa.me/', 'https://api.whatsapp.com/send')):
        m = re.search(r'(?:wa\.me/|phone=)([+\d۰-۹٠-٩]+)', wa_raw)
        n = normalize_number(m.group(1), cc) if m else ''
    else:
        n = normalize_number(wa_raw, cc) or phone
    if n:
        out['whatsapp'] = 'whatsapp://send?phone=' + n

    tg_raw = str(s.get('telegram') or '').strip()
    user = _handle(tg_raw, {'t.me', 'telegram.me'})
    if user:
        out['telegram'] = 'https://t.me/' + user
    elif re.fullmatch(r'\+?[\d۰-۹٠-٩\s-]{7,20}', tg_raw):
        out['telegram'] = 'https://t.me/+' + normalize_number(tg_raw, cc)

    ig = _handle(s.get('instagram'), {'instagram.com', 'instagr.am'})
    if ig:
        out['instagram'] = 'https://instagram.com/' + ig

    mail = str(s.get('email') or '').strip()
    if re.fullmatch(r'[^@\s<>"\']+@[^@\s<>"\']+\.[^@\s<>"\']+', mail):
        out['email'] = 'mailto:' + mail
    return out


def jalali(value):
    """'2026-11-23 09:40:00' -> '۲ آذر ۱۴۰۵'. در صورت خطا همان مقدار برمی‌گردد."""
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', str(value or ''))
    if not m:
        return str(value or '')
    gy, gm, gd = map(int, m.groups())
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    names = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']
    return f'{jd} {names[jm - 1]} {jy}'.translate(_PERSIAN_DIGITS)


# ---------------------------------------------------------------- اسکیمای بلوک‌ها
def F(key, label, kind='text', default='', **kw):
    return dict(key=key, label=label, kind=kind, default=default, **kw)

BG = [['none', 'بدون پس‌زمینه'], ['dark', 'تیره'], ['light', 'روشن'], ['gold', 'طلایی']]
SECTION_HINT = 'با گذاشتن *ستاره* دور کلمه، آن کلمه برجسته می‌شود.'

BLOCK_TYPES = {
    'hero': dict(label='بنر اصلی', icon='★', builtin=True,
        fields=[F('eyebrow', 'برچسب بالای عنوان', default='تخصص، دقت، ماندگاری'),
                F('title', 'عنوان اصلی', 'textarea', 'سنگ را با هنر\nو سازه را با *اعتماد* بسازید.', hint=SECTION_HINT),
                F('btn1_text', 'متن دکمه اول', default='مشاهده نمونه‌کارها'), F('btn1_link', 'لینک دکمه اول', 'url', '#projects'),
                F('btn2_text', 'متن دکمه دوم', default='درخواست مشاوره'), F('btn2_link', 'لینک دکمه دوم', 'url', '#contact'),
                F('art_slogan', 'شعار روی تصویر', default='کیفیت در جزئیات است'), F('art_text', 'نوشته کوچک روی تصویر', default='KAZEMI / CONSTRUCTION')],
        settings=[F('heroText', 'متن معرفی', 'textarea'), F('experience', 'سال تجربه'), F('projectsCount', 'تعداد پروژه اجراشده')]),
    'about': dict(label='درباره ما', icon='ℹ', builtin=True,
        fields=[F('label', 'برچسب بخش', default='درباره پیمانکاری کاظمی'),
                F('title', 'عنوان', 'textarea', 'ساختن فقط اجرا نیست؛\n*تعهد به نتیجه است.*', hint=SECTION_HINT),
                F('link_text', 'متن لینک پایین', default='برای شروع همکاری با ما تماس بگیرید')],
        settings=[F('aboutText', 'متن درباره ما', 'textarea'), F('about_bg_image', 'تصویر پس‌زمینه', 'image')]),
    'services': dict(label='خدمات', icon='▧', builtin=True,
        fields=[F('label', 'برچسب بخش', default='خدمات ما'), F('title', 'عنوان', 'textarea', 'تخصص‌هایی برای *ساخت بهتر*', hint=SECTION_HINT),
                F('subtitle', 'توضیح', 'textarea', 'خدمات اجرایی با توجه به کیفیت مصالح، دقت نصب و نیاز واقعی هر پروژه.')],
        settings=[]),
    'projects': dict(label='نمونه‌کارها', icon='▦', builtin=True,
        fields=[F('label', 'برچسب بخش', default='پروژه‌ها'), F('title', 'عنوان', 'textarea', 'نتیجه کار، *معرف ماست*', hint=SECTION_HINT),
                F('subtitle', 'توضیح', 'textarea', 'نمونه‌کارهای واقعی و جزئیات پروژه‌های اجراشده را مشاهده کنید.')],
        settings=[F('home_projects_limit', 'تعداد نمونه‌کار در صفحه اصلی', 'number')]),
    'blog': dict(label='مجله / وبلاگ', icon='✎', builtin=True,
        fields=[F('label', 'برچسب بخش', default='دانش و تجربه'), F('title', 'عنوان', 'textarea', 'مجله *کاظمی*', hint=SECTION_HINT),
                F('subtitle', 'توضیح', 'textarea', 'راهنماها، تجربه‌های اجرایی و نکات کاربردی درباره سنگ‌کاری و ساختمان.')],
        settings=[]),
    'statement': dict(label='جمله شاخص', icon='❝', builtin=True, fields=[],
        settings=[F('quote', 'جمله', 'textarea'), F('statement_bg_image', 'تصویر پس‌زمینه', 'image')]),
    'contact': dict(label='تماس و فرم', icon='✆', builtin=True,
        fields=[F('label', 'برچسب بخش', default='تماس و مشاوره'), F('title', 'عنوان', 'textarea', 'پروژه‌تان را\n*با ما شروع کنید.*', hint=SECTION_HINT),
                F('subtitle', 'توضیح', 'textarea', 'برای دریافت مشاوره، برآورد اولیه یا هماهنگی بازدید از پروژه با ما در تماس باشید.'),
                F('form_title', 'عنوان فرم', default='درخواست مشاوره')],
        settings=[]),
    'text': dict(label='متن', icon='¶',
        fields=[F('title', 'عنوان', default='عنوان بخش'), F('body', 'متن', 'textarea', 'متن خود را اینجا بنویسید.'),
                F('align', 'چینش', 'select', 'right', options=[['right', 'راست'], ['center', 'وسط']]), F('bg', 'پس‌زمینه', 'select', 'none', options=BG)]),
    'image': dict(label='تصویر', icon='🖼',
        fields=[F('image', 'تصویر', 'image'), F('caption', 'توضیح زیر تصویر'),
                F('size', 'اندازه', 'select', 'wide', options=[['full', 'تمام‌عرض'], ['wide', 'بزرگ'], ['narrow', 'کوچک']])]),
    'cta': dict(label='دکمه / فراخوان', icon='➜',
        fields=[F('title', 'عنوان', default='برای مشاوره رایگان تماس بگیرید'), F('text', 'متن', 'textarea'),
                F('button_text', 'متن دکمه', default='تماس با ما'), F('button_link', 'لینک دکمه', 'url', '#contact'),
                F('bg', 'پس‌زمینه', 'select', 'gold', options=BG)]),
    'stats': dict(label='آمار و اعداد', icon='№',
        fields=[F('items', 'هر خط: عدد|عنوان', 'textarea', '۱۰+|سال تجربه\n۷۰+|پروژه اجراشده\n۱۰۰٪|تعهد به کیفیت'),
                F('bg', 'پس‌زمینه', 'select', 'dark', options=BG)]),
    'faq': dict(label='سوالات متداول', icon='?',
        fields=[F('title', 'عنوان', default='سوالات متداول'), F('items', 'هر خط: سوال|پاسخ', 'textarea', 'هزینه اجرا چگونه محاسبه می‌شود؟|بر اساس متراژ، نوع سنگ و شرایط پروژه برآورد می‌شود.'),
                F('bg', 'پس‌زمینه', 'select', 'light', options=BG)]),
    'spacer': dict(label='فاصله خالی', icon='↕', fields=[F('height', 'ارتفاع (پیکسل)', 'number', 60)]),
}
DEFAULT_ORDER = ['hero', 'about', 'services', 'projects', 'blog', 'statement', 'contact']

SETTING_FIELDS = {  # کلید -> (نوع، حداکثر طول)
    'company': ('text', 120), 'slogan': ('text', 200), 'logo_letter': ('text', 2), 'header_cta_text': ('text', 40),
    'phone': ('text', 40), 'whatsapp': ('text', 200), 'telegram': ('text', 200), 'instagram': ('text', 200),
    'email': ('text', 120), 'country_code': ('text', 6), 'address': ('text', 300), 'footer_text': ('text', 300),
    'heroText': ('textarea', 600), 'aboutText': ('textarea', 1500), 'quote': ('textarea', 400),
    'experience': ('text', 20), 'projectsCount': ('text', 20), 'home_projects_limit': ('number', 60),
    'about_bg_image': ('image', 300), 'statement_bg_image': ('image', 300),
    'seo_title': ('text', 160), 'seo_description': ('textarea', 300), 'seo_city': ('text', 80),
    'maker_text': ('text', 80), 'maker_url': ('url', 300), 'float_enabled': ('flag', 1),
}

APPEARANCE = dict(
    transition=('none', 'fade', 'fade-up', 'slide-left', 'zoom', 'flip', 'blur'),
    hover_effect=('none', 'zoom', 'lift', 'tilt'),
    gallery_layout=('grid', 'masonry', 'slider'),
    title_style=('classic', 'underline', 'center'),
    font=('Tahoma', 'Arial', 'Vazirmatn', 'sans-serif'),
)
APPEARANCE_DEFAULT = dict(transition='fade-up', hover_effect='zoom', gallery_layout='grid', title_style='classic', font='Tahoma', accent='#c7a46b', radius=14, duration=650)


def _clean_value(kind, value, maxlen=4000, default=''):
    if kind in ('text', 'textarea'):
        v = str(value if value is not None else default)
        v = v.replace('\r', '')
        return (v if kind == 'textarea' else v.replace('\n', ' ')).strip()[:maxlen if maxlen != 4000 else (200 if kind == 'text' else 4000)]
    if kind == 'url':
        return safe_url(value)
    if kind == 'image':
        v = str(value or '')
        return v if v.startswith(UPLOAD_PREFIX) and not re.search(r'[\s"\'()<>]', v) else ''
    if kind == 'number':
        try:
            return max(0, min(int(value), 600 if maxlen == 4000 else maxlen))
        except (TypeError, ValueError):
            return int(default or 0)
    if kind == 'flag':
        return '1' if str(value) in ('1', 'true', 'True', 'on') else '0'
    return ''


def fill_defaults(btype, data):
    spec = BLOCK_TYPES[btype]
    data = data if isinstance(data, dict) else {}
    return {f['key']: data.get(f['key'], f['default']) for f in spec['fields']}


def clean_block(btype, data):
    spec = BLOCK_TYPES[btype]
    data = data if isinstance(data, dict) else {}
    out = {}
    for f in spec['fields']:
        v = data.get(f['key'], f['default'])
        if f['kind'] == 'select':
            out[f['key']] = v if v in [o[0] for o in f['options']] else f['default']
        else:
            out[f['key']] = _clean_value(f['kind'], v, 4000, f['default'])
    return out


def clean_blocks(items):
    """لیست بلوک‌های ارسالی از صفحه‌ساز؛ بخش‌های اصلی فقط یک بار مجازند."""
    out, seen = [], set()
    for it in (items if isinstance(items, list) else [])[:80]:
        if not isinstance(it, dict) or it.get('type') not in BLOCK_TYPES:
            continue
        t = it['type']
        if BLOCK_TYPES[t].get('builtin'):
            if t in seen:
                continue
            seen.add(t)
        out.append({'type': t, 'visible': bool(it.get('visible', True)), 'data': clean_block(t, it.get('data'))})
    return out


def clean_settings(values):
    out = {}
    for k, v in (values or {}).items():
        if k in SETTING_FIELDS:
            kind, ln = SETTING_FIELDS[k]
            out[k] = _clean_value(kind, v, ln, '')
            if kind == 'number' and out[k] < 3:
                out[k] = 12
    return out


def clean_appearance(values):
    v = values if isinstance(values, dict) else {}
    out = {k: (v.get(k) if v.get(k) in opts else APPEARANCE_DEFAULT[k]) for k, opts in APPEARANCE.items()}
    acc = str(v.get('accent', ''))
    out['accent'] = acc if re.fullmatch(r'#[0-9a-fA-F]{6}', acc) else APPEARANCE_DEFAULT['accent']
    for k, lo, hi in (('radius', 0, 40), ('duration', 100, 2000)):
        try:
            out[k] = max(lo, min(hi, int(v.get(k, APPEARANCE_DEFAULT[k]))))
        except (TypeError, ValueError):
            out[k] = APPEARANCE_DEFAULT[k]
    return out


def public_schema():
    fields = {k: {'label': v['label'], 'icon': v['icon'], 'builtin': bool(v.get('builtin')), 'fields': v['fields'], 'settings': v['settings'] if 'settings' in v else []}
              for k, v in BLOCK_TYPES.items()}
    return {'types': fields, 'appearance': {k: list(o) for k, o in APPEARANCE.items()}}
