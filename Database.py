import os
import certifi
import motor.motor_asyncio
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise RuntimeError("❌ Thiếu biến môi trường MONGO_URI! Hãy cấu hình trong .env hoặc Render.")

DB_NAME = os.getenv("MONGO_DB_NAME", "database0")

client = motor.motor_asyncio.AsyncIOMotorClient(
    MONGO_URI,
    tlsCAFile=certifi.where(),
    maxPoolSize=10,
    minPoolSize=1,
    serverSelectionTimeoutMS=5000,
)

db = client[DB_NAME]

# --- CORE & PARTY / DUNGEON ---
players_col = db["players"]
parties_col = db["parties"]
dungeon_configs_col = db["dungeon_configs"]
invite_roles_col = db["invite_roles_config"]

# --- SERVER CONFIG & PATCH SUMMARY ---
news_channel_col = db["server_configs"]
news_col = news_channel_col  # Alias giữ tương thích cho các cog cũ
patch_hub_col = db["patch_hub"]
patch_subscribers_col = db["patch_subscribers"]
patch_history_col = db["patch_history"]
patch_queue_col = db["patch_queue"]
patch_messages_col = db["patch_messages"]

# --- MARKET TRACKER & GIVEAWAYS ---
shop_subscriptions_col = db["shop_subscriptions"]
user_slots_col = db["user_slots"]
bot_logs_col = db["bot_logs"]
market_history_col = db["market_history"]

# --- TẠM GIỮ TƯƠNG THÍCH (Sẽ kiểm tra và xóa ở Giai đoạn 2 nếu không Cog nào dùng) ---
world_boss_col = db["world_boss"]
boss_channels_col = db["boss_channels"]
cross_messages_col = db["cross_chat_logs"]


async def init_indexes():
    """Khởi tạo các Index quan trọng khi Bot khởi động để tăng tốc truy vấn và tiết kiệm dung lượng."""
    try:
        await players_col.create_index("user_id", unique=True, sparse=True)
        await shop_subscriptions_col.create_index("subscribers.user_id")
        await parties_col.create_index([("status", 1), ("created_at", -1)])
        await parties_col.create_index("members.user_id")

        # Index vẽ biểu đồ giá chợ + tự xóa dữ liệu cũ hơn 30 ngày
        await market_history_col.create_index([("items.item_name", 1), ("timestamp", -1)])
        await market_history_col.create_index("timestamp", expireAfterSeconds=2592000)

        # Tự xóa log cũ hơn 7 ngày
        await bot_logs_col.create_index("created_at", expireAfterSeconds=604800)
        print("✅ Đã khởi tạo MongoDB Indexes thành công!", flush=True)
    except Exception as e:
        print(f"⚠️ Cảnh báo khởi tạo Index: {e}", flush=True)