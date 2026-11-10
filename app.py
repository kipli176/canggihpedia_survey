"""Canggihpedia Research: aplikasi wawancara kebutuhan belajar digital (Flask + SQLite)."""
import csv
import io
import json
import os
import re
import secrets
import sqlite3
import time
from collections import Counter, deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from threading import Lock
from typing import Any, Callable, Deque, Dict, Iterator, List, Optional, Tuple, TypeVar

from flask import (Flask, Response, abort, flash, redirect, render_template_string,
                   request, session, url_for)
from markupsafe import escape
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

F = TypeVar('F', bound=Callable[..., Any])

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get('DATABASE_PATH') or os.path.join(
    os.environ.get('DATA_DIR') or os.path.join(BASE, 'data'), 'survey.sqlite3')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
if os.environ.get('APP_ENV') == 'production' and not os.environ.get('SECRET_KEY'):
    raise RuntimeError('SECRET_KEY wajib di production')
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', '0') == '1',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=100_000,
)

VERSION = 3
USERNAME_RE = re.compile(r'[a-z0-9._-]{3,40}')
USERNAME_MSG = 'Username 3-40 karakter: huruf kecil, angka, titik, garis bawah, atau strip.'
PASSWORD_MAX = 256

# ---------------------------------------------------------------- questionnaire
COMMON: List[Tuple[str, str, str, List[str]]] = [
    ('device', 'Perangkat yang tersedia untuk belajar', 'select', ['HP/tablet', 'Komputer/laptop', 'Keduanya', 'Tidak ada', 'Tidak tahu']),
    ('experience', 'Seberapa sering menggunakan komputer/laptop dalam sebulan terakhir?', 'select', ['Tidak pernah', '1–2 kali', '3–7 kali', '8 kali atau lebih', 'Tidak tahu']),
    ('skill', 'Kemampuan komputer saat ini', 'select', ['Belum pernah mencoba', 'Masih banyak dibantu', 'Bisa tugas sederhana sendiri', 'Sudah cukup mahir', 'Tidak tahu']),
    ('problem', 'Kesulitan paling nyata', 'select', ['Belum ada kesempatan praktik', 'Mouse/keyboard/mengetik', 'Membuat dokumen/tugas', 'File dan folder', 'Menggunakan aplikasi', 'Tidak ada kesulitan', 'Tidak tahu']),
    ('needs', 'Keterampilan yang paling dibutuhkan (maksimal 3)', 'multi', ['Komputer dasar dan mengetik', 'Word/Excel/PowerPoint', 'Desain dan kreativitas', 'Coding/game', 'AI secara aman', 'Keamanan internet', 'Belum tahu']),
    ('outcome', 'Hasil yang ingin terlihat setelah 3 bulan', 'select', ['Mandiri menggunakan komputer', 'Mampu membuat tugas/dokumen', 'Memiliki karya digital', 'Menguasai keterampilan kerja', 'Mencoba coding atau AI', 'Belum tahu']),
    ('interest', 'Jika ada kelas praktik komputer yang sesuai, bagaimana minatnya?', 'select', ['Sangat ingin tahu', 'Mungkin tertarik', 'Belum tertarik', 'Tidak tertarik']),
    ('barrier', 'Hambatan utama mengikuti kursus', 'select', ['Biaya', 'Jadwal', 'Jarak/transportasi', 'Belum yakin manfaat', 'Tidak berminat', 'Tidak ada hambatan', 'Lainnya']),
    ('format', 'Bentuk belajar yang paling sesuai', 'select', ['Reguler mingguan', 'Kursus singkat per keterampilan', 'Belum tahu']),
    ('schedule', 'Waktu yang paling memungkinkan', 'select', ['Hari sekolah sore', 'Sabtu pagi', 'Sabtu siang', 'Minggu', 'Malam hari', 'Belum tahu']),
    ('price', 'Untuk 8 pertemuan/bulan, kisaran anggaran yang nyaman (opsional)', 'select', ['Di bawah Rp100 ribu', 'Rp100–149 ribu', 'Rp150–199 ribu', 'Rp200–249 ribu', 'Rp250 ribu atau lebih', 'Belum tahu']),
    ('story', 'Contoh kebutuhan atau kesulitan, tanpa nama dan identitas (opsional)', 'text', []),
]
OPTIONAL = ('price', 'story')
SEGMENTS: Dict[str, str] = {'sd': 'Orang tua siswa SD', 'teen': 'Pelajar SMP/SMA/SMK (atau wali)', 'adult': 'Dewasa / umum'}
LEVELS: Dict[str, List[str]] = {
    'sd': ['Kelas 1–2 SD', 'Kelas 3–4 SD', 'Kelas 5–6 SD'],
    'teen': ['SMP', 'SMA', 'SMK'],
    'adult': ['Mahasiswa', 'Bekerja', 'Usaha mandiri', 'Mencari kerja', 'Lainnya'],
}
META_COLS = ['id', 'tutor', 'created_at', 'updated_at', 'version', 'segment', 'level', 'location_code', 'status']

# ---------------------------------------------------------------- database
@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=5000')
    try:
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def init_db() -> None:
    os.makedirs(os.path.dirname(os.path.abspath(DB)), exist_ok=True)
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ("admin","tutor")),active INTEGER NOT NULL DEFAULT 1)')
        has_old = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='interviews_v3'").fetchone()
        has_new = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='surveys'").fetchone()
        if has_old and not has_new:
            c.execute('ALTER TABLE interviews_v3 RENAME TO surveys')
        c.execute('''CREATE TABLE IF NOT EXISTS surveys (id INTEGER PRIMARY KEY,tutor_id INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,updated_at TEXT NOT NULL,version INTEGER NOT NULL,segment TEXT NOT NULL,level TEXT NOT NULL DEFAULT '',location_code TEXT NOT NULL,consent INTEGER NOT NULL CHECK(consent=1),status TEXT NOT NULL CHECK(status IN ('draft','complete')),answers TEXT NOT NULL)''')
        c.execute('DROP INDEX IF EXISTS idx_v3_tutor')
        c.execute('DROP INDEX IF EXISTS idx_v3_status')
        c.execute('CREATE INDEX IF NOT EXISTS idx_surveys_tutor ON surveys(tutor_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_surveys_status ON surveys(status,segment)')


