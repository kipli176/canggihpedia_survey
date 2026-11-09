import os, sqlite3, csv, io, secrets
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, session, redirect, url_for, render_template_string, flash, Response, abort
from werkzeug.security import generate_password_hash, check_password_hash

BASE=os.path.dirname(os.path.abspath(__file__))
DB=os.environ.get('DATABASE_PATH',os.path.join(os.environ.get('DATA_DIR',os.path.join(BASE,'data')),'survey.sqlite3'))
app=Flask(__name__)
app.secret_key=os.environ.get('SECRET_KEY') or secrets.token_hex(32)
if os.environ.get('APP_ENV')=='production' and not os.environ.get('SECRET_KEY'): raise RuntimeError('SECRET_KEY wajib di production')
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=__import__('datetime').timedelta(hours=8), SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE','0')=='1',MAX_CONTENT_LENGTH=100_000)
QUESTIONS=[('school_level','Kelas anak', ['1-2 SD','3-4 SD','5-6 SD']),('device','Perangkat yang biasa digunakan anak',['HP/tablet','Komputer/laptop','Keduanya','Belum menggunakan']),('computer_skill','Kemampuan komputer anak saat ini',['Belum bisa','Perlu bantuan','Cukup mandiri','Sudah mahir','Tidak tahu']),('difficulty','Kesulitan utama yang dialami anak',['Mengetik/mouse','Tugas sekolah','Menggunakan aplikasi','Internet aman','Tidak ada','Tidak tahu']),('priority','Keterampilan yang paling diharapkan',['Komputer dasar','Word/PowerPoint','Desain dan kreativitas','Coding/game','Keamanan digital','Belum tahu']),('outcome','Hasil yang ingin dilihat setelah 3 bulan',['Bisa mandiri menggunakan komputer','Bisa membuat tugas sekolah','Bisa membuat karya digital','Lebih aman berinternet','Lainnya']),('previous','Pernah mengikuti kursus komputer?',['Ya','Tidak','Tidak tahu'])]
FIELDS=[q[0] for q in QUESTIONS]
STYLE='''<style>
:root{--navy:#12365b;--blue:#1769aa;--blue-dark:#0f548d;--teal:#16818b;--ink:#172b43;--muted:#5d7088;--line:#dce5ef;--surface:#fff;--bg:#f4f7fb;--success:#13734b;--focus:#f2b84b}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Arial,sans-serif;background:var(--bg);color:var(--ink);margin:0;line-height:1.55}
a{color:var(--blue-dark)}a:hover{text-decoration-thickness:2px}.skip-link{position:absolute;left:-9999px;top:8px;background:#fff;color:var(--navy);padding:10px 14px;border-radius:8px;z-index:10}.skip-link:focus{left:12px}
header{background:var(--navy);color:#fff}.header-inner{max-width:1080px;margin:auto;padding:14px 20px;display:flex;align-items:center;gap:24px}.brand{color:#fff;text-decoration:none;font-weight:800;letter-spacing:.02em;white-space:nowrap}.brand span{font-weight:500;opacity:.75}
nav{display:flex;align-items:center;gap:6px;width:100%}nav a,.nav-button{color:#dcecff;text-decoration:none;border-radius:9px;padding:8px 11px;font-weight:650;font-size:.94rem}nav a:hover,nav a[aria-current="page"],.nav-button:hover{background:rgba(255,255,255,.12);color:#fff}.nav-primary{display:flex;gap:4px;align-items:center}.nav-utility{display:flex;gap:4px;align-items:center;margin-left:auto}.nav-new{background:#fff!important;color:var(--navy)!important}.nav-button{background:transparent;border:0;margin:0;cursor:pointer;font:inherit}
main{max-width:900px;margin:28px auto;padding:0 18px}.panel{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:0 3px 14px rgba(22,47,76,.045)}
h1,h2,h3{line-height:1.2}h1{font-size:clamp(1.65rem,4vw,2.15rem);margin-top:0}h2{font-size:1.2rem}label{display:block;font-weight:700;margin:16px 0 7px}input,select,textarea{width:100%;padding:12px 13px;border:1px solid #aebed0;border-radius:10px;background:#fff;color:var(--ink);font:inherit}textarea{resize:vertical}input:focus,select:focus,textarea:focus,button:focus-visible,a:focus-visible{outline:3px solid var(--focus);outline-offset:2px;border-color:var(--blue)}
button,.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;background:var(--blue);color:#fff;border:1px solid transparent;border-radius:10px;padding:11px 17px;text-decoration:none;cursor:pointer;font:inherit;font-weight:750;margin-top:14px;min-height:44px}button:hover,.btn:hover{background:var(--blue-dark)}.secondary{background:#edf3f9;color:var(--blue-dark);border-color:#d5e0eb}.secondary:hover{background:#dfeaf5}.link-button{background:transparent;color:var(--blue-dark);border-color:transparent}.link-button:hover{background:#edf3f9}
small,.muted{color:var(--muted)}.notice{padding:12px 15px;background:#e8f5ee;color:#145d41;border:1px solid #c5e8d5;border-radius:10px;margin-bottom:14px}.page-head{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;margin-bottom:20px}.page-head h1{margin-bottom:5px}.page-head p{margin:0}.page-head .btn{margin:0;white-space:nowrap}
table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid #e4e9ef;padding:12px 10px;text-align:left}th{font-size:.8rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}tbody tr:hover{background:#f8fafc}.status{display:inline-flex;padding:3px 9px;border-radius:999px;font-size:.82rem;font-weight:750}.status-complete{background:#e5f5ec;color:#11623f}.status-draft{background:#fff3d7;color:#77520b}.empty{text-align:center;color:var(--muted);padding:28px 12px}
@media(max-width:720px){.header-inner{align-items:flex-start;flex-direction:column;gap:10px;padding:12px 14px}.brand{padding:2px 4px}nav{align-items:stretch;gap:8px}.nav-primary{display:grid;grid-template-columns:1fr 1fr 1fr;flex:1}.nav-primary a{text-align:center;padding:9px 7px}.nav-utility{margin-left:0}.nav-utility a,.nav-button{padding:9px 7px}.nav-utility form{display:flex}main{margin:16px auto;padding:0 12px}.panel{padding:17px;border-radius:14px}.page-head{display:block}.page-head .btn{width:100%;margin-top:14px}table{font-size:.9rem}td,th{padding:10px 8px}}
@media(max-width:440px){.hide-mobile{display:none}.nav-utility a{display:none}.nav-primary{grid-template-columns:1fr 1fr 1fr}}
</style>'''
BASE_HTML='''<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="Sistem internal Canggihpedia untuk mencatat dan merangkum wawancara kebutuhan belajar digital."><title>Canggihpedia | Riset Internal</title>'''+STYLE+'''</head><body><a class="skip-link" href="#content">Lewati ke konten</a><header><div class="header-inner"><a class="brand" href="{{url_for('research_list')}}">CANGGIHPEDIA <span>Research</span></a>{% if session.get('uid') %}<nav aria-label="Navigasi utama"><div class="nav-primary"><a href="{{url_for('research_list')}}" {% if request.endpoint=='research_list' %}aria-current="page"{% endif %}>Data</a><a class="nav-new" href="{{url_for('research_new')}}" {% if request.endpoint=='research_new' %}aria-current="page"{% endif %}>+ Wawancara</a>{% if session.get('role')=='admin' %}<a class="admin-only" href="{{url_for('research_dashboard')}}" {% if request.endpoint=='research_dashboard' %}aria-current="page"{% endif %}>Ringkasan</a>{% endif %}</div><div class="nav-utility">{% if session.get('role')=='admin' %}<a href="{{url_for('users')}}" {% if request.endpoint=='users' %}aria-current="page"{% endif %}>Akun</a>{% endif %}<form method="post" action="{{url_for('logout')}}"><input type="hidden" name="_csrf" value="{{csrf()}}"><button class="nav-button" aria-label="Keluar dari akun {{session.get('username','')}}">Keluar</button></form></div></nav>{% endif %}</div></header><main id="content">{% for m in get_flashed_messages() %}<div class="notice" role="status">{{m}}</div>{% endfor %}{{content|safe}}</main></body></html>'''
def page(content,**ctx):
    return render_template_string(BASE_HTML,content=render_template_string(content,**ctx))
