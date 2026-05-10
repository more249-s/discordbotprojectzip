"""
web_panel.py — لوحة تحكم كاملة للبوت
Flask-based dashboard with full control over the bot
"""

import os
import sys
import datetime
import asyncio
import threading
from functools import wraps

from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify
from config import Config

app = Flask(__name__)
app.secret_key = Config.WEB_PANEL_SECRET or "catbi-secret-2025"

# Reference to the bot (set from main.py)
_bot_ref   = None
_db_module = None
_start_time = datetime.datetime.now(datetime.timezone.utc)

def set_bot(bot, db):
    global _bot_ref, _db_module
    _bot_ref   = bot
    _db_module = db


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def run_async(coro):
    """تشغيل coroutine من thread عادي."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── HTML Template ──────────────────────────────────────────────────────────
BASE_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Cat-Bi Panel</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css" rel="stylesheet">
  <style>
    :root { --accent: #7c5cfc; --dark: #1a1b2e; --card: #16213e; --border: #2a2d4e; }
    body { background: var(--dark); color: #e2e8f0; font-family: 'Segoe UI', sans-serif; }
    .sidebar { background: var(--card); min-height: 100vh; width: 240px; position: fixed; border-left: 1px solid var(--border); }
    .main-content { margin-right: 240px; padding: 24px; }
    .sidebar .nav-link { color: #94a3b8; padding: 10px 20px; border-radius: 8px; margin: 2px 8px; transition: all .2s; }
    .sidebar .nav-link:hover, .sidebar .nav-link.active { background: var(--accent); color: #fff; }
    .sidebar .nav-link i { margin-left: 8px; }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; }
    .stat-card { border-right: 4px solid var(--accent); }
    .stat-num { font-size: 2rem; font-weight: 700; color: var(--accent); }
    .table { color: #e2e8f0; }
    .table th { border-color: var(--border); color: #94a3b8; }
    .table td { border-color: var(--border); }
    .badge-online { background: #22c55e; }
    .badge-offline { background: #ef4444; }
    .log-box { background: #0d0f1a; border-radius: 8px; padding: 16px; max-height: 400px; overflow-y: auto; font-family: monospace; font-size: 13px; }
    .log-INFO { color: #94a3b8; }
    .log-WARN { color: #f59e0b; }
    .log-ERROR { color: #ef4444; }
    .log-OK { color: #22c55e; }
    .btn-accent { background: var(--accent); color: #fff; border: none; }
    .btn-accent:hover { background: #6a4de8; color: #fff; }
    h4 { color: #e2e8f0; }
    .brand { padding: 20px; font-size: 1.3rem; font-weight: 700; color: var(--accent); border-bottom: 1px solid var(--border); }
  </style>
</head>
<body>
<div class="d-flex">
  <div class="sidebar">
    <div class="brand"><i class="bi bi-robot"></i> Cat-Bi Panel</div>
    <nav class="nav flex-column mt-3">
      <a class="nav-link {% if page=='dashboard' %}active{% endif %}" href="/"><i class="bi bi-speedometer2"></i> Dashboard</a>
      <a class="nav-link {% if page=='users' %}active{% endif %}" href="/users"><i class="bi bi-people-fill"></i> المستخدمون</a>
      <a class="nav-link {% if page=='trackers' %}active{% endif %}" href="/trackers"><i class="bi bi-radar"></i> الرادار</a>
      <a class="nav-link {% if page=='sites' %}active{% endif %}" href="/sites"><i class="bi bi-globe2"></i> المواقع المخصصة</a>
      <a class="nav-link {% if page=='logs' %}active{% endif %}" href="/logs"><i class="bi bi-terminal-fill"></i> السجلات</a>
      <hr style="border-color: var(--border);">
      <a class="nav-link text-danger" href="/logout"><i class="bi bi-box-arrow-left"></i> تسجيل الخروج</a>
    </nav>
  </div>
  <div class="main-content flex-fill">
    {% block content %}{% endblock %}
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

DASHBOARD_HTML = BASE_HTML.replace("{% block content %}{% endblock %}", """
<h4 class="mb-4"><i class="bi bi-speedometer2"></i> Dashboard</h4>
<div class="row g-3 mb-4">
  <div class="col-md-3">
    <div class="card stat-card p-3">
      <div class="text-muted small">حالة البوت</div>
      <div class="stat-num mt-1">
        {% if bot_online %}<span class="badge badge-online">🟢 Online</span>{% else %}<span class="badge badge-offline">🔴 Offline</span>{% endif %}
      </div>
    </div>
  </div>
  <div class="col-md-3">
    <div class="card stat-card p-3">
      <div class="text-muted small">المستخدمون</div>
      <div class="stat-num">{{ user_count }}</div>
    </div>
  </div>
  <div class="col-md-3">
    <div class="card stat-card p-3">
      <div class="text-muted small">الرادار (متتبعات)</div>
      <div class="stat-num">{{ tracker_count }}</div>
    </div>
  </div>
  <div class="col-md-3">
    <div class="card stat-card p-3">
      <div class="text-muted small">وقت التشغيل</div>
      <div class="stat-num" style="font-size:1.2rem;">{{ uptime }}</div>
    </div>
  </div>
