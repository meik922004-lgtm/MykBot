import os
import hmac
import time
from functools import wraps
from collections import OrderedDict
from datetime import datetime, timezone
from flask import request, jsonify
import certifi
from flask import Flask, request, redirect, url_for, session, render_template_string, jsonify
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET")
if not app.secret_key:
    raise RuntimeError("❌ Thiếu biến môi trường FLASK_SECRET!")

MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise RuntimeError("❌ Thiếu biến môi trường MONGO_URI!")

DB_NAME = os.getenv("MONGO_DB_NAME", "database0")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD")
if not DASHBOARD_PASSWORD:
    raise RuntimeError("❌ Thiếu biến môi trường DASHBOARD_PASSWORD!")

client = MongoClient(
    MONGO_URI,
    tlsCAFile=certifi.where(),
    serverSelectionTimeoutMS=3000,
    maxPoolSize=5,
)
db = client[DB_NAME]

players_col = db["players"]
slots_col = db["user_slots"]
shop_col = db["shop_subscriptions"]

IGN_CACHE: OrderedDict[int, tuple[str, float]] = OrderedDict()
CACHE_TTL = 60
MAX_CACHE_SIZE = 500


def get_igns_batch(user_ids: list[int]) -> dict[int, str]:
    now = time.time()
    result: dict[int, str] = {}
    missing_ids: list[int] = []

    for uid in user_ids:
        cached = IGN_CACHE.get(uid)
        if cached and (now - cached[1] < CACHE_TTL):
            IGN_CACHE.move_to_end(uid)
            result[uid] = cached[0]
        else:
            missing_ids.append(uid)

    if missing_ids:
        try:
            cursor = players_col.find(
                {"user_id": {"$in": missing_ids}},
                {"user_id": 1, "ign": 1, "_id": 0},
            )
            found_map = {doc["user_id"]: doc.get("ign") for doc in cursor}
        except Exception:
            found_map = {}

        for uid in missing_ids:
            raw_ign = found_map.get(uid)
            ign = raw_ign if raw_ign and raw_ign != "Not Set" else f"ID: {uid}"
            result[uid] = ign
            IGN_CACHE[uid] = (ign, now)
            IGN_CACHE.move_to_end(uid)

        while len(IGN_CACHE) > MAX_CACHE_SIZE:
            IGN_CACHE.popitem(last=False)

    return result


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    error_msg = ""
    if request.method == "POST":
        if request.form.get("password") == DASHBOARD_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("admin"))
        error_msg = '<div class="alert alert-danger py-2 small">Sai mật khẩu!</div>'

    return f"""
    <!DOCTYPE html><html><head><title>Admin Login</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>body{{background-color:#0d1117;color:#fff;height:100vh;display:flex;align-items:center;justify-content:center;}}
    .card{{background:#161b22;padding:30px;border-radius:10px;border:1px solid #30363d;width:100%;max-width:380px;}}</style>
    </head><body>
    <div class="card shadow-lg text-center">
        <h4 class="text-primary mb-3">MyKBot Control Panel</h4>
        {error_msg}
        <form method="POST">
            <input type="password" name="password" class="form-control bg-dark text-white border-secondary mb-3" placeholder="Mật khẩu Admin..." required autofocus>
            <button class="btn btn-primary w-100 fw-bold">Đăng Nhập</button>
        </form>
    </div></body></html>
    """


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@app.route("/admin")
@login_required
def admin():
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
                <span class="me-3 small text-muted"><span class="pulse-dot me-1"></span> Live Data (10s)</span>
                <a href="/logout" class="btn btn-sm btn-outline-danger"><i class="fa-solid fa-power-off"></i></a>
            </div>
        </nav>

        <div class="container-fluid px-4">
            <div class="card p-3 mb-4">
                <div class="row g-2 align-items-center">
                    <div class="col-auto"><strong class="text-warning"><i class="fa-solid fa-user-gear me-1"></i> Cấp Slot:</strong></div>
                    <div class="col-auto"><input type="text" id="slot_user_id" class="form-control form-control-sm bg-dark text-white border-secondary" placeholder="Discord User ID"></div>
                    <div class="col-auto"><input type="number" id="slot_count" class="form-control form-control-sm bg-dark text-white border-secondary" style="width: 100px;" placeholder="Slots" min="0"></div>
                    <div class="col-auto"><button onclick="updateSlot()" class="btn btn-sm btn-warning fw-bold">Cập Nhật</button></div>
                    <div class="col-auto"><span id="slot_status" class="small ms-2"></span></div>
                </div>
            </div>

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
                if (document.hidden) return;
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

            fetchData();
            setInterval(fetchData, 10000);
            document.addEventListener("visibilitychange", () => { if (!document.hidden) fetchData(); });
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template)