def conn():
    c=sqlite3.connect(DB,timeout=20)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=5000')
    return c
def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB)),exist_ok=True)
    with conn() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ("admin","tutor")),active INTEGER NOT NULL DEFAULT 1)')
init_db()
def csrf():
    if 'csrf' not in session:session['csrf']=secrets.token_urlsafe(32)
    return session['csrf']
app.jinja_env.globals['csrf']=csrf
@app.before_request
def protect():
    legacy_paths={'/legacy','/survey/new','/dashboard','/export.csv'}
    if request.path in legacy_paths or request.path.startswith('/survey/') or request.path=='/v2' or request.path.startswith('/v2/'):
        abort(404)
    if session.get('uid'):
        with conn() as c: u=c.execute('SELECT role,active FROM users WHERE id=?',(session['uid'],)).fetchone()
        if not u or not u['active']:session.clear()
        else:session['role']=u['role']
    if request.method=='POST' and not secrets.compare_digest(request.form.get('_csrf',''),csrf()):abort(400,'Invalid CSRF token')
def login_required(f):
    @wraps(f)
    def wrapper(*a,**kw):
        if not session.get('uid'):return redirect(url_for('login'))
        return f(*a,**kw)
    return wrapper
def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*a,**kw):
        if session.get('role')!='admin':abort(403)
        return f(*a,**kw)
    return wrapper
@app.route('/setup',methods=['GET','POST'])
def setup():
    with conn() as c:exists=c.execute('SELECT 1 FROM users LIMIT 1').fetchone()
    if exists:abort(404)
    if request.method=='POST':
        user=request.form.get('username','').strip().lower();password=request.form.get('password','')
        if len(user)<3 or len(password)<12:flash('Username minimal 3 karakter dan kata sandi minimal 12 karakter.')
        else:
            with conn() as c:c.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',(user,generate_password_hash(password),'admin'))
            flash('Admin dibuat. Silakan login.');return redirect(url_for('login'))
    return page('''<div class="panel"><h1>Pengaturan admin pertama</h1><form method="post"><input type="hidden" name="_csrf" value="{{csrf()}}"><label>Username admin</label><input name="username" required><label>Kata sandi (minimal 12 karakter)</label><input name="password" type="password" minlength="12" required><button>Buat admin</button></form></div>''')
@app.route('/login',methods=['GET','POST'])
def login():
    with conn() as c:exists=c.execute('SELECT 1 FROM users LIMIT 1').fetchone()
    if not exists:return redirect(url_for('setup'))
    if request.method=='POST':
        with conn() as c:u=c.execute('SELECT * FROM users WHERE username=? AND active=1',(request.form.get('username','').strip().lower(),)).fetchone()
        if u and check_password_hash(u['password_hash'],request.form.get('password','')):
            session.clear();session.update(uid=u['id'],role=u['role'],username=u['username']);session.permanent=True;return redirect(url_for('research_list'))
        flash('Login gagal. Periksa akun dan kata sandi.')
    return page('''<div class="panel"><h1>Masuk</h1><form method="post"><input type="hidden" name="_csrf" value="{{csrf()}}"><label>Username</label><input name="username" autocomplete="username" required><label>Kata sandi</label><input type="password" name="password" autocomplete="current-password" required><button>Masuk</button></form></div>''')
@app.route('/logout',methods=['POST'])
def logout():session.clear();return redirect(url_for('login'))
@app.route('/health')
def health():
    try:
        with conn() as c:c.execute('SELECT 1').fetchone()
        return {'status':'ok'}
    except sqlite3.Error:
        return {'status':'error'},503
@app.route('/legacy')
@login_required
def home():
    with conn() as c:
        if session['role']=='admin':rows=c.execute('SELECT s.*,u.username FROM surveys s JOIN users u ON s.tutor_id=u.id ORDER BY s.id DESC LIMIT 30').fetchall()
        else:rows=c.execute('SELECT s.*,u.username FROM surveys s JOIN users u ON s.tutor_id=u.id WHERE tutor_id=? ORDER BY s.id DESC LIMIT 30',(session['uid'],)).fetchall()
    return page('''<div class="panel"><h1>Wawancara orang tua SD</h1><p class="muted">Survei kebutuhan pendidikan digital · Versi 1. Jangan mencatat identitas anak, nomor telepon, atau nama lengkap orang tua.</p><a class="btn" href="{{url_for('new_interview')}}">+ Input wawancara v2</a></div><div class="panel"><h2>Input terbaru</h2><table><tr><th>ID</th><th>Kelas</th><th>Tanggal</th><th>Aksi</th></tr>{% for r in rows %}<tr><td>#{{r.id}}</td><td>{{r.school_level}}</td><td>{{r.created_at[:16]}}</td><td><a href="{{url_for('edit_survey',survey_id=r.id)}}">Lihat / edit</a></td></tr>{% else %}<tr><td colspan="4">Belum ada wawancara.</td></tr>{% endfor %}</table></div>''',rows=rows)
