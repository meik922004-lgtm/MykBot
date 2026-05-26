import discord
from discord.ext import commands
from discord import app_commands
import uuid
import math
from datetime import datetime, timezone
# Import trực tiếp các collection từ Database.py của bạn
from Database import players_col, parties_col, dungeon_configs

# ==========================================
# CONSTANTS & HELPER FUNCTIONS (EMBED BUILDERS)
# ==========================================

async def build_lobby_embed(page: int = 1, search_query: str = None):
    """Builds the main party lobby listing embed based on pagination and filters"""
    query_filter = {}
    if search_query:
        query_filter["dungeon"] = {"$regex": search_query, "$options": "i"}

    # Pagination calculation
    total_parties = await parties_col.count_documents(query_filter)
    per_page = 5
    max_pages = max(1, math.ceil(total_parties / per_page))
    
    # Clamp page limits
    if page < 1: page = 1
    if page > max_pages: page = max_pages
    
    skip_value = (page - 1) * per_page
    active_parties = await parties_col.find(query_filter).skip(skip_value).limit(per_page).to_list(length=per_page)

    embed = discord.Embed(
        title="⚔️ SYSTEM PARTY LOBBY HUB ⚔️",
        description=f"Showing active dungeon recruiting parties.\nFilter keyword: `{search_query or 'None'}`",
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text=f"Page {page}/{max_pages} • Total Parties: {total_parties}")

    count = 0
    for party in active_parties:
        count += 1
        leader = f"<@{party['leader_id']}>"
        member_count = len(party.get("members", []))
        max_slots = party.get("slots", 4)
        
        embed.add_field(
            name=f"{count}. 🏰 {party['dungeon'].upper()}",
            value=f"• **Leader:** {leader}\n"
                  f"• **Slots:** `{member_count}/{max_slots}`\n"
                  f"• **Requirements:** *{party.get('requirements', 'None')}*\n"
                  f"• **Party ID:** `{party['id']}`",
            inline=False
        )
        
    if count == 0:
        embed.description += "\n\n🛑 *No active parties found matching the criteria.*"

    return embed, max_pages


def build_manage_embed(party):
    """Builds the internal management dashboard embed for party leaders/members"""
    embed = discord.Embed(
        title=f"🛡️ PARTY MANAGEMENT: {party['dungeon'].upper()}",
        description=f"**Party ID:** `{party['id']}`\n**Requirements:** {party.get('requirements', 'None')}",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc)
    )
    
    leader_id = party["leader_id"]
    embed.add_field(name="👑 Party Leader", value=f"<@{leader_id}>", inline=False)
    
    # Members text compilation
    members_str = ""
    for idx, m in enumerate(party.get("members", []), 1):
        members_str += f"{idx}. <@{m['user_id']}> (IGN: `{m.get('ign', 'Unknown')}`)\n"
    
    embed.add_field(name=f"👥 Members ({len(party['members'])}/{party['slots']})", value=members_str or "*Empty*", inline=False)
    
    # Pending requests text compilation (Only relevant for leaders)
    reqs_str = ""
    for r in party.get("requests", []):
        reqs_str += f"• <@{r['user_id']}> (IGN: `{r.get('ign', 'Unknown')}`) - Role: `{r.get('role', 'DPS')}`\n"
        
    embed.add_field(name=f"⏳ Pending Requests ({len(party.get('requests', []))})", value=reqs_str or "*No pending requests*", inline=False)
    return embed

# ==========================================
# INTERACTIVE MODALS
# ==========================================

class SearchDungeonModal(discord.ui.Modal):
    query = discord.ui.TextInput(
        label="Enter dungeon keyword", 
        placeholder="e.g., Castle / Hard / Raid... (Leave blank to show all)",
        required=False
    )

    def __init__(self, current_page: int):
        super().__init__(title="Search For Parties")
        self.current_page = current_page

    async def on_submit(self, interaction: discord.Interaction):
        search_str = self.query.value.strip() or None
        embed, _ = await build_lobby_embed(page=1, search_query=search_str)
        view = LobbyView(page=1, search_query=search_str)
        await interaction.response.edit_message(embed=embed, view=view)


