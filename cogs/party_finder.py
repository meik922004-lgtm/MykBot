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
# 1. MODALS
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
        }
        
        # --- Logic Ping Role ---
        target_roles = [role.mention for role in interaction.guild.roles if self.dg_name.value.lower() in role.name.lower()]
        mention_text = " ".join(target_roles) if target_roles else ""

        # --- Gửi thông báo kênh party-board ---
        channel = discord.utils.get(interaction.guild.text_channels, name="party-board")
        if channel:
            embed = discord.Embed(title="📢 New Party Created!", color=discord.Color.green())
            embed.add_field(name="Dungeon", value=self.dg_name.value, inline=True)
            embed.add_field(name="Roles Needed", value=self.roles_needed.value, inline=True)
            embed.add_field(name="Start Time", value=self.start_time.value, inline=False)
            embed.set_footer(text=f"Host: {interaction.user.name} | ID: {party_id}")
            await channel.send(content=mention_text, embed=embed)

        await interaction.response.send_message(f"✅ Party **{self.dg_name.value}** created!", ephemeral=True)

class JoinPartyModal(discord.ui.Modal, title="Send Join Request"):
    ign = discord.ui.TextInput(label="Ingame Name", required=True)
    my_role = discord.ui.TextInput(label="Your Role", required=True)
    note = discord.ui.TextInput(label="Note (Optional)", style=discord.TextStyle.paragraph, required=False)

    def __init__(self, party_id):
        super().__init__()
        self.party_id = party_id

    async def on_submit(self, interaction: discord.Interaction):
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

class PartyDashboardView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Create Party", style=discord.ButtonStyle.primary, custom_id="btn_create")
    async def create_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreatePartyModal())

    @discord.ui.button(label="Refresh Board", style=discord.ButtonStyle.secondary, custom_id="btn_refresh")
    async def refresh_board(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="🎮 Party Hall - Active", color=discord.Color.blue())
        if not active_parties:
            embed.description = "No parties open."
        else:
            for p_id, data in active_parties.items():
                embed.add_field(
                    name=f"⚔️ {data['dg_name']}", 
                    value=f"**Host:** {data['host_name']}\n**Time:** {data['start_time']}\n**Roles:** {data['roles_needed']}\n**ID:** `{p_id}`", 
                    inline=False
                )
        await interaction.response.edit_message(embed=embed, view=self)

# ==========================
# 3. COG
# ==========================
class RealTimePartyFinder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
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