FORM='''<div class="panel"><h1>{{'Edit' if survey else 'Wawancara baru'}}</h1><p class="muted">Tanyakan secara netral, wawancara hanya jika orang tua bersedia. Jangan mencatat nama orang tua/anak, kontak, atau data sensitif.</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf()}}"><label>Kode lokasi/sekolah (contoh: SD-A; bukan nama anak)</label><input name="school_code" maxlength="40" required value="{{survey.school_code if survey else ''}}">{% for key,label,options in questions %}<label>{{loop.index}}. {{label}}</label><select name="{{key}}" required><option value="">Pilih jawaban</option>{% for opt in options %}<option value="{{opt}}" {% if survey and survey[key]==opt %}selected{% endif %}>{{opt}}</option>{% endfor %}</select>{% endfor %}<label>Catatan tambahan (opsional, tanpa identitas pribadi)</label><textarea name="notes" maxlength="500" rows="3">{{survey.notes if survey else ''}}</textarea><label style="font-weight:normal"><input style="width:auto" type="checkbox" name="consent" value="1" required {% if survey %}checked{% endif %}> Orang tua bersedia diwawancarai dan jawabannya dicatat secara anonim</label><button>Simpan wawancara</button></form></div>'''
def save_survey(survey_id=None):
    data={k:request.form.get(k,'') for k in FIELDS}
    if request.form.get('consent')!='1' or any(data[k] not in opts for k,_,opts in QUESTIONS):flash('Lengkapi persetujuan dan semua jawaban.');return False
    school=request.form.get('school_code','').strip()[:40];notes=request.form.get('notes','').strip()[:500]
    if not school:flash('Kode lokasi wajib diisi.');return False
    now=datetime.now(timezone.utc).isoformat(timespec='seconds')
    with conn() as c:
        if survey_id:
            c.execute('UPDATE surveys SET updated_at=?,school_code=?,notes=?, '+','.join(k+'=?' for k in FIELDS)+' WHERE id=?',(now,school,notes,*[data[k] for k in FIELDS],survey_id))
        else:
            c.execute('INSERT INTO surveys(tutor_id,created_at,updated_at,school_code,consent,notes,'+','.join(FIELDS)+') VALUES(?,?,?,?,?,?,'+','.join('?' for _ in FIELDS)+')',(session['uid'],now,now,school,1,notes,*[data[k] for k in FIELDS]))
    flash('Wawancara berhasil disimpan.');return True
@app.route('/survey/new',methods=['GET','POST'])
@login_required
def new_survey():
    if request.method=='POST' and save_survey():return redirect(url_for('research_list'))
    return page(FORM,survey=None,questions=QUESTIONS)
@app.route('/survey/<int:survey_id>',methods=['GET','POST'])
@login_required
def edit_survey(survey_id):
    with conn() as c:r=c.execute('SELECT * FROM surveys WHERE id=?',(survey_id,)).fetchone()
    if not r:abort(404)
    if session['role']!='admin' and r['tutor_id']!=session['uid']:abort(403)
    if request.method=='POST' and save_survey(survey_id):return redirect(url_for('research_list'))
    return page(FORM,survey=r,questions=QUESTIONS)
@app.route('/dashboard')
@admin_required
def dashboard():
    with conn() as c:
        total=c.execute('SELECT COUNT(*) FROM surveys').fetchone()[0]
        by_tutor=c.execute('SELECT u.username,COUNT(s.id) n FROM users u LEFT JOIN surveys s ON s.tutor_id=u.id GROUP BY u.id ORDER BY n DESC').fetchall()
        by_level=c.execute('SELECT school_level,COUNT(*) n FROM surveys GROUP BY school_level ORDER BY school_level').fetchall()
        by_priority=c.execute('SELECT priority,COUNT(*) n FROM surveys GROUP BY priority ORDER BY n DESC').fetchall()
    return page('''<div class="panel"><h1>Dashboard survei</h1><h2>{{total}} wawancara</h2><a class="btn" href="{{url_for('export_csv')}}">Unduh CSV</a><p class="muted">Angka merupakan hasil sampel wawancara, bukan estimasi populasi.</p></div>{% for title,rows,label in [('Per tutor',by_tutor,'username'),('Per kelas',by_level,'school_level'),('Kebutuhan utama',by_priority,'priority')] %}<div class="panel"><h2>{{title}}</h2><table>{% for r in rows %}<tr><td>{{r[label]}}</td><td>{{r.n}}</td></tr>{% endfor %}</table></div>{% endfor %}''',total=total,by_tutor=by_tutor,by_level=by_level,by_priority=by_priority)
