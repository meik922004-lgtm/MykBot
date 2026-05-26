import discord
from discord.ext import commands
from discord import app_commands
import os
import uuid
import asyncio
from datetime import datetime, timezone
# ❌ ĐÃ XÓA dòng: from pymongo import MongoClient (Không cần nữa)

# ==========================================
# DATABASE CONNECTION INITIALIZATION (MONGO)
# ==========================================
# 🟢 Chỉ cần import trực tiếp các collection từ file Database.py của bạn là đủ sạch sẽ
from Database import players_col, parties_col, dungeon_configs

# ❌ XÓA CÁC DÒNG NÀY ĐI (vì lệnh import ở trên đã lấy trực tiếp các biến này rồi, không cần định nghĩa lại nữa):

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def build_lobby_embed(page: int = 1, search_query: str = None):
    """Builds the party lobby list interface with pagination"""
    items_per_page = 5
    query = {}
    if search_query:
        query["dg_name"] = {"$regex": search_query, "$options": "i"}
        
    total_parties = parties_col.count_documents(query)
    max_pages = max(1, (total_parties + items_per_page - 1) // items_per_page)
    
    if page < 1: page = 1
    if page > max_pages: page = max_pages
    
    skip = (page - 1) * items_per_page
    parties_on_page = list(parties_col.find(query).skip(skip).limit(items_per_page))
    
    embed = discord.Embed(
        title="🎮 PARTY FINDER LOBBY", 
        description=f"Find or create a party for dungeons. Real-time broadcast board.\n🔍 Current Search: `{search_query or 'All'}`",
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Page {page}/{max_pages} • Total: {total_parties} parties")
    
    if not parties_on_page:
        embed.add_field(name="🪹 Empty", value="There are no active parties at the moment.", inline=False)
    else:
        for p in parties_on_page:
            created_time = p["created_at"].replace(tzinfo=timezone.utc).timestamp()
            header = f"⚔️ **{p['dg_name']}** (ID: `{p['id']}`)"
            
            # Check Gear Filter status
            filter_status = "🟢 Enabled" if p.get("auto_filter", True) else "🔴 Disabled"
            
            body = (
                f"> 👑 **Leader:** {p['leader_ign']} | 🎯 **Looking for:** {p['recruitment']}\n"
                f"> 👥 **Members:** `{len(p['members'])}/4` | ⏳ **Start time:** {p['start_in']}\n"
                f"> ⚙️ **Auto-Filter:** {filter_status} | 🕒 Created: <t:{int(created_time)}:R>\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            embed.add_field(name=header, value=body, inline=False)
            
    return embed, max_pages

async def update_party_broadcasts(bot: commands.Bot, party_id: str):
    """Updates the display of the party on all party-board channels across servers"""
    party = parties_col.find_one({"id": party_id})
    if not party:
        return
        
    embed = discord.Embed(title=f"🚨 RECRUITING PARTY: {party['dg_name']}", color=discord.Color.green())
    
    members_text = ""
    for idx, m in enumerate(party["members"], 1):
        members_text += f"{idx}. {m['ign']} ({m['role']})\n"
        
    embed.add_field(name="📌 Info", value=f"**ID:** `{party['id']}`\n**Leader:** {party['leader_ign']}\n**Recruiting:** {party['recruitment']}\n**Schedule:** {party['start_in']}", inline=True)
    embed.add_field(name="👥 Lineup", value=members_text or "Empty", inline=True)
    embed.set_footer(text="Click 'Join Request' below to apply for this party")
    
    # Loop through sent messages to update content
    broadcasts = party.get("broadcasts", [])
    for b in broadcasts:
        try:
            channel = bot.get_channel(b["channel_id"]) or await bot.fetch_channel(b["channel_id"])
            if channel:
                message = await channel.fetch_message(b["message_id"])
                if message:
                    await message.edit(embed=embed, view=BroadcastJoinView(party_id))
        except Exception:
            pass

async def clear_party_broadcasts(bot: commands.Bot, party_id: str):
    """Deletes all public recruitment messages when a party is disbanded"""
    party = parties_col.find_one({"id": party_id})
    if party:
        for b in party.get("broadcasts", []):
            try:
                channel = bot.get_channel(b["channel_id"]) or await bot.fetch_channel(b["channel_id"])
                if channel:
                    msg = await channel.fetch_message(b["message_id"])
                    await msg.delete()
            except Exception:
                pass

# ==========================================
# INTERACTIVE VIEWS & MODALS
# ==========================================

class CreatePartyModal(discord.ui.Modal, title="Create New Dungeon Party"):
    dg_name = discord.ui.TextInput(label="Dungeon / Raid Name", placeholder="e.g., Shadow Castle Hard...")
    leader_ign = discord.ui.TextInput(label="Your IGN (In-Game Name)", placeholder="Enter your character name...")
    role = discord.ui.TextInput(label="Your Role / Class", placeholder="DPS / Tanker / Healer / Support...")
    recruitment = discord.ui.TextInput(label="Looking For", placeholder="e.g., Need 1 Healer with Buff...")
    start_in = discord.ui.TextInput(label="Estimated Start Time", placeholder="e.g., When full / 21:00 UTC...")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Check if user is already in another party
        existing = parties_col.find_one({"$or": [{"leader_id": interaction.user.id}, {"members.id": interaction.user.id}]})
        if existing:
            await interaction.followup.send("❌ You are already in another party! Please leave it first.", ephemeral=True)
            return

        pid = str(uuid.uuid4())[:6].upper()
        
        # 1. Create Private Thread
        thread_id = None
        try:
            thread = await interaction.channel.create_thread(
                name=f"🔒 Party {pid}: {self.dg_name.value}",
                type=discord.ChannelType.private_thread,
                auto_archive_duration=60
            )
            thread_id = thread.id
            await thread.add_user(interaction.user)
            await thread.send(f"👋 Welcome {interaction.user.mention}! This is the **🔒 PRIVATE** group chat for your party **{self.dg_name.value}**. Approved members will be added automatically.")
        except Exception as e:
            print(f"Error creating private thread: {e}")

        # 2. Save to database
        party_data = {
            "id": pid,
            "leader_id": interaction.user.id,
            "leader_ign": self.leader_ign.value,
            "dg_name": self.dg_name.value,
            "recruitment": self.recruitment.value,
            "start_in": self.start_in.value,
            "auto_filter": True,
            "thread_id": thread_id,
            "created_at": datetime.now(timezone.utc),
            "members": [{"id": interaction.user.id, "ign": self.leader_ign.value, "role": self.role.value}],
            "broadcasts": []
        }
        parties_col.insert_one(party_data)
        
        # 3. Broadcast recruitment messages to 'party-board' channels
        broadcast_list = []
        embed = discord.Embed(title=f"🚨 RECRUITING PARTY: {self.dg_name.value}", color=discord.Color.green())
        embed.add_field(name="📌 Info", value=f"**ID:** `{pid}`\n**Leader:** {self.leader_ign.value}\n**Recruiting:** {self.recruitment.value}\n**Schedule:** {self.start_in.value}", inline=True)
        embed.add_field(name="👥 Lineup", value=f"1. {self.leader_ign.value} ({self.role.value})", inline=True)
        
        for guild in interaction.client.guilds:
            channel = discord.utils.get(guild.text_channels, name="party-board")
            if channel:
                try:
                    msg = await channel.send(embed=embed, view=BroadcastJoinView(pid))
                    broadcast_list.append({"guild_id": guild.id, "channel_id": channel.id, "message_id": msg.id})
                except Exception:
                    pass
                    
        parties_col.update_one({"id": pid}, {"$set": {"broadcasts": broadcast_list}})
        await interaction.followup.send(f"✅ Successfully created party `{pid}` and broadcasted to the system!", ephemeral=True)


class BroadcastJoinView(discord.ui.View):
    """Join button layout displayed in public broadcast channels"""
    def __init__(self, party_id: str):
        super().__init__(timeout=None)
        self.party_id = party_id
        
    @discord.ui.button(label="Join Request", style=discord.Style.primary, custom_id="btn_join_req")
    async def join_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Anti-spam rate limiting system
        if not hasattr(interaction.client, "join_cooldowns"):
            interaction.client.join_cooldowns = {}
        
        user_id = interaction.user.id
        now = datetime.now()
        if user_id in interaction.client.join_cooldowns:
            diff = (now - interaction.client.join_cooldowns[user_id]).total_seconds()
            if diff < 10:
                await interaction.response.send_message(f"⏳ Actions are too fast! Please wait {10 - int(diff)} seconds.", ephemeral=True)
                return
        interaction.client.join_cooldowns[user_id] = now

        await interaction.response.send_message(content="Please fill in your application info:", view=JoinFormView(self.party_id), ephemeral=True)


class JoinFormView(discord.ui.View):
    """Sub-view to select Role before completing application"""
    def __init__(self, party_id: str):
        super().__init__(timeout=60)
        self.party_id = party_id

    @discord.ui.select(placeholder="Choose your Role / Class...", options=[
        discord.SelectOption(label="DPS", value="DPS", emoji="⚔️"),
        discord.SelectOption(label="Tanker", value="Tanker", emoji="🛡️"),
        discord.SelectOption(label="Healer", value="Healer", emoji="🧪"),
        discord.SelectOption(label="Support/Buff", value="Support", emoji="✨")
    ])
    async def select_role(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_role = select.values[0]
        # Open IGN input Modal next
        await interaction.response.send_modal(JoinInputIGNModal(self.party_id, self.selected_role))


class JoinInputIGNModal(discord.ui.Modal, title="Enter Character Name"):
    ign = discord.ui.TextInput(label="Your In-Game Name (IGN)", placeholder="Must be exact for Gear validation...")

    def __init__(self, party_id: str, role: str):
        super().__init__()
        self.party_id = party_id
        self.role = role

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        party = parties_col.find_one({"id": self.party_id})
        
        if not party:
            await interaction.followup.send("❌ This party no longer exists or has been cancelled.", ephemeral=True)
            return
            
        if len(party["members"]) >= 4:
            await interaction.followup.send("❌ This party is already full!", ephemeral=True)
            return

        # Check if candidate is locked in another room
        in_other = parties_col.find_one({"$or": [{"leader_id": interaction.user.id}, {"members.id": interaction.user.id}]})
        if in_other:
            await interaction.followup.send("❌ You are already in a group, cannot apply for another.", ephemeral=True)
            return

        # --- FEATURE 1: AUTO-FILTER QUALIFICATION (GEAR CHECK) ---
        if party.get("auto_filter", True):
            player_profile = players_col.find_one({"id": interaction.user.id})
            dg_conf = dungeon_configs.find_one({"name": party["dg_name"]})
            
            if dg_conf and "min_gear" in dg_conf:
                if not player_profile or player_profile.get("gear_score", 0) < dg_conf["min_gear"]:
                    await interaction.followup.send(
                        f"❌ **Auto-Rejected:** This dungeon requires a minimum of **{dg_conf['min_gear']} Gear Score**.\n"
                        f"Your current score: `{player_profile.get('gear_score', 0) if player_profile else 'Not Registered'}`.", 
                        ephemeral=True
                    )
                    return

        # Fetch profile data to forward to Leader
        p_prof = players_col.find_one({"id": interaction.user.id}) or {}
        
        # --- FEATURE 2: REQUEST TO JOIN (SEND LOBBY COMMAND TO LEADER DM) ---
        try:
            leader_user = interaction.client.get_user(party["leader_id"]) or await interaction.client.fetch_user(party["leader_id"])
            if leader_user:
                dm_embed = discord.Embed(title="📥 INCOMING JOIN REQUEST", color=discord.Color.orange())
                dm_embed.add_field(name="Party Info", value=f"**Dungeon:** {party['dg_name']} (`{party['id']}`)", inline=False)
                dm_embed.add_field(name="Applicant", value=f"**User:** {interaction.user.mention}\n**IGN:** {self.ign.value}\n**Applied Role:** `{self.role}`", inline=True)
                dm_embed.add_field(name="DB Gear Profile", value=f"• Gear Score: `{p_prof.get('gear_score', 'N/A')}`\n• Deck: `{p_prof.get('deck', 'N/A')}`\n• Elements: `{p_prof.get('vice', 'N/A')}`", inline=True)
                
                await leader_user.send(embed=dm_embed, view=DecisionView(self.party_id, interaction.user, self.ign.value, self.role))
                await interaction.followup.send("✅ Request sent successfully! Waiting for Party Leader approval...", ephemeral=True)
        except Exception:
            await interaction.followup.send("❌ Failed to send DM to the Leader. They might have disabled direct messages from strangers.", ephemeral=True)


class DecisionView(discord.ui.View):
    """Accept / Reject panel sent directly to the Leader's DMs"""
    def __init__(self, party_id: str, candidate: discord.User, ign: str, role: str):
        super().__init__(timeout=None)
        self.party_id = party_id
        self.candidate = candidate
        self.ign = ign
        self.role = role

    @discord.ui.button(label="Accept", style=discord.Style.success, custom_id="dec_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        party = parties_col.find_one({"id": self.party_id})
        
        if not party:
            await interaction.followup.send("❌ This party has already been disbanded.", ephemeral=True)
            return
        if len(party["members"]) >= 4:
            await interaction.followup.send("❌ The party is full, cannot add this member.", ephemeral=True)
            return
            
        # Append member to database array
        new_member = {"id": self.candidate.id, "ign": self.ign, "role": self.role}
        parties_col.update_one({"id": self.party_id}, {"$push": {"members": new_member}})
        
        # Update Leader's DM message interface
        await interaction.edit_original_response(content=f"✅ You have APPROVED {self.candidate.mention} into the party.", embed=None, view=None)
        
        # --- ADD AND PING MEMBER IN PRIVATE THREAD ---
        if party.get("thread_id"):
            try:
                thread = interaction.client.get_channel(party["thread_id"]) or await interaction.client.fetch_channel(party["thread_id"])
                if thread:
                    await thread.add_user(self.candidate)
                    await thread.send(f"🎉 Welcome {self.candidate.mention} ({self.role}) to the Party! Get your gears ready.")
            except Exception as e:
                print(f"Error adding member to thread: {e}")

        # Update public board broadcasts
        await update_party_broadcasts(interaction.client, self.party_id)
        
        # Notify candidate in their DMs
        try: await self.candidate.send(f"🎉 Success! Your request to join **{party['dg_name']}** has been approved!")
        except: pass

    @discord.ui.button(label="Reject", style=discord.Style.danger, custom_id="dec_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await interaction.edit_original_response(content=f"❌ You have REJECTED {self.candidate.mention}.", embed=None, view=None)
        
        try: await self.candidate.send(f"⚠️ Your request to join the party has been declined by the Leader.")
        except: pass


class LobbyView(discord.ui.View):
    """Main interactive dashboard at the Lobby Hub"""
    def __init__(self, page: int = 1, search_query: str = None):
        super().__init__(timeout=None)
        self.page = page
        self.search_query = search_query

    @discord.ui.button(label="◀️ Prev", style=discord.Style.secondary, custom_id="lobby_prev")
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 1:
            self.page -= 1
            embed, _ = build_lobby_embed(self.page, self.search_query)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.send_message("You are already on the first page!", ephemeral=True)

    @discord.ui.button(label="Next ▶️", style=discord.Style.secondary, custom_id="lobby_next")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed, max_pages = build_lobby_embed(self.page, self.search_query)
        if self.page < max_pages:
            self.page += 1
            embed, _ = build_lobby_embed(self.page, self.search_query)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.send_message("You are already on the last page!", ephemeral=True)

    @discord.ui.button(label="➕ Create Party", style=discord.Style.success, custom_id="lobby_create")
    async def create_party_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreatePartyModal())

    @discord.ui.button(label="🔍 Search Dungeon", style=discord.Style.primary, custom_id="lobby_search")
    async def search_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchDungeonModal(self.page))
class SearchDungeonModal(discord.ui.Modal):
    query = discord.ui.TextInput(label="Enter dungeon keyword", placeholder="e.g., Castle / Hard / Raid... (Leave blank to show all)")

    def __init__(self, current_page: int):
        super().__init__(title="Search For Parties")
        self.current_page = current_page

    async def on_submit(self, interaction: discord.Interaction):
        q = self.query.value.strip() or None
        embed, _ = build_lobby_embed(page=1, search_query=q)
        await interaction.response.edit_message(embed=embed, view=LobbyView(page=1, search_query=q))


class ManagePartyView(discord.ui.View):
    """Internal Control Panel for Party Members and Leaders"""
    def __init__(self, party_id: str, user_id: int):
        super().__init__(timeout=None)
        self.party_id = party_id
        self.user_id = user_id

    @discord.ui.button(label="Leave Party", style=discord.Style.danger, custom_id="manage_leave")
    async def leave_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        party = parties_col.find_one({"id": self.party_id})
        if not party:
            await interaction.followup.send("❌ Party room data not found.", ephemeral=True)
            return

        if party["leader_id"] == self.user_id:
            await interaction.followup.send("👑 You are the Leader! To cancel the group, please use **Disband Party**.", ephemeral=True)
            return

        # Pull member from database array
        parties_col.update_one({"id": self.party_id}, {"$pull": {"members": {"id": self.user_id}}})
        await interaction.followup.send("✅ You have successfully left the party.", ephemeral=True)

        # Remove user from Private Thread
        if party.get("thread_id"):
            try:
                thread = interaction.client.get_channel(party["thread_id"]) or await interaction.client.fetch_channel(party["thread_id"])
                if thread:
                    member_obj = await interaction.guild.fetch_member(self.user_id)
                    await thread.remove_user(member_obj)
                    await thread.send(f"🏃‍♂️ Member `{interaction.user.name}` has left the party.")
            except Exception: pass

        await update_party_broadcasts(interaction.client, self.party_id)

    @discord.ui.button(label="Disband Party", style=discord.Style.danger, custom_id="manage_disband")
    async def disband_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        party = parties_col.find_one({"id": self.party_id})
        
        if not party or party["leader_id"] != self.user_id:
            await interaction.followup.send("❌ You do not have permission to Disband this party!", ephemeral=True)
            return

        # 1. Clear broadcast messages first
        await clear_party_broadcasts(interaction.client, self.party_id)

        # 2. Delete and terminate Private Thread group chat completely
        if party.get("thread_id"):
            try:
                thread = interaction.client.get_channel(party["thread_id"]) or await interaction.client.fetch_channel(party["thread_id"])
                if thread:
                    await thread.send("💥 System: The leader has disbanded the party. This channel will close in 3 seconds...")
                    await asyncio.sleep(3)
                    await thread.delete()
            except Exception: pass

        # 3. Wipe record out from Database
        parties_col.delete_one({"id": self.party_id})
        await interaction.followup.send("✅ Party has been successfully closed and data cleared.", ephemeral=True)

    @discord.ui.button(label="Edit Requirements", style=discord.Style.primary, custom_id="manage_edit")
    async def edit_need(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = parties_col.find_one({"id": self.party_id})
        if not party or party["leader_id"] != self.user_id:
            await interaction.response.send_message("❌ Only the Party Leader can modify recruitment details!", ephemeral=True)
            return
        await interaction.response.send_modal(EditNeedModal(self.party_id))

    @discord.ui.button(label="Kick Member", style=discord.Style.secondary, custom_id="manage_kick")
    async def kick_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = parties_col.find_one({"id": self.party_id})
        if not party or party["leader_id"] != self.user_id:
            await interaction.response.send_message("❌ Only the Party Leader can kick members!", ephemeral=True)
            return
            
        if len(party["members"]) <= 1:
            await interaction.response.send_message("There are no other members in the party to kick.", ephemeral=True)
            return
            
        # Call View containing Select Menu for filtering lineup
        await interaction.response.send_message("Select the member you want to kick from the party:", view=KickSelectView(party), ephemeral=True)

    @discord.ui.button(label="Ready Check", style=discord.Style.success, custom_id="manage_ready")
    async def ready_check(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = parties_col.find_one({"id": self.party_id})
        if not party or party["leader_id"] != self.user_id:
            await interaction.response.send_message("❌ Only the Party Leader can initiate a Ready Check!", ephemeral=True)
            return

        await interaction.response.send_message("🚀 Launching Ready Check requests to all members...", ephemeral=True)
        
        # Ping group chat within the Private Thread if valid
        thread = None
        if party.get("thread_id"):
            thread = interaction.client.get_channel(party["thread_id"]) or await interaction.client.fetch_channel(party["thread_id"])
            if thread:
                await thread.send("📢 **READY CHECK!** The leader has requested a status check. Please look for the DM sent by the Bot!")

        # Spin up surveying cycle via DMs
        rc_view = ReadyCheckCollectorView(party["members"])
        for m in party["members"]:
            try:
                user = interaction.client.get_user(m["id"]) or await interaction.client.fetch_user(m["id"])
                if user:
                    await user.send(f"⚡ **Ready Check:** Are you ready to start **{party['dg_name']}** right now?", view=rc_view)
            except Exception: pass

        # Hang on for input tracking for 60 seconds
        await asyncio.sleep(60)
        rc_view.stop()

        # Consolidate reporting summaries
        summary = "📊 **READY CHECK RESULTS (AFTER 60S):**\n"
        for m in party["members"]:
            status = rc_view.results.get(m["id"], "⏳ No Response")
            summary += f"• {m['ign']}: {status}\n"

        if thread:
            await thread.send(summary)

    @discord.ui.button(label="Toggle Gear Filter", style=discord.Style.secondary, custom_id="manage_toggle_filter")
    async def toggle_filter(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        party = parties_col.find_one({"id": self.party_id})
        if not party or party["leader_id"] != self.user_id:
            await interaction.followup.send("❌ You are not the party leader.", ephemeral=True)
            return

        current_status = party.get("auto_filter", True)
        new_status = not current_status
        parties_col.update_one({"id": self.party_id}, {"$set": {"auto_filter": new_status}})
        
        txt = "ENABLED (Strict checks matching Dungeon requirements)" if new_status else "DISABLED (Open recruitment without filters)"
        await interaction.followup.send(f"⚙️ Auto-Filter status has been toggled to: **{txt}**", ephemeral=True)


class EditNeedModal(discord.ui.Modal, title="Update Recruitment Requirements"):
    recruitment = discord.ui.TextInput(label="New requirements", placeholder="e.g., Changed to: looking for 1 Fire-element DPS...")

    def __init__(self, party_id: str):
        super().__init__()
        self.party_id = party_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        parties_col.update_one({"id": self.party_id}, {"$set": {"recruitment": self.recruitment.value}})
        await interaction.followup.send("✅ Recruitment message updated successfully!", ephemeral=True)
        await update_party_broadcasts(interaction.client, self.party_id)


class KickSelectView(discord.ui.View):
    """Select Menu filtering teammates to execute kick actions"""
    def __init__(self, party: dict):
        super().__init__(timeout=60)
        self.party = party
        
        options = []
        for m in party["members"]:
            if m["id"] != party["leader_id"]: # Prevent showing leader themselves from the list
                options.append(discord.SelectOption(label=m["ign"], value=str(m["id"]), description=f"Role: {m['role']}"))
                
        self.add_item(self.KickSelectMenu(options, party))

    class KickSelectMenu(discord.ui.Select):
        def __init__(self, options, party_dict):
            super().__init__(placeholder="Select a member to kick...", options=options)
            self.party_dict = party_dict

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            target_id = int(self.values[0])
            
            # Execute array deletion within DB
            parties_col.update_one({"id": self.party_dict["id"]}, {"$pull": {"members": {"id": target_id}}})
            await interaction.followup.send("❌ Member has been kicked from the party lineup.", ephemeral=True)

            # Strip thread access permissions
            if self.party_dict.get("thread_id"):
                try:
                    thread = interaction.client.get_channel(self.party_dict["thread_id"]) or await interaction.client.fetch_channel(self.party_dict["thread_id"])
                    if thread:
                        target_member = await interaction.guild.fetch_member(target_id)
                        await thread.remove_user(target_member)
                        await thread.send(f"⛔ `{target_member.name}` has been kicked from the party by the Leader.")
                except Exception: pass

            await update_party_broadcasts(interaction.client, self.party_dict["id"])


class ReadyCheckCollectorView(discord.ui.View):
    """Surveying layout sent into DMs for tracking click statuses"""
    def __init__(self, members: list):
        super().__init__(timeout=60)
        self.results = {} # Tracks state as user_id: status mapping
        
    @discord.ui.button(label="READY", style=discord.Style.success)
    async def ready(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.results[interaction.user.id] = "✅ Ready"
        await interaction.response.edit_message(content="Success! Your status is saved as: **Ready**.", view=None)

    @discord.ui.button(label="NOT READY", style=discord.Style.danger)
    async def not_ready(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.results[interaction.user.id] = "❌ Not Ready"
        await interaction.response.edit_message(content="Success! Your status is saved as: **Not Ready**.", view=None)

# ==========================================
# MAIN COG DEFINITION STRUCTURE
# ==========================================
class PartyFinder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="party_lobby", description="Open the main Party Lobby Hub to find or create groups")
    async def party_lobby(self, interaction: discord.Interaction):
        embed, _ = build_lobby_embed(page=1, search_query=None)
        await interaction.response.send_message(embed=embed, view=LobbyView(page=1, search_query=None), ephemeral=True)

    @app_commands.command(name="manage_party", description="Open the control panel for your current active party")
    async def manage_party(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        party = parties_col.find_one({"$or": [{"leader_id": interaction.user.id}, {"members.id": interaction.user.id}]})
        
        if not party:
            await interaction.followup.send("❌ You are not currently in any party room.", ephemeral=True)
            return

        role_title = "👑 PARTY LEADER" if party["leader_id"] == interaction.user.id else "⚔️ PARTY MEMBER"
        embed = discord.Embed(title=f"🛠️ PARTY CONTROL PANEL - {role_title}", color=discord.Color.purple())
        embed.add_field(name="Party Info", value=f"• Dungeon: **{party['dg_name']}**\n• Room ID: `{party['id']}`\n• Start Time: `{party['start_in']}`", inline=False)
        
        member_list = ""
        for i, m in enumerate(party["members"], 1):
            star = "⭐ " if m["id"] == party["leader_id"] else ""
            member_list += f"{i}. {star}{m['ign']} — `{m['role']}`\n"
            
        embed.add_field(name="Current Lineup", value=member_list, inline=False)
        
        await interaction.followup.send(embed=embed, view=ManagePartyView(party["id"], interaction.user.id), ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(PartyFinder(bot))