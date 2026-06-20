import os
from flask import Flask, request, redirect, url_for, session, flash
from pymongo import MongoClient
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "super-secret-key-myk-bot-1928")

MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    MONGO_URI = "mongodb+srv://meik922004_db_user:LrXxnoloY8TaezNI@database0.gjbsfwh.mongodb.net/?appName=database0"

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client["database0"]

players_col = db["players"]
slots_col = db["user_slots"]
shop_col = db["shop_subscriptions"]
parties_col = db["parties"]
logs_col = db["bot_logs"]

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin123")

# ========================================================================
# LAYOUT & TEMPLATE CACHE SYSTEM
# ========================================================================
BASE_LAYOUT = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MyKBot - Admin Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background-color: #0d1117; color: #ffffff; font-family: 'Segoe UI', sans-serif; font-weight: 500; }
        .navbar { background-color: #161b22 !important; border-bottom: 1px solid #30363d; }
        .card { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; }
        .card-header { background-color: #21262d; border-bottom: 1px solid #30363d; font-weight: bold; }
        .table { color: #f0f6fc; border-color: #30363d; }
        .table th { background-color: #1f242c; color: #58a6ff; font-weight: bold; }
        .table td { vertical-align: middle; }
        .sidebar { background-color: #161b22; min-height: calc(100vh - 56px); border-right: 1px solid #30363d; padding-top: 20px; }
        .sidebar a { color: #c9d1d9; text-decoration: none; padding: 12px 20px; display: block; border-radius: 4px; margin: 4px 10px; font-weight: bold; transition: 0.2s; }
        .sidebar a:hover, .sidebar a.active { background-color: #21262d; color: #58a6ff; transform: translateX(5px); }
        .text-light-custom { color: #e6edf3 !important; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand text-primary fw-bold fs-4" href="/"><i class="fa-solid fa-robot me-2"></i>MyKBot Center</a>
            <div class="d-flex align-items-center">
                <span class="navbar-text me-4 text-success fw-bold"><i class="fa-solid fa-circle-check me-1"></i> System Online</span>
                <a href="{{ url_for('logout') }}" class="btn btn-sm btn-outline-danger fw-bold"><i class="fa-solid fa-right-from-bracket"></i> Logout</a>
            </div>
        </div>
    </nav>
    <div class="container-fluid">
        <div class="row">
            <div class="col-md-2 d-none d-md-block sidebar px-0">
                <a href="{{ url_for('index') }}" class="{% if active_page == 'home' %}active{% endif %}">Tổng Quan</a>
                <a href="{{ url_for('manage_slots') }}" class="{% if active_page == 'slots' %}active{% endif %}">Cấp Quyền & Slots</a>
                <a href="{{ url_for('view_players') }}" class="{% if active_page == 'players' %}active{% endif %}">Người Chơi (IGN)</a>
                <a href="{{ url_for('view_shops') }}" class="{% if active_page == 'shops' %}active{% endif %}">Mặt Hàng Theo Dõi</a>
            </div>
            <div class="col-md-10 ms-sm-auto px-4 py-4">
                {% with messages = get_flashed_messages(with_categories=true) %}
                    {% if messages %}
                        {% for category, message in messages %}
                            <div class="alert alert-{{ category if category != 'error' else 'danger' }} alert-dismissible fw-bold text-white fs-6 border-0 shadow">{{ message }}</div>
                        {% endfor %}
                    {% endif %}
                {% endwith %}
                </div>
        </div>
    </div>
</body>
</html>
"""

TEMPLATE_CACHE = {}

def get_cached_template(name, content_html):
    if name not in TEMPLATE_CACHE:
        final_html = BASE_LAYOUT.replace("", content_html)
        TEMPLATE_CACHE[name] = app.jinja_env.from_string(final_html)
    return TEMPLATE_CACHE[name]

@app.template_filter('comma_filter')
def comma_filter(value):
    return f"{value:,}"

def login_required(f):
    def wrapper(*args, **kwargs):
        if not session.get('logged_in'): return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

def get_ign(user_id):
    try:
        p = players_col.find_one({"user_id": int(user_id)})
        return p.get("ign") if p and p.get("ign") and p.get("ign") != "Not Set" else "Unknown (No Profile)"
    except ValueError:
        return "Unknown"

# ========================================================================
# ROUTES 
# ========================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == DASHBOARD_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        flash("Sai mật khẩu quản trị viên!", "danger")
    
    login_html = """
    <!DOCTYPE html><html><head><title>MyKBot Login</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>body{background-color:#0d1117;color:#ffffff;height:100vh;display:flex;align-items:center;justify-content:center;font-weight:bold;} .login-card{background-color:#161b22;padding:40px;border-radius:12px; border:1px solid #30363d;}</style>
    </head><body>
    <div class="login-card shadow-lg text-center">
        <h2 class="text-primary mb-4">MyKBot Admin</h2>
        <form method="POST">
            <input type="password" name="password" class="form-control form-control-lg mb-4 bg-dark text-white border-secondary" required autofocus placeholder="Nhập mật khẩu...">
            <button type="submit" class="btn btn-primary btn-lg w-100 fw-bold">Đăng Nhập</button>
        </form>
    </div></body></html>
    """
    if 'login' not in TEMPLATE_CACHE:
        TEMPLATE_CACHE['login'] = app.jinja_env.from_string(login_html)
    return TEMPLATE_CACHE['login'].render()

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    stats = {
        "players": players_col.count_documents({}),
        "slots": slots_col.count_documents({}),
        "shops": shop_col.count_documents({}),
        "parties": parties_col.count_documents({})
    }
    
    recent_logs = list(logs_col.find().sort([("_id", -1)]).limit(10))
    for log in recent_logs:
        log["ign"] = get_ign(log["user_id"])
    
    content = """
    <h2 class="mb-4 text-white fw-bold">Báo Cáo Tổng Quan</h2>
    <div class="row mb-4">
        <div class="col-md-3"><div class="card p-3 border-start border-4 border-primary"><h5>Users</h5><h2 class="fw-bold">{{ stats.players }}</h2></div></div>
        <div class="col-md-3"><div class="card p-3 border-start border-4 border-warning"><h5>VIP Slots</h5><h2 class="fw-bold">{{ stats.slots }}</h2></div></div>
        <div class="col-md-3"><div class="card p-3 border-start border-4 border-success"><h5>Shops</h5><h2 class="fw-bold">{{ stats.shops }}</h2></div></div>
        <div class="col-md-3"><div class="card p-3 border-start border-4 border-danger"><h5>Parties</h5><h2 class="fw-bold">{{ stats.parties }}</h2></div></div>
    </div>
    <div class="card shadow">
        <div class="card-header text-info fs-5">Nhật Ký Hệ Thống</div>
        <div class="card-body p-0">
            <table class="table table-dark table-striped table-hover mb-0">
                <thead><tr><th>Hành Động</th><th>Người Chơi (IGN)</th><th>Chi Tiết Bản Ghi</th></tr></thead>
                <tbody>
                    {% for log in recent_logs %}
                    <tr>
                        <td><span class="badge bg-primary px-3 py-2 fs-6">{{ log.action }}</span></td>
                        <td class="text-warning fw-bold">{{ log.ign }}</td>
                        <td class="text-light-custom fs-6">{{ log.details }}</td>
                    </tr>
                    {% else %}<tr><td colspan="3" class="text-center py-4 fs-5 text-light-custom">Chưa có dữ liệu.</td></tr>{% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """
    template = get_cached_template('index', content)
    return template.render(active_page='home', stats=stats, recent_logs=recent_logs)

@app.route('/slots', methods=['GET', 'POST'])
@login_required
def manage_slots():
    if request.method == 'POST':
        user_id = int(request.form.get("user_id").strip())
        max_slots = int(request.form.get("max_slots", 0))
        slots_col.update_one({"_id": user_id}, {"$set": {"max_slots": max_slots}}, upsert=True)
        flash(f"Đã cấp {max_slots} slots thành công!", "success")
        return redirect(url_for('manage_slots'))
        
    all_slots = list(slots_col.find())
    for item in all_slots:
        item["ign"] = get_ign(item["_id"])

    content = """
    <h2 class="text-white mb-4 fw-bold"><i class="fa-solid fa-user-shield text-warning me-2"></i>Quản Lý Quyền Truy Cập</h2>
    <div class="card p-4 border-warning shadow">
        <table class="table table-dark table-hover mb-0">
            <thead>
                <tr class="text-warning fs-5"><th>Người Chơi (IGN)</th><th>Discord ID</th><th>Hạn Mức Slots</th></tr>
            </thead>
            <tbody>
                {% for item in all_slots %}
                <tr>
                    <td class="text-white fs-5 fw-bold">{{ item.ign }}</td>
                    <td class="text-info fs-6">{{ item._id }}</td>
                    <td><span class="badge bg-warning text-dark fw-bold px-3 py-2 fs-6">{{ item.max_slots }} Slots</span></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    """
    return get_cached_template('slots', content).render(active_page='slots', all_slots=all_slots)

@app.route('/players')
@login_required
def view_players():
    players = list(players_col.find())
    content = """
    <h2 class="text-white mb-4 fw-bold"><i class="fa-solid fa-gamepad text-primary me-2"></i>Danh Sách Người Chơi</h2>
    <div class="row">
        {% for p in players %}
        <div class="col-md-3">
            <div class="card mb-4 border-primary shadow text-center">
                <div class="card-body">
                    <h4 class="text-primary fw-bold mb-2">{{ p.ign }}</h4>
                    <p class="text-light-custom fs-6 mb-3">ID: <code>{{ p.user_id }}</code></p>
                    <span class="badge bg-primary px-3 py-2 fs-6">UTC {{ p.tz_offset }}</span>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    """
    return get_cached_template('players', content).render(active_page='players', players=players)

@app.route('/shops')
@login_required
def view_shops():
    shops = list(shop_col.find())
    for s in shops:
        for sub in s.get("subscribers", []):
            sub["ign"] = get_ign(sub["user_id"])

    content = """
    <h2 class="text-white mb-4 fw-bold"><i class="fa-solid fa-store text-success me-2"></i>Mặt Hàng Giám Sát</h2>
    <div class="row">
        {% for s in shops %}
        <div class="col-md-4">
            <div class="card border-success mb-4 shadow">
                <div class="card-header bg-success text-white fw-bold fs-5">{{ s._id | upper }}</div>
                <div class="card-body">
                    <p class="text-light-custom fs-6 mb-3">Số người theo dõi: <b class="text-white fs-5">{{ s.subscribers|length }}</b></p>
                    <ul class="list-unstyled mb-0">
                        {% for sub in s.subscribers %}
                        <li class="border-bottom border-secondary py-2 d-flex justify-content-between align-items-center">
                            <span class="text-warning fw-bold fs-6">{{ sub.ign }}</span>
                            <span class="text-info fw-bold fs-6">≤ {{ sub.max_price | comma_filter }}</span>
                        </li>
                        {% endfor %}
                    </ul>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    """
    return get_cached_template('shops', content).render(active_page='shops', shops=shops)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)