@app.route('/export.csv')
@admin_required
def export_csv():
    with conn() as c:rows=c.execute('SELECT s.*,u.username tutor FROM surveys s JOIN users u ON u.id=s.tutor_id ORDER BY s.id').fetchall()
    buf=io.StringIO();writer=csv.writer(buf)
    keys=['id','tutor','created_at','updated_at','questionnaire_version','school_code',*FIELDS,'notes'];writer.writerow(keys)
    for r in rows:writer.writerow([r[k] for k in keys])
    return Response('\ufeff'+buf.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=canggihpedia_survey.csv'})
@app.route('/users',methods=['GET','POST'])
@admin_required
def users():
    if request.method=='POST':
        username=request.form.get('username','').strip().lower();password=request.form.get('password','')
        if len(username)<3 or len(password)<12:flash('Username minimal 3 karakter, kata sandi minimal 12 karakter.')
        else:
            try:
                with conn() as c:c.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',(username,generate_password_hash(password),'tutor'))
                flash('Akun tutor dibuat.')
            except sqlite3.IntegrityError:flash('Username sudah dipakai.')
    with conn() as c:rows=c.execute('SELECT username,role,active FROM users ORDER BY id').fetchall()
    return page('''<div class="panel"><h1>Kelola akun</h1><h2>Tambah tutor</h2><form method="post"><input type="hidden" name="_csrf" value="{{csrf()}}"><label>Username</label><input name="username" required><label>Kata sandi sementara (minimal 12 karakter)</label><input name="password" type="password" minlength="12" required><button>Tambah tutor</button></form></div><div class="panel"><h2>Akun aktif</h2><table>{% for r in rows %}<tr><td>{{r.username}}</td><td>{{r.role}}</td><td>{{'Aktif' if r.active else 'Nonaktif'}}</td></tr>{% endfor %}</table><small>Untuk versi pertama, reset kata sandi/nonaktif akun dilakukan oleh administrator server.</small></div>''',rows=rows)

# Questionnaire v2 is intentionally stored separately: legacy v1 data remains intact.
import json
V2_VERSION=2
V2_QUESTIONS=[
 ('grade','Kelas anak saat ini','select',['1 SD','2 SD','3 SD','4 SD','5 SD','6 SD'],'Profil'),
 ('access','Perangkat yang bisa digunakan anak untuk belajar di rumah','select',['HP/tablet saja','Komputer/laptop saja','Keduanya','Tidak ada','Tidak tahu'],'Kondisi saat ini'),
 ('frequency','Seberapa sering anak menggunakan komputer/laptop dalam 1 bulan terakhir?','select',['Tidak pernah','1–2 kali','3–7 kali','8 kali atau lebih','Tidak tahu'],'Kondisi saat ini'),
 ('ability','Apa yang anak sudah bisa lakukan sendiri di komputer?','multi',['Menggerakkan mouse dan klik','Mengetik kalimat','Menyimpan dan membuka file','Membuat dokumen','Membuat presentasi','Belum ada','Tidak tahu'],'Kondisi saat ini'),
 ('challenge','Kesulitan paling nyata yang pernah dialami anak saat menggunakan komputer?','select',['Belum pernah mencoba komputer','Menggunakan mouse/keyboard','Mengetik dan membuat tugas','Menyimpan atau mencari file','Memahami instruksi aplikasi','Tidak ada kesulitan','Tidak tahu'],'Kebutuhan'),
 ('story','Boleh ceritakan contoh kesulitan atau pengalaman anak? (opsional)','text',[],'Kebutuhan'),
 ('goal','Setelah belajar selama sekitar 3 bulan, hasil apa yang paling diharapkan?','select',['Mandiri memakai komputer','Mengetik dan membuat tugas sekolah','Membuat desain/karya digital','Lebih aman menggunakan internet','Mencoba coding/game','Belum tahu','Lainnya'],'Harapan'),
 ('priority','Keterampilan mana yang paling penting menurut Bapak/Ibu?','multi',['Komputer dasar','Mengetik','Dokumen/presentasi','Desain dan kreativitas','Coding/game','Keamanan internet','Belum tahu'],'Harapan'),
 ('past','Apakah anak pernah mengikuti kursus komputer?','select',['Pernah','Belum pernah','Tidak tahu'],'Pengalaman'),
 ('interest','Jika tersedia kegiatan praktik komputer untuk anak, bagaimana ketertarikan Bapak/Ibu?','select',['Ingin mengetahui lebih lanjut','Mungkin tertarik','Belum tertarik','Tidak tertarik'],'Minat'),
 ('barrier','Hal apa yang paling mungkin menghalangi keikutsertaan?','select',['Biaya','Jadwal','Jarak/transportasi','Anak kurang berminat','Belum yakin manfaatnya','Tidak ada kendala','Lainnya'],'Minat'),
 ('schedule','Waktu yang paling mungkin cocok? (opsional)','select',['Hari sekolah sore','Sabtu pagi','Sabtu siang','Minggu','Belum tahu'],'Minat'),
 ('extra','Catatan jawaban lain tanpa identitas pribadi (opsional)','text',[],'Penutup')
]
V2_FIELDS=[x[0] for x in V2_QUESTIONS]
V2_MULTI={'ability','priority'}
V2_OPTIONAL={'story','schedule','extra'}
V2_CSS='''<style>
body{background:#f5f8fc}main{max-width:760px;margin:16px auto}.panel{padding:20px;border-radius:18px;box-shadow:0 3px 16px #172e5210}
.hero{background:linear-gradient(125deg,#175ca6,#168ca2);color:white;border-radius:18px;padding:22px;margin-bottom:16px}.hero p{opacity:.92}
.section{border:1px solid #dce5ef;border-radius:13px;padding:15px;margin:15px 0;background:#fbfdff}.section h2{font-size:1.08rem;margin:0 0 12px}
.field{margin:13px 0 18px}.field label{margin:0 0 8px}.choice{display:flex;gap:11px;align-items:flex-start;border:1px solid #d9e2ed;padding:12px;margin:7px 0;border-radius:11px;background:white;font-weight:400;cursor:pointer}.choice:has(input:checked){border-color:#2379c4;background:#eaf4ff}.choice input{width:19px;height:19px;flex:none;margin:1px 0 0}.choice span{flex:1}
.actions{display:flex;gap:10px;flex-wrap:wrap}.actions button{flex:1;min-width:130px}.muted{line-height:1.5}.progress{height:8px;background:#e1eaf4;border-radius:12px;overflow:hidden;margin:10px 0}.progress div{height:100%;background:#36a4a0;width:0;transition:width .2s}.tag{font-size:.76rem;border-radius:8px;background:#e6f4ef;color:#166b56;padding:4px 8px}
@media(max-width:600px){main{padding:0 10px;margin:10px auto}.panel{padding:14px}.hero{padding:18px}button,.btn{min-height:46px}input,select,textarea{font-size:16px}}
</style>'''
V2_FORM='''<div class="hero"><h1>Wawancara orang tua SD</h1><p>Riset kebutuhan pendidikan digital · Kuesioner v2 · ± 5 menit</p></div>
<div class="panel"><p class="muted">Perkenalkan tujuan dengan jujur. Mintalah persetujuan. Jangan meminta nama, nomor telepon, alamat, atau identitas anak. Pertanyaan tidak boleh diarahkan untuk menjual program.</p>
<form method="post" id="interview" novalidate><input type="hidden" name="_csrf" value="{{csrf()}}">
<div class="field"><label for="location_code">Kode lokasi / sekolah (bukan identitas anak) *</label><input id="location_code" name="location_code" maxlength="40" required value="{{location_code}}" placeholder="Contoh: SEK-A"></div>
<div class="field"><label class="choice"><input type="checkbox" name="consent" value="1" {% if consent %}checked{% endif %}><span>Orang tua telah bersedia diwawancarai dan jawabannya dicatat secara anonim.</span></label></div>
<div class="progress"><div id="progressFill"></div></div><small id="stepInfo"></small>
{% for section, items in sections %}<section class="section survey-step" data-step="{{loop.index0}}" {% if not loop.first %}hidden{% endif %}><h2>{{section}}</h2>
{% for key,label,kind,options,group in items %}<div class="field"><label for="{{key}}">{{label}} {% if key not in optional %}*{% endif %}</label>
{% if kind=='text' %}<textarea id="{{key}}" name="{{key}}" maxlength="500" rows="3" placeholder="Catat sesuai jawaban, tanpa data pribadi">{{answers.get(key,'')}}</textarea>
{% elif kind=='multi' %}<div>{% for opt in options %}<label class="choice"><input type="checkbox" name="{{key}}" value="{{opt}}" {% if opt in answers.get(key,[]) %}checked{% endif %}><span>{{opt}}</span></label>{% endfor %}</div>
{% else %}<select id="{{key}}" name="{{key}}"><option value="">Pilih jawaban</option>{% for opt in options %}<option value="{{opt}}" {% if answers.get(key)==opt %}selected{% endif %}>{{opt}}</option>{% endfor %}</select>{% endif %}
</div>{% endfor %}</section>{% endfor %}
<div class="actions"><button type="button" class="secondary" id="prev" style="display:none">Kembali</button><button type="button" id="next">Lanjut</button><button type="submit" class="secondary" name="action" value="draft" id="draft">Simpan draf</button><button type="submit" name="action" value="complete" id="finish" style="display:none">Selesaikan wawancara</button></div>
</form></div>
<script>
(()=>{const steps=[...document.querySelectorAll('.survey-step')],prev=document.getElementById('prev'),next=document.getElementById('next'),finish=document.getElementById('finish'),form=document.getElementById('interview');let i=0;
function show(){steps.forEach((s,j)=>s.hidden=j!==i);prev.style.display=i?'':'none';next.style.display=i===steps.length-1?'none':'';finish.style.display=i===steps.length-1?'':'none';document.getElementById('stepInfo').textContent=`Bagian ${i+1} dari ${steps.length}`;document.getElementById('progressFill').style.width=`${(i+1)/steps.length*100}%`;window.scrollTo({top:0,behavior:'smooth'});}
function validStep(step){let ok=true;for(const field of step.querySelectorAll('select')){if(field.name!=='schedule'&&!field.value){field.focus();ok=false;break}}if(ok)for(const name of ['ability','priority']){if(step.querySelector(`input[name="${name}"]`)&&!step.querySelector(`input[name="${name}"]:checked`)){alert('Pilih minimal satu jawaban untuk pertanyaan ini.');ok=false;break}}return ok}
next.onclick=()=>{if(validStep(steps[i])){i++;show()}};prev.onclick=()=>{i--;show()};form.addEventListener('submit',e=>{if(e.submitter?.value==='draft')return;if(!document.querySelector('input[name="consent"]').checked||!document.getElementById('location_code').value.trim()){e.preventDefault();alert('Isi kode lokasi dan persetujuan wawancara.');return}for(let j=0;j<steps.length;j++)if(!validStep(steps[j])){e.preventDefault();i=j;show();return}});show();})();
</script>'''

def v2_sections():
    out=[]
    for q in V2_QUESTIONS:
        if not out or out[-1][0]!=q[4]:out.append((q[4],[]))
        out[-1][1].append(q)
    return out

def parse_v2():
    answers={}
    for key,label,kind,opts,group in V2_QUESTIONS:
        if kind=='multi':
            values=request.form.getlist(key)
            if len(values)!=len(set(values)) or any(v not in opts for v in values):return None
            answers[key]=values
        else:
            val=request.form.get(key,'').strip()
            if len(val)>500 or (kind=='select' and val and val not in opts):return None
            answers[key]=val
    return answers

def v2_form_handler(interview_id=None):
    with conn() as c:
        r=c.execute('SELECT * FROM interviews_v2 WHERE id=?',(interview_id,)).fetchone() if interview_id else None
    if interview_id and not r:abort(404)
    if r and session['role']!='admin' and r['tutor_id']!=session['uid']:abort(403)
    answers=json.loads(r['answers']) if r else {}
    location_code=r['location_code'] if r else ''
    consent=r['consent'] if r else 0
    if request.method=='POST':
        parsed=parse_v2()
        if parsed is None:flash('Jawaban tidak valid. Periksa pilihan.');return redirect(request.path)
        answers=parsed;location_code=request.form.get('location_code','').strip()[:40];consent=int(request.form.get('consent')=='1')
        status='draft' if request.form.get('action')=='draft' else 'complete'
        if not location_code or not consent:
            flash('Kode lokasi dan persetujuan wajib diisi sebelum menyimpan.')
        elif status=='complete' and any((not answers[k]) for k in V2_FIELDS if k not in V2_OPTIONAL):
            flash('Lengkapi semua pertanyaan wajib sebelum menyelesaikan.')
        else:
            now=datetime.now(timezone.utc).isoformat(timespec='seconds')
            with conn() as c:
                if r:c.execute('UPDATE interviews_v2 SET updated_at=?,location_code=?,status=?,answers=?,consent=? WHERE id=?',(now,location_code,status,json.dumps(answers,ensure_ascii=False),consent,interview_id))
                else:c.execute('INSERT INTO interviews_v2(tutor_id,created_at,updated_at,questionnaire_version,location_code,status,answers,consent) VALUES(?,?,?,?,?,?,?,?)',(session['uid'],now,now,V2_VERSION,location_code,status,json.dumps(answers,ensure_ascii=False),consent))
            flash('Wawancara tersimpan sebagai '+('draf.' if status=='draft' else 'selesai.'))
            return redirect(url_for('interviews_v2'))
    return page(V2_CSS+V2_FORM,sections=v2_sections(),answers=answers,optional=V2_OPTIONAL,location_code=location_code,consent=consent)

@app.route('/v2/new',methods=['GET','POST'])
@login_required
def new_interview():return v2_form_handler()

@app.route('/v2/<int:interview_id>',methods=['GET','POST'])
@login_required
def edit_interview(interview_id):return v2_form_handler(interview_id)

@app.route('/v2')
@login_required
def interviews_v2():
    with conn() as c:
        if session['role']=='admin':rows=c.execute('SELECT v.*,u.username FROM interviews_v2 v JOIN users u ON u.id=v.tutor_id ORDER BY v.id DESC LIMIT 150').fetchall()
        else:rows=c.execute('SELECT v.*,u.username FROM interviews_v2 v JOIN users u ON u.id=v.tutor_id WHERE v.tutor_id=? ORDER BY v.id DESC LIMIT 150',(session['uid'],)).fetchall()
    return page(V2_CSS+'''<div class="hero"><h1>Riset Canggihpedia v2</h1><p>Wawancara anonim · Draf tersimpan di server · Dirancang untuk HP tutor</p></div><div class="panel"><a class="btn" href="{{url_for('new_interview')}}">+ Wawancara baru</a><h2>Daftar wawancara</h2><div style="overflow-x:auto"><table><tr><th>ID</th><th>Lokasi</th><th>Status</th><th>Tutor</th><th>Aksi</th></tr>{% for r in rows %}<tr><td>#{{r.id}}</td><td>{{r.location_code}}</td><td>{{'Selesai' if r.status=='complete' else 'Draf'}}</td><td>{{r.username}}</td><td><a href="{{url_for('edit_interview',interview_id=r.id)}}">Buka</a></td></tr>{% else %}<tr><td colspan="5">Belum ada wawancara.</td></tr>{% endfor %}</table></div></div>''',rows=rows)

@app.route('/v2/dashboard')
@admin_required
def dashboard_v2():
    from collections import Counter
    with conn() as c:rows=c.execute("SELECT v.*,u.username FROM interviews_v2 v JOIN users u ON u.id=v.tutor_id WHERE v.status='complete'").fetchall()
    counts={key:Counter() for key in ['grade','access','frequency','challenge','goal','interest','barrier','priority']}
    tutors=Counter()
    for r in rows:
        tutors[r['username']]+=1
        a=json.loads(r['answers'])
        for k in counts:
            val=a.get(k,[] if k in V2_MULTI else '')
            for x in (val if isinstance(val,list) else [val]):
                if x:counts[k][x]+=1
    sections=[('Per tutor',tutors),('Kelas anak',counts['grade']),('Akses perangkat',counts['access']),('Penggunaan komputer',counts['frequency']),('Kesulitan utama',counts['challenge']),('Hasil 3 bulan',counts['goal']),('Minat awal',counts['interest']),('Hambatan',counts['barrier']),('Keterampilan prioritas (multi-pilih)',counts['priority'])]
    return page(V2_CSS+'''<div class="hero"><h1>Dashboard survei v2</h1><p>{{total}} wawancara selesai (draf tidak dihitung)</p></div><div class="panel"><a class="btn" href="{{url_for('export_v2')}}">Ekspor CSV v2</a><p class="muted">Sampel wawancara bukan estimasi seluruh populasi. Pertanyaan multi-pilih dapat berjumlah lebih besar dari total responden.</p></div>{% for title,counts in sections %}<div class="panel"><h2>{{title}}</h2><div style="overflow-x:auto"><table>{% for label,n in counts.most_common() %}<tr><td>{{label}}</td><td>{{n}}</td></tr>{% else %}<tr><td>Belum ada data</td></tr>{% endfor %}</table></div></div>{% endfor %}''',total=len(rows),sections=sections)

@app.route('/v2/export.csv')
@admin_required
def export_v2():
    with conn() as c:rows=c.execute('SELECT v.*,u.username tutor FROM interviews_v2 v JOIN users u ON u.id=v.tutor_id ORDER BY v.id').fetchall()
    buf=io.StringIO();writer=csv.writer(buf)
    writer.writerow(['id','tutor','created_at','updated_at','questionnaire_version','location_code','status',*V2_FIELDS])
    for r in rows:
        a=json.loads(r['answers'])
        vals=[(' | '.join(a.get(k,[])) if isinstance(a.get(k),list) else a.get(k,'')) for k in V2_FIELDS]
        # Avoid spreadsheet formula execution when CSV is opened in Excel.
        vals=[("'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v) for v in vals]
        writer.writerow([r['id'],r['tutor'],r['created_at'],r['updated_at'],r['questionnaire_version'],r['location_code'],r['status'],*vals])
    return Response('\ufeff'+buf.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=canggihpedia_wawancara_v2.csv'})

# Unified, age-appropriate survey.
from collections import Counter
V3_VERSION=3
COMMON=[
 ('device','Perangkat yang tersedia untuk belajar','select',['HP/tablet','Komputer/laptop','Keduanya','Tidak ada','Tidak tahu']),
 ('experience','Seberapa sering menggunakan komputer/laptop dalam sebulan terakhir?','select',['Tidak pernah','1–2 kali','3–7 kali','8 kali atau lebih','Tidak tahu']),
 ('skill','Kemampuan komputer saat ini','select',['Belum pernah mencoba','Masih banyak dibantu','Bisa tugas sederhana sendiri','Sudah cukup mahir','Tidak tahu']),
 ('problem','Kesulitan paling nyata','select',['Belum ada kesempatan praktik','Mouse/keyboard/mengetik','Membuat dokumen/tugas','File dan folder','Menggunakan aplikasi','Tidak ada kesulitan','Tidak tahu']),
 ('needs','Keterampilan yang paling dibutuhkan (maksimal 3)','multi',['Komputer dasar dan mengetik','Word/Excel/PowerPoint','Desain dan kreativitas','Coding/game','AI secara aman','Keamanan internet','Belum tahu']),
 ('outcome','Hasil yang ingin terlihat setelah 3 bulan','select',['Mandiri menggunakan komputer','Mampu membuat tugas/dokumen','Memiliki karya digital','Menguasai keterampilan kerja','Mencoba coding atau AI','Belum tahu']),
 ('interest','Jika ada kelas praktik komputer yang sesuai, bagaimana minatnya?','select',['Sangat ingin tahu','Mungkin tertarik','Belum tertarik','Tidak tertarik']),
 ('barrier','Hambatan utama mengikuti kursus','select',['Biaya','Jadwal','Jarak/transportasi','Belum yakin manfaat','Tidak berminat','Tidak ada hambatan','Lainnya']),
 ('format','Bentuk belajar yang paling sesuai','select',['Reguler mingguan','Kursus singkat per keterampilan','Belum tahu']),
 ('schedule','Waktu yang paling memungkinkan','select',['Hari sekolah sore','Sabtu pagi','Sabtu siang','Minggu','Malam hari','Belum tahu']),
 ('price','Untuk 8 pertemuan/bulan, kisaran anggaran yang nyaman (opsional)','select',['Di bawah Rp100 ribu','Rp100–149 ribu','Rp150–199 ribu','Rp200–249 ribu','Rp250 ribu atau lebih','Belum tahu']),
 ('story','Contoh kebutuhan atau kesulitan, tanpa nama dan identitas (opsional)','text',[]),
]
SEGMENTS={'sd':'Orang tua siswa SD','teen':'Pelajar SMP/SMA/SMK (atau wali)','adult':'Dewasa / umum'}
LEVELS={'sd':['Kelas 1–2 SD','Kelas 3–4 SD','Kelas 5–6 SD'], 'teen':['SMP','SMA','SMK'], 'adult':['Mahasiswa','Bekerja','Usaha mandiri','Mencari kerja','Lainnya']}
with conn() as c:
    old_table=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='interviews_v3'").fetchone()
    new_table=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='surveys'").fetchone()
    if old_table and not new_table:
        c.execute('ALTER TABLE interviews_v3 RENAME TO surveys')
    c.execute('''CREATE TABLE IF NOT EXISTS surveys (id INTEGER PRIMARY KEY,tutor_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,updated_at TEXT NOT NULL,version INTEGER NOT NULL,segment TEXT NOT NULL,level TEXT NOT NULL DEFAULT '',location_code TEXT NOT NULL,consent INTEGER NOT NULL CHECK(consent=1),status TEXT NOT NULL CHECK(status IN ('draft','complete')),answers TEXT NOT NULL)''')
    c.execute('DROP INDEX IF EXISTS idx_v3_tutor')
    c.execute('DROP INDEX IF EXISTS idx_v3_status')
    c.execute('CREATE INDEX IF NOT EXISTS idx_surveys_tutor ON surveys(tutor_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_surveys_status ON surveys(status,segment)')

V3_CSS='''<style>
.hero{background:linear-gradient(125deg,var(--navy),var(--teal));color:#fff;border-radius:16px;padding:24px;margin-bottom:16px}.hero h1{margin:0 0 6px}.hero p{margin:0;color:#e5f7fa}.choice{display:flex;align-items:flex-start;gap:12px;padding:13px;border:1px solid #d5e0ee;border-radius:12px;margin:8px 0;font-weight:500;cursor:pointer}.choice:hover{border-color:#8da9c5;background:#f8fbfd}.choice:has(input:checked){background:#e8f5fb;border-color:#2683a2}.choice input{width:20px;height:20px;flex:none;margin:2px 0 0}fieldset{border:0;padding:0;margin:16px 0}legend{font-weight:700;margin-bottom:7px}.progress-label{display:flex;justify-content:space-between;gap:12px;color:var(--muted);font-size:.86rem;font-weight:700}.steps{display:flex;gap:6px;margin:8px 0 24px}.steps span{height:7px;background:#d7e4f0;flex:1;border-radius:9px}.steps span.on{background:var(--teal)}.wizard{display:none}.wizard.active{display:block}.wizard h2{margin-top:0}.actions{display:flex;align-items:center;gap:8px;margin-top:24px;padding-top:18px;border-top:1px solid var(--line)}.actions button{margin:0}.actions .spacer{flex:1}.error{color:#8b2525;background:#fff0f0;border:1px solid #f0caca;padding:11px 13px;border-radius:9px}.scroll{overflow-x:auto}.form-note{padding:12px 14px;border-left:4px solid #6ba5bd;background:#f1f7fa;border-radius:0 9px 9px 0}.required-note{font-size:.88rem;color:var(--muted);margin:0 0 14px}
@media(max-width:600px){button,.btn{min-height:46px}input,textarea,select{font-size:16px}.actions{display:grid;grid-template-columns:1fr 1fr}.actions .spacer{display:none}.actions button{width:100%}.actions #save-draft{grid-column:1/-1;grid-row:2}.actions:has(#back[style*="none"]) #next{grid-column:1/-1}.hero{padding:20px}.choice{padding:12px}}
</style>'''
V3_FORM='''<div class="hero"><h1>{{'Edit wawancara' if record else 'Wawancara baru'}}</h1><p>Survei kebutuhan belajar digital · sekitar 5 menit</p></div>
<div class="panel"><p class="form-note">Jelaskan tujuan riset dengan jujur dan minta persetujuan. Jangan tulis nama, kontak, alamat, atau identitas anak. Untuk pelajar di bawah umur, wawancarai wali atau dengan izin wali.</p>
{% if error %}<p class="error" role="alert">{{error}}</p>{% endif %}
<form method="post" id="research-form"><input type="hidden" name="_csrf" value="{{csrf()}}">
<div class="progress-label"><span id="step-title">Profil responden</span><span id="step-count">Langkah 1 dari 4</span></div>
<div class="steps" id="stepbars"><span></span><span></span><span></span><span></span></div>
<section class="wizard active"><h2>1. Profil responden</h2>
<p class="required-note">Semua pertanyaan wajib diisi kecuali yang ditandai opsional.</p>
<label for="location_code">Kode lokasi (misalnya SD-A atau RW-01)</label><input id="location_code" name="location_code" maxlength="40" required value="{{loc}}" placeholder="Tanpa nama pribadi">
<label for="segment">Kelompok responden</label><select name="segment" id="segment" required><option value="">Pilih kelompok</option>{% for key,label in segments.items() %}<option value="{{key}}" {% if segment==key %}selected{% endif %}>{{label}}</option>{% endfor %}</select>
<label for="level">Tingkat / kategori</label><select name="level" id="level" required><option value="">Pilih kategori</option></select>
<label class="choice"><input type="checkbox" name="consent" value="1" {% if consent %}checked{% endif %}> <span>Responden telah bersedia diwawancarai dan jawaban anonimnya dicatat.</span></label></section>
<section class="wizard"><h2>2. Kondisi saat ini</h2>{% for key,label,kind,options in questions[:4] %}{{field(key,label,kind,options,answers)|safe}}{% endfor %}</section>
<section class="wizard"><h2>3. Kebutuhan belajar</h2>{% for key,label,kind,options in questions[4:8] %}{{field(key,label,kind,options,answers)|safe}}{% endfor %}</section>
<section class="wizard"><h2>4. Preferensi dan catatan</h2>{% for key,label,kind,options in questions[8:] %}{{field(key,label,kind,options,answers)|safe}}{% endfor %}</section>
<div class="actions"><button type="button" id="back" class="secondary">← Kembali</button><div class="spacer"></div><button type="submit" name="action" value="draft" id="save-draft" class="link-button">Simpan sebagai draf</button><button type="button" id="next">Lanjut →</button><button type="submit" name="action" value="complete" id="finish">Selesaikan wawancara</button></div>
</form></div>
<script>
const levels={{levels|tojson}};let oldLevel={{level|tojson}},sel=document.getElementById('segment'),lvl=document.getElementById('level');
function setLevels(){let previous=lvl.value||oldLevel;lvl.innerHTML='<option value="">Pilih kategori</option>';for(let v of levels[sel.value]||[]){let o=document.createElement('option');o.value=v;o.textContent=v;if(v===previous)o.selected=true;lvl.appendChild(o)}}sel.addEventListener('change',()=>{oldLevel='';setLevels()});setLevels();
let step=0,steps=[...document.querySelectorAll('.wizard')],bars=[...document.querySelectorAll('#stepbars span')],titles=['Profil responden','Kondisi saat ini','Kebutuhan belajar','Preferensi dan catatan'];function show(){steps.forEach((x,i)=>x.classList.toggle('active',i===step));bars.forEach((x,i)=>x.classList.toggle('on',i<=step));document.getElementById('step-title').textContent=titles[step];document.getElementById('step-count').textContent=`Langkah ${step+1} dari 4`;document.getElementById('back').style.display=step?'':'none';document.getElementById('next').style.display=step===3?'none':'';document.getElementById('finish').style.display=step===3?'':'none';window.scrollTo({top:0,behavior:'smooth'})}
function invalid(x,message){x.setCustomValidity(message);x.reportValidity();x.addEventListener('input',()=>x.setCustomValidity(''),{once:true});x.focus();return false}function valid(s){let el=steps[s];for(let x of el.querySelectorAll('[required]')){if(x.type==='checkbox'?!x.checked:!x.value)return invalid(x,'Lengkapi bagian ini sebelum melanjutkan.')}if(s===2&&!el.querySelector('input[name="needs"]:checked'))return invalid(el.querySelector('input[name="needs"]'),'Pilih minimal satu kebutuhan.');return true}
document.getElementById('next').onclick=()=>{if(valid(step)){step++;show()}};document.getElementById('back').onclick=()=>{step--;show()};document.getElementById('research-form').addEventListener('submit',e=>{if(e.submitter?.value==='draft')return;for(let i=0;i<4;i++)if(!valid(i)){e.preventDefault();step=i;show();return}});show();
document.querySelectorAll('input[name="needs"]').forEach(x=>x.addEventListener('change',()=>{let picked=document.querySelectorAll('input[name="needs"]:checked');if(picked.length>3){x.checked=false;x.setCustomValidity('Pilih maksimal tiga kebutuhan.');x.reportValidity();x.setCustomValidity('')}}));
</script>'''
from markupsafe import escape

def field(key,label,kind,options,answers):
    suffix='' if key in ('price','story') else ' *'
    if kind=='multi':
        out=f'<fieldset><legend>{escape(label)}{suffix}</legend>'
        for opt in options:
            checked=' checked' if opt in answers.get(key,[]) else ''
            out+=f'<label class="choice"><input type="checkbox" name="{key}" value="{escape(opt)}"{checked}><span>{escape(opt)}</span></label>'
        return out+'</fieldset>'
    out=f'<label for="{key}">{escape(label)}{suffix}</label>'
    if kind=='text':return out+f'<textarea id="{key}" name="{key}" rows="3" maxlength="400">{escape(answers.get(key,""))}</textarea>'
    out+=f'<select id="{key}" name="{key}"'+('' if key=='price' else ' required')+'><option value="">Pilih jawaban</option>'
    for opt in options:
        selected=' selected' if answers.get(key)==opt else ''
        out+=f'<option value="{escape(opt)}"{selected}>{escape(opt)}</option>'
    return out+'</select>'
app.jinja_env.globals['field']=field

def parse_v3():
    answers={}
    for key,label,kind,opts in COMMON:
        if kind=='multi':
            vals=request.form.getlist(key)
            if len(vals)>3 or len(vals)!=len(set(vals)) or any(x not in opts for x in vals):return None
            answers[key]=vals
        else:
            v=request.form.get(key,'').strip()
            if len(v)>(400 if kind=='text' else 100) or (kind=='select' and v and v not in opts):return None
            answers[key]=v
    return answers

@app.route('/')
@login_required
def research_list():
    with conn() as c:
        rows=c.execute('SELECT v.*,u.username FROM surveys v JOIN users u ON v.tutor_id=u.id '+('' if session['role']=='admin' else 'WHERE v.tutor_id=? ')+'ORDER BY v.id DESC LIMIT 250',() if session['role']=='admin' else (session['uid'],)).fetchall()
    return page(V3_CSS+'''<div class="panel"><div class="page-head"><div><h1>Data wawancara</h1><p class="muted">Survei aktif · data responden disimpan tanpa nama dan nomor telepon.</p></div><a class="btn" href="{{url_for('research_new')}}">+ Wawancara baru</a></div><div class="scroll"><table><thead><tr><th>ID</th><th>Kelompok</th><th>Status</th><th class="hide-mobile">Tutor</th><th><span class="hide-mobile">Aksi</span></th></tr></thead><tbody>{% for r in rows %}<tr><td>#{{r.id}}</td><td>{{segments[r.segment]}}</td><td><span class="status status-{{r.status}}">{{'Selesai' if r.status=='complete' else 'Draf'}}</span></td><td class="hide-mobile">{{r.username}}</td><td><a href="{{url_for('research_edit',rid=r.id)}}" aria-label="Buka wawancara nomor {{r.id}}">Buka</a></td></tr>{% else %}<tr><td class="empty" colspan="5">Belum ada wawancara. Mulai dengan tombol “Wawancara baru”.</td></tr>{% endfor %}</tbody></table></div></div>''',rows=rows,segments=SEGMENTS)

def research_form(rid=None):
    with conn() as c:r=c.execute('SELECT * FROM surveys WHERE id=?',(rid,)).fetchone() if rid else None
    if rid and not r:abort(404)
    if r and session['role']!='admin' and r['tutor_id']!=session['uid']:abort(403)
    answers=json.loads(r['answers']) if r else {}
    segment=r['segment'] if r else '';level=r['level'] if r else '';loc=r['location_code'] if r else '';consent=bool(r['consent']) if r else False;error=None
    if request.method=='POST':
        answers=parse_v3();segment=request.form.get('segment','');level=request.form.get('level','');loc=request.form.get('location_code','').strip();consent=request.form.get('consent')=='1';action=request.form.get('action')
        if answers is None or segment not in SEGMENTS or level not in LEVELS.get(segment,[]) or not (1<=len(loc)<=40) or not consent or action not in ('draft','complete'):
            error='Periksa profil, persetujuan, dan pilihan jawaban.'
            answers=answers or {}
        elif action=='complete' and any(not answers[k] for k,_,_,_ in COMMON if k not in ('price','story')):
            error='Lengkapi seluruh pertanyaan wajib sebelum menyelesaikan.'
        else:
            now=datetime.now(timezone.utc).isoformat(timespec='seconds');payload=json.dumps(answers,ensure_ascii=False)
            with conn() as c:
                if r:c.execute('UPDATE surveys SET updated_at=?,segment=?,level=?,location_code=?,status=?,answers=? WHERE id=?',(now,segment,level,loc,'draft' if action=='draft' else 'complete',payload,rid))
                else:c.execute('INSERT INTO surveys(tutor_id,created_at,updated_at,version,segment,level,location_code,consent,status,answers) VALUES(?,?,?,?,?,?,?,?,?,?)',(session['uid'],now,now,V3_VERSION,segment,level,loc,1,'draft' if action=='draft' else 'complete',payload))
            flash('Wawancara berhasil disimpan.');return redirect(url_for('research_list'))
    return page(V3_CSS+V3_FORM,record=r,questions=COMMON,answers=answers,segments=SEGMENTS,levels=LEVELS,segment=segment,level=level,loc=loc,consent=consent,error=error)

@app.route('/research/new',methods=['GET','POST'])
@login_required
def research_new():return research_form()
@app.route('/research/<int:rid>',methods=['GET','POST'])
@login_required
def research_edit(rid):return research_form(rid)

@app.route('/research/dashboard')
@admin_required
def research_dashboard():
    with conn() as c:rows=c.execute("SELECT v.*,u.username FROM surveys v JOIN users u ON v.tutor_id=u.id WHERE status='complete'").fetchall()
    segments=Counter(r['segment'] for r in rows);by_tutor=Counter(r['username'] for r in rows)
    sections=[]
    for key,label,kind,_ in COMMON:
        if kind=='text':continue
        counts=Counter()
        for r in rows:
            value=json.loads(r['answers']).get(key,[] if kind=='multi' else '')
            for v in (value if isinstance(value,list) else [value]):
                if v:counts[v]+=1
        sections.append((label,counts))
    return page(V3_CSS+'''<div class="hero"><h1>Ringkasan riset</h1><p>{{total}} wawancara selesai · draf tidak dihitung</p></div><div class="panel"><div class="page-head"><div><h2>Hasil survei aktif</h2><p class="muted">Sampel nonacak; hasil menunjukkan pola responden yang diwawancarai, bukan seluruh masyarakat. Total jawaban multi-pilih dapat melebihi jumlah responden.</p><p><a href="{{url_for('users')}}">Kelola akun tutor</a></p></div><a class="btn secondary" href="{{url_for('research_export')}}">Unduh CSV</a></div><h2>Kelompok responden</h2><table>{% for k,n in segments.most_common() %}<tr><td>{{labels[k]}}</td><td>{{n}}</td></tr>{% else %}<tr><td class="empty">Belum ada data selesai</td></tr>{% endfor %}</table><h2>Per tutor</h2><table>{% for k,n in by_tutor.most_common() %}<tr><td>{{k}}</td><td>{{n}}</td></tr>{% else %}<tr><td class="empty">Belum ada data selesai</td></tr>{% endfor %}</table></div>{% for label,counts in sections %}<div class="panel"><h2>{{label}}</h2><table>{% for k,n in counts.most_common() %}<tr><td>{{k}}</td><td>{{n}}</td></tr>{% else %}<tr><td class="empty">Belum ada jawaban</td></tr>{% endfor %}</table></div>{% endfor %}''',total=len(rows),segments=segments,by_tutor=by_tutor,sections=sections,labels=SEGMENTS)

@app.route('/research/export.csv')
@admin_required
def research_export():
    with conn() as c:rows=c.execute('SELECT v.*,u.username tutor FROM surveys v JOIN users u ON v.tutor_id=u.id ORDER BY v.id').fetchall()
    def safe(v):
        v=str(v)
        return "'"+v if v.lstrip().startswith(('=','+','-','@','\t','\r')) else v
    buf=io.StringIO();w=csv.writer(buf)
    w.writerow(['id','tutor','created_at','updated_at','version','segment','level','location_code','status']+[k for k,_,_,_ in COMMON])
    for r in rows:
        a=json.loads(r['answers']);w.writerow([safe(r[k]) for k in ['id','tutor','created_at','updated_at','version','segment','level','location_code','status']]+[safe(' | '.join(a.get(k,[])) if isinstance(a.get(k),list) else a.get(k,'')) for k,_,_,_ in COMMON])
    return Response('\ufeff'+buf.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=canggihpedia_research_v3.csv','Cache-Control':'no-store'})

@app.after_request
def secure_headers(response):
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Cache-Control']='no-store'
    response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; form-action 'self'; base-uri 'self'; frame-ancestors 'none'"
    return response


if __name__=='__main__':
    from waitress import serve
    serve(app,host=os.environ.get('HOST','127.0.0.1'),port=int(os.environ.get('PORT','8080')))
