import discord
from discord import app_commands
from discord.ext import commands
import json
import os

CONFIG_FILE = "roles_config.json"

def load_roles_data():
    if not os.path.exists(CONFIG_FILE):
        default_data = {"general_roles": ["Member", "RBH", "MDG", "PDG", "MUGEN", "PIED", "APO", "PILLAR AB"], "combat_roles": ["DPS", "UFM", "TANK"]}
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_data, f)
        return default_data
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_roles_data(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f)

# Logic xử lý gán/xóa role chung cho Select Menu
async def handle_role_assignment(interaction: discord.Interaction, selected_values: list, category_roles: list):
    await interaction.response.defer(ephemeral=True)
    
    # Lấy các role object từ server
    roles_to_add = []
    roles_to_remove = []
    
    for r_name in category_roles:
        role_obj = discord.utils.get(interaction.guild.roles, name=r_name)
        if not role_obj: continue
        
        if r_name in selected_values:
            roles_to_add.append(role_obj)
        elif role_obj in interaction.user.roles:
            roles_to_remove.append(role_obj)
            
    if roles_to_remove:
        await interaction.user.remove_roles(*roles_to_remove)
    if roles_to_add:
        await interaction.user.add_roles(*roles_to_add)
        
    await interaction.followup.send(f"✅ Đã cập nhật xong role nhóm {category_roles[0]}!", ephemeral=True)

class GeneralRolesSelect(discord.ui.Select):
    def __init__(self):
        data = load_roles_data()
        roles = data.get("general_roles", ["Member"])
        options = [discord.SelectOption(label=r, emoji="🛡️") for r in roles]
        super().__init__(placeholder="💠 General & Dungeon Roles...", min_values=0, max_values=len(options), options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        data = load_roles_data()
        await handle_role_assignment(interaction, self.values, data.get("general_roles", []))

class DynamicCombatSelect(discord.ui.Select):
    def __init__(self):
        data = load_roles_data()
        roles = data.get("combat_roles", ["DPS", "UFM", "TANK"]) # Đã sửa lỗi thiếu dấu phẩy
        options = [discord.SelectOption(label=r, emoji="⚔️") for r in roles]
        super().__init__(placeholder="🗡️ Combat Styles...", min_values=0, max_values=len(options), options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        data = load_roles_data()
        await handle_role_assignment(interaction, self.values, data.get("combat_roles", []))

class ServerRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GeneralRolesSelect())
        self.add_item(DynamicCombatSelect())

class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup_role_panel", description="Tạo bảng chọn role")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_role_panel(self, interaction: discord.Interaction):
        await interaction.response.send_message("Panel created!", view=ServerRolesView())

    @app_commands.command(name="add_role", description="Thêm role vào danh sách menu")
    @app_commands.choices(category=[
        app_commands.Choice(name="General/Dungeon", value="general_roles"),
        app_commands.Choice(name="Combat", value="combat_roles")
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def add_role(self, interaction: discord.Interaction, role_name: str, category: str):
        data = load_roles_data()
        if role_name not in data[category]:
            data[category].append(role_name)
            save_roles_data(data)
            await interaction.response.send_message(f"✅ Đã thêm **{role_name}** vào **{category}**", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Role đã tồn tại trong danh sách!", ephemeral=True)

async def setup(bot):
    bot.add_view(ServerRolesView()) 
    await bot.add_cog(Roles(bot))
