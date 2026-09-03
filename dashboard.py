import os
import time
from flask import Flask, request, redirect, url_for, session, render_template_string, jsonify
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "super-secret-key-myk-bot-1928")

MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://meik922004_db_user:LrXxnoloY8TaezNI@Database0.gjbsfwh.mongodb.net/?appName=Database0")

# Giới hạn tối đa 5 connection pools để tiết kiệm RAM tuyệt đối trên Render Free
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000, maxPoolSize=5)
db = client["Database0"]

players_col = db["players"]
slots_col = db["user_slots"]
shop_col = db["shop_subscriptions"]

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin123")

# Cache RAM ngắn hạn cho IGN để tránh spam query MongoDB
IGN_CACHE = {}
CACHE_TTL = 30 # seconds

def get_ign_cached(user_id):
    if not user_id:
        return "Unknown"
    
    now = time.time()
    if user_id in IGN_CACHE:
        ign, timestamp = IGN_CACHE[user_id]
        if now - timestamp < CACHE_TTL:
            return ign

    try:
        p = players_col.find_one({"user_id": int(user_id)}, {"ign": 1, "_id": 0})
        ign = p.get("ign") if p and p.get("ign") and p.get("ign") != "Not Set" else f"ID: {user_id}"
    except Exception:
        ign = f"ID: {user_id}"

    IGN_CACHE[user_id] = (ign, now)
    return ign

