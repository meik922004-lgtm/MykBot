import discord
from discord.ext import commands
import os
import threading
from dotenv import load_dotenv
from flask import Flask

# 1. Web server cho Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot MyKBot is online 24/7!"

def run_health_check_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)

threading.Thread(target=run_health_check_server, daemon=True).start()

# 2. Cấu hình Bot
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ Không tìm thấy BOT_TOKEN!")

class MyKBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        # Gọi hàm load cog ở đây
        await self.load_all_extensions()
        
        # Sync lệnh cho guild test để hiện ngay. Xóa dòng này sau khi test xong
        GUILD_ID = 1266433856328831008  # Thay ID server của bạn vào
        guild = discord.Object(id=GUILD_ID)
        await self.tree.sync(guild=guild)
        print("✅ Synced commands to test guild")

    async def load_all_extensions(self):
        print("=== Bắt đầu load cogs ===", flush=True)
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    print(f"✅ Loaded cog thành công: {filename}", flush=True)
                except Exception as e:
                    print(f"❌ KHÔNG THỂ load được file {filename}!", flush=True)
                    import traceback
                    traceback.print_exc()  # in full traceback

bot = MyKBot()

@bot.command()
async def sync(ctx):
    if ctx.author.id == 1283689737567211581:
        try:
            bot.tree.clear_commands(guild=ctx.guild)
            await bot.tree.sync(guild=ctx.guild)
            synced = await bot.tree.sync()
            await ctx.send(f"✅ Đã đồng bộ thành công {len(synced)} lệnh Slash Global!")
        except Exception as e:
            await ctx.send(f"❌ Lỗi: {e}")
    else:
        await ctx.send("❌ You don't have permission to use this command.")

@bot.event
async def on_ready():
    print(f"🟢 Bot đã sẵn sàng với tên {bot.user} (ID: {bot.user.id})")

bot.run(TOKEN)