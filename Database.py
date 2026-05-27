import motor.motor_asyncio
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    MONGO_URI = "mongodb+srv://meik922004_db_user:LrXxnoloY8TaezNI@database0.gjbsfwh.mongodb.net/?appName=database0"

client = motor.motor_asyncio.AsyncIOMotorClient(
    MONGO_URI, 
    tlsAllowInvalidCertificates=True
)

db = client.database0

# Thêm 3 dòng này vào cuối file
players_col = db.players
parties_col = db.parties
dungeon_configs_col = db["dungeon_configs"]