</div>
<div class="row g-3">
  <div class="col-md-6">
    <div class="card p-3">
      <h6 class="text-muted mb-3"><i class="bi bi-info-circle"></i> معلومات البوت</h6>
      <table class="table table-sm mb-0">
        <tr><td class="text-muted">اسم البوت</td><td>{{ bot_name }}</td></tr>
        <tr><td class="text-muted">السيرفرات</td><td>{{ guild_count }}</td></tr>
        <tr><td class="text-muted">المواقع المخصصة</td><td>{{ custom_sites_count }}</td></tr>
        <tr><td class="text-muted">Gemini Channel</td><td>#{{ gemini_ch }}</td></tr>
      </table>
    </div>
  </div>
  <div class="col-md-6">
    <div class="card p-3">
      <h6 class="text-muted mb-3"><i class="bi bi-activity"></i> آخر السجلات</h6>
      <div class="log-box">
        {% for level, msg, ts in logs %}
        <div class="log-{{ level }}">[{{ ts[:19] }}] {{ msg }}</div>
        {% else %}
        <div class="text-muted">لا توجد سجلات بعد</div>
        {% endfor %}
      </div>
    </div>
  </div>
</div>
""")

USERS_HTML = BASE_HTML.replace("{% block content %}{% endblock %}", """
<div class="d-flex justify-content-between align-items-center mb-4">
  <h4><i class="bi bi-people-fill"></i> إدارة المستخدمين</h4>
</div>
{% if msg %}<div class="alert alert-info">{{ msg }}</div>{% endif %}
<div class="card p-3 mb-3">
  <h6 class="text-muted mb-3">إضافة / تعديل مستخدم</h6>
  <form method="post" action="/users/add" class="row g-2">
    <div class="col-md-4"><input name="user_id" class="form-control bg-dark text-white border-secondary" placeholder="Discord User ID" required></div>
    <div class="col-md-3">
      <select name="rank" class="form-select bg-dark text-white border-secondary">
        <option value="1">👤 User</option>
        <option value="2">⭐ VIP</option>
      </select>
    </div>
    <div class="col-md-3"><input name="note" class="form-control bg-dark text-white border-secondary" placeholder="ملاحظة (اختياري)"></div>
    <div class="col-md-2"><button class="btn btn-accent w-100">إضافة</button></div>
  </form>
</div>
<div class="card p-3">
  <h6 class="text-muted mb-3">المستخدمون المسجّلون</h6>
  <div class="table-responsive">
  <table class="table table-hover">
    <thead><tr><th>User ID</th><th>الرتبة</th><th>ملاحظة</th><th>تاريخ الإضافة</th><th>إجراء</th></tr></thead>
    <tbody>
      {% for uid, rank, note, added in users %}
      <tr>
        <td><code>{{ uid }}</code></td>
        <td>{% if rank>=3 %}👑 Owner{% elif rank==2 %}⭐ VIP{% else %}👤 User{% endif %}</td>
        <td>{{ note or '—' }}</td>
        <td>{{ added[:10] if added else '—' }}</td>
        <td>
          <form method="post" action="/users/remove" style="display:inline">
            <input type="hidden" name="user_id" value="{{ uid }}">
            <button class="btn btn-sm btn-danger" onclick="return confirm('حذف؟')">حذف</button>
          </form>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="5" class="text-center text-muted">لا يوجد مستخدمون</td></tr>
      {% endfor %}
    </tbody>
  </table>
  </div>