init_db()


def users_exist() -> bool:
    with db() as c:
        return c.execute('SELECT 1 FROM users LIMIT 1').fetchone() is not None


# ---------------------------------------------------------------- security
def csrf() -> str:
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return str(session['csrf'])


app.jinja_env.globals['csrf'] = csrf

_FAILS: Dict[str, Deque[float]] = {}
_FAILS_LOCK = Lock()
FAIL_WINDOW = 900
FAIL_LIMITS = {'user': 8, 'ip': 40}
_DUMMY_HASH = generate_password_hash(secrets.token_hex(16))


def _fail_keys(username: str) -> List[Tuple[str, str]]:
    return [('user:' + username, 'user'), ('ip:' + str(request.remote_addr), 'ip')]


def login_blocked(username: str) -> bool:
    now = time.time()
    with _FAILS_LOCK:
        for key, kind in _fail_keys(username):
            q = _FAILS.get(key)
            if not q:
                continue
            while q and now - q[0] > FAIL_WINDOW:
                q.popleft()
            if not q:
                _FAILS.pop(key, None)
            elif len(q) >= FAIL_LIMITS[kind]:
                return True
    return False


def record_fail(username: str) -> None:
    now = time.time()
    with _FAILS_LOCK:
        if len(_FAILS) > 5000:
            _FAILS.clear()
        for key, _ in _fail_keys(username):
            _FAILS.setdefault(key, deque()).append(now)


def clear_fails(username: str) -> None:
    with _FAILS_LOCK:
        _FAILS.pop('user:' + username, None)


@app.before_request
def protect() -> None:
    if request.endpoint == 'static':
        return
    if session.get('uid'):
        with db() as c:
            u = c.execute('SELECT role,active FROM users WHERE id=?', (session['uid'],)).fetchone()
        if not u or not u['active']:
            session.clear()
        else:
            session['role'] = u['role']
    if request.method == 'POST':
        sent = request.form.get('_csrf', '').encode('utf-8')
        if not secrets.compare_digest(sent, csrf().encode('utf-8')):
            abort(400, 'Sesi kedaluwarsa. Muat ulang halaman lalu coba lagi.')


def login_required(f: F) -> F:
    @wraps(f)
    def wrapper(*a: Any, **kw: Any) -> Any:
        if not session.get('uid'):
            return redirect(url_for('login'))
        return f(*a, **kw)
    return wrapper  # type: ignore[return-value]


def admin_required(f: F) -> F:
    @wraps(f)
    @login_required
    def wrapper(*a: Any, **kw: Any) -> Any:
        if session.get('role') != 'admin':
            abort(403)
        return f(*a, **kw)
    return wrapper  # type: ignore[return-value]


