"""تست‌های دودی: python -m unittest -v   (نیاز به pip install -r requirements.txt)"""
import os, re, tempfile, unittest, json

os.environ['KAZEMI_DB'] = os.path.join(tempfile.mkdtemp(), 'test.db')
os.environ['ADMIN_PASSWORD'] = 'test-password-123456'
import app as A, helpers as H


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        A.app.config['TESTING'] = True

    def login(self):
        c = A.app.test_client()
        tok = re.search(r'name="csrf_token" value="([^"]+)"', c.get('/admin/login').get_data(True)).group(1)
        r = c.post('/admin/login', data={'username': 'admin', 'password': 'test-password-123456', 'csrf_token': tok})
        self.assertEqual(r.status_code, 302)
        with c.session_transaction() as s:
            self.tok = s['csrf_token']
        return c

    def save(self, c, **payload):
        return c.post('/admin/builder/save', json=payload, headers={'X-CSRF-Token': self.tok})


class Helpers(unittest.TestCase):
    def test_jalali(self):
        self.assertEqual(H.jalali('2026-11-23 09:40:00'), '۲ آذر ۱۴۰۵')

    def test_links(self):
        s = {'phone': '۰۷۰۰ ۱۲۳ ۴۵۶', 'country_code': '93', 'telegram': '@kazemi_co', 'instagram': 'instagram.com/kz.stone'}
        L = H.contact_links(s)
        self.assertEqual(L['tel_href'], 'tel:+93700123456')
        self.assertEqual(L['whatsapp'], 'https://wa.me/93700123456')
        self.assertEqual(L['telegram'], 'https://t.me/kazemi_co')
        self.assertEqual(L['instagram'], 'https://instagram.com/kz.stone')

    def test_links_reject_unsafe(self):
        L = H.contact_links({'phone': '', 'telegram': 'javascript:alert(1)', 'whatsapp': 'https://evil.com/x', 'instagram': 'https://evil.com/a'})
        self.assertEqual((L['telegram'], L['whatsapp'], L['instagram']), ('', '', ''))
        self.assertEqual(H.safe_url('javascript:alert(1)'), '')
        self.assertEqual(H.safe_url('//evil.com'), '')


