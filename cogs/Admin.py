import asyncio
from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands
from Database import news_channel_col
from utils.checks import is_admin_or_bot_owner


class BroadcastModal(discord.ui.Modal, title="📢 Global System Broadcast"):
    """Modal allowing Bot Owners to compose and broadcast announcements to all subscribed servers."""

    message_input = discord.ui.TextInput(
        label="Announcement Message",
        style=discord.TextStyle.long,
        placeholder="Write your announcement here (supports line breaks and Markdown)...",
        required=True,
        max_length=4000,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        message = self.message_input.value
        channels_data = await news_channel_col.find({}, {"channel_id": 1}).to_list(length=None)

        utc_now = datetime.now(timezone.utc)
        day = utc_now.day
        suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        date_title = f"📢 {utc_now.strftime('%B')} {day}{suffix}, {utc_now.year}"

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
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                if channel:
                    await channel.send(embed=embed)
                    success_count += 1
                    await asyncio.sleep(0.3)  # Rate-limit protection
                else:
                    fail_count += 1
            except (discord.Forbidden, discord.NotFound):
                fail_count += 1
            except Exception as e:
                print(f"[Broadcast] Failed to send to channel {channel_id}: {e}", flush=True)
                fail_count += 1

        summary = (
            f"✅ **Global Broadcast Completed**\n"
            f"🟢 Delivered: `{success_count}` servers\n"
            f"🔴 Failed: `{fail_count}` servers"
        )
        await interaction.followup.send(summary, ephemeral=True)


class NewsSystemCog(commands.Cog):
    """Handles global announcement channel setup and owner broadcasts."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def open_broadcast_modal(self, interaction: discord.Interaction):
        """Helper invoked from /menu Owner Control Panel."""
        await interaction.response.send_modal(BroadcastModal(self.bot))

    @app_commands.command(
        name="setup_announcement",
        description="[Admin/Owner] Set the channel for global bot announcements",
    )
    @app_commands.describe(channel="Target text channel for bot announcements")
    @app_commands.default_permissions(administrator=True)
    @is_admin_or_bot_owner()
    async def setup_announcement(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        await news_channel_col.update_one(
            {"guild_id": interaction.guild_id},
            {"$set": {"channel_id": channel.id}},
            upsert=True,
        )
        embed = discord.Embed(
            title="✅ Announcement Channel Configured",
            description=f"This server will now receive global bot announcements in {channel.mention}.",
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


class Admin(commands.Cog):
    """Owner-only system maintenance commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="reloadall")
    @commands.is_owner()
    async def reload_all(self, ctx: commands.Context):
        """Reload all loaded extensions and sync global slash commands."""
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
                reloaded.append(f"🔄 Synced **{len(synced)}** global slash commands")
            except Exception as e:
                errors.append(f"❌ **Sync Tree**: `{e}`")

        embed = discord.Embed(
            title="🔄 System Reload",
            color=discord.Color.red() if errors else discord.Color.green(),
        )
        if reloaded:
            embed.add_field(name="Succeeded", value="\n".join(reloaded), inline=False)
        if errors:
            embed.add_field(name="Errors", value="\n".join(errors), inline=False)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(NewsSystemCog(bot))
    await bot.add_cog(Admin(bot))