import discord
from discord.ext import commands
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv

# ==========================================
# 1. KHỞI TẠO WEB SERVER ĐỂ RENDER HEALTH CHECK (BẮT BUỘC)
# ==========================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot MyKBot is online 24/7!")

    # Vô hiệu hóa log ra terminal để tránh rác log của bot
    def log_message(self, format, *args):
        return

def run_health_check_server():
    # Render tự động cấp port qua biến môi trường PORT
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"[System] Web server listening on port {port} for Render health check.")
    server.serve_forever()

# Chạy web server trên một luồng riêng biệt để không chặn bot hoạt động
threading.Thread(target=run_health_check_server, daemon=True).start()

# ==========================================
# 2. CẤU HÌNH VÀ KHỞI CHẠY BOT DISCORD
# ==========================================
load_dotenv()

# Sử dụng BOT_TOKEN cho đồng bộ với cấu hình Environment Variables trên Render
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("❌ Không tìm thấy BOT_TOKEN! Hãy kiểm tra lại cấu hình trên Render.")

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

# LỆNH KÍCH HOẠT CHẠY BOT (Giữ tiến trình chính luôn sống, tránh lỗi Port scan timeout)
bot.run(TOKEN)