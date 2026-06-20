import os
from flask import Flask, request, redirect, url_for, session, flash
from pymongo import MongoClient
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "super-secret-key-myk-bot-1928")

# Kết nối Database đồng bộ
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
# LAYOUT & TEMPLATE CACHE SYSTEM (GIẢM TẢI RAM TỐI ĐA CHO RENDER)
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
        body { background-color: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', sans-serif; }
        .navbar { background-color: #161b22 !important; border-bottom: 1px solid #30363d; }
        .card { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; }
        .card-header { background-color: #21262d; border-bottom: 1px solid #30363d; }
        .table { color: #c9d1d9; border-color: #30363d; }
        .table th { background-color: #1f242c; color: #58a6ff; }
        .sidebar { background-color: #161b22; min-height: calc(100vh - 56px); border-right: 1px solid #30363d; padding-top: 20px; }
        .sidebar a { color: #8b949e; text-decoration: none; padding: 10px 20px; display: block; border-radius: 4px; margin: 4px 10px; }
        .sidebar a:hover, .sidebar a.active { background-color: #21262d; color: #58a6ff; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand text-primary fw-bold" href="/"><i class="fa-solid fa-robot me-2"></i>MyKBot Center</a>
            <div class="d-flex">
                <span class="navbar-text me-3 text-success"><i class="fa-solid fa-circle-check me-1"></i> System Online</span>
                <a href="{{ url_for('logout') }}" class="btn btn-sm btn-outline-danger"><i class="fa-solid fa-right-from-bracket"></i> Logout</a>
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
                            <div class="alert alert-{{ category if category != 'error' else 'danger' }} alert-dismissible">{{ message }}</div>
                        {% endfor %}
                    {% endif %}
                {% endwith %}
                <!-- CONTENT_PLACEHOLDER -->
            </div>
        </div>
    </div>
</body>
</html>
"""

# Bộ lưu trữ Template Compiled để tránh OOM
TEMPLATE_CACHE = {}

def get_cached_template(name, content_html):
    if name not in TEMPLATE_CACHE:
        final_html = BASE_LAYOUT.replace("<!-- CONTENT_PLACEHOLDER -->", content_html)
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
    <style>body{background-color:#0d1117;color:#c9d1d9;height:100vh;display:flex;align-items:center;justify-content:center;} .login-card{background-color:#161b22;padding:30px;border-radius:8px;}</style>
    </head><body>
    <div class="login-card shadow-lg text-center">
        <h3 class="text-primary mb-4">MyKBot Admin</h3>
        <form method="POST">
            <input type="password" name="password" class="form-control mb-3" required autofocus placeholder="Nhập mật khẩu...">
            <button type="submit" class="btn btn-primary w-100 fw-bold">Đăng Nhập</button>
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
    # Tối ưu: Dùng _id (mặc định đã được index) thay vì timestamp để tránh tràn RAM DB
    recent_logs = list(logs_col.find().sort([("_id", -1)]).limit(10))
    
    content = """
    <h2 class="mb-4 text-white">Báo Cáo Tổng Quan</h2>
    <div class="row mb-4">
        <div class="col-md-3"><div class="card p-3 border-start border-4 border-primary"><h5>Users</h5><h2>{{ stats.players }}</h2></div></div>
        <div class="col-md-3"><div class="card p-3 border-start border-4 border-warning"><h5>VIP Slots</h5><h2>{{ stats.slots }}</h2></div></div>
        <div class="col-md-3"><div class="card p-3 border-start border-4 border-success"><h5>Shops</h5><h2>{{ stats.shops }}</h2></div></div>
        <div class="col-md-3"><div class="card p-3 border-start border-4 border-danger"><h5>Parties</h5><h2>{{ stats.parties }}</h2></div></div>
    </div>
    <div class="card">
        <div class="card-header text-info">Nhật Ký Hệ Thống</div>
        <div class="card-body p-0">
            <table class="table table-dark table-striped mb-0">
                <thead><tr><th>Hành Động</th><th>Chi Tiết Bản Ghi</th></tr></thead>
                <tbody>
                    {% for log in recent_logs %}
                    <tr><td><span class="badge bg-primary">{{ log.action }}</span></td><td>{{ log.details }}</td></tr>
                    {% else %}<tr><td colspan="2" class="text-center py-3">Chưa có dữ liệu.</td></tr>{% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """
    template = get_cached_template('index', content)
    return template.render(active_page='home', stats=stats, recent_logs=recent_logs)

@app.route('/slots')
@login_required
def manage_slots():
    return "Tính năng hiển thị slots tạm ẩn để test tải CPU/RAM, vui lòng bấm về trang 'Tổng Quan'."

@app.route('/players')
@login_required
def view_players():
    return "Tính năng tạm ẩn để test tải CPU/RAM, vui lòng bấm về trang 'Tổng Quan'."

@app.route('/shops')
@login_required
def view_shops():
    return "Tính năng tạm ẩn để test tải CPU/RAM, vui lòng bấm về trang 'Tổng Quan'."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)