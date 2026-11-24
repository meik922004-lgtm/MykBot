import os
import discord
from discord import app_commands
from discord.ext import commands

_raw_owners = os.getenv("BOT_OWNER_IDS", "1283689737567211581")
BOT_OWNER_IDS = {int(x.strip()) for x in _raw_owners.split(",") if x.strip().isdigit()}


async def check_is_owner(bot: commands.Bot, user: discord.abc.User) -> bool:
    if user.id in BOT_OWNER_IDS:
        return True
    if bot.owner_ids and user.id in bot.owner_ids:
        return True
    return await bot.is_owner(user)


def is_bot_owner_slash():
    """Chỉ cho phép Bot Owner (dùng cho broadcast, setraid, setevent...)."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if await check_is_owner(interaction.client, interaction.user):
            return True
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "⛔ Lệnh này chỉ dành riêng cho **Bot Owner**.",
                ephemeral=True,
            )
        return False

    return app_commands.check(predicate)


def is_admin_or_bot_owner():
    """Cho phép Admin Server (Administrator/Manage Guild) HOẶC Bot Owner (dùng cho các lệnh setup)."""
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
                "⛔ Bạn cần quyền **Administrator** hoặc **Bot Owner** để sử dụng lệnh setup này.",
                ephemeral=True,
            )
        return False

    return app_commands.check(predicate)