@app.route("/api/live_data")
@login_required
def api_live_data():
    slots_map = {
        int(doc["_id"]): doc.get("max_slots", 10)
        for doc in slots_col.find({}, {"_id": 1, "max_slots": 1})
        if str(doc["_id"]).isdigit()
    }

    users_data = {}
    for doc in shop_col.find({}, {"_id": 1, "subscribers": 1}):
        item_name = str(doc["_id"]).title()
        for sub in doc.get("subscribers", []):
            uid = int(sub["user_id"])
            if uid not in users_data:
                users_data[uid] = {
                    "user_id": str(uid),
                    "max_slots": slots_map.get(uid, 10),
                    "items": [],
                }
            users_data[uid]["items"].append({
                "name": item_name,
                "max_price": sub["max_price"],
            })

    ign_map = get_igns_batch(list(users_data.keys()))

    result = []
    for uid, uinfo in users_data.items():
        uinfo["ign"] = ign_map.get(uid, f"ID: {uid}")
        uinfo["used_slots"] = len(uinfo["items"])
        result.append(uinfo)

    return jsonify(result)


@app.route("/api/update_slot", methods=["POST"])
@login_required
def api_update_slot():
    data = request.json or {}
    user_id_raw = str(data.get("user_id", "")).strip()
    max_slots = data.get("max_slots")

    if user_id_raw.isdigit() and isinstance(max_slots, int) and max_slots >= 0:
        slots_col.update_one(
            {"_id": int(user_id_raw)},
            {"$set": {"max_slots": max_slots}},
            upsert=True,
        )
        return jsonify({"status": "success"})
    return jsonify({"error": "Invalid payload"}), 400

# Load SIEM ingestion key from environment
SIEM_API_KEY = os.getenv("SIEM_API_KEY", "")
siem_events_col = db["siem_events"]

# Bounded LRU cache for per-IP rate limiting (max 60 requests / 60s)
SIEM_RATE_LIMIT = OrderedDict()
MAX_TRACKED_IPS = 500
RATE_WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 60


def _is_siem_rate_limited(client_ip: str) -> bool:
    """Enforce sliding-window rate limiting per client IP using bounded memory."""
    now = time.time()
    timestamps = SIEM_RATE_LIMIT.get(client_ip, [])
    timestamps = [ts for ts in timestamps if now - ts < RATE_WINDOW_SECONDS]

    if len(timestamps) >= MAX_REQUESTS_PER_WINDOW:
        SIEM_RATE_LIMIT[client_ip] = timestamps
        SIEM_RATE_LIMIT.move_to_end(client_ip)
        return True

    timestamps.append(now)
    SIEM_RATE_LIMIT[client_ip] = timestamps
    SIEM_RATE_LIMIT.move_to_end(client_ip)

    if len(SIEM_RATE_LIMIT) > MAX_TRACKED_IPS:
        SIEM_RATE_LIMIT.popitem(last=False)
    return False


@app.route("/api/siem/ingest", methods=["POST"])
def ingest_siem_event():
    """Receive Windows/Active Directory security telemetry over HTTPS."""
    if not SIEM_API_KEY:
        return jsonify({"error": "SIEM ingestion is not configured on server"}), 503

    # Constant-time comparison to prevent timing side-channel attacks
    provided_key = request.headers.get("X-SIEM-API-KEY", "")
    if not provided_key or not hmac.compare_digest(provided_key, SIEM_API_KEY):
        return jsonify({"error": "Unauthorized"}), 401

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if _is_siem_rate_limited(client_ip):
        return jsonify({"error": "Rate limit exceeded"}), 429

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400

    # Validate required telemetry fields
    required_fields = ("hostname", "event_id", "channel", "message")
    if any(field not in payload for field in required_fields):
        return jsonify({"error": "Missing required telemetry fields"}), 400

    try:
        event_id = int(payload["event_id"])
    except (ValueError, TypeError):
        return jsonify({"error": "event_id must be an integer"}), 400

    # Sanitize and bound string lengths to prevent oversized document injection
    doc = {
        "hostname": str(payload.get("hostname", ""))[:128],
        "domain": str(payload.get("domain", "WORKGROUP"))[:128],
        "event_id": event_id,
        "channel": str(payload.get("channel", "Security"))[:64],
        "level": str(payload.get("level", "Information"))[:32],
        "target_user": str(payload.get("target_user", ""))[:128],
        "source_ip": str(payload.get("source_ip", ""))[:64],
        "logon_type": str(payload.get("logon_type", ""))[:16],
        "message": str(payload.get("message", ""))[:2000],
        "timestamp": str(payload.get("timestamp", datetime.now(timezone.utc).isoformat()))[:64],
        "ingested_at": datetime.now(timezone.utc),
        "alerted": False,
    }

    siem_events_col.insert_one(doc)
    return jsonify({"status": "ingested", "event_id": event_id}), 201

if __name__ == "__main__":
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)