import discord
from discord import app_commands
from discord.ext import commands
import uuid
import os
from datetime import timedelta
from pymongo import MongoClient

# ==========================================
# CẤU HÌNH & KẾT NỐI DB
# ==========================================
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://meik922004_db_user:LrXxnoloY8TaezNI@database0.gjbsfwh.mongodb.net/?appName=database0")
mongo_client = MongoClient(MONGO_URI, tlsAllowInvalidCertificates=True)
players_col = mongo_client["database0"]["players"]

active_parties = {}

def get_gear_from_db(user_id: int) -> str:
    player_data = players_col.find_one({"user_id": user_id})
    if not player_data or "my_stats" not in player_data: return None
    stats = player_data["my_stats"]
    return f"**Role:** {stats.get('role', 'N/A')}\n**Gear:** {stats.get('gear', 'N/A')}"

# ==========================================
# CÁC CLASS QUẢN LÝ (CŨ)
# ==========================================
class DecisionView(discord.ui.View):
    def __init__(self, applicant, applicant_ign, applicant_role, party_id):
        super().__init__(timeout=None)
        self.applicant, self.party_id = applicant, party_id
        self.ign, self.role = applicant_ign, applicant_role
    
    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def btn_accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = active_parties.get(self.party_id)
        if party:
            party["members"].append({"id": self.applicant.id, "ign": self.ign, "role": self.role, "ready": False})
            await interaction.response.edit_message(content="✅ Accepted!", view=None)

class MemberManageSelect(discord.ui.Select):
    def __init__(self, party):
        self.party = party
        opts = [discord.SelectOption(label=f"{m['ign']} ({m['role']})", value=str(m["id"])) for m in party["members"] if m["id"] != party["host_id"]]
        if not opts: opts.append(discord.SelectOption(label="Empty", value="none"))
        super().__init__(placeholder="Member manager", options=opts)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none": return await interaction.response.send_message("No member.", ephemeral=True)
        gear = get_gear_from_db(int(self.values[0]))
        await interaction.response.send_message(embed=discord.Embed(title="Profile", description=gear or "No Data"), ephemeral=True)

class PartyControlPanel(discord.ui.View):
    def __init__(self, party, is_leader):
        super().__init__(timeout=None)
        self.party = party
        if is_leader: self.add_item(MemberManageSelect(party))
        btn_leave = discord.ui.Button(label="Leave/Cancel party", style=discord.ButtonStyle.danger)
        async def leave_cb(inter):
            self.party["members"] = [m for m in self.party["members"] if m["id"] != inter.user.id]
            await inter.response.edit_message(content="Left/Canceled.", embed=None, view=None)
        btn_leave.callback = leave_cb
        self.add_item(btn_leave)

# ==========================================
# MODALS
# ==========================================
class RequestJoinModal(discord.ui.Modal, title="Send Request"):
    ign = discord.ui.TextInput(label="Your IGN", required=True)
    role = discord.ui.TextInput(label="Your role", required=True)
    def __init__(self, party_id, host_id):
        super().__init__()
        self.party_id, self.host_id = party_id, host_id
    async def on_submit(self, interaction: discord.Interaction):
        party = active_parties.get(self.party_id)
        host_user = interaction.client.get_user(self.host_id)
        if host_user:
            await host_user.send(f"New request from {self.ign.value}", view=DecisionView(interaction.user, self.ign.value, self.role.value, self.party_id))
        await interaction.response.send_message("✅ Request sent!", ephemeral=True)

