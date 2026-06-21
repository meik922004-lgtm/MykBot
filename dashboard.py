import os
from flask import Flask, request, redirect, url_for, session, flash, render_template_string
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "super-secret-key-myk-bot-1928")

MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    MONGO_URI = "mongodb+srv://meik922004_db_user:LrXxnoloY8TaezNI@database0.gjbsfwh.mongodb.net/?appName=database0"

# Giới hạn maxPoolSize để tiết kiệm RAM kết nối với MongoDB
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000, maxPoolSize=10)
db = client["database0"]

players_col = db["players"]
slots_col = db["user_slots"]
shop_col = db["shop_subscriptions"]

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin123")

# ========================================================================
# LAYOUT SYSTEM (Đã gỡ bỏ các trang con)
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
                <a href="{{ url_for('index') }}" class="{% if active_page == 'slots' %}active{% endif %}">Cấp Quyền & Slots</a>
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
                {{ content|safe }}
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.template_filter('comma_filter')
def comma_filter(value):
    return f"{value:,}"

def login_required(f):
    def wrapper(*args, **kwargs):
        if not session.get('logged_in'): return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# Tối ưu RAM: Chỉ kéo field 'ign' thay vì toàn bộ profile người chơi
def get_ign(user_id):
    if not user_id:
        return "Unknown"
    try:
        p = players_col.find_one({"user_id": int(user_id)}, {"ign": 1, "_id": 0})
        return p.get("ign") if p and p.get("ign") and p.get("ign") != "Not Set" else "Unknown (No Profile)"
    except Exception:
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
    return render_template_string(login_html)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    # Gộp route /slots làm trang chủ để giảm thiểu lượng code và routing
    if request.method == 'POST':
        user_id_raw = request.form.get("user_id", "").strip()
        if user_id_raw.isdigit():
            user_id = int(user_id_raw)
            max_slots = int(request.form.get("max_slots", 0))
            slots_col.update_one({"_id": user_id}, {"$set": {"max_slots": max_slots}}, upsert=True)
            flash(f"Đã cập nhật {max_slots} slots thành công!", "success")
        else:
            flash("ID Discord không hợp lệ!", "error")
        return redirect(url_for('index'))
        
    all_slots = list(slots_col.find())
    for item in all_slots:
        item["ign"] = get_ign(item.get("_id"))

    content = """
    <h2 class="text-white mb-4 fw-bold"><i class="fa-solid fa-user-shield text-warning me-2"></i>Quản Lý Quyền Truy Cập & Slots</h2>
    
    <div class="card p-4 border-warning shadow mb-4">
        <h5 class="text-warning mb-3">Thêm / Chỉnh sửa Slot</h5>
        <form method="POST" class="row g-3 align-items-center">
            <div class="col-auto">
                <input type="text" name="user_id" class="form-control bg-dark text-white border-secondary" placeholder="Nhập Discord ID" required>
            </div>
            <div class="col-auto">
                <input type="number" name="max_slots" class="form-control bg-dark text-white border-secondary" placeholder="Số lượng Slots" required>
            </div>
            <div class="col-auto">
                <button type="submit" class="btn btn-warning fw-bold text-dark">Cập Nhật</button>
            </div>
        </form>
    </div>

    <div class="card p-4 border-secondary shadow">
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
    
    # Kết xuất nội dung nhúng thẳng vào layout
    rendered_content = render_template_string(content, all_slots=all_slots)
    return render_template_string(BASE_LAYOUT, content=rendered_content, active_page='slots')

@app.route('/shops')
@login_required
def view_shops():
    shops = list(shop_col.find())
    for s in shops:
        for sub in s.get("subscribers", []):
            sub["ign"] = get_ign(sub.get("user_id"))

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
    rendered_content = render_template_string(content, shops=shops)
    return render_template_string(BASE_LAYOUT, content=rendered_content, active_page='shops')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)