class JoinInputIGNModal(discord.ui.Modal):
    ign = discord.ui.TextInput(
        label="Your In-Game Name (IGN)", 
        placeholder="Must be exact for validation...",
        min_length=2,
        max_length=20
    )

    def __init__(self, party_id: str, role: str):
        super().__init__(title="Enter Character Name")
        self.party_id = party_id
        self.role = role

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        ign_val = self.ign.value.strip()
        
        # Save or update user IGN cache linkage
        players_col.update_one({"user_id": user_id}, {"$set": {"ign": ign_val}}, upsert=True)
        
        party = parties_col.find_one({"id": self.party_id})
        if not party:
            await interaction.response.send_message("❌ This party no longer exists.", ephemeral=True)
            return
            
        # Check if already a member or in request pool
        if any(m["user_id"] == user_id for m in party.get("members", [])):
            await interaction.response.send_message("⚠️ You are already a member of this party.", ephemeral=True)
            return
            
        if any(r["user_id"] == user_id for r in party.get("requests", [])):
            await interaction.response.send_message("⚠️ You already have a pending join request for this party.", ephemeral=True)
            return

        # Push request info to pool
        new_request = {"user_id": user_id, "ign": ign_val, "role": self.role, "timestamp": datetime.now(timezone.utc)}
        parties_col.update_one({"id": self.party_id}, {"$push": {"requests": new_request}})
        
        await interaction.response.send_message("✅ Your join request has been submitted to the leader!", ephemeral=True)


class EditNeedModal(discord.ui.Modal):
    recruitment = discord.ui.TextInput(
        label="New requirements", 
        placeholder="e.g., Looking for 1 Support / 140%+ Support Data...",
        max_length=100
    )

    def __init__(self, party_id: str):
        super().__init__(title="Update Recruitment Requirements")
        self.party_id = party_id

    async def on_submit(self, interaction: discord.Interaction):
        new_req = self.recruitment.value.strip() or "None"
        parties_col.update_one({"id": self.party_id}, {"$set": {"requirements": new_req}})
        
        party = parties_col.find_one({"id": self.party_id})
        embed = build_manage_embed(party)
        await interaction.response.edit_message(embed=embed, view=ManagePartyView(self.party_id, interaction.user.id))


class CreatePartyModal(discord.ui.Modal):
    dungeon = discord.ui.TextInput(label="Dungeon Name", placeholder="e.g., Nanomon Hard / Kimera Raid", max_length=50)
    slots = discord.ui.TextInput(label="Max Slots (2-4)", placeholder="Default is 4", default="4", max_length=1)
    reqs = discord.ui.TextInput(label="Requirements", placeholder="e.g., 150k+ HP / Reset deck", required=False, max_length=100)

    def __init__(self):
        super().__init__(title="Create New Party")

    async def on_submit(self, interaction: discord.Interaction):
        # Validate slots allocation input
        try:
            max_slots = int(self.slots.value)
            if not (2 <= max_slots <= 4): raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Invalid slots number. Must be an integer between 2 and 4.", ephemeral=True)
            return

        user_id = interaction.user.id
        # Check if user already leading a party
        existing = parties_col.find_one({"leader_id": user_id})
        if existing:
            await interaction.response.send_message(f"❌ You are already leading a party for `{existing['dungeon']}`! Disband it first.", ephemeral=True)
            return

        # Fetch player profile link
        player_profile = players_col.find_one({"user_id": user_id})
        ign = player_profile.get("ign", "Unknown") if player_profile else "Unknown"

        party_id = str(uuid.uuid4())[:8] # Clean readable unique segment hex string
        new_party = {
            "id": party_id,
            "leader_id": user_id,
            "dungeon": self.dungeon.value.strip(),
            "slots": max_slots,
            "requirements": self.reqs.value.strip() or "None",
            "members": [{"user_id": user_id, "ign": ign, "role": "Leader"}],
            "requests": [],
            "created_at": datetime.now(timezone.utc)
        }
        
        parties_col.insert_one(new_party)
        
        # Broadcast creation message notification publicly to the server channel
        broadcast_embed = discord.Embed(
            title=f"📢 NEW PARTY BROADCAST: {new_party['dungeon'].upper()}",
            description=f"**Leader:** <@{user_id}>\n**Slots Available:** `1/{max_slots}`\n**Requirements:** {new_party['requirements']}",
            color=discord.Color.purple()
        )
        broadcast_embed.set_footer(text=f"Party ID: {party_id} • Click button below to request join")
        
        # Deploy dynamic non-conflicting target tracking custom view
        public_view = BroadcastJoinView(party_id)
        
        # Attempt to target dispatch messaging to dedicated text board
        chan = discord.utils.get(interaction.guild.text_channels, name="party-board")
        if chan:
            await chan.send(embed=broadcast_embed, view=public_view)
            
        # Refresh current UI
        embed, _ = await build_lobby_embed(page=1)
        await interaction.response.edit_message(embed=embed, view=LobbyView(page=1))


# ==========================================
# CORE HUB GOTO VIEW
# ==========================================

