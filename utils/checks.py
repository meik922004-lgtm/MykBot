import os
import discord
from discord import app_commands
from discord.ext import commands

# Load Bot Owner IDs from environment variables (e.g., BOT_OWNER_IDS=123456789,987654321)
_raw_owners = os.getenv("BOT_OWNER_IDS", "1283689737567211581")
BOT_OWNER_IDS = {int(x.strip()) for x in _raw_owners.split(",") if x.strip().isdigit()}


async def check_is_owner(bot: commands.Bot, user: discord.abc.User) -> bool:
    """Return True if the user is a configured Bot Owner or Discord Application Owner."""
    if user.id in BOT_OWNER_IDS:
        return True
    if bot.owner_ids and user.id in bot.owner_ids:
        return True
    return await bot.is_owner(user)


def is_bot_owner_slash():
    """App command check restricting usage strictly to Bot Owners."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if await check_is_owner(interaction.client, interaction.user):
            return True
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "⛔ Access denied. This action is restricted to **Bot Owners** only.",
                ephemeral=True,
            )
        return False

    return app_commands.check(predicate)


def is_admin_or_bot_owner():
    """App command check allowing Server Administrators (or Manage Guild) and Bot Owners."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if await check_is_owner(interaction.client, interaction.user):
            return True
        if interaction.guild and (
            interaction.user.guild_permissions.administrator
            or interaction.user.guild_permissions.manage_guild
        ):
            return True
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "⛔ Access denied. You need **Administrator** or **Bot Owner** permissions to use this setup command.",
                ephemeral=True,
            )
        return False

    return app_commands.check(predicate)