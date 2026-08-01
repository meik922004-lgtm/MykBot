import discord
from discord.ext import commands
from discord import app_commands
import json
import os

# ==========================================
# CẤU HÌNH ID OWNER TẠI ĐÂY
OWNER_IDS = [1283689737567211581]  # Thay thế bằng ID Discord của bạn
# ==========================================

CONFIG_PATH = "roles_config.json"

def load_config():
    if not os.path.exists(CONFIG_PATH):
        default_config = {
            "stage": ["Endgame stage", "Newbie stage", "Midgame stage"],
            "general": ["Member", "Tourist", "PIED", "Mugen", "MDG", "PDG", "APO", "PILLAR AB", "RBH"],
            "combat": ["DPS SK/AA", "UFM", "TANK"]
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=4, ensure_ascii=False)
        return default_config
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

# BỘ LỌC TỰ ĐỊNH NGHĨA: HOẶC LÀ ADMIN HOẶC LÀ OWNER
def is_admin_or_owner():
    def predicate(interaction: discord.Interaction) -> bool:
        # 1. Kiểm tra nếu là Bot Owner
        if interaction.user.id in OWNER_IDS:
            return True
        # 2. Kiểm tra nếu là Admin của Server
        if interaction.guild and interaction.user.guild_permissions.administrator:
            return True
        return False
    return app_commands.check(predicate)

        
class StageSelect(discord.ui.Select):
    def __init__(self, options_list):
        options = [discord.SelectOption(label=name, value=name) for name in options_list]
        super().__init__(placeholder="Select stage role (Only 1)...", min_values=1, max_values=1, options=options, custom_id="roles_select:stage")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        selected_name = self.values[0]
        config = load_config()
        stage_roles_names = config.get("stage", [])
        
        target_role = discord.utils.get(guild.roles, name=selected_name)
        if not target_role:
            return await interaction.followup.send(f"❌ Role **{selected_name}** không tồn tại trên server!", ephemeral=True)

        # Nếu người dùng đã có role này rồi => Xóa role (Toggle OFF)
        if target_role in member.roles:
            await member.remove_roles(target_role)
            await interaction.followup.send(f"🗑️ Bạn đã gỡ role stage: **{selected_name}**", ephemeral=True)
        else:
            # Nếu chọn role mới => Xóa tất cả các role stage cũ khác và thêm role mới
            roles_to_remove = [discord.utils.get(guild.roles, name=n) for n in stage_roles_names if n != selected_name and discord.utils.get(guild.roles, name=n) in member.roles]
            roles_to_remove = [r for r in roles_to_remove if r]
            
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove)
            
            await member.add_roles(target_role)
            await interaction.followup.send(f"✅ Stage Role của bạn đã được cập nhật thành: **{selected_name}**", ephemeral=True)


class GeneralSelect(discord.ui.Select):
    def __init__(self, options_list):
        options = [discord.SelectOption(label=name, value=name) for name in options_list]
        max_vals = min(len(options), 25) if options else 1
        super().__init__(placeholder="Select General Roles...", min_values=1, max_values=max_vals, options=options, custom_id="roles_select:general")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        
        roles_to_add = []
        roles_to_remove = []
        
        # Kiểm tra từng role được bấm chọn
        for role_name in self.values:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                if role in member.roles:
                    roles_to_remove.append(role) # Đã có -> Xóa
                else:
                    roles_to_add.append(role)   # Chưa có -> Thêm
        
        msg_parts = []
        if roles_to_add:
            await member.add_roles(*roles_to_add)
            added_names = ", ".join([f"**{r.name}**" for r in roles_to_add])
            msg_parts.append(f"➕ Đã thêm: {added_names}")
            
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)
            removed_names = ", ".join([f"**{r.name}**" for r in roles_to_remove])
            msg_parts.append(f"➖ Đã gỡ: {removed_names}")
            
        if msg_parts:
            await interaction.followup.send("\n".join(msg_parts), ephemeral=True)
        else:
            await interaction.followup.send("⚠️ Không có thay đổi nào được thực hiện.", ephemeral=True)


