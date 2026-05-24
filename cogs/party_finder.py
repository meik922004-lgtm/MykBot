import discord
from discord import app_commands
from discord.ext import commands
import uuid

# ==========================
# CROSS-SERVER CONFIGURATION
# ==========================
TARGET_CHANNEL_NAME = "party-board" 
TARGET_ROLE_NAME = "Dungeon Player" 

# Temporary memory storage for active parties
active_parties = {}

# ==========================
# HELPER: GENERATE REAL-TIME EMBED
# ==========================
def generate_party_embed(party_id: str) -> discord.Embed:
    data = active_parties.get(party_id)
    if not data:
        return discord.Embed(title="❌ Party Does Not Exist", color=discord.Color.red())

    current_count = len(data["members"])
    max_slots = data["max_slots"]
    
    is_full = current_count >= max_slots
    color = discord.Color.red() if is_full else discord.Color.green()
    
    embed = discord.Embed(
        title=f"⚔️ CROSS-SERVER LFG [{current_count}/{max_slots}] ⚔️",
        description="Real-time multi-server party matchmaking status dashboard.",
        color=color
    )
    embed.add_field(name="📍 Dungeon Target", value=f"**{data['dg_name']}**", inline=False)
    
    # Displaying current team members
    member_list = ""
    for idx, member in enumerate(data["members"], 1):
        icon = "👑" if idx == 1 else "⚔️"
        member_list += f"{icon} {idx}. **{member['ign']}** ({member['mention']}) - *{member['role']}*\n"
    embed.add_field(name="👥 Current Members", value=member_list, inline=False)

    # Displaying remaining roles needed
    if is_full:
        embed.add_field(name="🛑 Status", value="**PARTY IS FULL!**", inline=False)
    else:
        roles_text = ", ".join([f"`{r}`" for r in data["roles_needed"]])
        embed.add_field(name="🔍 Recruiting Roles", value=roles_text, inline=False)
        
    embed.set_footer(text=f"Party ID: {party_id} • System Auto-updates")
    return embed

# ==========================
# HELPER: UPDATE ALL SERVER MESSAGES
# ==========================
async def update_all_broadcasts(bot, party_id: str):
    data = active_parties.get(party_id)
    if not data:
        return

    new_embed = generate_party_embed(party_id)
    is_full = len(data["members"]) >= data["max_slots"]

    for channel_id, message_id in data["messages"]:
        try:
            channel = bot.get_channel(channel_id)
            if channel:
                message = await channel.fetch_message(message_id)
                if is_full:
                    disabled_view = discord.ui.View(timeout=None)
                    disabled_view.add_item(discord.ui.Button(label="Party is Full", style=discord.ButtonStyle.grey, disabled=True, emoji="🔒"))
                    await message.edit(embed=new_embed, view=disabled_view)
                else:
                    # Keep the original view (Join & Cancel buttons) active
                    view = discord.ui.View(timeout=None)
                    view.add_item(discord.ui.Button(label="Join Request", style=discord.ButtonStyle.green, custom_id=f"join_pt_{party_id}", emoji="📩"))
                    view.add_item(discord.ui.Button(label="Cancel Party", style=discord.ButtonStyle.danger, custom_id=f"cancel_pt_{party_id}", emoji="❌"))
                    await message.edit(embed=new_embed, view=view)
        except Exception:
            pass

