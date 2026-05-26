import discord
from discord.ext import commands
import os
import threading
from dotenv import load_dotenv
from flask import Flask
# ==========================================
# 1. KHỞI TẠO WEB SERVER ĐỂ RENDER HEALTH CHECK
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot MyKBot is online 24/7!"

def run_health_check_server():
    # Lấy port Render cấp, nếu không có thì mặc định 10000
    port = int(os.environ.get("PORT", 10000))
    # use_reloader=False rất quan trọng khi chạy bằng Thread để tránh lỗi loop
    app.run(host='0.0.0.0', port=port, use_reloader=False) 

threading.Thread(target=run_health_check_server, daemon=True).start()

# ==========================================
# 2. CẤU HÌNH BOT
# ==========================================
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("❌ Không tìm thấy BOT_TOKEN!")

class MyKBot(commands.Bot):
    def __init__(self):
        # Thiết lập intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        
        # BẮT BUỘC PHẢI CÓ DÒNG NÀY ĐỂ KHỞI TẠO BOT
        super().__init__(
            command_prefix="!", 
            intents=intents, 
            help_command=None
        )

    async def setup_hook(self):
        # 1. Load các Cogs
        cog_path = "./cogs"
        if os.path.exists(cog_path):
            for filename in os.listdir(cog_path):
                if filename.endswith(".py") and not filename.startswith("__"):
                    try:
                        await self.load_extension(f"cogs.{filename[:-3]}")
                        print(f"✅ Loaded extension: {filename}")
                    except Exception as e:
                        print(f"❌ Failed to load {filename}: {e}")
        
bot = MyKBot()

@bot.command()
async def sync(ctx):
    # Thay '123456789012345678' bằng ID Discord của bạn để bảo mật
    if ctx.author.id == 1283689737567211581: 
        try:
            synced = await bot.tree.sync()
            await ctx.send(f"✅ Đã đồng bộ thành công {len(synced)} lệnh Slash!")
        except Exception as e:
            await ctx.send(f"❌ Lỗi: {e}")
    else:
        await ctx.send("❌ You dont have permission to use this command.")


@bot.event
async def on_ready():
    print(f"🟢 Bot đã sẵn sàng với tên {bot.user} (ID: {bot.user.id})")
    

bot.run(TOKEN)