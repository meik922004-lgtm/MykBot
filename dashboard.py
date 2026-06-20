import os
from flask import Flask, render_template_string, request, redirect, url_for, session, flash
from pymongo import MongoClient
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "super-secret-key-myk-bot-1928")

# Kết nối Database đồng bộ (Phù hợp với Flask)
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    MONGO_URI = "mongodb+srv://meik922004_db_user:LrXxnoloY8TaezNI@database0.gjbsfwh.mongodb.net/?appName=database0"

client = MongoClient(MONGO_URI)
db = client["database0"]

# Các bộ sưu tập dữ liệu (Collections)
players_col = db["players"]
slots_col = db["user_slots"]
shop_col = db["shop_subscriptions"]
parties_col = db["parties"]
logs_col = db["bot_logs"]

# Cấu hình mật khẩu Admin Dashboard
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin123")

# ========================================================================
# LAYOUT GIAO DIỆN CHUNG (BASE HTML TEMPLATE)
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
        body { background-color: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .navbar { background-color: #161b22 !important; border-bottom: 1px solid #30363d; }
        .card { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; color: #fff; }
        .card-header { background-color: #21262d; border-bottom: 1px solid #30363d; }
        .table { color: #c9d1d9; border-color: #30363d; }
        .table th { background-color: #1f242c; color: #58a6ff; }
        .sidebar { background-color: #161b22; min-height: calc(100vh - 56px); border-right: 1px solid #30363d; padding-top: 20px; }
        .sidebar a { color: #8b949e; text-decoration: none; padding: 10px 20px; display: block; border-radius: 4px; margin: 4px 10px; }
        .sidebar a:hover, .sidebar a.active { background-color: #21262d; color: #58a6ff; }
        .stat-card { transition: transform 0.2s; }
        .stat-card:hover { transform: translateY(-3px); }
        .badge-action { text-transform: uppercase; font-size: 0.75rem; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand text-primary fw-bold" href="/"><i class="fa-solid fa-robot me-2"></i>MyKBot Center</a>
            <div class="d-flex">
                <span class="navbar-text me-3 text-success"><i class="fa-solid fa-circle-check me-1"></i> System Online</span>
                <a href="{{ url_for('logout') }}" class="btn btn-sm btn-outline-danger"><i class="fa-solid fa-right-from-bracket"></i> Đăng xuất</a>
            </div>
        </div>
    </nav>
    
    <div class="container-fluid">
        <div class="row">
            <div class="col-md-2 d-none d-md-block sidebar px-0">
                <a href="{{ url_for('index') }}" class="{% if active_page == 'home' %}active{% endif %}"><i class="fa-solid fa-chart-pie me-2"></i> Tổng Quan</a>
                <a href="{{ url_for('manage_slots') }}" class="{% if active_page == 'slots' %}active{% endif %}"><i class="fa-solid fa-user-lock me-2"></i> Cấp Quyền & Slots</a>
                <a href="{{ url_for('view_players') }}" class="{% if active_page == 'players' %}active{% endif %}"><i class="fa-solid fa-gamepad me-2"></i> Người Chơi (IGN)</a>
                <a href="{{ url_for('view_shops') }}" class="{% if active_page == 'shops' %}active{% endif %}"><i class="fa-solid fa-store me-2"></i> Mặt Hàng Theo Dõi</a>
            </div>
            
            <div class="col-md-10 ms-sm-auto px-4 py-4">
                {% with messages = get_flashed_messages(with_categories=true) %}
                    {% if messages %}
                        {% for category, message in messages %}
                            <div class="alert alert-{{ category if category != 'error' else 'danger' }} alert-dismissible fade show" role="alert">
                                {{ message }}
                                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                            </div>
                        {% endfor %}
                    {% endif %}
                {% endwith %}
                
                {% block content %}{% endblock %}
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

# ========================================================================
# ROUTES & LOGIC
# ========================================================================

def login_required(f):
    def wrapper(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == DASHBOARD_PASSWORD:
            session['logged_in'] = True
            flash("Đăng nhập bảng điều khiển thành công!", "success")
            return redirect(url_for('index'))
        else:
            flash("Sai mật khẩu quản trị viên!", "danger")
    
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>MyKBot Login</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { background-color: #0d1117; color: #c9d1d9; height: 100vh; display: flex; align-items: center; justify-content: center; }
            .login-card { background-color: #161b22; border: 1px solid #30363d; width: 400px; padding: 30px; border-radius: 8px; }
        </style>
    </head>
    <body>
        <div class="login-card shadow-lg text-center">
            <h3 class="text-primary mb-4"><i class="all fa-solid fa-unlock-keyhole me-2"></i>MyKBot Admin</h3>
            {% with messages = get_flashed_messages() %}
              {% if messages %}
                {% for message in messages %}<div class="alert alert-danger py-2">{{ message }}</div>{% endfor %}
              {% endif %}
            {% endwith %}
            <form method="POST">
                <div class="mb-3 text-start">
                    <label class="form-label text-secondary">Mật khẩu bảo mật</label>
                    <input type="password" name="password" class="form-control bg-dark text-white border-secondary" required autofocus>
                </div>
                <button type="submit" class="btn btn-primary w-100 fw-bold">Xác Minh Danh Tính</button>
            </form>
        </div>
    </body>
    </html>
    """)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# 1. Trang tổng quan (Dashboard)
@app.route('/')
@login_required
def index():
    stats = {
        "players": players_col.count_documents({}),
        "slots": slots_col.count_documents({}),
        "shops": shop_col.count_documents({}),
        "parties": parties_col.count_documents({})
    }
    
    # Lấy 10 lịch sử thao tác mới nhất từ bộ lọc log hành động
    recent_logs = list(logs_col.find().sort("timestamp", -1).limit(10))
    
    content = """
    {% extends "base" %}
    {% block content %}
    <h2 class="mb-4 text-white"><i class="fa-solid fa-gauge-high text-info me-2"></i>Báo Cáo Tổng Quan</h2>
    
    <div class="row mb-4">
        <div class="col-md-3">
            <div class="card stat-card p-3 border-start border-4 border-primary">
                <div class="text-secondary small fw-bold">NGƯỜI CHƠI ĐĂNG KÝ IGN</div>
                <div class="fs-2 fw-bold text-white">{{ stats.players }}</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card stat-card p-3 border-start border-4 border-warning">
                <div class="text-secondary small fw-bold">TÀI KHOẢN ĐƯỢC CẤP PHÉP SLOTS</div>
                <div class="fs-2 fw-bold text-white">{{ stats.slots }}</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card stat-card p-3 border-start border-4 border-success">
                <div class="text-secondary small fw-bold">MẶT HÀNG ĐANG GIÁM SÁT GIÁ</div>
                <div class="fs-2 fw-bold text-white">{{ stats.shops }}</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card stat-card p-3 border-start border-4 border-danger">
                <div class="text-secondary small fw-bold">PHÒNG ĐỘI SĂN DUNGEON HOẠT ĐỘNG</div>
                <div class="fs-2 fw-bold text-white">{{ stats.parties }}</div>
            </div>
        </div>
    </div>
    
    <div class="card">
        <div class="card-header fw-bold text-info"><i class="fa-solid fa-clock-rotate-left me-2"></i>Nhật Ký Hoạt Động Của Hệ Thống Bot (Real-time)</div>
        <div class="card-body p-0">
            <div class="table-responsive">
                <table class="table table-dark table-striped mb-0">
                    <thead>
                        <tr>
                            <th>Thời Gian (UTC)</th>
                            <th>User ID Discord</th>
                            <th>Hành Động</th>
                            <th>Chi Tiết Bản Ghi</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for log in recent_logs %}
                        <tr>
                            <td class="text-secondary">{{ log.timestamp.strftime('%Y-%m-%d %H:%M:%S') if log.timestamp else 'N/A' }}</td>
                            <td><code>{{ log.user_id }}</code></td>
                            <td><span class="badge bg-primary badge-action">{{ log.action }}</span></td>
                            <td>{{ log.details }}</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="4" class="text-center text-secondary py-3">Chưa có nhật ký hoạt động nào được ghi nhận.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    {% endblock %}
    """
    return render_template_string(content, base=BASE_LAYOUT, active_page='home', stats=stats, recent_logs=recent_logs)

# 2. Trang quản lý quyền và phân phối Slots
@app.route('/slots', methods=['GET', 'POST'])
@login_required
def manage_slots():
    if request.method == 'POST':
        action_type = request.form.get("form_action")
        user_id = int(request.form.get("user_id").strip())
        
        if action_type == "update":
            max_slots = int(request.form.get("max_slots", 0))
            slots_col.update_one({"_id": user_id}, {"$set": {"max_slots": max_slots}}, upsert=True)
            flash(f"Đã cập nhật giới hạn của thành viên {user_id} lên {max_slots} slots thành công!", "success")
        elif action_type == "delete":
            slots_col.delete_one({"_id": user_id})
            flash(f"Đã thu hồi toàn bộ slots và tước quyền truy cập của {user_id}.", "warning")
            
        return redirect(url_for('manage_slots'))
        
    all_slots = list(slots_col.find())
    content = """
    {% extends "base" %}
    {% block content %}
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="text-white"><i class="fa-solid fa-user-lock text-warning me-2"></i>Phân Quyền & Hạn Mức Tính Năng Private Shop</h2>
        <button class="btn btn-success fw-bold btn-sm" data-bs-toggle="modal" data-bs-target="#addSlotModal"><i class="fa-solid fa-user-plus me-1"></i> Cấp Quyền Cho Thành Viên Mới</button>
    </div>
    
    <div class="card">
        <div class="card-body p-0">
            <table class="table table-dark table-hover mb-0">
                <thead>
                    <tr>
                        <th>Discord User ID</th>
                        <th>Hạn Mức Slots Được Cấp</th>
                        <th class="text-center">Thao Tác Quản Trị</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in all_slots %}
                    <tr>
                        <td class="align-middle"><code>{{ item._id }}</code></td>
                        <td class="align-middle">
                            <span class="badge bg-{{ 'success' if item.max_slots > 0 else 'secondary' }} fs-6">{{ item.max_slots }} Slots</span>
                        </td>
                        <td class="text-center">
                            <form method="POST" class="d-inline-block me-1">
                                <input type="hidden" name="form_action" value="update">
                                <input type="hidden" name="user_id" value="{{ item._id }}">
                                <div class="input-group input-group-sm" style="width: 150px;">
                                    <input type="number" name="max_slots" class="form-control bg-dark text-white border-secondary" value="{{ item.max_slots }}" min="0">
                                    <button type="submit" class="btn btn-primary"><i class="fa-solid fa-floppy-disk"></i></button>
                                </div>
                            </form>
                            <form method="POST" class="d-inline-block">
                                <input type="hidden" name="form_action" value="delete">
                                <input type="hidden" name="user_id" value="{{ item._id }}">
                                <button type="submit" class="btn btn-sm btn-danger" onclick="return confirm('Bạn có chắc chắn muốn xóa thành viên này?')"><i class="fa-solid fa-trash"></i></button>
                            </form>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="3" class="text-center text-secondary py-3">Hiện chưa có thành viên VIP nào được cấu hình từ trước.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    
    <div class="modal fade" id="addSlotModal" tabindex="-1" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content bg-dark text-white border border-secondary">
          <div class="modal-header border-bottom border-secondary">
            <h5 class="modal-title">Cấp Slots Cho User ID Mới</h5>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
          </div>
          <form method="POST">
              <div class="modal-body">
                <input type="hidden" name="form_action" value="update">
                <div class="mb-3">
                    <label class="form-label">Discord User ID</label>
                    <input type="text" name="user_id" class="form-control bg-secondary text-white" placeholder="Ví dụ: 1283689737567211581" required>
                </div>
                <div class="mb-3">
                    <label class="form-label">Số lượng slots muốn cung cấp</label>
                    <input type="number" name="max_slots" class="form-control bg-secondary text-white" value="2" min="1" required>
                </div>
              </div>
              <div class="modal-footer border-top border-secondary">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Đóng</button>
                <button type="submit" class="btn btn-success">Xác Nhận Cấp Quyền</button>
              </div>
          </form>
        </div>
      </div>
    </div>
    {% endblock %}
    """
    return render_template_string(content, base=BASE_LAYOUT, active_page='slots', all_slots=all_slots)

# 3. Xem danh sách Profile Người chơi (IGN & Dungeon Gears)
@app.route('/players')
@login_required
def view_players():
    players = list(players_col.find())
    content = """
    {% extends "base" %}
    {% block content %}
    <h2 class="mb-4 text-white"><i class="fa-solid fa-gamepad text-primary me-2"></i>Hồ Sơ Người Chơi Hệ Thống (IGN & Gear Stats)</h2>
    <div class="card">
        <div class="card-body p-0">
            <table class="table table-dark table-striped mb-0">
                <thead>
                    <tr>
                        <th>User ID Discord</th>
                        <th>Tên Trong Game (IGN)</th>
                        <th>Múi Giờ Cấu Hình</th>
                    </tr>
                </thead>
                <tbody>
                    {% for p in players %}
                    <tr>
                        <td><code>{{ p.user_id }}</code></td>
                        <td><strong class="text-warning">{{ p.ign }}</strong></td>
                        <td>UTC {{ '+' if p.tz_offset and p.tz_offset > 0 else '' }}{{ p.tz_offset if p.tz_offset is not none else 'Chưa cài đặt' }}</td>
                    </tr>
                    {% else %}
                    <tr><td colspan="3" class="text-center text-secondary py-3">Chưa có người chơi nào khởi tạo cấu hình dữ liệu /mygear.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    {% endblock %}
    """
    return render_template_string(content, base=BASE_LAYOUT, active_page='players', players=players)

# 4. Xem các mặt hàng thị trường đang được theo dõi
@app.route('/shops')
@login_required
def view_shops():
    shops = list(shop_col.find())
    content = """
    {% extends "base" %}
    {% block content %}
    <h2 class="mb-4 text-white"><i class="fa-solid fa-store text-success me-2"></i>Danh Sách Vật Phẩm Đang Đăng Ký Theo Dõi Giá</h2>
    <div class="row">
        {% for s in shops %}
        <div class="col-md-4 mb-3">
            <div class="card shadow-sm">
                <div class="card-header bg-dark fw-bold text-capitalize text-success"><i class="fa-solid fa-tag me-2"></i>{{ s._id }}</div>
                <div class="card-body">
                    <p class="text-secondary mb-2 small fw-bold">DANH SÁCH NGƯỜI CHỜ PING:</p>
                    <ul class="list-unstyled mb-0">
                        {% for sub in s.subscribers %}
                        <li class="border-bottom border-secondary py-1 d-flex justify-content-between">
                            <span>User: <code>{{ sub.user_id }}</code></span>
                            <span class="text-info fw-bold">< {{ sub.max_price | comma_filter }} EA</span>
                        </li>
                        {% endfor %}
                    </ul>
                </div>
            </div>
        </div>
        {% else %}
        <div class="col-12"><div class="alert alert-secondary text-center">Chưa có mặt hàng nào được đưa vào danh sách săn giá tự động.</div></div>
        {% endfor %}
    </div>
    {% endblock %}
    """
    return render_template_string(content, base=BASE_LAYOUT, active_page='shops', shops=shops)

@app.template_filter('comma_filter')
def comma_filter(value):
    return f"{value:,}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)