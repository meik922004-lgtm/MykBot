import motor.motor_asyncio
import os
from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    # Nếu không tìm thấy biến môi trường, hệ thống sẽ lấy chuỗi mặc định của bạn để chạy ổn định
    MONGO_URI = "mongodb+srv://meik922004_db_user:LrXxnoloY8TaezNI@database0.gjbsfwh.mongodb.net/?appName=database0"

# SỬA TẠI ĐÂY: Thêm tham số tlsAllowInvalidCertificates=True vào Client để vượt qua lỗi SSL trên Render
client = motor.motor_asyncio.AsyncIOMotorClient(
    MONGO_URI, 
    tlsAllowInvalidCertificates=True
)
db = client.database0