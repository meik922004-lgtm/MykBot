import discord
from discord import app_commands
from discord.ext import commands
import uuid
import math

# LƯU Ý: Thay 'main' bằng tên file chứa biến kết nối 'db' của bạn
from Database import db 

# ==========================
# DATABASE CHECKER
# ==========================
async def check_user_profile(user_id: int) -> bool:
    """Kiểm tra user_id trong collection 'players' của MongoDB"""
    try:
        player = await db.players.find_one({"user_id": user_id})
        return player is not None
    except Exception as e:
        print(f"Error: cant check DB: {e}")
        return False

active_parties = {}

# ==========================
# MODALS: CREATE & SEARCH
# ==========================
class CreatePartyModal(discord.ui.Modal, title="Create New Party"):
    dg_name = discord.ui.TextInput(label="Dungeon Name", placeholder="e.g. PDG, MDG, Mugen...", required=True)
    start_time = discord.ui.TextInput(label="Start Time", placeholder="e.g 5 mins later...", required=True)
    ign = discord.ui.TextInput(label="Your Ingame Name", required=True)
    my_role = discord.ui.TextInput(label="Your Role", placeholder="e.g. DPS, Tank...", required=True)
    roles_needed = discord.ui.TextInput(label="Roles Needed", placeholder="e.g. 2 DPS, 1 Healer...", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        party_id = str(uuid.uuid4())[:8]
        active_parties[party_id] = {
            "host_id": interaction.user.id,
            "host_name": interaction.user.name,
            "dg_name": self.dg_name.value,
            "start_time": self.start_time.value,
            "roles_needed": self.roles_needed.value,
            "members": [{"id": interaction.user.id, "ign": self.ign.value, "role": self.my_role.value}],
            "max_slots": 4
        }
        await interaction.response.send_message(f"✅ Party **{self.dg_name.value}** created! (ID: {party_id})", ephemeral=True)

class SearchModal(discord.ui.Modal, title="Search Party"):
    keyword = discord.ui.TextInput(label="Dungeon Name", required=True)
    
    def __init__(self, dashboard_view):
        super().__init__()
        self.dashboard_view = dashboard_view

    async def on_submit(self, interaction: discord.Interaction):
        self.dashboard_view.filter_query = self.keyword.value
        await self.dashboard_view.refresh_ui(interaction)

# ==========================
# DASHBOARD VIEW
# ==========================
class PartyDashboardView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.page = 0
        self.filter_query = ""

    def get_parties(self):
        p_list = list(active_parties.items())
        if self.filter_query:
            p_list = [p for p in p_list if self.filter_query.lower() in p[1]["dg_name"].lower()]
        return p_list

    async def refresh_ui(self, interaction: discord.Interaction):
        parties = self.get_parties()
        max_pages = max(0, math.ceil(len(parties) / 6) - 1)
        self.page = min(self.page, max_pages)

        embed = discord.Embed(title="⚔️ Party Board", description=f"Page {self.page+1}/{max_pages+1}", color=discord.Color.blue())
        batch = parties[self.page * 6 : (self.page + 1) * 6]
        
        if not batch:
            embed.description = "No parties available."
        else:
            for p_id, data in batch:
                embed.add_field(
                    name=f"{data['dg_name']} ({len(data['members'])}/4)",
                    value=(f"🕒 **Start:** {data.get('start_time', 'N/A')}\n"
                           f"👑 Host: {data['host_name']} | 🔍 Needs: {data['roles_needed']}\n"
                           f"🆔 ID: `{p_id}`"),
                    inline=False
                )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Create Party", style=discord.ButtonStyle.primary)
    async def btn_create(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_user_profile(interaction.user.id):
            return await interaction.response.send_message("❌ You didn't setup profile (/mygear), can't create party!", ephemeral=True)
        await interaction.response.send_modal(CreatePartyModal())

    @discord.ui.button(label="Search", style=discord.ButtonStyle.secondary)
    async def btn_search(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchModal(self))

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.primary)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0: self.page -= 1
        await self.refresh_ui(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await self.refresh_ui(interaction)

# ==========================
# MAIN COG
# ==========================
class RealTimePartyFinder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="make_party", description="Open party dashboard")
    async def make_party(self, interaction: discord.Interaction):
        view = PartyDashboardView(self.bot)
        embed = discord.Embed(title="🎮 Party Hall", description=None)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(RealTimePartyFinder(bot))