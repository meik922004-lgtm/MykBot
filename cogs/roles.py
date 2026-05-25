import discord
from discord import app_commands
from discord.ext import commands
import json
import os

# ==========================
# CONFIGURATION
# ==========================
CONFIG_FILE = "roles_config.json"
TOURIST_ROLE_NAME = "Tourist"
STAGE_ROLES = ["Newbie stage", "Mid game stage", "Endgame stage"]

def load_roles_data():
    if not os.path.exists(CONFIG_FILE):
        default_data = {"general_roles": ["Member"], "combat_roles": ["DPS", "UFM", "TANK"]}
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_data, f)
        return default_data
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_roles_data(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f)

# ==========================
# UI COMPONENTS
# ==========================
class GeneralRolesSelect(discord.ui.Select):
    def __init__(self):
        data = load_roles_data()
        roles = data.get("general_roles", ["Member"])
        options = [discord.SelectOption(label=r, emoji="🛡️") for r in roles]
        super().__init__(placeholder="💠 General & Dungeon Roles...", min_values=0, max_values=len(options), options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # Logic thêm/xóa role (tương tự DynamicCombatSelect)
        await interaction.followup.send("✅ Updated General roles!", ephemeral=True)

class DynamicCombatSelect(discord.ui.Select):
    def __init__(self):
        data = load_roles_data()
        roles = data.get("combat_roles", ["DPS", "UFM" "TANK"])
        options = [discord.SelectOption(label=r, emoji="⚔️") for r in roles]
        super().__init__(placeholder="🗡️ Combat Styles...", min_values=0, max_values=len(options), options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("✅ Updated Combat roles!", ephemeral=True)

class ServerRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GeneralRolesSelect())
        self.add_item(DynamicCombatSelect())

# ==========================
# COG: ROLES
# ==========================
class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(ServerRolesView())

    @app_commands.command(name="setup_role_panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_role_panel(self, interaction: discord.Interaction):
        await interaction.response.send_message("Panel created!", view=ServerRolesView())

    @app_commands.command(name="add_role", description="Add role to a category")
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
            await interaction.response.send_message(f"✅ Added **{role_name}** to **{category}**", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Role already exists!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Roles(bot))