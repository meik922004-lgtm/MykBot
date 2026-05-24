import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
import uuid
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
import os

# --- CẤU HÌNH ---
MONGO_URI = os.getenv("MONGO_URI", "YOUR_MONGO_URI_HERE")
client = MongoClient(MONGO_URI)
db = client["database0"]
players_col = db["players"]

active_parties = {}

def get_gear_from_db(user_id: int):
    player = players_col.find_one({"user_id": user_id})
    if not player or "my_stats" not in player: return "Please update your profile first(/mygear)"
    return f"Role: {player['my_stats'].get('role', 'N/A')} | Gear: {player['my_stats'].get('gear', 'N/A')}"

# --- MODAL TẠO PARTY ---
class CreatePartyModal(ui.Modal, title="Tạo Party Mới"):
    dg_name = ui.TextInput(label="Dungeon name", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        pid = str(uuid.uuid4())[:6].upper()
        active_parties[pid] = {
            "dg_name": self.dg_name.value, 
            "host_id": interaction.user.id, 
            "members": [{"id": interaction.user.id, "ign": "Host", "role": "Leader"}], 
            "created_at": datetime.now(timezone.utc)
        }
        await interaction.response.send_message(f"✅ Party created! **{self.dg_name.value}** (ID: {pid})", ephemeral=True)

# --- MODAL GỬI REQUEST ---
class RequestJoinModal(ui.Modal, title="Join party"):
    ign = ui.TextInput(label="Your Ingame-name", required=True)
    role = ui.TextInput(label="Your role", required=True)

    def __init__(self, party_id, host_id):
        super().__init__()
        self.party_id, self.host_id = party_id, host_id

    async def on_submit(self, interaction: discord.Interaction):
        party = active_parties.get(self.party_id)
        if not party or len(party["members"]) >= 4:
            return await interaction.response.send_message("The party does not exist or already full.!", ephemeral=True)
        
        gear_info = get_gear_from_db(interaction.user.id)
        host = interaction.client.get_user(self.host_id)
        if host:
            embed = discord.Embed(title=f"Request to join {party['dg_name']}", color=discord.Color.gold())
            embed.add_field(name="User", value=interaction.user.mention, inline=False)
            embed.add_field(name="Ingame-name", value=self.ign.value, inline=True)
            embed.add_field(name="Role", value=self.role.value, inline=True)
            embed.add_field(name="Gear profile", value=gear_info, inline=False)
            await host.send(embed=embed, view=DecisionView(self.party_id, interaction.user.id, self.ign.value, self.role.value))
        await interaction.response.send_message("✅ Request has been submitted.!", ephemeral=True)

# --- DUYỆT (DM LEADER) ---
class DecisionView(ui.View):
    def __init__(self, party_id, applicant_id, ign, role):
        super().__init__(timeout=None)
        self.party_id, self.applicant_id = party_id, applicant_id
        self.ign, self.role = ign, role

    @ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        party = active_parties.get(self.party_id)
        if party and len(party["members"]) < 4:
            party["members"].append({"id": self.applicant_id, "ign": self.ign, "role": self.role})
            await interaction.response.edit_message(content="✅ Accepted!", view=None)
        else:
            await interaction.response.edit_message(content="❌ Cannot add (full).", view=None)
# --- BẢNG ĐIỀU KHIỂN (KICK/LEAVE) ---
class ManagePartyView(ui.View):
    def __init__(self, party_id, is_leader):
        super().__init__(timeout=None)
        self.party_id = party_id
        self.is_leader = is_leader

    @ui.button(label="Leave Party", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: ui.Button):
        party = active_parties.get(self.party_id)
        if party:
            party["members"] = [m for m in party["members"] if m["id"] != interaction.user.id]
            await interaction.response.send_message("Bạn đã rời party.", ephemeral=True)

    @ui.button(label="Kick Member", style=discord.ButtonStyle.secondary)
    async def kick(self, interaction: discord.Interaction, button: ui.Button):
        if not self.is_leader: return await interaction.response.send_message("Bạn không phải Leader!", ephemeral=True)
        party = active_parties.get(self.party_id)
        
        # Chọn người kick
        select = ui.Select(placeholder="Choose the person you want to kick.", 
            options=[discord.SelectOption(label=m['ign'], value=str(m['id'])) for m in party['members'] if m['id'] != party['host_id']])
        
        async def callback(i):
            party["members"] = [m for m in party["members"] if str(m["id"]) != select.values[0]]
            await i.response.edit_message(content="Kick successful..", view=None)
        
        select.callback = callback
        view = ui.View()
        view.add_item(select)
        await interaction.response.send_message(view=view, ephemeral=True)

# --- COG CHÍNH & LOBBY ---
class PartyFinder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cleanup_task.start()

    @tasks.loop(hours=1)
    async def cleanup_task(self):
        now = datetime.now(timezone.utc)
        to_delete = [pid for pid, p in active_parties.items() if now - p["created_at"] > timedelta(days=1)]
        for pid in to_delete: del active_parties[pid]

    @app_commands.command(name="party_lobby", description="Party Dashboard")
    async def party_lobby(self, interaction: discord.Interaction):
        # UI Chính
        embed = discord.Embed(title="⚔️ ACTIVE PARTIES", color=discord.Color.blurple())
        if not active_parties:
            embed.description = "There are no parties yet. Please create a new party.!"
        else:
            for pid, p in active_parties.items():
                count = len(p["members"])
                embed.add_field(name=f"{p['dg_name']} (ID: {pid})", value=f"Status: [{count}/4] | Host: <@{p['host_id']}>", inline=False)
        
        # Nút tương tác
        view = ui.View()
        
        async def create_cb(i): await i.response.send_modal(CreatePartyModal())
        async def req_cb(i):
            if not active_parties: return await i.response.send_message("No party to join..", ephemeral=True)
            await i.response.send_modal(RequestJoinModal(list(active_parties.keys())[0], list(active_parties.values())[0]["host_id"]))
        async def manage_cb(i):
            target_pid = next((pid for pid, p in active_parties.items() if any(m["id"] == i.user.id for m in p["members"])), None)
            if not target_pid: return await i.response.send_message("You're not in any party.", ephemeral=True)
            await i.response.send_message(view=ManagePartyView(target_pid, i.user.id == active_parties[target_pid]["host_id"]), ephemeral=True)
        
        btn_create = ui.Button(label="Create Party", style=discord.ButtonStyle.primary)
        btn_create.callback = create_cb
        btn_req = ui.Button(label="Send Request", style=discord.ButtonStyle.success)
        btn_req.callback = req_cb
        btn_manage = ui.Button(label="Manage My Party", style=discord.ButtonStyle.blurple)
        btn_manage.callback = manage_cb
        
        view.add_item(btn_create)
        view.add_item(btn_req)
        view.add_item(btn_manage)
        
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(PartyFinder(bot))