@app.after_request
def secure_headers(response: Response) -> Response:
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'public, max-age=86400' if request.endpoint == 'static' else 'no-store'
    response.headers['Content-Security-Policy'] = ("default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                                                   "img-src 'self' data:; form-action 'self'; base-uri 'self'; frame-ancestors 'none'")
    return response


# ---------------------------------------------------------------- theme (navy, amber, cyan, putih)
STYLE = '''<style>
:root{--navy:#0d2a5c;--navy-2:#17408a;--cyan:#12b0e6;--cyan-soft:#e2f5fc;--cyan-ink:#065f80;--amber:#f5a300;--amber-soft:#fff1cf;--amber-ink:#7a4a00;--ink:#12284b;--muted:#5a6b85;--line:#dbe4ef;--paper:#f4f7fb;--white:#fff;--danger:#a52a2a;--bar-h:56px}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font-family:"Segoe UI",Roboto,"Helvetica Neue",Arial,system-ui,sans-serif;font-size:16px;line-height:1.5;-webkit-tap-highlight-color:transparent}
img{max-width:100%;display:block}
a{color:var(--navy-2)}
h1,h2,h3{color:var(--navy);line-height:1.2;margin:0}
h1{font-size:1.6rem;font-weight:800;letter-spacing:-.015em}
h2{font-size:1.05rem;font-weight:800;margin-bottom:12px}
p{margin:0 0 10px}
.muted,small{color:var(--muted)}
.skip-link{position:absolute;left:-9999px;top:8px;background:#fff;color:var(--navy);padding:10px 14px;border-radius:10px;z-index:100}
.skip-link:focus{left:12px}

/* app bar */
.bar{position:sticky;top:0;z-index:20;background:var(--white);border-bottom:1px solid var(--line);padding-top:env(safe-area-inset-top,0px)}
.bar-in{max-width:720px;margin:0 auto;height:var(--bar-h);padding:0 16px;display:flex;align-items:center;gap:12px}
.bar-brand{display:flex;align-items:center;gap:9px;text-decoration:none;border-radius:8px}
.bar-mark{width:36px;height:30px;object-fit:contain}
.bar-word{width:142px;height:17px;object-fit:contain}
.bar-title{font-size:1.08rem;font-weight:800;flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-close{margin-left:auto;color:var(--navy);font-weight:700;text-decoration:none;padding:10px 12px;border-radius:10px;min-height:44px;display:inline-flex;align-items:center}
.bar-close:hover{background:var(--paper)}

/* layout */
.wrap{max-width:720px;margin:0 auto;padding:20px 16px 32px}
.has-tabs .wrap{padding-bottom:calc(104px + env(safe-area-inset-bottom,0px))}
.flow .wrap{padding-bottom:calc(112px + env(safe-area-inset-bottom,0px))}
.head{margin-bottom:16px}
.head p{margin:4px 0 0}

/* buttons: specificity 0 so any class can override */
:where(button,.btn){display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:48px;padding:0 20px;border:0;border-radius:12px;background:var(--navy);color:#fff;font:inherit;font-weight:700;text-decoration:none;cursor:pointer;margin-top:16px}
:where(button,.btn):hover{background:var(--navy-2)}
.btn-accent,#finish{background:var(--amber);color:var(--navy)}
.btn-accent:hover,#finish:hover{background:#e29800}
.secondary{background:#e8eef7;color:var(--navy)}
.secondary:hover{background:#d9e3f1}
.link-button{background:transparent;color:var(--navy);padding:0 10px}
.link-button:hover{background:#e8eef7}
.btn-line{background:var(--white);color:var(--navy);box-shadow:inset 0 0 0 1.5px var(--navy)}
.btn-line:hover{background:#eef3fa}
.tools{display:flex;flex-wrap:wrap;gap:10px;margin:0}
.tools .btn{margin:0}
:focus-visible{outline:3px solid var(--cyan);outline-offset:2px}

/* forms */
label{display:block;font-weight:700;font-size:.95rem;margin:18px 0 7px}
input,select,textarea{width:100%;min-height:48px;padding:11px 14px;border:1.5px solid #b4c3d8;border-radius:12px;background:#fff;color:var(--ink);font:inherit;font-size:16px}
textarea{resize:vertical;min-height:96px}
select{appearance:none;-webkit-appearance:none;padding-right:42px;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='9' viewBox='0 0 14 9'%3E%3Cpath d='M1 1.5l6 6 6-6' fill='none' stroke='%230d2a5c' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 15px center}
input:focus,select:focus,textarea:focus{border-color:var(--navy);outline:3px solid rgba(18,176,230,.45);outline-offset:0}
input[type=checkbox]{appearance:none;-webkit-appearance:none;width:24px;height:24px;min-height:0;padding:0;flex:none;border:2px solid #8fa3bf;border-radius:7px;background:#fff;margin:0}
input[type=checkbox]:checked{background:var(--navy) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M5.5 12.5l4.2 4.2 8.8-9.4' fill='none' stroke='white' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center/18px no-repeat;border-color:var(--navy)}
.choice{display:flex;align-items:flex-start;gap:13px;padding:13px 14px;margin:8px 0;border:1.5px solid var(--line);border-radius:12px;background:#fff;font-weight:500;font-size:1rem;cursor:pointer}
.choice input{margin-top:1px}
.choice:has(input:checked){border-color:var(--navy);background:var(--cyan-soft)}
fieldset{border:0;padding:0;margin:18px 0 0;min-width:0}
legend{font-weight:700;font-size:.95rem;padding:0;margin-bottom:6px}
.required-note{font-size:.88rem;color:var(--muted);margin:0 0 4px}
.form-note{padding:12px 14px;border-left:4px solid var(--cyan);background:var(--cyan-soft);border-radius:0 10px 10px 0;font-size:.94rem}
.error{padding:12px 14px;border-radius:10px;background:#fdeceb;border:1px solid #f0c4c1;color:var(--danger);font-weight:600}
.notice{padding:12px 14px;background:var(--cyan-soft);border-left:4px solid var(--cyan);border-radius:0 10px 10px 0;margin-bottom:16px;color:var(--ink);font-weight:600}

/* wizard */
.panel,.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:14px}
.progress-label{display:flex;justify-content:space-between;gap:12px;margin-top:16px;color:var(--muted);font-size:.86rem;font-weight:700}
.steps{display:flex;gap:6px;margin:8px 0 22px}
.steps span{flex:1;height:6px;border-radius:4px;background:#d9e4f1}
.steps span.on{background:var(--navy)}
.wizard{display:none}
.wizard.active{display:block}
.wizard h2{font-size:1.2rem;margin-bottom:4px}
.actions{position:fixed;left:0;right:0;bottom:0;z-index:30;display:flex;align-items:center;gap:8px;background:#fff;border-top:1px solid var(--line);padding:10px max(16px,calc((100vw - 688px)/2)) calc(10px + env(safe-area-inset-bottom,0px))}
.actions button{margin:0}
.actions .spacer{display:none}
#next,#finish{flex:1}
.actions button{white-space:nowrap}

/* tab bar */
.tabs{position:fixed;left:0;right:0;bottom:0;z-index:30;background:#fff;border-top:1px solid var(--line);padding-bottom:env(safe-area-inset-bottom,0px)}
.tabs-in{max-width:640px;margin:0 auto;display:flex;align-items:stretch;height:62px}
.tab-form{flex:1;display:flex;margin:0}
.tab{position:relative;flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;margin:0;padding:0;min-height:0;border-radius:0;background:transparent;color:var(--muted);font:inherit;font-size:.75rem;font-weight:600;text-decoration:none}
.tab svg{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}
.tab:hover{background:transparent;color:var(--navy)}
.tab[aria-current="page"]{color:var(--navy);font-weight:800}
.tab[aria-current="page"]::before{content:"";position:absolute;top:-1px;width:30px;height:3px;border-radius:0 0 3px 3px;background:var(--amber)}
.tab-fab{color:var(--navy);font-weight:800}
.tab-fab .fab{width:54px;height:54px;margin-top:-30px;border-radius:50%;display:grid;place-items:center;background:var(--amber);color:var(--navy);border:4px solid #fff;box-shadow:0 0 0 1px var(--line)}
.tab-fab .fab svg{width:26px;height:26px;stroke-width:2.8}
.tab-fab:hover .fab{background:#e29800}

/* list rows */
.chips{display:flex;gap:8px;margin:0 0 14px;overflow-x:auto;padding-bottom:2px}
.chip{margin:0;min-height:40px;padding:0 15px;border-radius:99px;background:#fff;color:var(--navy);box-shadow:inset 0 0 0 1.5px var(--line);font-weight:700;font-size:.92rem;white-space:nowrap}
.chip b{font-weight:800;color:var(--muted)}
.chip:hover{background:#eef3fa}
.chip.on{background:var(--navy);color:#fff;box-shadow:none}
.chip.on b{color:var(--amber)}
.rows{display:grid;grid-template-columns:minmax(0,1fr);gap:10px}
.row{display:flex;align-items:center;gap:12px;min-height:68px;padding:12px 14px;background:#fff;border:1px solid var(--line);border-left:6px solid var(--line);border-radius:12px;color:var(--ink);text-decoration:none}
a.row:active{background:#eef5fb}
@media(hover:hover){a.row:hover{background:#f6f9fd}}
.row-draft{border-left-color:var(--amber)}
.row-complete{border-left-color:var(--cyan)}
.row-admin{border-left-color:var(--navy)}
.row-tutor{border-left-color:var(--cyan)}
.row-off{opacity:.55}
.row-main{flex:1;min-width:0;display:flex;flex-direction:column}
.row-main strong{color:var(--navy);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row-main span{font-size:.88rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.status{display:inline-flex;align-items:center;padding:3px 11px;border-radius:99px;font-size:.8rem;font-weight:800;white-space:nowrap}
.status-complete,.status-tutor{background:var(--cyan-soft);color:var(--cyan-ink)}
.status-draft{background:var(--amber-soft);color:var(--amber-ink)}
.status-admin{background:var(--navy);color:#fff}
.status-off{background:#e6ebf2;color:var(--muted)}
.empty{text-align:center;color:var(--muted);padding:34px 16px;background:#fff;border:1px dashed #b8c7da;border-radius:12px}

/* dashboard */
.stat-row{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}
.stat-num{font-size:2.4rem;font-weight:800;color:var(--navy);line-height:1}
.stat-lbl{color:var(--muted);font-size:.9rem}
.note{font-size:.9rem;color:var(--muted);margin:14px 0 0}
.meter{margin:14px 0 0}
.meter-line{display:flex;justify-content:space-between;gap:12px;font-size:.95rem}
.meter-line b{font-variant-numeric:tabular-nums;white-space:nowrap}
.meter-line small{margin-left:6px;font-weight:600}
.meter-track{height:10px;margin-top:6px;border-radius:6px;background:#e6edf6;overflow:hidden}
.meter-track i{display:block;height:100%;min-width:4px;border-radius:6px;background:var(--cyan)}
.meter.top .meter-track i{background:var(--amber)}
details.card summary{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:30px;cursor:pointer;list-style:none;font-weight:800;color:var(--navy)}
details.card summary::-webkit-details-marker{display:none}
details.card summary::after{content:"";width:9px;height:9px;border-right:2.5px solid var(--navy);border-bottom:2.5px solid var(--navy);transform:rotate(45deg) translate(-2px,-2px);transition:transform .15s}
details.card[open] summary::after{transform:rotate(-135deg)}
details.card[open] summary{margin-bottom:2px}

/* login / setup */
.auth .wrap{max-width:420px;padding-top:max(36px,9vh)}
.brand-block{text-align:center;margin-bottom:22px}
.brand-block .m{width:112px;margin:0 auto}
.brand-block .w{width:250px;margin:10px auto 0}
.brand-block p{margin:10px 0 0;color:var(--muted)}
.auth form button{width:100%}

@media(max-width:360px){.bar-word{width:118px}.tab{font-size:.7rem}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}details.card summary::after{transition:none}}
</style>'''

BASE_HTML = '''<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0d2a5c"><meta name="description" content="Sistem internal Canggihpedia untuk mencatat dan merangkum wawancara kebutuhan belajar digital."><link rel="icon" type="image/png" href="{{url_for('static',filename='favicon.png')}}"><link rel="apple-touch-icon" href="{{url_for('static',filename='apple-touch-icon.png')}}"><title>Canggihpedia Riset</title>'''+STYLE+'''</head>
{% set ep=request.endpoint %}{% set authed=session.get('uid') %}{% set admin=session.get('role')=='admin' %}{% set flow=ep in ('research_new','research_edit') %}
<body class="{{'auth' if not authed else ('flow' if flow else 'has-tabs')}}"><a class="skip-link" href="#content">Lewati ke konten</a>
{% if authed %}<header class="bar"><div class="bar-in">
{% if flow %}<a class="bar-brand" href="{{url_for('research_list')}}" aria-label="Kembali ke daftar wawancara"><img class="bar-mark" src="{{url_for('static',filename='logo-mark.png')}}" alt="" width="36" height="30"></a><h1 class="bar-title">{{'Edit wawancara' if ep=='research_edit' else 'Wawancara baru'}}</h1><a class="bar-close" href="{{url_for('research_list')}}">Tutup</a>
{% else %}<a class="bar-brand" href="{{url_for('research_list')}}"><img class="bar-mark" src="{{url_for('static',filename='logo-mark.png')}}" alt="" width="36" height="30"><img class="bar-word" src="{{url_for('static',filename='logo-wordmark.png')}}" alt="Canggihpedia" width="142" height="17"></a>{% endif %}
</div></header>{% endif %}
<main id="content" class="wrap">{% for m in get_flashed_messages() %}<div class="notice" role="status">{{m}}</div>{% endfor %}{{content|safe}}</main>
{% if authed and not flow %}<nav class="tabs" aria-label="Menu utama"><div class="tabs-in">
<a class="tab" href="{{url_for('research_list')}}" {% if ep=='research_list' %}aria-current="page"{% endif %}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r=".8"/><circle cx="4.5" cy="12" r=".8"/><circle cx="4.5" cy="18" r=".8"/></svg><span>Data</span></a>
{% if admin %}<a class="tab" href="{{url_for('research_dashboard')}}" {% if ep=='research_dashboard' %}aria-current="page"{% endif %}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 20V11M12 20V4M19 20v-6"/></svg><span>Ringkasan</span></a>{% endif %}
<a class="tab tab-fab" href="{{url_for('research_new')}}"><span class="fab"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg></span><span>Wawancara</span></a>
{% if admin %}<a class="tab" href="{{url_for('users')}}" {% if ep=='users' %}aria-current="page"{% endif %}><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.6"/><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6"/></svg><span>Akun</span></a>{% endif %}
<form class="tab-form" method="post" action="{{url_for('logout')}}"><input type="hidden" name="_csrf" value="{{csrf()}}"><button class="tab" aria-label="Keluar dari akun {{session.get('username','')}}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4M15 8l4 4-4 4M19 12H9"/></svg><span>Keluar</span></button></form>
</div></nav>{% endif %}
</body></html>'''

_BRAND = '''<div class="brand-block"><img class="m" src="{{url_for('static',filename='logo-mark.png')}}" alt="" width="112" height="94"><img class="w" src="{{url_for('static',filename='logo-wordmark.png')}}" alt="Canggihpedia" width="250" height="30">'''

LOGIN_TPL = _BRAND + '''<p>Riset kebutuhan belajar digital</p></div>
<div class="card"><h1>Masuk</h1><form method="post"><input type="hidden" name="_csrf" value="{{csrf()}}"><label for="username">Username</label><input id="username" name="username" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" required><label for="password">Kata sandi</label><input id="password" type="password" name="password" autocomplete="current-password" required><button class="btn-accent">Masuk</button></form></div>'''

SETUP_TPL = _BRAND + '''<p>Siapkan akun admin pertama</p></div>
<div class="card"><h1>Buat admin</h1><form method="post"><input type="hidden" name="_csrf" value="{{csrf()}}"><label for="username">Username admin</label><input id="username" name="username" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" required><label for="password">Kata sandi, minimal 12 karakter</label><input id="password" name="password" type="password" minlength="12" autocomplete="new-password" required><button class="btn-accent">Buat admin</button></form></div>'''

LIST_TPL = '''{% set ns=namespace(c=0,d=0) %}{% for r in rows %}{% if r.status=='complete' %}{% set ns.c=ns.c+1 %}{% else %}{% set ns.d=ns.d+1 %}{% endif %}{% endfor %}
<div class="head"><h1>Data wawancara</h1><p class="muted">Jawaban disimpan tanpa nama dan nomor telepon.</p></div>
<div class="chips" role="group" aria-label="Filter status"><button type="button" class="chip on" data-f="all" aria-pressed="true">Semua <b>{{rows|length}}</b></button><button type="button" class="chip" data-f="draft" aria-pressed="false">Draf <b>{{ns.d}}</b></button><button type="button" class="chip" data-f="complete" aria-pressed="false">Selesai <b>{{ns.c}}</b></button></div>
<div class="rows">{% for r in rows %}<a class="row row-{{r.status}}" data-status="{{r.status}}" href="{{url_for('research_edit',rid=r.id)}}"><div class="row-main"><strong>{{segments.get(r.segment,r.segment)}}</strong><span>{{r.level}}, lokasi {{r.location_code}}</span><span>#{{r.id}} tanggal {{r.created_at[:10]}}{% if session.get('role')=='admin' %}, oleh {{r.username}}{% endif %}</span></div><span class="status status-{{r.status}}">{{'Selesai' if r.status=='complete' else 'Draf'}}</span></a>{% else %}<div class="empty">Belum ada wawancara. Ketuk tombol Wawancara di bawah untuk mulai.</div>{% endfor %}</div>
<p class="empty" id="no-match" hidden>Tidak ada wawancara dengan status ini.</p>
<script>
(()=>{const chips=[...document.querySelectorAll('.chip')],rows=[...document.querySelectorAll('a.row')],none=document.getElementById('no-match');
chips.forEach(c=>c.addEventListener('click',()=>{const f=c.dataset.f;let n=0;chips.forEach(x=>{x.classList.toggle('on',x===c);x.setAttribute('aria-pressed',String(x===c))});rows.forEach(r=>{const show=f==='all'||r.dataset.status===f;r.hidden=!show;if(show)n++});none.hidden=n>0||!rows.length}))})();
</script>'''

DASH_TPL = '''{% macro bars(counts,total,names=None) %}{% for k,n in counts.most_common() %}{% set pct=([(n*100/total)|round|int,100]|min) if total else 0 %}<div class="meter{% if loop.first %} top{% endif %}"><div class="meter-line"><span>{{names[k] if names else k}}</span><b>{{n}}<small>{{pct}}%</small></b></div><div class="meter-track"><i style="width:{{pct}}%"></i></div></div>{% else %}<p class="muted">Belum ada data selesai.</p>{% endfor %}{% endmacro %}
<div class="head"><h1>Ringkasan riset</h1></div>
<div class="card"><div class="stat-row"><div><div class="stat-num">{{total}}</div><div class="stat-lbl">wawancara selesai, draf tidak dihitung</div></div><div class="tools"><a class="btn btn-line" href="{{url_for('research_export')}}">Unduh CSV</a></div></div>
<p class="note">Sampel nonacak: hasil menunjukkan pola responden yang diwawancarai, bukan seluruh masyarakat. Jawaban multi-pilih bisa berjumlah lebih dari total responden.</p></div>
<details class="card" open><summary>Kelompok responden</summary>{{bars(segments,total,labels)}}</details>
<details class="card" open><summary>Per tutor</summary>{{bars(by_tutor,total)}}</details>
{% for label,counts in sections %}<details class="card" open><summary>{{label}}</summary>{{bars(counts,total)}}</details>{% endfor %}'''

USERS_TPL = '''<div class="head"><h1>Akun</h1></div>
<div class="card"><h2>Tambah tutor</h2><form method="post"><input type="hidden" name="_csrf" value="{{csrf()}}"><label for="username" style="margin-top:0">Username</label><input id="username" name="username" autocomplete="off" autocapitalize="none" autocorrect="off" spellcheck="false" required><label for="password">Kata sandi sementara, minimal 12 karakter</label><input id="password" name="password" type="password" minlength="12" autocomplete="new-password" required><button class="btn-accent">Tambah tutor</button></form></div>
<h2 style="margin:22px 2px 10px">Akun terdaftar</h2>
<div class="rows">{% for r in rows %}<div class="row row-{{r.role}}{% if not r.active %} row-off{% endif %}"><div class="row-main"><strong>{{r.username}}</strong><span>{{'Aktif' if r.active else 'Nonaktif'}}</span></div><span class="status status-{{r.role}}">{{'Admin' if r.role=='admin' else 'Tutor'}}</span></div>{% endfor %}</div>
<p class="note">Reset kata sandi dan penonaktifan akun saat ini dilakukan oleh administrator server.</p>'''


def page(content: str, **ctx: Any) -> str:
    return render_template_string(BASE_HTML, content=render_template_string(content, **ctx))


ERROR_TEXT = {400: 'Permintaan tidak valid.', 403: 'Akses ditolak untuk akun ini.', 404: 'Halaman tidak ditemukan.',
              405: 'Metode tidak diizinkan.', 413: 'Data terlalu besar.'}


@app.errorhandler(HTTPException)
def http_error(e: HTTPException) -> Tuple[str, int]:
    code = e.code or 500
    msg = e.description if code == 400 and e.description else ERROR_TEXT.get(code, 'Terjadi kesalahan.')
    return page('<div class="card"><h1>{{code}}</h1><p class="muted" style="margin-top:8px">{{msg}}</p><a class="btn" href="{{url_for(\'research_list\')}}">Kembali ke beranda</a></div>', code=code, msg=msg), code


# ---------------------------------------------------------------- form wawancara
V3_FORM = '''<div class="panel"><p class="form-note">Jelaskan tujuan riset dengan jujur dan minta persetujuan. Jangan tulis nama, kontak, alamat, atau identitas anak. Untuk pelajar di bawah umur, wawancarai wali atau dengan izin wali.</p>
{% if error %}<p class="error" role="alert" style="margin-top:14px">{{error}}</p>{% endif %}
<form method="post" id="research-form"><input type="hidden" name="_csrf" value="{{csrf()}}">
<div class="progress-label"><span id="step-title">Profil responden</span><span id="step-count">Langkah 1 dari 4</span></div>
<div class="steps" id="stepbars"><span></span><span></span><span></span><span></span></div>
<section class="wizard active"><h2>1. Profil responden</h2>
<p class="required-note">Semua pertanyaan wajib diisi kecuali yang ditandai opsional.</p>
<label for="location_code">Kode lokasi (misalnya SD-A atau RW-01)</label><input id="location_code" name="location_code" maxlength="40" required value="{{loc}}" placeholder="Tanpa nama pribadi">
<label for="segment">Kelompok responden</label><select name="segment" id="segment" required><option value="">Pilih kelompok</option>{% for key,label in segments.items() %}<option value="{{key}}" {% if segment==key %}selected{% endif %}>{{label}}</option>{% endfor %}</select>
<label for="level">Tingkat / kategori</label><select name="level" id="level" required><option value="">Pilih kategori</option></select>
<label class="choice"><input type="checkbox" name="consent" value="1" required {% if consent %}checked{% endif %}> <span>Responden telah bersedia diwawancarai dan jawaban anonimnya dicatat.</span></label></section>
<section class="wizard"><h2>2. Kondisi saat ini</h2>{% for key,label,kind,options in questions[:4] %}{{field(key,label,kind,options,answers)|safe}}{% endfor %}</section>
<section class="wizard"><h2>3. Kebutuhan belajar</h2>{% for key,label,kind,options in questions[4:8] %}{{field(key,label,kind,options,answers)|safe}}{% endfor %}</section>
<section class="wizard"><h2>4. Preferensi dan catatan</h2>{% for key,label,kind,options in questions[8:] %}{{field(key,label,kind,options,answers)|safe}}{% endfor %}</section>
<div class="actions"><button type="button" id="back" class="secondary">Kembali</button><div class="spacer"></div><button type="submit" name="action" value="draft" id="save-draft" class="link-button" formnovalidate>Simpan draf</button><button type="button" id="next">Lanjut</button><button type="submit" name="action" value="complete" id="finish">Selesaikan</button></div>
</form></div>
<script>
const levels={{levels|tojson}};let oldLevel={{level|tojson}},sel=document.getElementById('segment'),lvl=document.getElementById('level');
function setLevels(){let previous=lvl.value||oldLevel;lvl.innerHTML='<option value="">Pilih kategori</option>';for(let v of levels[sel.value]||[]){let o=document.createElement('option');o.value=v;o.textContent=v;if(v===previous)o.selected=true;lvl.appendChild(o)}}sel.addEventListener('change',()=>{oldLevel='';setLevels()});setLevels();
let step=0,steps=[...document.querySelectorAll('.wizard')],bars=[...document.querySelectorAll('#stepbars span')],titles=['Profil responden','Kondisi saat ini','Kebutuhan belajar','Preferensi dan catatan'];function show(){steps.forEach((x,i)=>x.classList.toggle('active',i===step));bars.forEach((x,i)=>x.classList.toggle('on',i<=step));document.getElementById('step-title').textContent=titles[step];document.getElementById('step-count').textContent=`Langkah ${step+1} dari 4`;document.getElementById('back').style.display=step?'':'none';document.getElementById('next').style.display=step===3?'none':'';document.getElementById('finish').style.display=step===3?'':'none';window.scrollTo({top:0,behavior:'smooth'})}
function invalid(x,message){x.setCustomValidity(message);x.reportValidity();x.addEventListener('input',()=>x.setCustomValidity(''),{once:true});x.focus();return false}function valid(s){let el=steps[s];for(let x of el.querySelectorAll('[required]')){if(x.type==='checkbox'?!x.checked:!x.value)return invalid(x,'Lengkapi bagian ini sebelum melanjutkan.')}if(s===2&&!el.querySelector('input[name="needs"]:checked'))return invalid(el.querySelector('input[name="needs"]'),'Pilih minimal satu kebutuhan.');return true}
document.getElementById('next').onclick=()=>{if(valid(step)){step++;show()}};document.getElementById('back').onclick=()=>{step--;show()};document.getElementById('research-form').addEventListener('submit',e=>{if(e.submitter&&e.submitter.value==='draft')return;for(let i=0;i<4;i++)if(!valid(i)){e.preventDefault();step=i;show();return}});show();
document.querySelectorAll('input[name="needs"]').forEach(x=>x.addEventListener('change',()=>{let picked=document.querySelectorAll('input[name="needs"]:checked');if(picked.length>3){x.checked=false;x.setCustomValidity('Pilih maksimal tiga kebutuhan.');x.reportValidity();x.setCustomValidity('')}}));
</script>'''


def field(key: str, label: str, kind: str, options: List[str], answers: Dict[str, Any]) -> str:
    suffix = '' if key in OPTIONAL else ' *'
    if kind == 'multi':
        chosen = answers.get(key) or []
        out = f'<fieldset><legend>{escape(label)}{suffix}</legend>'
        for opt in options:
            checked = ' checked' if opt in chosen else ''
            out += f'<label class="choice"><input type="checkbox" name="{key}" value="{escape(opt)}"{checked}><span>{escape(opt)}</span></label>'
        return out + '</fieldset>'
    out = f'<label for="{key}">{escape(label)}{suffix}</label>'
    if kind == 'text':
        return out + f'<textarea id="{key}" name="{key}" rows="3" maxlength="400">{escape(answers.get(key) or "")}</textarea>'
    req = '' if key in OPTIONAL else ' required'
    out += f'<select id="{key}" name="{key}"{req}><option value="">Pilih jawaban</option>'
    for opt in options:
        selected = ' selected' if answers.get(key) == opt else ''
        out += f'<option value="{escape(opt)}"{selected}>{escape(opt)}</option>'
    return out + '</select>'


app.jinja_env.globals['field'] = field


def parse_answers() -> Optional[Dict[str, Any]]:
    answers: Dict[str, Any] = {}
    for key, _label, kind, opts in COMMON:
        if kind == 'multi':
            vals = request.form.getlist(key)
            if len(vals) > 3 or len(vals) != len(set(vals)) or any(x not in opts for x in vals):
                return None
            answers[key] = vals
        else:
            v = request.form.get(key, '').strip()
            if len(v) > (400 if kind == 'text' else 100) or (kind == 'select' and v and v not in opts):
                return None
            answers[key] = v
    return answers


def raw_answers() -> Dict[str, Any]:
    """Isi form apa adanya untuk ditampilkan ulang saat validasi gagal."""
    out: Dict[str, Any] = {}
    for key, _label, kind, _opts in COMMON:
        out[key] = request.form.getlist(key)[:7] if kind == 'multi' else request.form.get(key, '').strip()[:400]
    return out


def research_form(rid: Optional[int] = None) -> Any:
    record = None
    if rid is not None:
        with db() as c:
            record = c.execute('SELECT * FROM surveys WHERE id=?', (rid,)).fetchone()
        if not record:
            abort(404)
        if session['role'] != 'admin' and record['tutor_id'] != session['uid']:
            abort(403)
    answers: Dict[str, Any] = json.loads(record['answers']) if record else {}
    segment = record['segment'] if record else ''
    level = record['level'] if record else ''
    loc = record['location_code'] if record else ''
    consent = bool(record['consent']) if record else False
    error: Optional[str] = None
    if request.method == 'POST':
        parsed = parse_answers()
        segment = request.form.get('segment', '')
        level = request.form.get('level', '')
        loc = request.form.get('location_code', '').strip()
        consent = request.form.get('consent') == '1'
        action = request.form.get('action', '')
        if parsed is None or segment not in SEGMENTS or level not in LEVELS.get(segment, []) \
                or not 1 <= len(loc) <= 40 or not consent or action not in ('draft', 'complete'):
            error = 'Periksa profil, persetujuan, dan pilihan jawaban. Profil dan persetujuan wajib diisi, bahkan untuk draf.'
            answers = raw_answers()
        elif action == 'complete' and any(not parsed[k] for k, _l, _t, _o in COMMON if k not in OPTIONAL):
            error = 'Lengkapi seluruh pertanyaan wajib sebelum menyelesaikan.'
            answers = parsed
        else:
            status = 'draft' if action == 'draft' else 'complete'
            now = datetime.now(timezone.utc).isoformat(timespec='seconds')
            payload = json.dumps(parsed, ensure_ascii=False)
            with db() as c:
                if record:
                    c.execute('UPDATE surveys SET updated_at=?,segment=?,level=?,location_code=?,status=?,answers=? WHERE id=?',
                              (now, segment, level, loc, status, payload, rid))
                else:
                    c.execute('INSERT INTO surveys(tutor_id,created_at,updated_at,version,segment,level,location_code,consent,status,answers) VALUES(?,?,?,?,?,?,?,?,?,?)',
                              (session['uid'], now, now, VERSION, segment, level, loc, 1, status, payload))
            flash('Draf wawancara tersimpan.' if status == 'draft' else 'Wawancara selesai dan tersimpan.')
            return redirect(url_for('research_list'))
    return page(V3_FORM, record=record, questions=COMMON, answers=answers, segments=SEGMENTS, levels=LEVELS,
                segment=segment, level=level, loc=loc, consent=consent, error=error)


# ---------------------------------------------------------------- routes
@app.route('/setup', methods=['GET', 'POST'])
def setup() -> Any:
    if users_exist():
        abort(404)
    if request.method == 'POST':
        user = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        if not USERNAME_RE.fullmatch(user):
            flash(USERNAME_MSG)
        elif not 12 <= len(password) <= PASSWORD_MAX:
            flash('Kata sandi 12-256 karakter.')
        else:
            try:
                with db() as c:
                    c.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',
                              (user, generate_password_hash(password), 'admin'))
            except sqlite3.IntegrityError:
                flash('Username sudah dipakai.')
            else:
                flash('Admin dibuat. Silakan masuk.')
                return redirect(url_for('login'))
    return page(SETUP_TPL)


