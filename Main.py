import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv

# Load môi trường
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

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
        # Load Cogs từ thư mục cogs/
        cog_path = "./cogs"
        if os.path.exists(cog_path):
            for filename in os.listdir(cog_path):
                if filename.endswith(".py") and not filename.startswith("__"):
                    try:
                        await self.load_extension(f"cogs.{filename[:-3]}")
                        print(f"✅ Loaded extension: {filename}")
                    except Exception as e:
                        print(f"❌ Failed to load {filename}: {e}")
        
        # In thông báo để biết bot đã sẵn sàng
        print("🟢 Các Cog đã được tải xong.")

bot = MyKBot()

@bot.command()
async def sync(ctx):
    """Lệnh này sync lệnh Slash vào server hiện tại NGAY LẬP TỨC"""
    if ctx.author.id == 1283689737567211581: 
        try:
            # Sync lệnh Slash vào đúng server hiện tại để test nhanh
            bot.tree.copy_global_to(guild=ctx.guild)
            synced = await bot.tree.sync(guild=ctx.guild)
            await ctx.send(f"✅ Đã đồng bộ thành công {len(synced)} lệnh Slash vào server này!")
        except Exception as e:
            await ctx.send(f"❌ Lỗi: {e}")
    else:
        await ctx.send("❌ You don't have permission.")

@bot.event
async def on_ready():
    print(f"🟢 Bot đã sẵn sàng: {bot.user} (ID: {bot.user.id})")

# Chạy bot
if __name__ == "__main__":
    bot.run(TOKEN)