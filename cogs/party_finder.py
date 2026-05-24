import discord
from discord import app_commands
from discord.ext import commands, tasks
import uuid
from datetime import datetime, timedelta
from Database import db 

# Biến toàn cục
request_counts = {}
active_parties = {}

# ==========================
# 1. MODALS (Phải nằm trên cùng)
# ==========================
class CreatePartyModal(discord.ui.Modal, title="Create New Party"):
    dg_name = discord.ui.TextInput(label="Dungeon Name", placeholder="e.g. PDG, MDG", required=True)
    start_time = discord.ui.TextInput(label="Start Time", placeholder="e.g. 5 mins later...", required=True)
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
            "created_at": datetime.now(),
            "roles_needed": self.roles_needed.value,
            "members": [{"id": interaction.user.id, "ign": self.ign.value, "role": self.my_role.value}],
            "max_slots": 4
        }
        await interaction.response.send_message(f"✅ Party **{self.dg_name.value}** created! (ID: {party_id})", ephemeral=True)

class JoinPartyModal(discord.ui.Modal, title="Send Join Request"):
    ign = discord.ui.TextInput(label="Ingame Name", required=True)
    my_role = discord.ui.TextInput(label="Your Role", required=True)
    note = discord.ui.TextInput(label="Note (Optional)", style=discord.TextStyle.paragraph, required=False)

    def __init__(self, party_id):
        super().__init__()
        self.party_id = party_id

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        request_counts[user_id] = request_counts.get(user_id, 0) + 1
        if request_counts[user_id] > 2:
            return await interaction.response.send_message("❌ Limit reached (2 requests)!", ephemeral=True)
        # (Phần logic gửi request giữ nguyên như cũ)
        await interaction.response.send_message("✅ Request sent!", ephemeral=True)

# ==========================
# 2. VIEWS
# ==========================
class DecisionView(discord.ui.View):
    def __init__(self, applicant: discord.Member, party_id: str):
        super().__init__(timeout=None)
        self.applicant = applicant
        self.party_id = party_id
    
    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(content="✅ Accepted", view=self)

class ManagePartyView(discord.ui.View):
    def __init__(self, party_id, bot):
        super().__init__(timeout=None)
        self.party_id = party_id
        self.bot = bot

class PartyDashboardView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Create Party", style=discord.ButtonStyle.primary, custom_id="btn_create")
    async def create_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreatePartyModal())

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, custom_id="btn_refresh")
    async def refresh_board(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=self)

# ==========================
# 3. COG
# ==========================
class RealTimePartyFinder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Đăng ký View vào bot để giữ nút bấm hoạt động vĩnh viễn
        self.bot.add_view(PartyDashboardView(self.bot))
        self.cleanup_task.start()

    @tasks.loop(minutes=1)
    async def cleanup_task(self):
        now = datetime.now()
        to_delete = [pid for pid, data in active_parties.items() if now - data['created_at'] > timedelta(hours=1)]
        for pid in to_delete: del active_parties[pid]

    @app_commands.command(name="make_party", description="Open dashboard")
    async def make_party(self, interaction: discord.Interaction):
        view = PartyDashboardView(self.bot)
        await interaction.response.send_message("🎮 **Party Hall**", view=view, ephemeral=True)

async def setup(bot): await bot.add_cog(RealTimePartyFinder(bot))