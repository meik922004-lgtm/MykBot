import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# --- KHỞI TẠO WEB SERVER ĐỂ GIỮ BOT LUÔN CHẠY TRÊN RENDER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot MyKBot đang hoạt động 24/7!"

def run_server():
    # Render sẽ cấp một cổng PORT ngẫu nhiên qua biến môi trường, mặc định là 8080
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_server)
    t.start()
# --------------------------------------------------------
# ==========================================
# ĐOẠN CODE BẮT BUỘC ĐỂ CHẠY TRÊN RENDER WEB SERVICE
# ==========================================
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import os

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is online and healthy!")

    # Vô hiệu hóa log ra terminal của server web để tránh rác log của bot
    def log_message(self, format, *args):
        return

def run_health_check_server():
    # Render tự động cấp port qua biến môi trường PORT, nếu chạy local sẽ dùng port 10000
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"[System] Web server listening on port {port} for Render health check.")
    server.serve_forever()

# Chạy web server trên một luồng (thread) riêng biệt để không chặn bot hoạt động
threading.Thread(target=run_health_check_server, daemon=True).start()
# ==========================================

# Phía dưới này giữ nguyên lệnh chạy bot gốc của bạn
# Ví dụ: bot.run(os.getenv("BOT_TOKEN"))

# Tải token từ .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise ValueError("❌ Không tìm thấy DISCORD_TOKEN trong file .env!")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

class MyKBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        # Tải toàn bộ Cogs trong thư mục ./cogs
        if not os.path.exists("./cogs"):
            os.makedirs("./cogs")
            
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py") and not filename.startswith("__"):
                try:
                    await self.load_extension(f"cogs.{filename[:-3]}")
                    print(f"✅ Loaded: {filename}")
                except Exception as e:
                    print(f"❌ Failed to load {filename}: {e}")

bot = MyKBot()

@bot.event
async def on_ready():
    print(f"🟢 Bot đã sẵn sàng với tên {bot.user} (ID: {bot.user.id})")

# client.run(BOT_TOKEN) hoặc bot.run()