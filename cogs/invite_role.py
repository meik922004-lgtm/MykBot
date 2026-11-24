import discord
from discord import app_commands
from discord.ext import commands
from Database import invite_roles_col
from utils.checks import is_admin_or_bot_owner


class InviteRole(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.invite_cache: dict[int, dict[str, int]] = {}

    async def _cache_guild_invites(self, guild: discord.Guild):
        if not guild.me or not guild.me.guild_permissions.manage_guild:
            return
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {inv.code: inv.uses or 0 for inv in invites}
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._cache_guild_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild:
            self.invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if invite.guild and invite.guild.id in self.invite_cache:
            self.invite_cache[invite.guild.id].pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        if not guild.me or not guild.me.guild_permissions.manage_guild:
            return

        try:
            new_invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return

        old_invites = self.invite_cache.get(guild.id, {})
        used_code = None

        for inv in new_invites:
            old_uses = old_invites.get(inv.code, 0)
            if (inv.uses or 0) > old_uses:
                used_code = inv.code
                break

        # Cập nhật toàn bộ cache mới nhất
        self.invite_cache[guild.id] = {inv.code: inv.uses or 0 for inv in new_invites}

        if not used_code:
            return

        config = await invite_roles_col.find_one({"guild_id": guild.id})
        if config and used_code in config.get("invites", {}):
            role_id = int(config["invites"][used_code])
            role = guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role, reason=f"Joined via invite {used_code}")
                except discord.Forbidden:
                    print(f"[InviteRole] Thiếu quyền cấp role {role.name} tại server {guild.name}", flush=True)
                except Exception as e:
                    print(f"[InviteRole] Lỗi cấp role: {e}", flush=True)

    @app_commands.command(name="set_invite_role", description="Liên kết link mời với một Role tự động")
    @app_commands.describe(invite_code="Mã mời (VD: abcXYZ) hoặc dán trực tiếp link discord.gg/abcXYZ", role="Role cần cấp")
    @is_admin_or_bot_owner()
    async def set_invite_role(self, interaction: discord.Interaction, invite_code: str, role: discord.Role):
        clean_code = invite_code.strip().rstrip("/").split("/")[-1]
        await invite_roles_col.update_one(
            {"guild_id": interaction.guild_id},
            {"$set": {f"invites.{clean_code}": role.id}},
            upsert=True,
        )
        await interaction.response.send_message(
            f"✅ Đã liên kết mã mời `{clean_code}` với role **{role.name}**.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(InviteRole(bot))