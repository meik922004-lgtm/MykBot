import discord
from discord import app_commands
from discord.ext import commands, tasks
import uuid
import os
from datetime import timedelta
from pymongo import MongoClient

# ==========================================
# 1. KẾT NỐI MONGODB
# ==========================================
# Đảm bảo biến môi trường MONGO_URI đã được thiết lập trên hosting của bạn
MONGO_URI = os.getenv("MONGO_URI") 
mongo_client = MongoClient(MONGO_URI)
players_col = mongo_client["database0"]["players"]

def get_gear_from_db(user_id: int) -> str:
    """Trích xuất thông tin my_stats từ MongoDB dựa theo user_id"""
    player_data = players_col.find_one({"user_id": user_id})
    
    if not player_data or "my_stats" not in player_data:
        return None

    stats = player_data["my_stats"]
    # Trả về chuỗi thông tin gear theo đúng cấu trúc DB của bạn
    return (
        f"**Role:** {stats.get('role', 'N/A')}\n"
        f"**Gear:** {stats.get('gear', 'N/A')}\n"
        f"**Vice:** {stats.get('vice', 'N/A')}\n"
        f"**Deck:** {stats.get('deck', 'N/A')}"
    )

# ==========================================
# BIẾN TOÀN CỤC
# ==========================================
active_parties = {}

# ==========================================
# 2. MODALS (GIAO DIỆN NHẬP LIỆU)
# ==========================================
class RequestJoinModal(discord.ui.Modal, title="Send Request"):
    ign = discord.ui.TextInput(label="Your ingame", placeholder="input IGN...", required=True)
    role = discord.ui.TextInput(label="Your role", placeholder="e.g: DPS, Tank...", required=True)

    def __init__(self, party_id, host_id):
        super().__init__()
        self.party_id = party_id
        self.host_id = host_id

    async def on_submit(self, interaction: discord.Interaction):
        party = active_parties.get(self.party_id)
        if not party: return await interaction.response.send_message("❌ This party no longer exist!", ephemeral=True)

        gear_info = get_gear_from_db(interaction.user.id)
        if not gear_info: return await interaction.response.send_message("❌ Cant find data in DB!", ephemeral=True)

        host_user = interaction.client.get_user(self.host_id)
        if host_user:
            embed = discord.Embed(title="📩 Request invite!", color=discord.Color.gold())
            embed.add_field(name="Dungeon", value=party['dg_name'], inline=True)
            embed.add_field(name="Infomation", value=f"```\n{gear_info}\n```", inline=False)
            await host_user.send(embed=embed, view=DecisionView(interaction.user, self.ign.value, self.role.value, self.party_id))

        await interaction.response.send_message("✅ Send request!", ephemeral=True)