class CreatePartyModal(discord.ui.Modal, title="Create new party"):
    dg_name = discord.ui.TextInput(label="Dungeon name", required=True)
    start_time = discord.ui.TextInput(label="Start in", required=True)
    ign = discord.ui.TextInput(label="Your IGN", required=True)
    
    async def on_submit(self, interaction: discord.Interaction):
        dg_key = self.dg_name.value.lower().strip()
        ping_roles = [r.mention for r in interaction.guild.roles if dg_key in r.name.lower()]
        ping_text = " ".join(ping_roles) if ping_roles else ""

        party_id = str(uuid.uuid4())[:3].upper()
        active_parties[party_id] = {
            "id": party_id, "host_id": interaction.user.id, "dg_name": self.dg_name.value,
            "members": [{"id": interaction.user.id, "ign": self.ign.value, "role": "Host", "ready": True}],
            "created_at": discord.utils.utcnow()
        }
        await interaction.response.send_message(f"✅ Created {self.dg_name.value}!", ephemeral=True)
        await update_lobby_boards(interaction.client, content_ping=ping_text)
# ==========================================
# UI & BROADCAST
# ==========================================
async def update_lobby_boards(bot, content_ping=""):
    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name="party-board")
        if channel:
            view = MainLobbyView(bot)
            embed = view.get_embed()
            async for message in channel.history(limit=5):
                if message.author == bot.user:
                    await message.edit(content=content_ping, embed=embed, view=view)
                    return
            await channel.send(content=content_ping, embed=embed, view=view)

class JoinButton(discord.ui.Button):
    def __init__(self, party_id):
        super().__init__(label=f"Join {party_id}", style=discord.ButtonStyle.success, custom_id=f"btn_join_{party_id}")
        self.party_id = party_id
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RequestJoinModal(self.party_id, active_parties[self.party_id]['host_id']))

class MainLobbyView(discord.ui.View):
    def __init__(self, bot, page=0):
        super().__init__(timeout=None)
        self.bot, self.page, self.items_per_page = bot, page, 3
        self.add_components()

    def add_components(self):
        keys = list(active_parties.keys())
        start = self.page * self.items_per_page
        page_keys = keys[start : start + self.items_per_page]

        for p_id in page_keys:
            self.add_item(JoinButton(p_id))

        self.add_item(discord.ui.Button(label="<<", style=discord.ButtonStyle.secondary, callback=self.prev_page))
        self.add_item(discord.ui.Button(label=">>", style=discord.ButtonStyle.secondary, callback=self.next_page))
        self.add_item(discord.ui.Button(label="Create", style=discord.ButtonStyle.primary, callback=self.create_cb))
        self.add_item(discord.ui.Button(label="Manage", style=discord.ButtonStyle.blurple, callback=self.manage_cb))

    async def prev_page(self, i):
        if self.page > 0: self.page -= 1
        await self.update_view(i)
    async def next_page(self, i):
        if (self.page + 1) * self.items_per_page < len(active_parties): self.page += 1
        await self.update_view(i)
    async def create_cb(self, i): await i.response.send_modal(CreatePartyModal())
    async def manage_cb(self, i):
        for pid, data in active_parties.items():
            if data["host_id"] == i.user.id:
                return await i.response.send_message(view=PartyControlPanel(data, True), ephemeral=True)
        await i.response.send_message("No party found.", ephemeral=True)

    async def update_view(self, i):
        self.clear_items(); self.add_components()
        await i.response.edit_message(embed=self.get_embed(), view=self)

    def get_embed(self):
        start = self.page * self.items_per_page
        page_items = list(active_parties.items())[start : start + self.items_per_page]
        embed = discord.Embed(title="⚔️ ACTIVE PARTIES", color=discord.Color.blurple())
        for p_id, data in page_items:
            embed.add_field(name=f"🎮 {data['dg_name']} [ID: {p_id}]", value="Status: Waiting...", inline=False)
        embed.set_footer(text=f"Page {self.page + 1}")
        return embed

# ==========================================
# COG (MAIN)
# ==========================================
class RealTimePartyFinder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(MainLobbyView(bot))

    @app_commands.command(name="party_lobby", description="Open Lobby")
    async def party_lobby(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=MainLobbyView(self.bot).get_embed(), view=MainLobbyView(self.bot))

async def setup(bot):
    await bot.add_cog(RealTimePartyFinder(bot))