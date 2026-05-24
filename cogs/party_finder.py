import discord
from discord import app_commands
from discord.ext import commands
import uuid
import math

# ==========================
# CONFIG & MOCK DB
# ==========================
TARGET_CHANNEL_NAME = "party-board" 
active_parties = {}
# Giả lập database profile: key là user_id, value là bool (True nếu đã có profile)
user_profiles = {} 

def check_user_profile(user_id: int) -> bool:
    # Thay thế logic này bằng hàm kiểm tra profile thực tế của bạn
    return user_profiles.get(user_id, False)

# ==========================
# HELPERS
# ==========================
def generate_party_embed(party_id: str) -> discord.Embed:
    data = active_parties.get(party_id)
    if not data:
        return discord.Embed(title="❌ Party not exist", color=discord.Color.red())

    current_count = len(data["members"])
    max_slots = data["max_slots"]
    is_full = current_count >= max_slots
    
    embed = discord.Embed(
        title=f"⚔️ {data['dg_name']} | {current_count}/{max_slots}",
        color=discord.Color.green() if not is_full else discord.Color.red()
    )
    
    member_list = ""
    for idx, member in enumerate(data["members"], 1):
        icon = "👑" if idx == 1 else "⚔️"
        member_list += f"{icon} {idx}. **{member['ign']}** - *{member['role']}*\n"
    
    embed.add_field(name="👥 Member", value=member_list, inline=False)
    embed.add_field(name="🔍 Search:", value=data['roles_needed'], inline=False)
    embed.set_footer(text=f"ID: {party_id}")
    return embed

# ==========================
# MODALS & VIEWS
# ==========================

# 1. MODAL TẠO PARTY (CHO PHÉP NHẬP ROLE TỰ DO)
class CreatePartyModal(discord.ui.Modal, title="Creat new party"):
    dg_name = discord.ui.TextInput(label="Dungeon name", placeholder="EX: PDG, MDG, Mugen...", required=True)
    ign = discord.ui.TextInput(label="Your ingame name", required=True)
    my_role = discord.ui.TextInput(label="Your role", placeholder="EX: DPS, Tank...", required=True)
    roles_needed = discord.ui.TextInput(label="Role needed", placeholder="EX: 2 DPS, 1 Healer...", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        party_id = str(uuid.uuid4())[:8]
        active_parties[party_id] = {
            "host_id": interaction.user.id,
            "dg_name": self.dg_name.value,
            "max_slots": 4,
            "roles_needed": self.roles_needed.value,
            "members": [{"id": interaction.user.id, "ign": self.ign.value, "role": self.my_role.value}],
            "messages": []
        }
        await interaction.response.send_message(f"✅ Party created {self.dg_name.value}!", ephemeral=True)
        # Refresh dashboard sau khi tạo
        await update_dashboard(interaction.client)

# 2. MODAL TÌM KIẾM
class SearchModal(discord.ui.Modal, title="Search party"):
    keyword = discord.ui.TextInput(label="Keywork (Dungeon name)", placeholder="Input name here", required=True)
    
    def __init__(self, dashboard_view):
        super().__init__()
        self.dashboard_view = dashboard_view

    async def on_submit(self, interaction: discord.Interaction):
        self.dashboard_view.filter_query = self.keyword.value
        await self.dashboard_view.refresh_ui(interaction)

# 3. DASHBOARD CHÍNH (PAGINATION)
class PartyDashboardView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.page = 0
        self.filter_query = ""

    def get_filtered_parties(self):
        all_p = list(active_parties.items())
        if self.filter_query:
            all_p = [p for p in all_p if self.filter_query.lower() in p[1]["dg_name"].lower()]
        return all_p

    async def refresh_ui(self, interaction: discord.Interaction):
        parties = self.get_filtered_parties()
        max_pages = max(0, math.ceil(len(parties) / 6) - 1)
        self.page = min(self.page, max_pages)

        embed = discord.Embed(title="🎮 Party hall", description=f"Page {self.page+1}/{max_pages+1}")
        
        start = self.page * 6
        current_batch = parties[start:start+6]

        if not current_batch:
            embed.description = "No party has been created yet.."
        else:
            for p_id, data in current_batch:
                status = f"{len(data['members'])}/4" if len(data["members"]) < 4 else "Full"
                embed.add_field(
                    name=f"{data['dg_name']} ({status})",
                    value=f"Chủ: {self.bot.get_user(data['host_id'])} | Cần: {data['roles_needed']}\nID: `{p_id}`",
                    inline=False
                )

        # Cập nhật view
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Create party", style=discord.ButtonStyle.primary, row=0)
    async def btn_create(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_user_profile(interaction.user.id):
            return await interaction.response.send_message("❌ You didnt setup profile(/mygear), cant create party!", ephemeral=True)
        await interaction.response.send_modal(CreatePartyModal())

    @discord.ui.button(label="Tìm kiếm", style=discord.ButtonStyle.secondary, row=0)
    async def btn_search(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchModal(self))

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.primary, row=1)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0: self.page -= 1
        await self.refresh_ui(interaction)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.primary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        parties = self.get_filtered_parties()
        if (self.page + 1) * 6 < len(parties): self.page += 1
        await self.refresh_ui(interaction)

# 4. VIEW THAO TÁC TRONG PARTY (JOIN/LEAVE/KICK)
class PartyControlView(discord.ui.View):
    def __init__(self, party_id):
        super().__init__(timeout=None)
        self.party_id = party_id

    @discord.ui.button(label="Join", style=discord.ButtonStyle.green, custom_id="join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_user_profile(interaction.user.id):
            return await interaction.response.send_message("❌ You need to setup profile (/mygear) first!", ephemeral=True)
        # Logic gửi request... (giữ nguyên logic modal cũ của bạn ở đây)

    @discord.ui.button(label="Leave party", style=discord.ButtonStyle.danger, custom_id="leave")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Logic xóa user khỏi list members
        await interaction.response.send_message("You left the party!", ephemeral=True)

# ==========================
# MAIN COG
# ==========================
async def update_dashboard(bot):
    # Hàm này sẽ update lại cái tin nhắn dashboard gốc nếu bạn lưu message_id
    pass

class RealTimePartyFinder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="make_party", description="open party dashboard")
    async def make_party(self, interaction: discord.Interaction):
        view = PartyDashboardView(self.bot)
        # Hiển thị dashboard lần đầu
        parties = view.get_filtered_parties()
        embed = discord.Embed(title="🎮 Party hall", description="Use the button below to use the function.")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(RealTimePartyFinder(bot))