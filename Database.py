import motor.motor_asyncio
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise ValueError("❌ Thiếu cấu hình MONGO_URI trong tệp .env!")

client = motor.motor_asyncio.AsyncIOMotorClient(
    MONGO_URI, 
    tlsAllowInvalidCertificates=True
)

db = client.database0

# User & Core collections
players_col = db["players"]
parties_col = db["parties"]
dungeon_configs_col = db["dungeon_configs"]
invite_roles_col = db["invite_roles_config"]
rpg_profiles_col = db["rpg_profiles"]
world_boss_col = db["world_boss"]
boss_channels_col = db["boss_channels"]
cross_messages_col = db["cross_chat_logs"]

# System & Configs
news_channel_col = db["server_configs"]
patch_hub_col = db["patch_hub"]
patch_subscribers_col = db["patch_subscribers"]
patch_history_col = db["patch_history"]
patch_queue_col = db["patch_queue"]
patch_messages_col = db["patch_messages"]

# Market Tracker & Giveaways
shop_subscriptions_col = db["shop_subscriptions"]
user_slots_col = db["user_slots"]
bot_logs_col = db["bot_logs"]
market_history_col = db["market_history"]
giveaways_col = db["giveaways"]