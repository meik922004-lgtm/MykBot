import os
import traceback
import discord
from discord.ext import commands
from dotenv import load_dotenv
from Database import db, client as mongo_client, init_indexes
from utils.checks import BOT_OWNER_IDS

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ Không tìm thấy BOT_TOKEN trong biến môi trường!")


class MyKBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
            owner_ids=BOT_OWNER_IDS,
        )
        self.db = db

    async def setup_hook(self):
        await init_indexes()
        await self.load_all_extensions()

    async def load_all_extensions(self):
        print("=== Bắt đầu load cogs ===", flush=True)
        cogs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cogs")
        for filename in sorted(os.listdir(cogs_dir)):
            if filename.endswith(".py") and not filename.startswith("_"):
                ext_name = f"cogs.{filename[:-3]}"
                try:
                    await self.load_extension(ext_name)
                    print(f"✅ Loaded cog: {filename}", flush=True)
                except Exception as e:
                    print(f"❌ KHÔNG THỂ load file {filename}: {repr(e)}", flush=True)
                    print(traceback.format_exc(), flush=True)

    async def close(self):
        mongo_client.close()
        await super().close()


bot = MyKBot()


@bot.command(name="sync")
@commands.is_owner()
async def sync_cmd(ctx: commands.Context, scope: str = "global"):
    """Đồng bộ Slash Commands. Dùng: !sync (global) hoặc !sync guild (server hiện tại)."""
    try:
        if scope.lower() == "guild":
            bot.tree.copy_global_to(guild=ctx.guild)
            synced = await bot.tree.sync(guild=ctx.guild)
            await ctx.send(f"✅ Đã đồng bộ **{len(synced)}** lệnh Slash vào server này!")
        else:
            bot.tree.clear_commands(guild=ctx.guild)
            await bot.tree.sync(guild=ctx.guild)
            synced = await bot.tree.sync()
            await ctx.send(f"✅ Đã đồng bộ **{len(synced)}** lệnh Slash Global!")
    except Exception as e:
        await ctx.send(f"❌ Lỗi đồng bộ: `{e}`")


@sync_cmd.error
async def sync_error(ctx: commands.Context, error):
    if isinstance(error, commands.NotOwner):
        await ctx.send("⛔ Chỉ **Bot Owner** mới được phép sử dụng lệnh này.")


@bot.event
async def on_ready():
    print(f"🟢 Bot đã sẵn sàng: {bot.user} (ID: {bot.user.id}) | Owners: {BOT_OWNER_IDS}", flush=True)


if __name__ == "__main__":
    bot.run(TOKEN)