class LobbyView(discord.ui.View):
    """Main interactive dashboard at the Lobby Hub"""
    def __init__(self, page: int = 1, search_query: str = None):
        super().__init__(timeout=None)
        self.page = page
        self.search_query = search_query

    @discord.ui.button(label="◀️ Prev", style=discord.ButtonStyle.secondary, custom_id="lobby_prev")
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 1:
            self.page -= 1
            embed, _ = await build_lobby_embed(self.page, self.search_query)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.send_message("You are already on the first page!", ephemeral=True)

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.secondary, custom_id="lobby_next")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed, max_pages = await build_lobby_embed(self.page, self.search_query)
        if self.page < max_pages:
            self.page += 1
            embed, _ = await build_lobby_embed(self.page, self.search_query)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.send_message("You are already on the last page!", ephemeral=True)

    @discord.ui.button(label="🔍 Filter Dungeon", style=discord.ButtonStyle.primary, custom_id="lobby_filter")
    async def filter_dungeon(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchDungeonModal(self.page))

    @discord.ui.button(label="➕ Create Party", style=discord.ButtonStyle.success, custom_id="lobby_create")
    async def create_party_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreatePartyModal())

# ==========================================
# PUBLIC SERVER INTERACTION VIEW
# ==========================================

class BroadcastJoinView(discord.ui.View):
    """Persistent tracking view deployed inside public guild channels"""
    def __init__(self, party_id: str):
        super().__init__(timeout=None)
        self.party_id = party_id
        # Dynamic deterministic mapping custom string definition
        self.join_req_trigger.custom_id = f"btn_join_req:{party_id}"

    @discord.ui.button(label="Join Request", style=discord.ButtonStyle.primary)
    async def join_req_trigger(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = parties_col.find_one({"id": self.party_id})
        if not party:
            await interaction.response.send_message("❌ This party has already been disbanded.", ephemeral=True)
            return

        if len(party.get("members", [])) >= party.get("slots", 4):
            await interaction.response.send_message("🛑 This party is already full!", ephemeral=True)
            return

        # Construct selection role item
        select_view = discord.ui.View(timeout=60)
        role_select = discord.ui.Select(
            placeholder="Choose your operational combat role...",
            options=[
                discord.SelectOption(label="DPS Attacker", value="DPS", emoji="⚔️"),
                discord.SelectOption(label="Support / Healer", value="Support", emoji="🛡️"),
                discord.SelectOption(label="Tanker", value="Tank", emoji="🧱")
            ]
        )

        async def select_callback(inter: discord.Interaction):
            selected_role = role_select.values[0]
            # Route payload handling parameters forward directly to user validation data input modal
            await inter.response.send_modal(JoinInputIGNModal(self.party_id, selected_role))

        role_select.callback = select_callback
        select_view.add_item(role_select)
        await interaction.response.send_message("Select your role preference:", view=select_view, ephemeral=True)


# ==========================================
# INTERNAL PRIVATE CONTROL PANEL VIEW
# ==========================================

class ManagePartyView(discord.ui.View):
    """Internal Control Panel for Party Members and Leaders"""
    def __init__(self, party_id: str, user_id: int):
        super().__init__(timeout=600) # Memory leakage control timeout guard limit (10 Minutes)
        self.party_id = party_id
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        party = parties_col.find_one({"id": self.party_id})
        if not party:
            await interaction.response.send_message("❌ Party no longer active.", ephemeral=True)
            return False
        
        # Verify identity link clearance level
        is_leader = (party["leader_id"] == interaction.user.id)
        is_member = any(m["user_id"] == interaction.user.id for m in party.get("members", []))
        
        if not (is_leader or is_member):
            await interaction.response.send_message("❌ You are not part of this squad group.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📝 Edit Needs", style=discord.ButtonStyle.secondary)
    async def edit_requirements(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = parties_col.find_one({"id": self.party_id})
        if party["leader_id"] != interaction.user.id:
            await interaction.response.send_message("❌ Only the party leader can edit requirements.", ephemeral=True)
            return
        await interaction.response.send_modal(EditNeedModal(self.party_id))

    @discord.ui.button(label="✅ Approve Request", style=discord.ButtonStyle.success)
    async def approve_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = parties_col.find_one({"id": self.party_id})
        if party["leader_id"] != interaction.user.id:
            await interaction.response.send_message("❌ Authorization denied: Leader action item only.", ephemeral=True)
            return

        if not party.get("requests", []):
            await interaction.response.send_message("⚠️ No pending applications found.", ephemeral=True)
            return

        # Deploy select selection filtering item
        select_view = discord.ui.View(timeout=60)
        options = [
            discord.SelectOption(label=f"{r['ign']} ({r['role']})", value=str(r['user_id'])) 
            for r in party["requests"][:25]
        ]
        
        user_select = discord.ui.Select(placeholder="Select applicant to approve...", options=options)

        async def approve_callback(inter: discord.Interaction):
            target_id = int(user_select.values[0])
            curr_party = parties_col.find_one({"id": self.party_id})
            
            if len(curr_party.get("members", [])) >= curr_party.get("slots", 4):
                await inter.response.send_message("❌ Cannot approve: Squad capacity limit reached!", ephemeral=True)
                return

            target_req = next((r for r in curr_party["requests"] if r["user_id"] == target_id), None)
            if target_req:
                # Update operations data sequence allocation arrays
                parties_col.update_one(
                    {"id": self.party_id},
                    {
                        "$pull": {"requests": {"user_id": target_id}},
                        "$push": {"members": {"user_id": target_id, "ign": target_req["ign"], "role": target_req["role"]}}
                    }
                )
                
            updated = parties_col.find_one({"id": self.party_id})
            await inter.response.edit_message(embed=build_manage_embed(updated), view=ManagePartyView(self.party_id, self.user_id))

        user_select.callback = approve_callback
        select_view.add_item(user_select)
        await interaction.response.send_message("Approve selection:", view=select_view, ephemeral=True)

    @discord.ui.button(label="❌ Reject Request", style=discord.ButtonStyle.danger)
    async def reject_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = parties_col.find_one({"id": self.party_id})
        if party["leader_id"] != interaction.user.id:
            await interaction.response.send_message("❌ Authorization denied: Leader action item only.", ephemeral=True)
            return

        if not party.get("requests", []):
            await interaction.response.send_message("⚠️ No pending applications found.", ephemeral=True)
            return

        select_view = discord.ui.View(timeout=60)
        options = [discord.SelectOption(label=r["ign"], value=str(r["user_id"])) for r in party["requests"][:25]]
        user_select = discord.ui.Select(placeholder="Select applicant to reject...", options=options)

        async def reject_callback(inter: discord.Interaction):
            target_id = int(user_select.values[0])
            parties_col.update_one({"id": self.party_id}, {"$pull": {"requests": {"user_id": target_id}}})
            
            updated = parties_col.find_one({"id": self.party_id})
            await inter.response.edit_message(embed=build_manage_embed(updated), view=ManagePartyView(self.party_id, self.user_id))

        user_select.callback = reject_callback
        select_view.add_item(user_select)
        await interaction.response.send_message("Reject selection:", view=select_view, ephemeral=True)

    @discord.ui.button(label="💥 Disband / Leave", style=discord.ButtonStyle.danger)
    async def leave_or_disband(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = parties_col.find_one({"id": self.party_id})
        
        if party["leader_id"] == interaction.user.id:
            # Action logic: Complete wipe clean execution drop
            parties_col.delete_one({"id": self.party_id})
            await interaction.response.edit_message(content="💥 *The party group has been completely disbanded by the leader.*", embed=None, view=None)
        else:
            # Action logic: Splice out individual target user link elements
            parties_col.update_one({"id": self.party_id}, {"$pull": {"members": {"user_id": interaction.user.id}}})
            updated = parties_col.find_one({"id": self.party_id})
            await interaction.response.edit_message(embed=build_manage_embed(updated), view=self)


# ==========================================
# MAIN COMMANDS EXTENSION COG CLASS
# ==========================================
import asyncio
class PartyFinder(commands.Cog):
    """Professional System Group Formation and Dungeon Party Finder Engine"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="party_lobby", description="Open the system dungeon matchmaking party hub interface panel")
    async def party_lobby(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            await asyncio.sleep(0)  # ép chạy ngay
            embed, _ = await build_lobby_embed(page=1)
            view = LobbyView(page=1)
            await interaction.followup.send(embed=embed, view=view)
        except Exception as e:
            await interaction.followup.send(f"❌ Lỗi: {e}", ephemeral=True)

    @app_commands.command(name="manage_party", description="Open your current active party group panel dashboard dashboard")
    async def manage_party(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        # Search membership track indicators matches
        party = await parties_col.find_one({"$or": [{"leader_id": user_id}, {"members.user_id": user_id}]})
        
        if not party:
            await interaction.response.send_message("❌ You are currently not associated with any active raiding group parties.", ephemeral=True)
            return
            
        embed = build_manage_embed(party)
        view = ManagePartyView(party["id"], user_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PartyFinder(bot))