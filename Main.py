import discord
from discord.ext import commands
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv

# ==========================================
# 1. KHỞI TẠO WEB SERVER CHO RENDER HEALTH CHECK
# ==========================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot MyKBot is online 24/7!")

    def log_message(self, format, *args):
        return

def run_health_check_server():
    # Render tự cấp port qua biến môi trường PORT
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"[System] Web server listening on port {port}...")
    server.serve_forever()

# Chạy server web ngầm trên một luồng riêng
threading.Thread(target=run_health_check_server, daemon=True).start()

# ==========================================
# 2. CẤU HÌNH VÀ KHỞI CHẠY BOT DISCORD
# ==========================================
load_dotenv()

# Đã đồng bộ tên biến với cấu hình trên Render
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("❌ Không tìm thấy BOT_TOKEN! Hãy kiểm tra lại cấu hình Environment Variables trên Render.")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

class MyKBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
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

# KÍCH HOẠT CHẠY BOT (Dòng này sẽ giữ cho tiến trình luôn sống)
bot.run(TOKEN)