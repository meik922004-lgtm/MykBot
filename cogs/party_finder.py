import discord
import re
import uuid
from discord import app_commands, ui
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient
import os

# --- CẤU HÌNH ---
MONGO_URI = os.getenv("MONGO_URI", "YOUR_MONGO_URI_HERE")
client = MongoClient(MONGO_URI)
db = client["database0"]
players_col = db["players"]
dungeon_configs = db["dungeon_configs"] 

active_parties = {}

# --- HELPER FUNCTIONS ---
def get_ping_role(dungeon_name):
    # Regex tìm kiếm không phân biệt hoa thường (Case-insensitive)
    config = dungeon_configs.find_one({"dg_name": {"$regex": re.escape(dungeon_name), "$options": "i"}})
    return f"<@&{config['ping_role']}>" if config and "ping_role" in config else None

def get_gear_from_db(user_id: int, role_key: str):
    player = players_col.find_one({"user_id": user_id})
    if not player or "my_stats" not in player: return "Gear info didnt update"
    stats = player["my_stats"].get(role_key.upper())
    if not stats: return "This role didnt set up."
    return f"Gear: {stats.get('gear', 'N/A')} | Deck: {stats.get('deck', 'N/A')} | Vice: {stats.get('vice', 'N/A')}"

def is_player_qualified(user_id, role_key, dungeon_name):
    config = dungeon_configs.find_one({"dg_name": {"$regex": re.escape(dungeon_name), "$options": "i"}})
    if not config: return True
    player = players_col.find_one({"user_id": user_id})
    stats = player["my_stats"].get(role_key.upper()) if player else None
    if not stats: return False
    reqs = config.get("req", {})
    if stats.get("gear") not in reqs.get("gear", []): return False
    if stats.get("vice") not in reqs.get("vice", []): return False
    if stats.get("deck") not in reqs.get("deck", []): return False
    return True

# --- MODALS ---
class CreatePartyModal(ui.Modal, title="Create new party"):
    dg_name = ui.TextInput(label="Dungeon name", placeholder="e.g: PDG, MDG")
    leader_ign = ui.TextInput(label="Your IGN")
    recruitment = ui.TextInput(label="Role needed")
    start_in = ui.TextInput(label="Start in:")

    async def on_submit(self, interaction: discord.Interaction):
        if not players_col.find_one({"user_id": interaction.user.id}):
            return await interaction.response.send_message("❌ You haven't registered a profile(/mygear) yet.!", ephemeral=True)
        pid = str(uuid.uuid4())[:6].upper()
        active_parties[pid] = {
            "dg_name": self.dg_name.value, "leader_ign": self.leader_ign.value,
            "recruitment": self.recruitment.value, "start_in": self.start_in.value,
            "host_id": interaction.user.id, "created_at": datetime.now(timezone.utc),
            "members": [{"id": interaction.user.id, "ign": self.leader_ign.value, "role": "Leader"}],
            "filter_enabled": False
        }
        await interaction.response.send_message(f"✅ Party create **{self.dg_name.value}**!", ephemeral=True)

class RequestJoinModal(ui.Modal, title="Join party"):
    ign = ui.TextInput(label="Your IGN")
    role = ui.TextInput(label="Your role")
    def __init__(self, pid, host_id):
        super().__init__(); self.pid = pid; self.host_id = host_id
    async def on_submit(self, interaction: discord.Interaction):
        party = active_parties.get(self.pid)
        if not party: return await interaction.response.send_message("Party not exist!", ephemeral=True)
        if party.get("filter_enabled") and not is_player_qualified(interaction.user.id, self.role.value, party["dg_name"]):
            return await interaction.response.send_message("❌ Gear not get the requirement!", ephemeral=True)
        host = interaction.client.get_user(self.host_id)
        if host:
            embed = discord.Embed(title=f"Request to join {party['dg_name']}", color=discord.Color.gold())
            embed.add_field(name="User", value=interaction.user.mention); embed.add_field(name="Role", value=self.role.value)
            await host.send(embed=embed, view=DecisionView(self.pid, interaction.user.id, self.ign.value, self.role.value))
        await interaction.response.send_message("✅ Request has been submitted.!", ephemeral=True)
class DecisionView(ui.View):
    def __init__(self, pid, aid, ign, role):
        super().__init__(timeout=None); self.pid = pid; self.aid = aid; self.ign = ign; self.role = role
    @ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, i: discord.Interaction, b: ui.Button):
        party = active_parties.get(self.pid)
        if party and len(party["members"]) < 4:
            party["members"].append({"id": self.aid, "ign": self.ign, "role": self.role})
            await i.response.edit_message(content="✅ Accepted!", view=None)

class ManagePartyView(ui.View):
    def __init__(self, pid, is_leader):
        super().__init__(timeout=None); self.pid = pid; self.is_leader = is_leader

    @ui.button(label="Toggle Filter", style=discord.ButtonStyle.secondary)
    async def toggle_filter(self, i: discord.Interaction, b: ui.Button):
        p = active_parties.get(self.pid)
        if not p: return await i.response.send_message("Party ended!", ephemeral=True)
        p["filter_enabled"] = not p.get("filter_enabled", False)
        await i.response.edit_message(content=f"Filter Gear: **{'ON' if p['filter_enabled'] else 'OFF'}**")

    @ui.button(label="Broadcast", style=discord.ButtonStyle.primary)
    async def broadcast(self, i: discord.Interaction, b: ui.Button):
        p = active_parties.get(self.pid)
        if not p: return await i.response.send_message("Party ended!", ephemeral=True)
        role_mention = get_ping_role(p["dg_name"])
        embed = discord.Embed(title=f"⚔️ {p['dg_name']} Recruitment", description=f"Leader: {p['leader_ign']}\nNeed: {p['recruitment']}", color=discord.Color.green())
        await i.channel.send(content=f"{role_mention if role_mention else ''}", embed=embed)
        await i.response.send_message("✅ Broadcast successful!", ephemeral=True)

class PartyFinder(commands.Cog):
    def __init__(self, bot): self.bot = bot
    
    @app_commands.command(name="party_lobby")
    async def party_lobby(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⚔️ ACTIVE PARTIES")
        for pid, p in active_parties.items():
            embed.add_field(name=f"{p['dg_name']} ({pid})", value=f"Leader: {p['leader_ign']}\nFilter: {'ON' if p.get('filter_enabled') else 'OFF'}")
        
        # Nút bấm tương tác
        view = ui.View()
        async def create_cb(i): await i.response.send_modal(CreatePartyModal())
        btn_create = ui.Button(label="Create", style=discord.ButtonStyle.primary)
        btn_create.callback = create_cb
        view.add_item(btn_create)
        
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot): await bot.add_cog(PartyFinder(bot))