class CombatSelect(discord.ui.Select):
    def __init__(self, options_list):
        options = [discord.SelectOption(label=name, value=name) for name in options_list]
        max_vals = min(len(options), 25) if options else 1
        super().__init__(placeholder="Select Combat Roles...", min_values=1, max_values=max_vals, options=options, custom_id="roles_select:combat")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        
        roles_to_add = []
        roles_to_remove = []
        
        # Kiểm tra từng role được bấm chọn
        for role_name in self.values:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                if role in member.roles:
                    roles_to_remove.append(role) # Đã có -> Xóa
                else:
                    roles_to_add.append(role)   # Chưa có -> Thêm
        
        msg_parts = []
        if roles_to_add:
            await member.add_roles(*roles_to_add)
            added_names = ", ".join([f"**{r.name}**" for r in roles_to_add])
            msg_parts.append(f"➕ Đã thêm: {added_names}")
            
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)
            removed_names = ", ".join([f"**{r.name}**" for r in roles_to_remove])
            msg_parts.append(f"➖ Đã gỡ: {removed_names}")
            
        if msg_parts:
            await interaction.followup.send("\n".join(msg_parts), ephemeral=True)
        else:
            await interaction.followup.send("⚠️ Không có thay đổi nào được thực hiện.", ephemeral=True)


class RolesMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        config = load_config()
        if config.get("stage"): self.add_item(StageSelect(config["stage"]))
        if config.get("general"): self.add_item(GeneralSelect(config["general"]))
        if config.get("combat"): self.add_item(CombatSelect(config["combat"]))

class RolesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        load_config()

    # Xử lý thông báo khi thành viên thường cố tình bấm lệnh admin
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            error_msg = "❌ You do not have permission to use this command! (Administrator or Bot Owner privileges required)."
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)
        else:
            print(f"Error in RolesCog: {error}")

    @app_commands.command(name="roles_menu", description="Send the menu to automatically assign roles.")
    @is_admin_or_owner()  # Sử dụng bộ lọc Admin hoặc Owner mới
    async def send_roles_menu(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎭 AUTOMATIC ROLES RECOGNITION SYSTEM",
            description="Please interact with the dropdown menus below:\n\n1️⃣ **Stage Role**\n2️⃣ **General Roles**\n3️⃣ **Combat Roles**",
            color=discord.Color.from_rgb(46, 204, 113)
        )
        await interaction.response.send_message(embed=embed, view=RolesMenuView())

    @app_commands.command(name="addrole", description="Add a server role to the configuration menu.")
    @app_commands.describe(category="Categories to add roles to", role="Roles need to be added.")
    @app_commands.choices(category=[
        app_commands.Choice(name="Stage Role", value="stage"),
        app_commands.Choice(name="General Roles", value="general"),
        app_commands.Choice(name="Combat Roles", value="combat")
    ])
    @is_admin_or_owner()  # Sử dụng bộ lọc Admin hoặc Owner mới
    async def add_role_to_menu(self, interaction: discord.Interaction, category: app_commands.Choice[str], role: discord.Role):
        cat_value = category.value
        config = load_config()
        if role.name in config[cat_value]:
            return await interaction.response.send_message(f"⚠️ Role **{role.name}** existed.", ephemeral=True)

        config[cat_value].append(role.name)
        save_config(config)
        await interaction.response.send_message(f"✅**{role.name}** has been added to the menu. `{cat_value}`!", ephemeral=True)

    @app_commands.command(name="removerole", description="Remove a role from the configuration menu.")
    @app_commands.describe(category="Category containing roles to be deleted", role_name="Name of the role.")
    @app_commands.choices(category=[
        app_commands.Choice(name="Stage Role", value="stage"),
        app_commands.Choice(name="General Roles", value="general"),
        app_commands.Choice(name="Combat Roles", value="combat")
    ])
    @is_admin_or_owner()  # Sử dụng bộ lọc Admin hoặc Owner mới
    async def remove_role_from_menu(self, interaction: discord.Interaction, category: app_commands.Choice[str], role_name: str):
        cat_value = category.value
        config = load_config()
        if role_name not in config[cat_value]:
            return await interaction.response.send_message(f"⚠️  **{role_name}** not found.", ephemeral=True)

        config[cat_value].remove(role_name)
        save_config(config)
        await interaction.response.send_message(f"✅ **{role_name}** has been removed from the menu.`{cat_value}`!", ephemeral=True)

async def setup(bot):
    bot.add_view(RolesMenuView()) 
    await bot.add_cog(RolesCog(bot))