class Site(Base):
    def setUp(self):  # هر تست با چیدمان پیش‌فرض شروع می‌شود
        with A.db() as con:
            con.execute('DELETE FROM blocks'); A.seed_blocks(con)

    def test_public_pages_render(self):
        c = A.app.test_client()
        for url in ['/', '/blog', '/sitemap.xml', '/robots.txt', '/api/public', '/admin/login']:
            self.assertEqual(c.get(url).status_code, 200, url)
        html = c.get('/').get_data(True)
        for sid in ['id="home"', 'id="about"', 'id="services"', 'id="projects"', 'id="blog"', 'id="statement"', 'id="contact"']:
            self.assertIn(sid, html)
        self.assertEqual(c.get('/service/nope').status_code, 404)

    def test_inner_pages_render(self):
        with A.db() as con:
            con.execute("INSERT INTO projects(title,category,description) VALUES('پروژه <b>x</b>','سنگ لاشه','توضیح')")
            con.execute("INSERT INTO custom_pages(title,slug,content) VALUES('درباره','about-us','متن')")
            con.execute("INSERT INTO blog_posts(title,slug,excerpt,content) VALUES('مقاله','post-1','خلاصه','<p>متن</p>')")
            pid = con.execute('SELECT MAX(id) FROM projects').fetchone()[0]
        c = A.app.test_client()
        for url in [f'/project/{pid}', '/service/sang-lashe', '/page/about-us', '/blog/post-1', '/blog']:
            r = c.get(url); self.assertEqual(r.status_code, 200, url)
        self.assertNotIn('<b>x</b>', c.get(f'/project/{pid}').get_data(True))
        self.assertIn('/page/about-us', c.get('/').get_data(True))   # صفحه جدید در منو

    def test_legacy_migration(self):
        with A.db() as con:
            con.execute('DELETE FROM blocks'); con.execute('DELETE FROM home_sections')
            con.execute("INSERT INTO home_sections(title,content,is_visible,sort_order) VALUES('بخش قدیمی','محتوا',1,1)")
            con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('visual_layout',?)",
                        (json.dumps({'order': ['contact', 'home', 'about', 'services', 'projects', 'statement'], 'hidden': ['about']}),))
            A.seed_blocks(con)
            rows = [(r['type'], r['is_visible']) for r in con.execute('SELECT * FROM blocks ORDER BY sort_order')]
            con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('visual_layout','{}')")
        types = [t for t, _ in rows]
        self.assertEqual(types[0], 'contact')
        self.assertEqual(types.index('blog'), types.index('projects') + 1)
        self.assertLess(types.index('text'), types.index('statement'))
        self.assertEqual(dict(rows)['about'], 0)

    def test_admin_requires_login(self):
        c = A.app.test_client()
        self.assertEqual(c.get('/admin/builder').status_code, 302)
        self.assertEqual(c.post('/admin/builder/save', json={}).status_code, 302)

    def test_builder_requires_csrf(self):
        c = self.login()
        self.assertEqual(c.post('/admin/builder/save', json={'blocks': []}).status_code, 400)

    def test_builder_roundtrip_and_contact_settings(self):
        c = self.login()
        self.assertEqual(c.get('/admin/builder').status_code, 200)
        r = self.save(c, blocks=[
            {'type': 'contact', 'visible': True, 'data': {}},
            {'type': 'text', 'visible': True, 'data': {'title': '<script>alert(1)</script>', 'body': 'سلام\nدنیا', 'bg': 'evil'}},
            {'type': 'hero', 'visible': True, 'data': {}}, {'type': 'hero', 'visible': True, 'data': {}},
            {'type': 'hack', 'visible': True, 'data': {}}, {'type': 'spacer', 'visible': False, 'data': {'height': 80}}],
            settings={'phone': '۰۷۰۰۱۲۳۴۵۶', 'country_code': '93', 'telegram': '@my_tg', 'whatsapp': '', 'evil_key': 'x'},
            appearance={'accent': '#112233', 'font': 'Comic', 'radius': 999})
        self.assertEqual(r.get_json(), {'ok': True, 'blocks': 4})   # hero تکراری و نوع ناشناخته حذف شد
        html = c.get('/').get_data(True)
        self.assertLess(html.index('id="contact"'), html.index('id="home"'))      # ترتیب جدید اعمال شد
        self.assertNotIn('<script>alert(1)</script>', html)                        # XSS escape شد
        self.assertIn('class="section custom-block bg-none', html)                 # مقدار نامعتبر select به پیش‌فرض برگشت
        self.assertIn('tel:+93700123456', html)
        self.assertIn('https://wa.me/93700123456', html)
        self.assertIn('https://t.me/my_tg', html)
        self.assertIn('--gold:#112233', html); self.assertIn('--radius:40px', html)
        self.assertNotIn('Comic', html)
        self.assertNotIn('custom-spacer', html)                                    # بلوک مخفی نمایش داده نمی‌شود
        self.assertNotIn('evil_key', json.dumps(A.get_settings.__globals__['DEFAULTS']))

    def test_phone_change_updates_every_link(self):
        c = self.login()
        self.save(c, blocks=[{'type': 'contact', 'visible': True, 'data': {}}], settings={'phone': '+989121234567', 'whatsapp': '', 'telegram': '', 'country_code': ''}, appearance={})
        html = c.get('/blog').get_data(True)  # هدر/فوتر/دکمه شناور در همه صفحات
        self.assertGreaterEqual(html.count('tel:+989121234567'), 2)
        self.assertIn('wa.me/989121234567', html)

    def test_links_preview_endpoint(self):
        c = self.login()
        r = c.post('/admin/builder/links', json={'settings': {'phone': '0700111222', 'country_code': '93'}}, headers={'X-CSRF-Token': self.tok})
        self.assertEqual(r.get_json()['tel_href'], 'tel:+93700111222')

    def test_contact_form_honeypot_and_rate_limit(self):
        c = A.app.test_client()
        A.CONTACT_HITS.clear()
        self.assertEqual(c.post('/api/contact', json={'name': 'x', 'phone': '1'}).status_code, 200)
        before = len(A.db().execute('SELECT * FROM messages').fetchall())
        c.post('/api/contact', json={'name': 'bot', 'phone': '1', 'website': 'spam.com'})
        self.assertEqual(len(A.db().execute('SELECT * FROM messages').fetchall()), before)   # honeypot ذخیره نکرد
        self.assertEqual(c.post('/api/contact', json={'name': '', 'phone': ''}).status_code, 400)
        for _ in range(6): last = c.post('/api/contact', json={'name': 'a', 'phone': '2'})
        self.assertEqual(last.status_code, 429)

    def test_edit_project_validation(self):
        c = self.login()
        with A.db() as con:
            con.execute("INSERT INTO projects(title,category) VALUES('t','c')")
            pid = con.execute('SELECT MAX(id) FROM projects').fetchone()[0]
        r = c.post(f'/admin/projects/{pid}/edit', data={'title': '', 'category': 'c', 'csrf_token': self.tok})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(A.db().execute('SELECT title FROM projects WHERE id=?', (pid,)).fetchone()[0], 't')

    def test_dashboard_and_security_headers(self):
        c = self.login()
        r = c.get('/admin')
        self.assertEqual(r.status_code, 200); self.assertEqual(r.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn('whatsapp', r.get_data(True))


if __name__ == '__main__':
    unittest.main()
