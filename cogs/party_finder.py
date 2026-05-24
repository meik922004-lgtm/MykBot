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
# DATABASE CHECKER
# ==========================
async def check_user_profile(user_id: int) -> bool:
    try:
        player = await db.players.find_one({"user_id": user_id})
        return player is not None
    except Exception as e:
        print(f"Error checking DB: {e}")
        return False

# ==========================
# MODALS
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

        party = active_parties.get(self.party_id)
        if not party: return await interaction.response.send_message("❌ Party expired.", ephemeral=True)

        profile = await db.players.find_one({"user_id": user_id})
        leader = interaction.client.get_user(party["host_id"])
        
        if leader:
            embed = discord.Embed(title=f"📩 Request: {party['dg_name']}", color=discord.Color.gold())
            embed.add_field(name="Applicant", value=interaction.user.mention, inline=False)
            embed.add_field(name="Details", value=f"IGN: {self.ign.value}\nRole: {self.my_role.value}\nNote: {self.note.value or 'N/A'}")
            stats = str(profile.get('my_stats', 'Hidden')) if profile else "No profile data"
            embed.add_field(name="Profile Stats", value=stats, inline=False)
            await leader.send(embed=embed, view=DecisionView(interaction.user, self.party_id))
            await interaction.response.send_message(f"✅ Request sent! ({request_counts[user_id]}/2)", ephemeral=True)

# ==========================
# VIEWS: DASHBOARD & MANAGEMENT
# ==========================
class ManagePartyView(discord.ui.View):
    def __init__(self, party_id, bot):
        super().__init__(timeout=None)
        self.party_id = party_id
        self.bot = bot

    async def update_view(self, interaction: discord.Interaction):
        party = active_parties.get(self.party_id)
        if not party: return await interaction.response.send_message("❌ Party gone", ephemeral=True)
        
        embed = discord.Embed(title=f"⚙️ Manage: {party['dg_name']}", color=discord.Color.purple())
        self.clear_items()
        for member in party['members']:
            embed.add_field(name=f"{member['ign']}", value=f"Role: {member['role']}", inline=False)
            btn_view = discord.ui.Button(label=f"👤 {member['ign']}", custom_id=f"view_{member['id']}")
            btn_view.callback = lambda i: self.view_profile(i, member['id'])
            self.add_item(btn_view)
            if member['id'] != party['host_id']:
                btn_kick = discord.ui.Button(label="❌ Kick", style=discord.ButtonStyle.danger, custom_id=f"kick_{member['id']}")
                btn_kick.callback = lambda i: self.kick_member(i, member['id'])
                self.add_item(btn_kick)
        await interaction.response.edit_message(embed=embed, view=self)

    async def view_profile(self, interaction, user_id):
        profile = await db.players.find_one({"user_id": user_id})
        stats = str(profile.get('my_stats', 'N/A')) if profile else "N/A"
        await interaction.response.send_message(f"📊 Stats: {stats}", ephemeral=True)

    async def kick_member(self, interaction, user_id):
        active_parties[self.party_id]['members'] = [m for m in active_parties[self.party_id]['members'] if m['id'] != user_id]
        await interaction.response.send_message("✅ Kicked!", ephemeral=True)
        await self.update_view(interaction)

class DecisionView(discord.ui.View):
    def __init__(self, applicant: discord.Member, party_id: str):
        super().__init__(timeout=None)
        self.applicant = applicant
        self.party_id = party_id
    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(content="✅ Accepted", view=self)
        await self.applicant.send(f"🎉 Accepted into party `{self.party_id}`!")
    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(content="❌ Declined", view=self)

class SendRequestButton(discord.ui.Button):
    def __init__(self, party_id, dg_name):
        super().__init__(label=f"Request: {dg_name}", style=discord.ButtonStyle.success, custom_id=party_id)
        self.party_id = party_id
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(JoinPartyModal(self.party_id))

class PartyDashboardView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.page = 0

    async def refresh_ui(self, interaction: discord.Interaction):
        self.clear_items()
        batch = list(active_parties.items())[self.page * 3 : (self.page + 1) * 3]
        embed = discord.Embed(title="⚔️ Party Board", color=discord.Color.blue())
        for p_id, data in batch:
            embed.add_field(name=f"{data['dg_name']}", value=f"Host: {data['host_name']}\nID: `{p_id}`", inline=False)
            self.add_item(SendRequestButton(p_id, data['dg_name']))
            if interaction.user.id == data['host_id']:
                btn_manage = discord.ui.Button(label="⚙️ Manage", style=discord.ButtonStyle.secondary, custom_id=f"manage_{p_id}")
                btn_manage.callback = self.manage_party
                self.add_item(btn_manage)
        await interaction.response.edit_message(embed=embed, view=self)

    async def manage_party(self, interaction: discord.Interaction):
        p_id = interaction.data['custom_id'].split('_')[1]
        await ManagePartyView(p_id, self.bot).update_view(interaction)

# ==========================
# COG
# ==========================
class RealTimePartyFinder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cleanup_task.start()

    @tasks.loop(minutes=1)
    async def cleanup_task(self):
        now = datetime.now()
        to_delete = [pid for pid, data in active_parties.items() if now - data['created_at'] > timedelta(hours=1)]
        for pid in to_delete: del active_parties[pid]

    @app_commands.command(name="make_party", description="Open dashboard")
    async def make_party(self, interaction: discord.Interaction):
        view = PartyDashboardView(self.bot)
        embed = discord.Embed(title="🎮 Party Hall")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot): await bot.add_cog(RealTimePartyFinder(bot))