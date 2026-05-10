"""
web_panel.py — لوحة تحكم Cat-Bi الاحترافية
تصميم كامل + تحكم بالبوت (restart/stop/status)
"""

import os
import sys
import datetime
import asyncio
import signal
import threading
import time
from functools import wraps

from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify
from config import Config

app = Flask(__name__)
app.secret_key = Config.WEB_PANEL_SECRET or "catbi-secret-2025"

_bot_ref    = None
_db_module  = None
_start_time = datetime.datetime.now(datetime.timezone.utc)
_dl_count   = 0     # عداد التحميلات (يُزاد من main.py)


def set_bot(bot, db):
    global _bot_ref, _db_module
    _bot_ref   = bot
    _db_module = db


def inc_download():
    global _dl_count
    _dl_count += 1


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ══════════════════════════════════════════════════════════════
#  HTML — الواجهة الكاملة
# ══════════════════════════════════════════════════════════════
LOGIN_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8"><title>Cat-Bi Panel</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">
  <style>
    :root{--acc:#7c5cfc;--dark:#0e0f1a;--card:#16213e;--bdr:#2a2d4e}
    body{background:linear-gradient(135deg,#0e0f1a 0%,#1a1b3e 100%);min-height:100vh;
         display:flex;align-items:center;justify-content:center;font-family:'Segoe UI',sans-serif}
    .card{background:rgba(22,33,62,.95);border:1px solid var(--bdr);border-radius:20px;
          padding:40px;width:360px;box-shadow:0 20px 60px rgba(0,0,0,.5);backdrop-filter:blur(10px)}
    .brand{font-size:1.8rem;font-weight:800;color:var(--acc)}
    .form-control{background:#0d1020;color:#e2e8f0;border:1px solid var(--bdr);border-radius:10px;padding:12px}
    .form-control:focus{background:#0d1020;color:#e2e8f0;border-color:var(--acc);box-shadow:0 0 0 3px rgba(124,92,252,.25)}
    .btn-acc{background:linear-gradient(135deg,#7c5cfc,#6a4de8);color:#fff;border:none;
             border-radius:10px;padding:12px;font-weight:600;transition:.3s;width:100%}
    .btn-acc:hover{transform:translateY(-2px);box-shadow:0 8px 20px rgba(124,92,252,.4);color:#fff}
    .alert{background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.3);
           color:#fca5a5;border-radius:10px}
  </style>
</head>
<body>
<div class="card text-center">
  <div class="brand mb-2">🤖 Cat-Bi</div>
  <p class="text-muted mb-4" style="font-size:.9rem">لوحة تحكم البوت</p>
  {% if error %}<div class="alert mb-3 py-2">{{ error }}</div>{% endif %}
  <form method="post">
    <input type="password" name="password" class="form-control mb-3 text-center"
           placeholder="كلمة المرور" autocomplete="current-password" required>
    <button class="btn btn-acc">دخول <i class="bi bi-arrow-left-circle ms-1"></i></button>
  </form>
</div>
</body></html>"""


BASE_LAYOUT = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8"><title>Cat-Bi Panel — {page_title}</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">
  <style>
    :root{{--acc:#7c5cfc;--acc2:#6a4de8;--dark:#0e0f1a;--card:#111827;--card2:#1f2937;--bdr:#2a2d4e;
           --green:#22c55e;--red:#ef4444;--gold:#f59e0b;--blue:#3b82f6}}
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:var(--dark);color:#e2e8f0;font-family:'Segoe UI',sans-serif;display:flex;min-height:100vh}}

    /* ── Sidebar ── */
    .sidebar{{width:240px;min-height:100vh;background:var(--card);border-left:1px solid var(--bdr);
               position:fixed;top:0;right:0;z-index:100;display:flex;flex-direction:column}}
    .sidebar-brand{{padding:20px 16px;border-bottom:1px solid var(--bdr)}}
    .sidebar-brand .logo{{font-size:1.4rem;font-weight:800;color:var(--acc)}}
    .sidebar-brand .sub{{font-size:.75rem;color:#64748b;margin-top:2px}}
    .sidebar-status{{margin:10px 12px;background:var(--card2);border-radius:10px;padding:10px 12px;
                      font-size:.8rem;display:flex;align-items:center;gap:8px}}
    .dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0}}
    .dot.online{{background:var(--green);box-shadow:0 0 6px var(--green)}}
    .dot.offline{{background:var(--red);box-shadow:0 0 6px var(--red)}}
    .nav-section{{padding:10px 12px 4px;font-size:.7rem;color:#4b5563;text-transform:uppercase;
                   letter-spacing:.05em;font-weight:600}}
    .nav-link{{display:flex;align-items:center;gap:10px;padding:9px 16px;color:#94a3b8;
               border-radius:10px;margin:1px 8px;transition:.2s;font-size:.9rem;text-decoration:none}}
    .nav-link i{{font-size:1.1rem;width:20px;text-align:center}}
    .nav-link:hover{{background:rgba(124,92,252,.12);color:#c4b5fd}}
    .nav-link.active{{background:linear-gradient(135deg,rgba(124,92,252,.25),rgba(124,92,252,.1));
                       color:#a78bfa;border-right:3px solid var(--acc)}}
    .sidebar-footer{{margin-top:auto;padding:12px 8px;border-top:1px solid var(--bdr)}}

    /* ── Main ── */
    .main{{margin-right:240px;padding:24px;flex:1;min-width:0}}
    .page-header{{margin-bottom:24px}}
    .page-header h1{{font-size:1.5rem;font-weight:700;display:flex;align-items:center;gap:10px}}
    .page-header .breadcrumb{{font-size:.8rem;color:#64748b;margin-top:4px}}

    /* ── Cards ── */
    .card{{background:var(--card);border:1px solid var(--bdr);border-radius:14px}}
    .card-body{{padding:20px}}
    .card-title{{font-size:.85rem;color:#64748b;font-weight:500;text-transform:uppercase;
                  letter-spacing:.05em;margin-bottom:8px}}

    /* ── Stat Cards ── */
    .stat-card{{border-radius:14px;padding:20px;position:relative;overflow:hidden}}
    .stat-card::before{{content:'';position:absolute;top:0;left:0;right:0;bottom:0;opacity:.1;border-radius:14px}}
    .stat-card.purple{{background:linear-gradient(135deg,rgba(124,92,252,.15),rgba(124,92,252,.05));
                        border:1px solid rgba(124,92,252,.3)}}
    .stat-card.green{{background:linear-gradient(135deg,rgba(34,197,94,.15),rgba(34,197,94,.05));
                       border:1px solid rgba(34,197,94,.3)}}
    .stat-card.blue{{background:linear-gradient(135deg,rgba(59,130,246,.15),rgba(59,130,246,.05));
                      border:1px solid rgba(59,130,246,.3)}}
    .stat-card.gold{{background:linear-gradient(135deg,rgba(245,158,11,.15),rgba(245,158,11,.05));
                      border:1px solid rgba(245,158,11,.3)}}
    .stat-num{{font-size:2.2rem;font-weight:800;line-height:1}}
    .stat-label{{font-size:.8rem;color:#94a3b8;margin-top:6px}}
    .stat-icon{{font-size:2rem;opacity:.3;position:absolute;left:16px;top:50%;transform:translateY(-50%)}}

    /* ── Bot Controls ── */
    .ctrl-btn{{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:10px;
               font-size:.85rem;font-weight:600;border:none;cursor:pointer;transition:.2s}}
    .ctrl-btn:hover{{transform:translateY(-1px);box-shadow:0 4px 12px rgba(0,0,0,.3)}}
    .ctrl-restart{{background:rgba(245,158,11,.15);color:var(--gold);border:1px solid rgba(245,158,11,.3)}}
    .ctrl-stop{{background:rgba(239,68,68,.15);color:var(--red);border:1px solid rgba(239,68,68,.3)}}
    .ctrl-sync{{background:rgba(59,130,246,.15);color:var(--blue);border:1px solid rgba(59,130,246,.3)}}

    /* ── Tables ── */
    .table{{color:#e2e8f0}}
    .table th{{border-color:var(--bdr);color:#64748b;font-size:.8rem;text-transform:uppercase;
               letter-spacing:.05em;font-weight:500}}
    .table td{{border-color:var(--bdr);vertical-align:middle}}
    .table tbody tr:hover{{background:rgba(124,92,252,.04)}}

    /* ── Forms ── */
    .form-control,.form-select{{background:#0d1020;color:#e2e8f0;border:1px solid var(--bdr);
                                 border-radius:8px}}
    .form-control:focus,.form-select:focus{{background:#0d1020;color:#e2e8f0;border-color:var(--acc);
                                             box-shadow:0 0 0 3px rgba(124,92,252,.2)}}
    .form-select option{{background:#1a1b2e}}
    .btn-acc{{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;border:none;
              border-radius:8px;padding:8px 16px;font-weight:600;transition:.2s}}
    .btn-acc:hover{{transform:translateY(-1px);box-shadow:0 4px 12px rgba(124,92,252,.4);color:#fff}}
    .btn-danger-soft{{background:rgba(239,68,68,.12);color:var(--red);border:1px solid rgba(239,68,68,.25);
                       border-radius:8px;padding:4px 10px;font-size:.8rem;transition:.2s}}
    .btn-danger-soft:hover{{background:rgba(239,68,68,.25)}}

    /* ── Badges ── */
    .badge-online{{background:rgba(34,197,94,.2);color:var(--green);border:1px solid rgba(34,197,94,.3);
                    padding:3px 10px;border-radius:20px;font-size:.75rem}}
    .badge-offline{{background:rgba(239,68,68,.2);color:var(--red);border:1px solid rgba(239,68,68,.3);
                     padding:3px 10px;border-radius:20px;font-size:.75rem}}
    .badge-rank{{padding:3px 10px;border-radius:20px;font-size:.75rem}}
    .badge-owner{{background:rgba(245,158,11,.2);color:var(--gold);border:1px solid rgba(245,158,11,.3)}}
    .badge-vip{{background:rgba(124,92,252,.2);color:#a78bfa;border:1px solid rgba(124,92,252,.3)}}
    .badge-user{{background:rgba(59,130,246,.2);color:#93c5fd;border:1px solid rgba(59,130,246,.3)}}
    .badge-site{{background:rgba(34,197,94,.15);color:#86efac;border:1px solid rgba(34,197,94,.25);
                  padding:2px 8px;border-radius:6px;font-size:.75rem}}

    /* ── Logs ── */
    .log-box{{background:#080a10;border:1px solid var(--bdr);border-radius:10px;padding:14px;
               max-height:420px;overflow-y:auto;font-family:'Consolas',monospace;font-size:.78rem}}
    .log-OK{{color:#4ade80}}.log-INFO{{color:#94a3b8}}.log-WARN{{color:#fbbf24}}.log-ERROR{{color:#f87171}}
    .log-box::-webkit-scrollbar{{width:6px}}
    .log-box::-webkit-scrollbar-track{{background:transparent}}
    .log-box::-webkit-scrollbar-thumb{{background:var(--bdr);border-radius:3px}}

    /* ── Toast ── */
    .toast-container{{position:fixed;bottom:20px;left:20px;z-index:9999}}
    .toast{{background:var(--card2);border:1px solid var(--bdr);color:#e2e8f0;border-radius:10px;
             font-size:.85rem}}

    /* ── Divider ── */
    hr{{border-color:var(--bdr)}}
    code{{background:rgba(124,92,252,.15);color:#c4b5fd;padding:2px 6px;border-radius:4px;font-size:.85rem}}
    .text-muted{{color:#64748b!important}}
  </style>
</head>
<body>
<!-- Sidebar -->
<div class="sidebar">
  <div class="sidebar-brand">
    <div class="logo">🤖 Cat-Bi</div>
    <div class="sub">Manga Bot Control Panel</div>
  </div>
  <div class="sidebar-status">
    <div class="dot {status_dot}"></div>
    <span style="font-size:.8rem;color:#94a3b8">{status_txt}</span>
  </div>
  <div class="nav-section">الرئيسية</div>
  <a class="nav-link {a_dash}" href="/"><i class="bi bi-speedometer2"></i> Dashboard</a>
  <div class="nav-section">إدارة</div>
  <a class="nav-link {a_users}" href="/users"><i class="bi bi-people-fill"></i> المستخدمون</a>
  <a class="nav-link {a_trackers}" href="/trackers"><i class="bi bi-radar"></i> الرادار</a>
  <a class="nav-link {a_sites}" href="/sites"><i class="bi bi-globe2"></i> المواقع</a>
  <div class="nav-section">النظام</div>
  <a class="nav-link {a_logs}" href="/logs"><i class="bi bi-terminal-fill"></i> السجلات</a>
  <div class="sidebar-footer">
    <a class="nav-link text-danger" href="/logout"><i class="bi bi-box-arrow-left"></i> خروج</a>
  </div>
</div>

<!-- Main -->
<div class="main">
  {msg_html}
  {content}
</div>

<!-- Toast container -->
<div class="toast-container" id="toastContainer"></div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
function showToast(msg, type='success') {{
  var tc = document.getElementById('toastContainer');
  var id = 'toast_' + Date.now();
  var color = type==='success' ? '#4ade80' : type==='error' ? '#f87171' : '#fbbf24';
  tc.innerHTML += '<div id="'+id+'" class="toast show" style="border-left:3px solid '+color+'">'+
    '<div class="toast-body d-flex align-items-center gap-2"><span>'+msg+'</span></div></div>';
  setTimeout(function(){{ var el=document.getElementById(id); if(el) el.remove(); }}, 3000);
}}
function botAction(action) {{
  fetch('/bot/'+action, {{method:'POST'}})
    .then(r=>r.json()).then(d=>{{
      showToast(d.message || action, d.ok ? 'success' : 'error');
      if(action==='restart') setTimeout(()=>location.reload(), 5000);
    }}).catch(()=>showToast('خطأ في الاتصال','error'));
}}
</script>
</body></html>"""


def _render(page: str, content: str, msg: str = "", **extra):
    active = {"a_dash": "", "a_users": "", "a_trackers": "", "a_sites": "", "a_logs": ""}
    active[f"a_{page}"] = "active"

    bot_ok   = _bot_ref is not None and not _bot_ref.is_closed()
    status_dot = "online" if bot_ok else "offline"
    status_txt = (_bot_ref.user.name if bot_ok else "غير متصل") if _bot_ref else "جاري التحميل..."

    msg_html = ""
    if msg:
        kind = "success" if not msg.startswith("❌") else "danger"
        msg_html = f'<div class="alert alert-{kind} alert-dismissible fade show" role="alert">{msg}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>'

    page_titles = {
        "dash": "Dashboard", "users": "المستخدمون",
        "trackers": "الرادار", "sites": "المواقع", "logs": "السجلات"
    }

    return BASE_LAYOUT.format(
        page_title=page_titles.get(page, "Cat-Bi"),
        status_dot=status_dot, status_txt=status_txt,
        msg_html=msg_html, content=content,
        **active
    )


# ══════════════════════════════════════════════════════════════
#  Auth Routes
# ══════════════════════════════════════════════════════════════
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == Config.WEB_PANEL_SECRET:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        return render_template_string(LOGIN_HTML, error="❌ كلمة المرور خاطئة")
    return render_template_string(LOGIN_HTML, error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ══════════════════════════════════════════════════════════════
#  Bot Control API
# ══════════════════════════════════════════════════════════════
@app.route("/bot/restart", methods=["POST"])
@login_required
def bot_restart():
    def _do_restart():
        time.sleep(0.8)
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=_do_restart, daemon=True).start()
    return jsonify({"ok": True, "message": "🔄 البوت سيُعاد تشغيله خلال ثوانٍ..."})


@app.route("/bot/stop", methods=["POST"])
@login_required
def bot_stop():
    if _bot_ref and not _bot_ref.is_closed():
        asyncio.run_coroutine_threadsafe(_bot_ref.close(), _bot_ref.loop)
    return jsonify({"ok": True, "message": "⏹️ تم إيقاف البوت"})


@app.route("/health")
def health():
    bot_ok = _bot_ref is not None and not _bot_ref.is_closed()
    return jsonify({"status": "ok" if bot_ok else "starting", "bot": bot_ok}), 200


# ══════════════════════════════════════════════════════════════
#  Dashboard
# ══════════════════════════════════════════════════════════════
@app.route("/")
@login_required
def dashboard():
    bot_ok      = _bot_ref is not None and not _bot_ref.is_closed()
    bot_name    = str(_bot_ref.user) if bot_ok else "—"
    guild_count = len(_bot_ref.guilds) if bot_ok else 0
    uptime      = str(datetime.datetime.now(datetime.timezone.utc) - _start_time).split(".")[0]

    user_count    = run_async(_db_module.get_user_count())   if _db_module else 0
    tracker_count = run_async(_db_module.get_tracker_count()) if _db_module else 0
    custom_sites  = run_async(_db_module.get_custom_sites()) if _db_module else []
    logs          = run_async(_db_module.get_recent_logs(12)) if _db_module else []

    content = f"""
<div class="page-header">
  <h1><i class="bi bi-speedometer2"></i> Dashboard</h1>
  <div class="breadcrumb">نظرة عامة على حالة البوت</div>
</div>

<!-- Bot Controls -->
<div class="card mb-4">
  <div class="card-body">
    <div class="d-flex align-items-center justify-content-between flex-wrap gap-3">
      <div class="d-flex align-items-center gap-3">
        <div>
          <div style="font-weight:700;font-size:1.1rem">{bot_name}</div>
          <div class="text-muted" style="font-size:.8rem">Discord Bot</div>
        </div>
        {'<span class="badge-online">🟢 Online</span>' if bot_ok else '<span class="badge-offline">🔴 Offline</span>'}
      </div>
      <div class="d-flex gap-2">
        <button class="ctrl-btn ctrl-restart" onclick="botAction('restart')">
          <i class="bi bi-arrow-clockwise"></i> Restart
        </button>
        <button class="ctrl-btn ctrl-stop" onclick="botAction('stop')">
          <i class="bi bi-stop-circle"></i> Stop
        </button>
      </div>
    </div>
  </div>
</div>

<!-- Stats -->
<div class="row g-3 mb-4">
  <div class="col-6 col-lg-3">
    <div class="stat-card purple">
      <i class="bi bi-people-fill stat-icon" style="color:#a78bfa"></i>
      <div class="stat-num" style="color:#a78bfa">{user_count}</div>
      <div class="stat-label">المستخدمون</div>
    </div>
  </div>
  <div class="col-6 col-lg-3">
    <div class="stat-card green">
      <i class="bi bi-radar stat-icon" style="color:#4ade80"></i>
      <div class="stat-num" style="color:#4ade80">{tracker_count}</div>
      <div class="stat-label">متتبعات الرادار</div>
    </div>
  </div>
  <div class="col-6 col-lg-3">
    <div class="stat-card blue">
      <i class="bi bi-globe2 stat-icon" style="color:#93c5fd"></i>
      <div class="stat-num" style="color:#93c5fd">{len(custom_sites)}</div>
      <div class="stat-label">مواقع مخصصة</div>
    </div>
  </div>
  <div class="col-6 col-lg-3">
    <div class="stat-card gold">
      <i class="bi bi-server stat-icon" style="color:#fbbf24"></i>
      <div class="stat-num" style="color:#fbbf24">{guild_count}</div>
      <div class="stat-label">السيرفرات</div>
    </div>
  </div>
</div>

<!-- Info + Logs -->
<div class="row g-3">
  <div class="col-md-5">
    <div class="card h-100">
      <div class="card-body">
        <div class="card-title"><i class="bi bi-info-circle"></i> معلومات النظام</div>
        <table class="table table-sm mb-0">
          <tr><td class="text-muted">وقت التشغيل</td><td><code>{uptime}</code></td></tr>
          <tr><td class="text-muted">التحميلات</td><td><code>{_dl_count}</code></td></tr>
          <tr><td class="text-muted">Gemini Channel</td><td><code>#{Config.GEMINI_CHANNEL_ID}</code></td></tr>
          <tr><td class="text-muted">Guild ID</td><td><code>{Config.GUILD_ID or 'Global'}</code></td></tr>
        </table>
      </div>
    </div>
  </div>
  <div class="col-md-7">
    <div class="card h-100">
      <div class="card-body">
        <div class="d-flex justify-content-between align-items-center mb-2">
          <div class="card-title mb-0"><i class="bi bi-activity"></i> آخر السجلات</div>
          <a href="/logs" style="color:#a78bfa;font-size:.8rem">عرض الكل →</a>
        </div>
        <div class="log-box">
          {''.join(f'<div class="log-{lv}">[{ts[:19]}] {msg}</div>' for lv,msg,ts in logs) or '<span class="text-muted">لا توجد سجلات</span>'}
        </div>
      </div>
    </div>
  </div>
</div>
"""
    return _render("dash", content)


# ══════════════════════════════════════════════════════════════
#  Users
# ══════════════════════════════════════════════════════════════
@app.route("/users")
@login_required
def users_page():
    users = run_async(_db_module.get_all_users()) if _db_module else []
    msg   = request.args.get("msg", "")

    def rank_badge(rank):
        if rank >= 3: return '<span class="badge-rank badge-owner">👑 Owner</span>'
        if rank == 2: return '<span class="badge-rank badge-vip">⭐ VIP</span>'
        return '<span class="badge-rank badge-user">👤 User</span>'

    rows = "".join(f"""
      <tr>
        <td><code>{uid}</code></td>
        <td>{rank_badge(rank)}</td>
        <td class="text-muted">{note or '—'}</td>
        <td class="text-muted" style="font-size:.8rem">{(added or '')[:10]}</td>
        <td>
          <form method="post" action="/users/remove" style="display:inline">
            <input type="hidden" name="user_id" value="{uid}">
            <button class="btn-danger-soft" onclick="return confirm('حذف المستخدم {uid}؟')">
              <i class="bi bi-trash3"></i>
            </button>
          </form>
        </td>
      </tr>""" for uid,rank,note,added in users) or '<tr><td colspan="5" class="text-center text-muted py-3">لا يوجد مستخدمون</td></tr>'

    content = f"""
<div class="page-header">
  <h1><i class="bi bi-people-fill"></i> المستخدمون</h1>
  <div class="breadcrumb">{len(users)} مستخدم مسجّل</div>
</div>
<div class="card mb-3">
  <div class="card-body">
    <div class="card-title"><i class="bi bi-person-plus"></i> إضافة / تعديل مستخدم</div>
    <form method="post" action="/users/add">
      <div class="row g-2">
        <div class="col-md-4">
          <input name="user_id" class="form-control" placeholder="Discord User ID" required>
        </div>
        <div class="col-md-3">
          <select name="rank" class="form-select">
            <option value="1">👤 User</option>
            <option value="2">⭐ VIP</option>
          </select>
        </div>
        <div class="col-md-3">
          <input name="note" class="form-control" placeholder="ملاحظة (اختياري)">
        </div>
        <div class="col-md-2">
          <button class="btn btn-acc w-100">إضافة</button>
        </div>
      </div>
    </form>
  </div>
</div>
<div class="card">
  <div class="card-body">
    <div class="table-responsive">
      <table class="table table-hover mb-0">
        <thead><tr>
          <th>User ID</th><th>الرتبة</th><th>ملاحظة</th><th>تاريخ الإضافة</th><th>إجراء</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </div>
</div>"""
    return _render("users", content, msg)


@app.route("/users/add", methods=["POST"])
@login_required
def users_add():
    uid  = request.form.get("user_id", "").strip()
    rank = int(request.form.get("rank", 1))
    note = request.form.get("note", "").strip()
    if uid.isdigit():
        run_async(_db_module.set_user_rank(int(uid), rank, note or "Added via panel"))
    return redirect(url_for("users_page", msg="✅ تم إضافة المستخدم"))


@app.route("/users/remove", methods=["POST"])
@login_required
def users_remove():
    uid = request.form.get("user_id", "").strip()
    if uid.isdigit():
        run_async(_db_module.remove_user(int(uid)))
    return redirect(url_for("users_page", msg="🗑️ تم حذف المستخدم"))


# ══════════════════════════════════════════════════════════════
#  Trackers
# ══════════════════════════════════════════════════════════════
@app.route("/trackers")
@login_required
def trackers_page():
    trackers = run_async(_db_module.get_all_trackers()) if _db_module else []
    msg      = request.args.get("msg", "")

    rows = "".join(f"""
      <tr>
        <td><code>{tid}</code></td>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis">
          <a href="{url}" target="_blank" style="color:#a78bfa;font-size:.85rem">{url[-45:]}</a>
        </td>
        <td><code style="font-size:.75rem">{cid}</code></td>
        <td><code>{lch}</code></td>
        <td><span class="badge-site">{interval}h</span></td>
        <td>{'✅' if dl else '❌'}</td>
        <td style="font-size:.75rem;color:#64748b">{(last or '')[:16]}</td>
        <td>
          <form method="post" action="/trackers/remove" style="display:inline">
            <input type="hidden" name="tracker_id" value="{tid}">
            <input type="hidden" name="guild_id" value="{gid}">
            <button class="btn-danger-soft" onclick="return confirm('حذف المتتبع {tid}؟')">
              <i class="bi bi-trash3"></i>
            </button>
          </form>
        </td>
      </tr>""" for tid,gid,cid,url,lch,cmsg,interval,last,dl in trackers) or '<tr><td colspan="8" class="text-center text-muted py-3">لا توجد متتبعات</td></tr>'

    content = f"""
<div class="page-header">
  <h1><i class="bi bi-radar"></i> الرادار</h1>
  <div class="breadcrumb">{len(trackers)} متتبعة نشطة</div>
</div>
<div class="card">
  <div class="card-body">
    <div class="table-responsive">
      <table class="table table-hover mb-0" style="font-size:.88rem">
        <thead><tr>
          <th>ID</th><th>الرابط</th><th>القناة</th><th>آخر فصل</th>
          <th>الفاصل</th><th>تحميل</th><th>آخر فحص</th><th>حذف</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </div>
</div>"""
    return _render("trackers", content, msg)


@app.route("/trackers/remove", methods=["POST"])
@login_required
def trackers_remove():
    tid = int(request.form.get("tracker_id", 0))
    gid = int(request.form.get("guild_id", 0))
    run_async(_db_module.remove_tracker(tid, gid))
    return redirect(url_for("trackers_page", msg="🗑️ تم حذف المتتبع"))


# ══════════════════════════════════════════════════════════════
#  Custom Sites
# ══════════════════════════════════════════════════════════════
@app.route("/sites")
@login_required
def sites_page():
    sites = run_async(_db_module.get_custom_sites()) if _db_module else []
    msg   = request.args.get("msg", "")

    def type_badge(t):
        colors = {"madara": "#7c5cfc", "arabic": "#f59e0b", "generic": "#22c55e"}
        c = colors.get(t, "#94a3b8")
        return f'<span style="background:rgba(124,92,252,.1);color:{c};border:1px solid {c}44;padding:2px 8px;border-radius:6px;font-size:.75rem">{t}</span>'

    rows = "".join(f"""
      <tr>
        <td><code>{domain}</code></td>
        <td>{type_badge(stype)}</td>
        <td><code style="font-size:.75rem">{by or '—'}</code></td>
        <td class="text-muted" style="font-size:.8rem">{(at or '')[:10]}</td>
        <td class="text-muted" style="font-size:.8rem;max-width:200px">{notes or '—'}</td>
        <td>
          <form method="post" action="/sites/remove" style="display:inline">
            <input type="hidden" name="domain" value="{domain}">
            <button class="btn-danger-soft" onclick="return confirm('حذف {domain}؟')">
              <i class="bi bi-trash3"></i>
            </button>
          </form>
        </td>
      </tr>""" for domain,stype,by,at,notes in sites) or '<tr><td colspan="6" class="text-center text-muted py-3">لا توجد مواقع مخصصة</td></tr>'

    content = f"""
<div class="page-header">
  <h1><i class="bi bi-globe2"></i> المواقع المخصصة</h1>
  <div class="breadcrumb">{len(sites)} موقع مضاف</div>
</div>
<div class="card mb-3">
  <div class="card-body">
    <div class="card-title"><i class="bi bi-plus-circle"></i> إضافة موقع يدوياً</div>
    <form method="post" action="/sites/add">
      <div class="row g-2">
        <div class="col-md-4">
          <input name="domain" class="form-control" placeholder="domain.com" required>
        </div>
        <div class="col-md-3">
          <select name="site_type" class="form-select">
            <option value="madara">⚡ Madara (WordPress)</option>
            <option value="arabic">🇸🇦 Arabic</option>
            <option value="generic">🌐 Generic</option>
          </select>
        </div>
        <div class="col-md-3">
          <input name="notes" class="form-control" placeholder="ملاحظة">
        </div>
        <div class="col-md-2">
          <button class="btn btn-acc w-100">إضافة</button>
        </div>
      </div>
    </form>
  </div>
</div>
<div class="card">
  <div class="card-body">
    <div class="table-responsive">
      <table class="table table-hover mb-0">
        <thead><tr>
          <th>الدومين</th><th>النوع</th><th>أضيف بواسطة</th><th>التاريخ</th><th>ملاحظة</th><th>حذف</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </div>
</div>"""
    return _render("sites", content, msg)


@app.route("/sites/add", methods=["POST"])
@login_required
def sites_add():
    domain    = request.form.get("domain", "").strip().lower()
    site_type = request.form.get("site_type", "madara")
    notes     = request.form.get("notes", "").strip()
    if domain:
        run_async(_db_module.add_custom_site(domain, site_type, 0, notes or "Added via panel"))
    return redirect(url_for("sites_page", msg=f"✅ تم إضافة {domain}"))


@app.route("/sites/remove", methods=["POST"])
@login_required
def sites_remove():
    domain = request.form.get("domain", "").strip()
    if domain:
        run_async(_db_module.remove_custom_site(domain))
    return redirect(url_for("sites_page", msg=f"🗑️ تم حذف {domain}"))


# ══════════════════════════════════════════════════════════════
#  Logs
# ══════════════════════════════════════════════════════════════
@app.route("/logs")
@login_required
def logs_page():
    logs = run_async(_db_module.get_recent_logs(300)) if _db_module else []
    log_html = "".join(
        f'<div class="log-{lv}">[{ts[:19]}] <span style="opacity:.6">[{lv}]</span> {msg}</div>'
        for lv, msg, ts in logs
    ) or '<span class="text-muted">لا توجد سجلات</span>'

    content = f"""
<div class="page-header d-flex justify-content-between align-items-start">
  <div>
    <h1><i class="bi bi-terminal-fill"></i> السجلات</h1>
    <div class="breadcrumb">{len(logs)} سجل</div>
  </div>
  <button onclick="location.reload()" class="ctrl-btn ctrl-sync">
    <i class="bi bi-arrow-clockwise"></i> تحديث
  </button>
</div>
<div class="card">
  <div class="card-body p-0">
    <div class="log-box" id="logBox" style="border-radius:14px;max-height:600px">
      {log_html}
    </div>
  </div>
</div>
<script>
  var lb = document.getElementById('logBox');
  lb.scrollTop = lb.scrollHeight;
  setTimeout(function(){{ location.reload(); }}, 20000);
</script>"""
    return _render("logs", content)


# ══════════════════════════════════════════════════════════════
#  Runner
# ══════════════════════════════════════════════════════════════
def run_panel(port: int = 8080):
    import logging
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def start_panel(bot, db, port: int = 8080):
    set_bot(bot, db)
    t = threading.Thread(target=run_panel, args=(port,), daemon=True)
    t.start()
    return t