@app.route('/login', methods=['GET', 'POST'])
def login() -> Any:
    if not users_exist():
        return redirect(url_for('setup'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()[:80]
        password = request.form.get('password', '')[:PASSWORD_MAX]
        if login_blocked(username):
            flash('Terlalu banyak percobaan gagal. Coba lagi dalam 15 menit.')
            return page(LOGIN_TPL), 429
        with db() as c:
            u = c.execute('SELECT id,role,username,password_hash FROM users WHERE username=? AND active=1', (username,)).fetchone()
        ok = check_password_hash(u['password_hash'] if u else _DUMMY_HASH, password)
        if u and ok:
            clear_fails(username)
            session.clear()
            session.update(uid=u['id'], role=u['role'], username=u['username'])
            session.permanent = True
            return redirect(url_for('research_list'))
        record_fail(username)
        flash('Masuk gagal. Periksa username dan kata sandi.')
    return page(LOGIN_TPL)


@app.route('/logout', methods=['POST'])
def logout() -> Any:
    session.clear()
    return redirect(url_for('login'))


@app.route('/health')
def health() -> Any:
    try:
        with db() as c:
            c.execute('SELECT 1').fetchone()
        return {'status': 'ok'}
    except sqlite3.Error:
        return {'status': 'error'}, 503


@app.route('/')
@login_required
def research_list() -> Any:
    sql = 'SELECT v.id,v.segment,v.level,v.location_code,v.status,v.created_at,u.username FROM surveys v JOIN users u ON v.tutor_id=u.id'
    params: Tuple[Any, ...] = ()
    if session['role'] != 'admin':
        sql += ' WHERE v.tutor_id=?'
        params = (session['uid'],)
    with db() as c:
        rows = c.execute(sql + ' ORDER BY v.id DESC LIMIT 250', params).fetchall()
    return page(LIST_TPL, rows=rows, segments=SEGMENTS)


@app.route('/research/new', methods=['GET', 'POST'])
@login_required
def research_new() -> Any:
    return research_form()


@app.route('/research/<int:rid>', methods=['GET', 'POST'])
@login_required
def research_edit(rid: int) -> Any:
    return research_form(rid)


@app.route('/research/dashboard')
@admin_required
def research_dashboard() -> Any:
    with db() as c:
        rows = c.execute("SELECT v.segment,v.answers,u.username FROM surveys v JOIN users u ON v.tutor_id=u.id WHERE v.status='complete'").fetchall()
    segments = Counter(r['segment'] for r in rows)
    by_tutor = Counter(r['username'] for r in rows)
    parsed = [json.loads(r['answers']) for r in rows]
    sections: List[Tuple[str, Counter]] = []
    for key, label, kind, _opts in COMMON:
        if kind == 'text':
            continue
        counts: Counter = Counter()
        for a in parsed:
            value = a.get(key, [] if kind == 'multi' else '')
            for v in (value if isinstance(value, list) else [value]):
                if v:
                    counts[v] += 1
        sections.append((label, counts))
    return page(DASH_TPL, total=len(rows), segments=segments, by_tutor=by_tutor, sections=sections, labels=SEGMENTS)


def csv_safe(v: Any) -> str:
    s = '' if v is None else str(v)
    return "'" + s if s.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else s


@app.route('/research/export.csv')
@admin_required
def research_export() -> Response:
    with db() as c:
        rows = c.execute('SELECT v.*,u.username tutor FROM surveys v JOIN users u ON v.tutor_id=u.id ORDER BY v.id').fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(META_COLS + [k for k, _l, _t, _o in COMMON])
    for r in rows:
        a = json.loads(r['answers'])
        cells = [csv_safe(r[k]) for k in META_COLS]
        for k, _l, _t, _o in COMMON:
            val = a.get(k, '')
            cells.append(csv_safe(' | '.join(val) if isinstance(val, list) else val))
        w.writerow(cells)
    return Response('\ufeff' + buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=canggihpedia_research_v3.csv', 'Cache-Control': 'no-store'})


@app.route('/users', methods=['GET', 'POST'])
@admin_required
def users() -> Any:
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        if not USERNAME_RE.fullmatch(username):
            flash(USERNAME_MSG)
        elif not 12 <= len(password) <= PASSWORD_MAX:
            flash('Kata sandi 12-256 karakter.')
        else:
            try:
                with db() as c:
                    c.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',
                              (username, generate_password_hash(password), 'tutor'))
                flash('Akun tutor dibuat.')
            except sqlite3.IntegrityError:
                flash('Username sudah dipakai.')
    with db() as c:
        rows = c.execute('SELECT username,role,active FROM users ORDER BY id').fetchall()
    return page(USERS_TPL, rows=rows)


if __name__ == '__main__':
    from waitress import serve
    serve(app, host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT', '8080')))