# ==========================
# VIEW: HOST DECISION BUTTONS (SENT IN DM)
# ==========================
class HostDecisionView(discord.ui.View):
    def __init__(self, bot, party_id: str, applicant_id: int, applicant_ign: str, applicant_role: str):
        super().__init__(timeout=3600)
        self.bot = bot
        self.party_id = party_id
        self.applicant_id = applicant_id
        self.applicant_ign = applicant_ign
        self.applicant_role = applicant_role

    async def disable_buttons(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅")
    async def btn_accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.disable_buttons(interaction)
        data = active_parties.get(self.party_id)
        
        if not data or len(data["members"]) >= data["max_slots"]:
            await interaction.followup.send("❌ Cannot accept applicant. Party is full or no longer exists!", ephemeral=True)
            return

        applicant = self.bot.get_user(self.applicant_id)
        applicant_mention = applicant.mention if applicant else "Unknown User"
        
        data["members"].append({
            "ign": self.applicant_ign,
            "role": self.applicant_role,
            "mention": applicant_mention
        })

        await update_all_broadcasts(self.bot, self.party_id)

        if applicant:
            try:
                embed = discord.Embed(
                    title="🎉 REQUEST HAS BEEN ACCEPTED!",
                    description=(
                        f"Party leader **{data['host_ign']}** has accepted your application to join **{data['dg_name']}**!\n\n"
                        f"🎮 **Your ingame name:** {self.applicant_ign}\n"
                        f"👉 *Log into the game and wait for your team invitation!*"
                    ),
                    color=discord.Color.green()
                )
                await applicant.send(embed=embed)
            except discord.Forbidden:
                pass
        await interaction.followup.send(f"✅ Successfully added **{self.applicant_ign}** to the party!", ephemeral=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌")
    async def btn_reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.disable_buttons(interaction)
        applicant = self.bot.get_user(self.applicant_id)
        if applicant:
            try:
                embed = discord.Embed(
                    title="💔 REQUEST DENIED",
                    description="Your request to join the party has been declined by the Leader. Better luck next time!",
                    color=discord.Color.red()
                )
                await applicant.send(embed=embed)
            except discord.Forbidden:
                pass
        await interaction.followup.send("❌ Applicant has been rejected.", ephemeral=True)

# ==========================
# MODAL: APPLICANT SIGN-UP
# ==========================
class ApplicantModal(discord.ui.Modal, title="Join Party Request"):
    ign = discord.ui.TextInput(label="Your Ingame Name", placeholder="Enter character name exactly...", required=True)
    role = discord.ui.TextInput(label="Your Role/Class", placeholder="e.g., TANK or DPS...", required=True)

    def __init__(self, bot, party_id: str):
        super().__init__()
        self.bot = bot
        self.party_id = party_id

    async def on_submit(self, interaction: discord.Interaction):
        data = active_parties.get(self.party_id)
        if not data or len(data["members"]) >= data["max_slots"]:
            await interaction.response.send_message("❌ This party is already full or unavailable!", ephemeral=True)
            return

        host = self.bot.get_user(data["host_id"])
        if not host:
            await interaction.response.send_message("❌ Party leader could not be located.", ephemeral=True)
            return

        dm_embed = discord.Embed(title="🔔 NEW MEMBER JOIN REQUEST", color=discord.Color.orange())
        dm_embed.add_field(name="🎮 Ingame Name", value=self.ign.value, inline=True)
        dm_embed.add_field(name="⚔️ Applied Position", value=self.role.value, inline=True)
        dm_embed.add_field(name="👤 Discord Account", value=interaction.user.mention, inline=False)
        dm_embed.set_footer(text="Choose an action below to respond.")
        
        view = HostDecisionView(self.bot, self.party_id, interaction.user.id, self.ign.value, self.role.value)
        try:
            await host.send(embed=dm_embed, view=view)
            await interaction.response.send_message("✅ Your application has been sent! Please wait for the leader's decision.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Failed to send request because the Party Leader has disabled Direct Messages.", ephemeral=True)

# ==========================
# MODAL: HOST REGISTER IGN
# ==========================
class HostIgnModal(discord.ui.Modal, title="Final Step: Ingame Name"):
    ign = discord.ui.TextInput(label="Your Character Name", placeholder="Enter your in-game name...", required=True)

    def __init__(self, bot, setup_view):
        super().__init__()
        self.bot = bot
        self.setup_view = setup_view

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        party_id = str(uuid.uuid4())[:8]
        max_slots = 4 

        active_parties[party_id] = {
            "host_id": interaction.user.id,
            "host_ign": self.ign.value,
            "dg_name": self.setup_view.dg_name,
            "max_slots": max_slots,
            "roles_needed": self.setup_view.roles_needed,
            "members": [{
                "ign": self.ign.value,
                "role": self.setup_view.host_role,
                "mention": interaction.user.mention
            }],
            "messages": []
        }

        embed = generate_party_embed(party_id)

        # Added dynamic "Join Request" and "Cancel Party" control panel
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Join Request", style=discord.ButtonStyle.green, custom_id=f"join_pt_{party_id}", emoji="📩"))
        view.add_item(discord.ui.Button(label="Cancel Party", style=discord.ButtonStyle.danger, custom_id=f"cancel_pt_{party_id}", emoji="❌"))

        for guild in self.bot.guilds:
            channel = discord.utils.get(guild.text_channels, name=TARGET_CHANNEL_NAME)
            if channel:
                try:
                    msg = await channel.send(embed=embed, view=view)
                    active_parties[party_id]["messages"].append((channel.id, msg.id))
                except discord.Forbidden:
                    pass

        await interaction.followup.send(f"🚀 Your party listing has been successfully created and broadcasted!", ephemeral=True)

# ==========================
# VIEW: DASHBOARD INITIAL PANEL
# ==========================
class PartySetupView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=300)
        self.bot = bot
        self.dg_name = None
        self.host_role = None
        self.roles_needed = []

    @discord.ui.select(
        placeholder="1. Select Dungeon target...",
        options=[
            discord.SelectOption(label="MDG (Marine dragon domain)"),
            discord.SelectOption(label="PDG (Font yard of mansion)"),
            discord.SelectOption(label="Mugen (Back of the empire)"),
            discord.SelectOption(label="Pied (Stage of Clown)"),
            discord.SelectOption(label="APO (Void space)"),
            discord.SelectOption(label="Pillar A (Ruin of Four Pillar)"),
            discord.SelectOption(label="Pillar B (Ruin of Four Pillar)")
        ], row=0
    )
    async def select_dg(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.dg_name = select.values[0]
        await interaction.response.defer()

    @discord.ui.select(
        placeholder="2. Your Current Role...",
        options=[
            discord.SelectOption(label="DPS", emoji="🗡️"),
            discord.SelectOption(label="TANK", emoji="🛡️"),
            discord.SelectOption(label="UFM", emoji="🧩")
        ], row=1
    )
    async def select_host_role(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.host_role = select.values[0]
        await interaction.response.defer()

    @discord.ui.select(
        placeholder="3. Select Wanted Roles (Multiple choices enabled)...",
        min_values=1, max_values=3,
        options=[
            discord.SelectOption(label="Recruit DPS", value="DPS", emoji="🗡️"),
            discord.SelectOption(label="Recruit TANK", value="TANK", emoji="🛡️"),
            discord.SelectOption(label="Recruit UFM", value="UFM", emoji="🧩")
        ], row=2
    )
    async def select_roles(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.roles_needed = select.values
        await interaction.response.defer()

    @discord.ui.button(label="Initialize & Broadcast", style=discord.ButtonStyle.blurple, row=3, emoji="🚀")
    async def btn_submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not all([self.dg_name, self.host_role, self.roles_needed]):
            await interaction.response.send_message("⚠️ Please complete all 3 configuration setup fields!", ephemeral=True)
            return
        await interaction.response.send_modal(HostIgnModal(self.bot, self))

# ==========================
# MAIN COMMAND COG SYSTEM
# ==========================
class RealTimePartyFinder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Đã nâng cấp thành Slash Command
    @app_commands.command(name="make_pt", description="Tạo bảng tìm kiếm thành viên tổ đội liên server")
    async def make_pt(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🛠️ CROSS-SERVER LFG BUILDER", 
            description="Configure your dungeon specifications and desired squad compositions using the menus below.", 
            color=discord.Color.gold()
        )
        # Sử dụng interaction.response.send_message thay vì ctx.send
        await interaction.response.send_message(embed=embed, view=PartySetupView(self.bot), ephemeral=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
            
        custom_id = interaction.data.get("custom_id", "")
        
        # 1. HANDLE JOIN REQUEST BUTTON
        if custom_id.startswith("join_pt_"):
            party_id = custom_id.split("join_pt_")[1]
            data = active_parties.get(party_id)
            
            if not data:
                await interaction.response.send_message("❌ This party listing has expired or no longer exists.", ephemeral=True)
                return
            if interaction.user.id == data["host_id"]:
                await interaction.response.send_message("⚠️ You cannot join your own party!", ephemeral=True)
                return
            if len(data["members"]) >= data["max_slots"]:
                await interaction.response.send_message("❌ This party is currently full!", ephemeral=True)
                return

            await interaction.response.send_modal(ApplicantModal(self.bot, party_id))

        # 2. HANDLE CANCEL PARTY BUTTON
        elif custom_id.startswith("cancel_pt_"):
            party_id = custom_id.split("cancel_pt_")[1]
            data = active_parties.get(party_id)
            
            if not data:
                await interaction.response.send_message("❌ This party has already been disassembled or expired.", ephemeral=True)
                return
                
            # Security verification: check if execution user is the genuine Leader
            if interaction.user.id != data["host_id"]:
                await interaction.response.send_message("❌ Access Denied: Only the Party Leader can cancel this party!", ephemeral=True)
                return

            # Acknowledge the cancel command immediately
            await interaction.response.defer(ephemeral=True)

            # Build a closed cancellation announcement embed layout
            canceled_embed = discord.Embed(
                title="🚫 PARTY CANCELED 🚫",
                description=f"The cross-server listing for **{data['dg_name']}** has been dissolved by the Party Leader ({interaction.user.mention}).",
                color=discord.Color.light_grey()
            )
            canceled_view = discord.ui.View(timeout=None)
            canceled_view.add_item(discord.ui.Button(label="Party Canceled", style=discord.ButtonStyle.grey, disabled=True, emoji="🚫"))

            # Update across all distributed servers
            for channel_id, message_id in data["messages"]:
                try:
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        msg = await channel.fetch_message(message_id)
                        await msg.edit(embed=canceled_embed, view=canceled_view)
                except Exception:
                    pass

            # Purge data from temporal RAM cache register
            active_parties.pop(party_id, None)
            await interaction.followup.send("✅ Your party lobby has been successfully closed and unlinked across all servers.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(RealTimePartyFinder(bot))