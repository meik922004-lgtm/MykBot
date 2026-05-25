import discord
from discord import app_commands
from discord.ext import commands
import os
from motor.motor_asyncio import AsyncIOMotorClient

# --- KẾT NỐI MONGODB ---
MONGO_URL = os.getenv("MONGO_URL")
db_client = AsyncIOMotorClient(MONGO_URL)
db = db_client["mykbot_db"]
roles_collection = db["roles_config"]

DEFAULT_DATA = {
    "_id": "server_roles_config",
    "general_roles": ["Member", "RBH", "MDG", "PDG", "MUGEN", "PIED", "APO", "PILLAR AB"],
    "combat_roles": ["DPS", "UFM", "TANK"]
}

async def get_db_data():
    data = await roles_collection.find_one({"_id": "server_roles_config"})
    if not data:
        await roles_collection.insert_one(DEFAULT_DATA)
        return DEFAULT_DATA
    return data

# --- VIEW CẤU HÌNH (Dùng cho cả Menu Role và Update Menu) ---
class RoleSelect(discord.ui.Select):
    def __init__(self, roles, category, custom_id, emoji):
        options = [discord.SelectOption(label=r, emoji=emoji) for r in roles]
        super().__init__(placeholder=f"Chọn {category}...", min_values=0, max_values=len(options) or 1, 
                         options=options, custom_id=custom_id)
        self.category = category

    async def callback(self, interaction: discord.Interaction):
        data = await get_db_data()
        category_roles = data.get(self.category, [])
        
        # Xử lý gán role
        to_add = [discord.utils.get(interaction.guild.roles, name=r) for r in self.values if discord.utils.get(interaction.guild.roles, name=r)]
        to_remove = [discord.utils.get(interaction.guild.roles, name=r) for r in category_roles if r not in self.values]
        
        await interaction.user.add_roles(*[r for r in to_add if r])
        await interaction.user.remove_roles(*[r for r in to_remove if r])
        await interaction.response.send_message("✅ Đã cập nhật!", ephemeral=True)

class ServerRolesView(discord.ui.View):
    def __init__(self, data):
        super().__init__(timeout=None)
        self.add_item(RoleSelect(data.get("general_roles", []), "general_roles", "p_general", "🛡️"))
        self.add_item(RoleSelect(data.get("combat_roles", []), "combat_roles", "p_combat", "⚔️"))

# --- COG CHÍNH ---
class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup_role_panel", description="Tạo bảng chọn role")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_role_panel(self, interaction: discord.Interaction):
        data = await get_db_data()
        await interaction.response.send_message("💠 **BẢNG CHỌN ROLE**", view=ServerRolesView(data))

    @app_commands.command(name="add_role", description="Thêm role")
    async def add_role(self, interaction: discord.Interaction, role_name: str, category: str):
        data = await get_db_data()
        data[category].append(role_name)
        await roles_collection.replace_one({"_id": "server_roles_config"}, data)
        await interaction.response.send_message(f"✅ Đã thêm {role_name} vào {category}", ephemeral=True)

    @app_commands.command(name="remove_role", description="Xóa role")
    async def remove_role(self, interaction: discord.Interaction, role_name: str, category: str):
        data = await get_db_data()
        if role_name in data[category]:
            data[category].remove(role_name)
            await roles_collection.replace_one({"_id": "server_roles_config"}, data)
            await interaction.response.send_message(f"✅ Đã xóa {role_name}", ephemeral=True)

async def setup(bot):
    # Load data và đăng ký View ngay khi bot khởi động
    data = await get_db_data()
    bot.add_view(ServerRolesView(data))
    await bot.add_cog(Roles(bot))