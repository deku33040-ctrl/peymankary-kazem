#!/usr/bin/env python3
"""Reset the first admin account password without requiring werkzeug.security."""
import hashlib, secrets, sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent / 'kazemi.db'
if not DB.exists():
    raise SystemExit('kazemi.db پیدا نشد؛ این فایل را کنار app.py و دیتابیس اجرا کنید.')
salt = secrets.token_hex(8)
password = '123456'
digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
pwhash = f'pbkdf2:sha256:600000${salt}${digest}'
con = sqlite3.connect(DB)
try:
    row = con.execute('SELECT id, username FROM admins ORDER BY id LIMIT 1').fetchone()
    if row is None:
        con.execute('INSERT INTO admins(username,password_hash) VALUES(?,?)', ('admin', pwhash))
        username = 'admin'
    else:
        con.execute('UPDATE admins SET password_hash=? WHERE id=?', (pwhash, row[0]))
        username = row[1]
    con.commit()
    print(f'رمز مدیر بازنشانی شد. نام کاربری: {username} | رمز جدید: 123456')
finally:
    con.close()
