import asyncio
from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands
from Database import news_channel_col
from utils.checks import is_admin_or_bot_owner, is_bot_owner_slash


class BroadcastModal(discord.ui.Modal):
    def __init__(self, cog: commands.Cog):
        super().__init__(title="📢 Global System Broadcast")
        self.cog = cog

    message_input = discord.ui.TextInput(
        label="Nội dung thông báo",
        style=discord.TextStyle.long,
        placeholder="Nhập nội dung thông báo (hỗ trợ xuống dòng và Markdown)...",
        required=True,
        max_length=4000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        message = self.message_input.value
        channels_data = await news_channel_col.find({}, {"channel_id": 1}).to_list(length=None)

        utc_now = datetime.now(timezone.utc)
        day = utc_now.day
        suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        date_title = f"📢 {utc_now.strftime('%B')} {day}{suffix} {utc_now.year}"

        embed = discord.Embed(
            title=date_title,
            description=message,
            color=discord.Color.from_str("#2ecc71"),
            timestamp=utc_now,
        )
        embed.set_footer(text="Global System Announcement")

        success_count = 0
        fail_count = 0

        for data in channels_data:
            channel_id = data.get("channel_id")
            if not channel_id:
                continue
            try:
                channel = self.cog.bot.get_channel(channel_id) or await self.cog.bot.fetch_channel(channel_id)
                if channel:
                    await channel.send(embed=embed)
                    success_count += 1
                    await asyncio.sleep(0.3)  # Tránh dính rate-limit khi gửi nhiều server
                else:
                    fail_count += 1
            except (discord.Forbidden, discord.NotFound):
                fail_count += 1
            except Exception as e:
                print(f"[Broadcast] Lỗi gửi tới kênh {channel_id}: {e}", flush=True)
                fail_count += 1

        summary = (
            f"✅ **Hoàn tất gửi Broadcast!**\n"
            f"🟢 Thành công: `{success_count}` server\n"
            f"🔴 Thất bại: `{fail_count}` server"
        )
        await interaction.followup.send(summary, ephemeral=True)


class NewsSystemCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setup_news_channel", description="Thiết lập kênh nhận tin tức & thông báo từ Bot")
    @app_commands.describe(channel="Chọn kênh bạn muốn bot gửi thông báo")
    @is_admin_or_bot_owner()
    async def setup_news_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        await news_channel_col.update_one(
            {"guild_id": interaction.guild_id},
            {"$set": {"channel_id": channel.id}},
            upsert=True,
        )
        embed = discord.Embed(
            title="✅ Setup Thành Công",
            description=f"Server này sẽ nhận thông báo cập nhật tại kênh {channel.mention}.",
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="ownerbroadcast", description="[Bot Owner] Mở bảng soạn thông báo gửi toàn bộ server")
    @is_bot_owner_slash()
    async def ownerbroadcast(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BroadcastModal(self))


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="reloadall")
    @commands.is_owner()
    async def reload_all(self, ctx: commands.Context):
        async with ctx.typing():
            reloaded, errors = [], []
            for ext in list(self.bot.extensions.keys()):
                try:
                    await self.bot.reload_extension(ext)
                    reloaded.append(f"✅ `{ext.split('.')[-1]}`")
                except Exception as e:
                    errors.append(f"❌ **{ext.split('.')[-1]}**: `{e}`")

            try:
                synced = await self.bot.tree.sync()
                reloaded.append(f"🔄 Đã đồng bộ **{len(synced)}** Slash Commands")
            except Exception as e:
                errors.append(f"❌ **Sync Tree**: `{e}`")

        embed = discord.Embed(
            title="🔄 System Reload",
            color=discord.Color.red() if errors else discord.Color.green(),
        )
        if reloaded:
            embed.add_field(name="Thành công", value="\n".join(reloaded), inline=False)
        if errors:
            embed.add_field(name="Lỗi", value="\n".join(errors), inline=False)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(NewsSystemCog(bot))
    await bot.add_cog(Admin(bot))