</div>
""")

TRACKERS_HTML = BASE_HTML.replace("{% block content %}{% endblock %}", """
<h4 class="mb-4"><i class="bi bi-radar"></i> إدارة الرادار</h4>
{% if msg %}<div class="alert alert-info">{{ msg }}</div>{% endif %}
<div class="card p-3">
  <h6 class="text-muted mb-3">المتتبعات النشطة</h6>
  <div class="table-responsive">
  <table class="table table-hover">
    <thead><tr><th>ID</th><th>العمل</th><th>القناة</th><th>آخر فصل</th><th>الفاصل</th><th>تحميل تلقائي</th><th>آخر فحص</th><th>إجراء</th></tr></thead>
    <tbody>
      {% for tid, gid, cid, url, lch, msg, interval, last, dl in trackers %}
      <tr>
        <td><code>{{ tid }}</code></td>
        <td><a href="{{ url }}" target="_blank" class="text-accent" style="color:var(--accent)">{{ url[-40:] }}</a></td>
        <td><code>{{ cid }}</code></td>
        <td>{{ lch }}</td>
        <td>{{ interval }}h</td>
        <td>{% if dl %}✅{% else %}❌{% endif %}</td>
        <td>{{ last[:16] if last else '—' }}</td>
        <td>
          <form method="post" action="/trackers/remove" style="display:inline">
            <input type="hidden" name="tracker_id" value="{{ tid }}">
            <input type="hidden" name="guild_id" value="{{ gid }}">
            <button class="btn btn-sm btn-danger" onclick="return confirm('حذف؟')">حذف</button>
          </form>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="8" class="text-center text-muted">لا توجد متتبعات</td></tr>
      {% endfor %}
    </tbody>
  </table>
  </div>
</div>
""")

SITES_HTML = BASE_HTML.replace("{% block content %}{% endblock %}", """
<h4 class="mb-4"><i class="bi bi-globe2"></i> المواقع المخصصة</h4>
{% if msg %}<div class="alert alert-info">{{ msg }}</div>{% endif %}
<div class="card p-3 mb-3">
  <h6 class="text-muted mb-3">إضافة موقع يدوياً</h6>
  <form method="post" action="/sites/add" class="row g-2">
    <div class="col-md-5"><input name="domain" class="form-control bg-dark text-white border-secondary" placeholder="domain.com" required></div>
    <div class="col-md-3">
      <select name="site_type" class="form-select bg-dark text-white border-secondary">
        <option value="madara">Madara (WordPress)</option>
        <option value="arabic">Arabic</option>
        <option value="generic">Generic</option>
      </select>
    </div>
    <div class="col-md-2"><input name="notes" class="form-control bg-dark text-white border-secondary" placeholder="ملاحظة"></div>
    <div class="col-md-2"><button class="btn btn-accent w-100">إضافة</button></div>
  </form>
</div>
<div class="card p-3">
  <h6 class="text-muted mb-3">المواقع المضافة</h6>
  <div class="table-responsive">
  <table class="table table-hover">
    <thead><tr><th>الدومين</th><th>النوع</th><th>أضيف بواسطة</th><th>التاريخ</th><th>ملاحظة</th><th>إجراء</th></tr></thead>
    <tbody>
      {% for domain, stype, by, at, notes in sites %}
      <tr>
        <td><code>{{ domain }}</code></td>
        <td><span class="badge bg-secondary">{{ stype }}</span></td>
        <td><code>{{ by }}</code></td>
        <td>{{ at[:10] if at else '—' }}</td>
        <td>{{ notes or '—' }}</td>
        <td>
          <form method="post" action="/sites/remove" style="display:inline">
            <input type="hidden" name="domain" value="{{ domain }}">
            <button class="btn btn-sm btn-danger" onclick="return confirm('حذف؟')">حذف</button>
          </form>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="6" class="text-center text-muted">لا توجد مواقع مخصصة</td></tr>
      {% endfor %}
    </tbody>
  </table>
  </div>
</div>
""")

LOGS_HTML = BASE_HTML.replace("{% block content %}{% endblock %}", """
<div class="d-flex justify-content-between align-items-center mb-4">
  <h4><i class="bi bi-terminal-fill"></i> سجلات البوت</h4>
  <button onclick="location.reload()" class="btn btn-accent btn-sm"><i class="bi bi-arrow-clockwise"></i> تحديث</button>
</div>
<div class="card p-3">
  <div class="log-box" id="logbox">
    {% for level, msg, ts in logs %}
    <div class="log-{{ level }}">[{{ ts[:19] }}] [{{ level }}] {{ msg }}</div>
    {% else %}
    <div class="text-muted">لا توجد سجلات</div>
    {% endfor %}
  </div>
</div>
<script>
  var lb = document.getElementById('logbox');
  lb.scrollTop = lb.scrollHeight;
  setTimeout(function(){ location.reload(); }, 15000);
</script>
""")

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <title>Cat-Bi — تسجيل الدخول</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background: #1a1b2e; display:flex; align-items:center; justify-content:center; min-height:100vh; }
    .login-card { background:#16213e; border:1px solid #2a2d4e; border-radius:16px; padding:40px; min-width:360px; }
    h3 { color:#7c5cfc; }
    .form-control { background:#0d0f1a; color:#e2e8f0; border-color:#2a2d4e; }
    .btn-accent { background:#7c5cfc; color:#fff; border:none; }
    .btn-accent:hover { background:#6a4de8; color:#fff; }
    .alert { background:#2a2d4e; color:#e2e8f0; border:none; }
  </style>
</head>
<body>
<div class="login-card text-center">
  <h3 class="mb-4">🤖 Cat-Bi Panel</h3>
  {% if error %}<div class="alert alert-danger mb-3">{{ error }}</div>{% endif %}
  <form method="post">
    <input type="password" name="password" class="form-control mb-3 text-center" placeholder="كلمة المرور" required>
    <button class="btn btn-accent w-100">دخول</button>
  </form>
</div>
</body>
</html>
"""


