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
            "host_ign": self.ign.value,
            "dg_name": self.dg_name.value,
            "start_time": self.start_time.value,
            "created_at": datetime.now(),
            "roles_needed": self.roles_needed.value,
            "members": [{"id": interaction.user.id, "ign": self.ign.value, "role": self.my_role.value}],
        }
        
        # Ping Role
        target_roles = [role.mention for role in interaction.guild.roles if self.dg_name.value.lower() in role.name.lower()]
        mention_text = " ".join(target_roles) if target_roles else ""

        # Gửi thông báo
        channel = discord.utils.get(interaction.guild.text_channels, name="party-board")
        if channel:
            embed = discord.Embed(title="📢 New Party Created!", color=discord.Color.blurple())
            embed.add_field(name="Dungeon", value=self.dg_name.value, inline=True)
            embed.add_field(name="Roles", value=self.roles_needed.value, inline=True)
            embed.add_field(name="Host (IGN)", value=self.ign.value, inline=False)
            embed.set_footer(text=f"ID: {party_id}")
            
            # Sử dụng NotificationView có nút callback
            await channel.send(content=mention_text, embed=embed, view=NotificationView())

        await interaction.response.send_message(f"✅ Party **{self.dg_name.value}** created!", ephemeral=True)

# ==========================
# 2. VIEWS
# ==========================

# View cho tin nhắn thông báo (khi bấm sẽ hiện dashboard ephemeral)
class NotificationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Go to Dashboard", style=discord.ButtonStyle.primary, custom_id="persistent_go_dashboard")
    async def go_to_dashboard(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Hiện dashboard ephemerally cho riêng người bấm
        view = PartyDashboardView(None) # bot không cần thiết ở đây vì dashboard này chỉ để xem
        await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)

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
        self.page = 0

    def get_embed(self):
        embed = discord.Embed(title="🎮 Party Hall", color=discord.Color.dark_embed())
        all_parties = list(active_parties.items())
        
        start = self.page * 6
        end = start + 6
        page_items = all_parties[start:end]
        
        for i in range(6):
            if i < len(page_items):
                p_id, data = page_items[i]
                embed.add_field(
                    name=f"⚔️ {data['dg_name']} (ID: {p_id})", 
                    value=f"**Host:** {data['host_ign']}\n**Time:** {data['start_time']}\n**Need:** {data['roles_needed']}", 
                    inline=True
                )
            else:
                embed.add_field(name="Slot Empty", value="---", inline=True)
        
        total_pages = max(1, (len(all_parties) + 5) // 6)
        embed.set_footer(text=f"Page {self.page + 1}/{total_pages}")
        return embed

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary, custom_id="btn_prev")
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0: self.page -= 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary, custom_id="btn_next")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (self.page + 1) * 6 < len(active_parties): self.page += 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Create Party", style=discord.ButtonStyle.success, row=1)
    async def create_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreatePartyModal())

# ==========================
# 3. COG
# ==========================
class RealTimePartyFinder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Đăng ký các view để nút hoạt động vĩnh viễn
        self.bot.add_view(NotificationView())
        self.bot.add_view(PartyDashboardView(self.bot))
        self.cleanup_task.start()

    @tasks.loop(minutes=1)
    async def cleanup_task(self):
        now = datetime.now()
        to_delete = [pid for pid, data in active_parties.items() if now - data['created_at'] > timedelta(hours=1)]
        for pid in to_delete: del active_parties[pid]

    @app_commands.command(name="make_party", description="Open Party Dashboard")
    async def make_party(self, interaction: discord.Interaction):
        view = PartyDashboardView(self.bot)
        await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)

async def setup(bot): await bot.add_cog(RealTimePartyFinder(bot))