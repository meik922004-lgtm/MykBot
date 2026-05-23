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

# --- THÊM ĐOẠN NÀY ĐỂ ĐÁNH LỪA RENDER WEB SERVICE ---
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is running!")

def run_health_check():
    # Render luôn truyền một cổng mạng qua biến môi trường PORT (mặc định thường là 10000)
    import os
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# Chạy server web ngầm để Render không tắt bot
threading.Thread(target=run_health_check, daemon=True).start()
# ---------------------------------------------------

# Tiếp tục lệnh chạy bot gốc của bạn ở phía dưới...
# client.run(BOT_TOKEN) hoặc bot.run()