def login_required(f):
    def wrapper(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# ==========================================
# ROUTES & REALTIME API
# ==========================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == DASHBOARD_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin'))
    
    return """
    <!DOCTYPE html><html><head><title>Admin Login</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>body{background-color:#0d1117;color:#fff;height:100vh;display:flex;align-items:center;justify-content:center;}
    .card{background:#161b22;padding:30px;border-radius:10px;border:1px solid #30363d;width:100%;max-width:380px;}</style>
    </head><body>
    <div class="card shadow-lg text-center">
        <h4 class="text-primary mb-3">MyKBot Control Panel</h4>
        <form method="POST">
            <input type="password" name="password" class="form-control bg-dark text-white border-secondary mb-3" placeholder="Mật khẩu Admin..." required autofocus>
            <button class="btn btn-primary w-100 fw-bold">Đăng Nhập</button>
        </form>
    </div></body></html>
    """

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@app.route('/admin')
@login_required
def admin():
    # Trang Single-Page Admin giao diện gọn tối đa
    html_template = """
    <!DOCTYPE html>
    <html lang="vi">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>MyKBot Admin Live Dashboard</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            body { background: #0d1117; color: #c9d1d9; font-family: system-ui, -apple-system, sans-serif; }
            .card { background: #161b22; border: 1px solid #30363d; }
            .table-dark { --bs-table-bg: #161b22; border-color: #30363d; }
            .pulse-dot { height: 10px; width: 10px; background-color: #238636; border-radius: 50%; display: inline-block; box-shadow: 0 0 8px #238636; animation: pulse 1.5s infinite; }
            @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }
            .item-badge { background: #21262d; border: 1px solid #30363d; border-radius: 6px; padding: 4px 8px; margin: 2px; display: inline-block; font-size: 0.85rem; }
        </style>
    </head>
    <body>
        <nav class="navbar navbar-dark bg-dark border-bottom border-secondary px-3 mb-4">
            <span class="navbar-brand fw-bold text-primary"><i class="fa-solid fa-gauge-high me-2"></i>MyKBot Monitor</span>
            <div class="d-flex align-items-center">
                <span class="me-3 small text-muted"><span class="pulse-dot me-1"></span> Live Data (5s)</span>
                <a href="/logout" class="btn btn-sm btn-outline-danger"><i class="fa-solid fa-power-off"></i></a>
            </div>
        </nav>

        <div class="container-fluid px-4">
            <!-- Form cập nhật Slot nhanh -->
            <div class="card p-3 mb-4">
                <div class="row g-2 align-items-center">
                    <div class="col-auto"><strong class="text-warning"><i class="fa-solid fa-user-gear me-1"></i> Cấp Slot:</strong></div>
                    <div class="col-auto"><input type="text" id="slot_user_id" class="form-control form-control-sm bg-dark text-white border-secondary" placeholder="Discord User ID"></div>
                    <div class="col-auto"><input type="number" id="slot_count" class="form-control form-control-sm bg-dark text-white border-secondary" style="width: 100px;" placeholder="Slots"></div>
                    <div class="col-auto"><button onclick="updateSlot()" class="btn btn-sm btn-warning fw-bold">Cập Nhật</button></div>
                    <div class="col-auto"><span id="slot_status" class="small ms-2"></span></div>
                </div>
            </div>

            <!-- Bảng danh sách người dùng & Mặt hàng đang theo dõi -->
            <div class="card shadow-sm">
                <div class="card-header bg-dark border-bottom border-secondary d-flex justify-content-between align-items-center">
                    <h6 class="m-0 fw-bold text-white"><i class="fa-solid fa-users me-2 text-info"></i>Danh Sách Người Dùng & Watchlist Active</h6>
                    <span class="badge bg-secondary" id="total_users_count">0 Users</span>
                </div>
                <div class="table-responsive">
                    <table class="table table-dark table-hover align-middle mb-0">
                        <thead>
                            <tr class="text-secondary small">
                                <th>NGƯỜI CHƠI (IGN)</th>
                                <th>DISCORD ID</th>
                                <th>SLOTS SỬ DỤNG</th>
                                <th>MẶT HÀNG ĐANG THEO DÕI (TÊN | GIÁ MAX)</th>
                            </tr>
                        </thead>
                        <tbody id="user_table_body">
                            <tr><td colspan="4" class="text-center py-4 text-muted">Đang tải dữ liệu...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <script>
            async function fetchData() {
                try {
                    const res = await fetch('/api/live_data');
                    if (!res.ok) return;
                    const data = await res.json();
                    
                    document.getElementById('total_users_count').innerText = `${data.length} Active Users`;
                    const tbody = document.getElementById('user_table_body');
                    
                    if (data.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="4" class="text-center py-4 text-muted">Chưa có người dùng nào theo dõi mặt hàng.</td></tr>';
                        return;
                    }

                    let rows = '';
                    data.forEach(u => {
                        let itemsHtml = u.items.map(i => 
                            `<span class="item-badge">
                                <b class="text-info">${i.name}</b> 
                                <span class="text-warning">≤ ${i.max_price.toLocaleString()}</span>
                            </span>`
                        ).join('');

                        if (!itemsHtml) itemsHtml = '<i class="text-muted small">Chưa đăng ký item nào</i>';

                        rows += `
                            <tr>
                                <td class="fw-bold text-white">${u.ign}</td>
                                <td class="small text-muted">${u.user_id}</td>
                                <td><span class="badge bg-dark border border-secondary">${u.used_slots}/${u.max_slots}</span></td>
                                <td>${itemsHtml}</td>
                            </tr>
                        `;
                    });
                    tbody.innerHTML = rows;
                } catch (e) {
                    console.error("Lỗi cập nhật dữ liệu:", e);
                }
            }

            async function updateSlot() {
                const userId = document.getElementById('slot_user_id').value.trim();
                const slots = document.getElementById('slot_count').value.trim();
                const status = document.getElementById('slot_status');

                if (!userId || !slots) {
                    status.innerHTML = '<span class="text-danger">Vui lòng nhập đủ thông tin!</span>';
                    return;
                }

                const res = await fetch('/api/update_slot', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({user_id: userId, max_slots: parseInt(slots)})
                });

                if (res.ok) {
                    status.innerHTML = '<span class="text-success">✅ Thành công!</span>';
                    document.getElementById('slot_user_id').value = '';
                    document.getElementById('slot_count').value = '';
                    fetchData();
                } else {
                    status.innerHTML = '<span class="text-danger">❌ Thất bại!</span>';
                }
                setTimeout(() => status.innerHTML = '', 3000);
            }

            // Tự động Polling mỗi 5 giây
            fetchData();
            setInterval(fetchData, 5000);
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template)


# ==========================================
# LIGHTWEIGHT REALTIME APIS
# ==========================================

@app.route('/api/live_data')
@login_required
def api_live_data():
    # 1. Lấy danh sách giới hạn Slot
    slots_map = {}
    for doc in slots_col.find({}, {"_id": 1, "max_slots": 1}):
        slots_map[doc["_id"]] = doc.get("max_slots", 10)

    # 2. Lấy dữ liệu Shop Subscriptions
    users_data = {}
    
    # Chỉ lấy trường `_id` và `subscribers`
    cursor = shop_col.find({}, {"_id": 1, "subscribers": 1})
    for doc in cursor:
        item_name = doc["_id"].title()
        for sub in doc.get("subscribers", []):
            uid = sub["user_id"]
            if uid not in users_data:
                users_data[uid] = {
                    "user_id": uid,
                    "ign": get_ign_cached(uid),
                    "max_slots": slots_map.get(uid, 10),
                    "items": []
                }
            users_data[uid]["items"].append({
                "name": item_name,
                "max_price": sub["max_price"]
            })

    # Đưa kết quả về mảng và thêm thông tin used_slots
    result = []
    for uid, uinfo in users_data.items():
        uinfo["used_slots"] = len(uinfo["items"])
        result.append(uinfo)

    return jsonify(result)

@app.route('/api/update_slot', methods=['POST'])
@login_required
def api_update_slot():
    data = request.json or {}
    user_id_raw = str(data.get("user_id", "")).strip()
    max_slots = data.get("max_slots")

    if user_id_raw.isdigit() and isinstance(max_slots, int):
        slots_col.update_one({"_id": int(user_id_raw)}, {"$set": {"max_slots": max_slots}}, upsert=True)
        return jsonify({"status": "success"})
    return jsonify({"error": "Invalid payload"}), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)