class CreatePartyModal(discord.ui.Modal, title="Create new party"):
    dg_name = discord.ui.TextInput(label="Dungeon name", placeholder="e.g: PDG, Mugen...", required=True)
    start_time = discord.ui.TextInput(label="start in:", placeholder="e.g: 5 mins", required=True)
    ign = discord.ui.TextInput(label="Your IGN", required=True)
    my_role = discord.ui.TextInput(label="your role", required=True)
    roles_needed = discord.ui.TextInput(label="Role needed to recuit:", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        if not get_gear_from_db(interaction.user.id):
            return await interaction.response.send_message("❌ You didnt setup profile(/mygear)!", ephemeral=True)

        party_id = str(uuid.uuid4())[:6].upper()
        active_parties[party_id] = {
            "id": party_id, "host_id": interaction.user.id, "host_ign": self.ign.value,
            "dg_name": self.dg_name.value, "start_time": self.start_time.value,
            "created_at": discord.utils.utcnow(), "roles_needed": self.roles_needed.value,
            "members": [{"id": interaction.user.id, "ign": self.ign.value, "role": self.my_role.value, "ready": True}],
        }
        
        # LOGIC PING (Case-Insensitive)
        dg_key = self.dg_name.value.lower().strip()
        target_roles = [r.mention for r in interaction.guild.roles if dg_key in r.name.lower()]
        ping_text = " ".join(target_roles)

        channel = discord.utils.get(interaction.guild.text_channels, name="party-board")
        if channel:
            embed = discord.Embed(title="📢 New party!", color=discord.Color.green())
            embed.add_field(name="Dungeon", value=self.dg_name.value, inline=True)
            embed.add_field(name="Leader", value=self.ign.value, inline=True)
            embed.set_footer(text=f"ID: {party_id}")
            await channel.send(content=ping_text, embed=embed, view=BroadcastView())

        await interaction.response.send_message(f"✅ Party createdd **{self.dg_name.value}**!", ephemeral=True)

# ==========================================
# 3. VIEWS (GIAO DIỆN)
# ==========================================
class BroadcastView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Open party lobby", style=discord.ButtonStyle.primary, custom_id="btn_open_lobby")
    async def open_lobby(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MainLobbyView(interaction.client)
        await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)

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
            await interaction.response.edit_message(content="✅ ACcepted!", view=None)

class MemberManageSelect(discord.ui.Select):
    def __init__(self, party):
        self.party = party
        opts = [discord.SelectOption(label=f"{m['ign']} ({m['role']})", value=str(m["id"])) for m in party["members"] if m["id"] != party["host_id"]]
        if not opts: opts.append(discord.SelectOption(label="Trống", value="none"))
        super().__init__(placeholder="Member manager", options=opts)

    async def callback(self, interaction: discord.Interaction):
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
            await inter.response.edit_message(content="Left/ Canceled.", embed=None, view=None)
        btn_leave.callback = leave_cb
        self.add_item(btn_leave)

class PartyDropdown(discord.ui.Select):
    def __init__(self, parties_on_page):
        opts = [discord.SelectOption(label=f"[{p_id}] {data['dg_name']}", value=p_id) for p_id, data in parties_on_page.items()]
        if not opts: opts.append(discord.SelectOption(label="Trống", value="none"))
        super().__init__(placeholder="Select party to send request", options=opts)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RequestJoinModal(self.values[0], active_parties[self.values[0]]['host_id']))

class MainLobbyView(discord.ui.View):
    def __init__(self, bot, search_results=None):
        super().__init__(timeout=None)
        self.bot = bot; self.page = 0; self.source_data = search_results or active_parties
        self.update_components()

    def update_components(self):
        self.clear_items()
        page_items = dict(list(self.source_data.items())[self.page*6:self.page*6+6])
        self.add_item(PartyDropdown(page_items))
        self.add_item(discord.ui.Button(label="Creat party", style=discord.ButtonStyle.success, row=2, callback=lambda i: i.response.send_modal(CreatePartyModal())))
        self.add_item(discord.ui.Button(label="Manage", style=discord.ButtonStyle.primary, row=2, callback=self.manage_my_party))

    def get_embed(self):
        embed = discord.Embed(title="🎮 PARTY LOBBY", color=discord.Color.blurple())
        for p_id, data in list(self.source_data.items())[self.page*6:self.page*6+6]:
            embed.add_field(name=f"⚔️ {data['dg_name']}", value=f"ID: `{p_id}`\nMembers: {len(data['members'])}/6", inline=True)
        return embed

    async def manage_my_party(self, interaction: discord.Interaction):
        for pid, data in active_parties.items():
            if data["host_id"] == interaction.user.id or any(m["id"] == interaction.user.id for m in data["members"]):
                return await interaction.response.send_message(embed=discord.Embed(title=f"Party: {data['dg_name']}"), view=PartyControlPanel(data, data["host_id"] == interaction.user.id), ephemeral=True)
        await interaction.response.send_message("Không có party nào.", ephemeral=True)

# ==========================================
# 4. COG
# ==========================================
class RealTimePartyFinder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(BroadcastView())
        self.cleanup_task.start()

    @tasks.loop(minutes=30)
    async def cleanup_task(self):
        to_delete = [pid for pid, data in active_parties.items() if discord.utils.utcnow() - data['created_at'] > timedelta(hours=24)]
        for pid in to_delete: del active_parties[pid]

    @app_commands.command(name="party_lobby", description="Open Party Lobby")
    async def party_lobby(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=MainLobbyView(self.bot).get_embed(), view=MainLobbyView(self.bot), ephemeral=True)

async def setup(bot): await bot.add_cog(RealTimePartyFinder(bot))