# ── Routes ─────────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == Config.WEB_PANEL_SECRET:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        return render_template_string(LOGIN_HTML, error="كلمة المرور خاطئة")
    return render_template_string(LOGIN_HTML, error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    bot_online = _bot_ref is not None and not _bot_ref.is_closed()
    bot_name   = str(_bot_ref.user) if bot_online else "غير متصل"
    guild_count = len(_bot_ref.guilds) if bot_online else 0

    user_count       = run_async(_db_module.get_user_count())      if _db_module else 0
    tracker_count    = run_async(_db_module.get_tracker_count())   if _db_module else 0
    custom_sites     = run_async(_db_module.get_custom_sites())    if _db_module else []
    logs             = run_async(_db_module.get_recent_logs(10))   if _db_module else []

    uptime = str(datetime.datetime.now(datetime.timezone.utc) - _start_time).split(".")[0]

    return render_template_string(DASHBOARD_HTML,
        page="dashboard", bot_online=bot_online, bot_name=bot_name,
        guild_count=guild_count, user_count=user_count,
        tracker_count=tracker_count, custom_sites_count=len(custom_sites),
        gemini_ch=Config.GEMINI_CHANNEL_ID, uptime=uptime, logs=logs,
    )


@app.route("/users")
@login_required
def users_page():
    users = run_async(_db_module.get_all_users()) if _db_module else []
    return render_template_string(USERS_HTML, page="users", users=users, msg=request.args.get("msg"))


@app.route("/users/add", methods=["POST"])
@login_required
def users_add():
    uid  = request.form.get("user_id", "").strip()
    rank = int(request.form.get("rank", 1))
    note = request.form.get("note", "").strip()
    if uid.isdigit():
        run_async(_db_module.set_user_rank(int(uid), rank, note or "Added via panel"))
    return redirect(url_for("users_page", msg="تم إضافة المستخدم"))


@app.route("/users/remove", methods=["POST"])
@login_required
def users_remove():
    uid = request.form.get("user_id", "").strip()
    if uid.isdigit():
        run_async(_db_module.remove_user(int(uid)))
    return redirect(url_for("users_page", msg="تم حذف المستخدم"))


@app.route("/trackers")
@login_required
def trackers_page():
    trackers = run_async(_db_module.get_all_trackers()) if _db_module else []
    return render_template_string(TRACKERS_HTML, page="trackers", trackers=trackers, msg=request.args.get("msg"))


@app.route("/trackers/remove", methods=["POST"])
@login_required
def trackers_remove():
    tid = int(request.form.get("tracker_id", 0))
    gid = int(request.form.get("guild_id", 0))
    run_async(_db_module.remove_tracker(tid, gid))
    return redirect(url_for("trackers_page", msg="تم حذف المتتبع"))


@app.route("/sites")
@login_required
def sites_page():
    sites = run_async(_db_module.get_custom_sites()) if _db_module else []
    return render_template_string(SITES_HTML, page="sites", sites=sites, msg=request.args.get("msg"))


@app.route("/sites/add", methods=["POST"])
@login_required
def sites_add():
    domain    = request.form.get("domain", "").strip().lower()
    site_type = request.form.get("site_type", "madara")
    notes     = request.form.get("notes", "").strip()
    if domain:
        run_async(_db_module.add_custom_site(domain, site_type, 0, notes or "Added via panel"))
    return redirect(url_for("sites_page", msg=f"تم إضافة {domain}"))


@app.route("/sites/remove", methods=["POST"])
@login_required
def sites_remove():
    domain = request.form.get("domain", "").strip()
    if domain:
        run_async(_db_module.remove_custom_site(domain))
    return redirect(url_for("sites_page", msg=f"تم حذف {domain}"))


@app.route("/logs")
@login_required
def logs_page():
    logs = run_async(_db_module.get_recent_logs(200)) if _db_module else []
    return render_template_string(LOGS_HTML, page="logs", logs=logs)


@app.route("/health")
def health():
    bot_ok = _bot_ref is not None and not _bot_ref.is_closed()
    return jsonify({"status": "ok" if bot_ok else "starting", "bot": bot_ok}), 200


def run_panel(port: int = 8080):
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def start_panel(bot, db, port: int = 8080):
    set_bot(bot, db)
    t = threading.Thread(target=run_panel, args=(port,), daemon=True)
    t.start()
    return t
