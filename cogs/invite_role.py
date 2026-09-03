import discord
from discord.ext import commands
from discord import app_commands
from database import db # Giả định bạn dùng chung db với các file khác

# Collection để lưu cấu hình: { "guild_id": 123, "invites": {"abcXYZ": 987654321} }
# Trong đó abcXYZ là mã code, 987654321 là ID của role
invite_roles_col = db["invite_roles_config"]

class InviteRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Cache để theo dõi số lượng sử dụng của các invite link
        self.invite_cache = {}

    @commands.Cog.listener()
    async def on_ready(self):
        # Lưu lại trạng thái ban đầu của các invite link khi bot khởi động
        for guild in self.bot.guilds:
            if guild.me.guild_permissions.manage_guild:
                invites = await guild.invites()
                self.invite_cache[guild.id] = {invite.code: invite.uses for invite in invites}

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.guild.me.guild_permissions.manage_guild:
            return

        # Lấy danh sách invite hiện tại để so sánh
        new_invites = await member.guild.invites()
        old_invites = self.invite_cache.get(member.guild.id, {})

        for invite in new_invites:
            if invite.code in old_invites and invite.uses > old_invites[invite.code]:
                # Đây là link vừa được sử dụng
                config = await invite_roles_col.find_one({"guild_id": member.guild.id})
                if config and invite.code in config.get("invites", {}):
                    role_id = int(config["invites"][invite.code])
                    role = member.guild.get_role(role_id)
                    if role:
                        try:
                            await member.add_roles(role)
                        except Exception as e:
                            print(f"Error adding role: {e}")
                
                # Cập nhật lại cache
                self.invite_cache[member.guild.id][invite.code] = invite.uses
                break

    @app_commands.command(name="set_invite_role", description="Liên kết link mời với một Role")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_invite_role(self, interaction: discord.Interaction, invite_code: str, role: discord.Role):
        # Lưu cấu hình vào DB
        await invite_roles_col.update_one(
            {"guild_id": interaction.guild_id},
            {"$set": {f"invites.{invite_code}": role.id}},
            upsert=True
        )
        await interaction.response.send_message(f"✅ Đã liên kết code `{invite_code}` với role **{role.name}**.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(InviteRole(bot))