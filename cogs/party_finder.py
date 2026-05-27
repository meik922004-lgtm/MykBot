import discord
from discord.ext import commands
from discord import app_commands
from bson.objectid import ObjectId
from typing import List, Optional

# Import direct collections from your Database.py
from Database import players_col, parties_col, dungeon_configs_col

# --- DATABASE HELPER FUNCTIONS ---

async def get_player_profile(user_id: int):
    return await players_col.find_one({"user_id": user_id})

async def get_dungeon_config(dg_name: str):
    # Case-insensitive search
    return await dungeon_configs_col.find_one({"dg_name": {"$regex": f"^{dg_name}$", "$options": "i"}})

async def update_broadcast_messages(bot, party_id: str):
    party = await parties_col.find_one({"_id": ObjectId(party_id)})
    if not party: return

    embed = create_party_embed(party)
    for msg_data in party.get("broadcasts", []):
        try:
            channel = bot.get_channel(msg_data["channel_id"])
            if channel:
                msg = await channel.fetch_message(msg_data["message_id"])
                await msg.edit(embed=embed)
        except Exception:
            pass # Ignore if message was deleted

def create_party_embed(party: dict) -> discord.Embed:
    embed = discord.Embed(title=f"⚔️ Party: {party.get('dg_name', 'Unknown DG')}", color=discord.Color.blue())
    embed.add_field(name="👑 Leader", value=party.get('leader_ign', 'Unknown'), inline=True)
    embed.add_field(name="⏰ Start Time", value=party.get('start_time', 'N/A'), inline=True)
    embed.add_field(name="📋 Requirements", value=party.get('requirements') or "None", inline=False)
    
    members_text = ""
    for idx, member in enumerate(party.get('members', [])):
        members_text += f"{idx+1}. **{member.get('ign', 'Unknown')}** (Role: {member.get('role', 'Unknown')})\n"
    
    embed.add_field(name=f"👥 Members ({len(party.get('members', []))}/4)", value=members_text or "Empty", inline=False)
    return embed

# --- UI VIEWS ---

class RequestJoinView(discord.ui.View):
    def __init__(self, bot, party_id, applicant_id):
        super().__init__(timeout=86400) # 24-hour timeout
        self.bot = bot
        self.party_id = party_id
        self.applicant_id = applicant_id

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="accept_join")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        applicant_profile = await get_player_profile(self.applicant_id)
        
        if not party or not applicant_profile:
            return await interaction.response.send_message("Party or player no longer exists.", ephemeral=True)
        
        if len(party.get('members', [])) >= 4:
            return await interaction.response.send_message("Party is already full!", ephemeral=True)

        stats = applicant_profile.get("my_stats", {})
        main_role = stats.get("role", "Unknown") 
        
        new_member = {
            "user_id": self.applicant_id,
            "ign": applicant_profile.get("ign", "Unknown"),
            "role": main_role
        }

        await parties_col.update_one({"_id": ObjectId(self.party_id)}, {"$push": {"members": new_member}})
        await update_broadcast_messages(self.bot, self.party_id)
        
        for child in self.children: child.disabled = True
        await interaction.message.edit(content="✅ Request accepted.", view=self)
        
        await handle_cross_server_chat(self.bot, party, self.applicant_id, action="add")
        
        applicant = self.bot.get_user(self.applicant_id)
        if applicant: await applicant.send(f"🎉 Leader {party.get('leader_ign', 'Unknown')} has **ACCEPTED** your request to join {party.get('dg_name', 'Unknown DG')}!")

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="reject_join")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        for child in self.children: child.disabled = True
        await interaction.message.edit(content="❌ Request rejected.", view=self)
        
        applicant = self.bot.get_user(self.applicant_id)
        if applicant and party: await applicant.send(f"💔 Your request to join {party.get('dg_name', 'Unknown DG')} was rejected.")


class ManagePartyView(discord.ui.View):
    def __init__(self, bot, party):
        super().__init__(timeout=None)
        self.bot = bot
        self.party = party

    @discord.ui.button(label="Edit Requirements", style=discord.ButtonStyle.primary, row=0)
    async def edit_reqs(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.party.get('leader_id'):
            return await interaction.response.send_message("Only the leader can edit this!", ephemeral=True)
        await interaction.response.send_modal(EditReqModal(self.bot, self.party['_id']))

    @discord.ui.button(label="View Gear", style=discord.ButtonStyle.secondary, row=0)
    async def view_gear(self, interaction: discord.Interaction, button: discord.ui.Button):
        options = [discord.SelectOption(label=m.get('ign', 'Unknown'), value=str(m.get('user_id'))) for m in self.party.get('members', [])]
        select = discord.ui.Select(placeholder="Select member to view gear...", options=options)
        
        async def select_callback(inter: discord.Interaction):
            profile = await get_player_profile(int(select.values[0]))
            stats = profile.get("my_stats", {})
            embed = discord.Embed(title=f"Gear Profile: {profile.get('ign')}", color=discord.Color.gold())
            
            for role, data in stats.items():
                if isinstance(data, dict) and "gear" in data:
                    embed.add_field(name=f"Role: {role}", value=f"**Gear:** {data.get('gear')}\n**Vice:** {data.get('vice')}\n**Deck:** {data.get('deck')}", inline=False)
            await inter.response.send_message(embed=embed, ephemeral=True)
            
        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message("Select a member:", view=view, ephemeral=True)

    @discord.ui.button(label="Disband / Leave", style=discord.ButtonStyle.danger, row=0)
    async def disband_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.party.get('leader_id'):
            await parties_col.delete_one({"_id": self.party['_id']})
            await handle_cross_server_chat(self.bot, self.party, action="delete")
            
            embed = discord.Embed(title="❌ Party Disbanded", color=discord.Color.red())
            for msg_data in self.party.get("broadcasts", []):
                channel = self.bot.get_channel(msg_data["channel_id"])
                if channel:
                    try:
                        msg = await channel.fetch_message(msg_data["message_id"])
                        await msg.edit(embed=embed, view=None)
                    except: pass
            await interaction.response.send_message("Party has been disbanded!", ephemeral=True)
        else:
            await parties_col.update_one({"_id": self.party['_id']}, {"$pull": {"members": {"user_id": interaction.user.id}}})
            await update_broadcast_messages(self.bot, self.party['_id'])
            await handle_cross_server_chat(self.bot, self.party, interaction.user.id, action="remove")
            await interaction.response.send_message("You have left the party.", ephemeral=True)

    @discord.ui.button(label="Broadcast Again", style=discord.ButtonStyle.success, row=1)
    async def broadcast(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.party.get('leader_id'):
            return await interaction.response.send_message("Only the leader can broadcast!", ephemeral=True)
        
        dg_config = await get_dungeon_config(self.party.get('dg_name', ''))
        ping_text = f"<@&{dg_config['ping_role']}>" if dg_config and dg_config.get('ping_role') else ""
        
        embed = create_party_embed(self.party)
        msg = await interaction.channel.send(content=f"📢 Recruiting for **{self.party.get('dg_name', 'Unknown DG')}**! {ping_text}", embed=embed)
        
        await parties_col.update_one({"_id": self.party['_id']}, {"$push": {"broadcasts": {"channel_id": interaction.channel.id, "message_id": msg.id}}})
        await interaction.response.send_message("Broadcast updated!", ephemeral=True)


class LobbyPaginationView(discord.ui.View):
    def __init__(self, bot, parties, page=0, search_term=None):
        super().__init__(timeout=None)
        self.bot = bot
        self.parties = parties
        self.page = page
        self.search_term = search_term
        self.items_per_page = 5
        self.max_pages = max(1, (len(parties) - 1) // self.items_per_page + 1)
        
        current_parties = self.parties[self.page * self.items_per_page : (self.page + 1) * self.items_per_page]
        if current_parties:
            # Sửa lỗi KeyError bằng cách sử dụng .get() phòng khi tài liệu khuyết field
            options = [discord.SelectOption(
                label=f"{p.get('dg_name', 'Unknown DG')} (Ldr: {p.get('leader_ign', 'Unknown')})", 
                description=f"{len(p.get('members', []))}/4 - {p.get('start_time', 'N/A')}", 
                value=str(p['_id'])
            ) for p in current_parties]
            
            self.select = discord.ui.Select(placeholder="Select a party to join...", options=options, row=0)
            self.select.callback = self.send_request_callback
            self.add_item(self.select)

    async def send_request_callback(self, interaction: discord.Interaction):
        party_id = self.select.values[0]
        applicant = await get_player_profile(interaction.user.id)
        if not applicant:
            return await interaction.response.send_message("⚠️ Please set up your gear profile with `/mygear` first!", ephemeral=True)
        
        party = await parties_col.find_one({"_id": ObjectId(party_id)})
        
        existing_party = await parties_col.find_one({"members.user_id": interaction.user.id})
        if existing_party:
            return await interaction.response.send_message("❌ You are already in a party!", ephemeral=True)

        leader = self.bot.get_user(party.get('leader_id', 0))
        if leader:
            stats = applicant.get("my_stats", {})
            embed = discord.Embed(title="📩 Join Request Received!", color=discord.Color.green())
            embed.add_field(name="Applicant", value=applicant.get('ign'), inline=True)
            embed.add_field(name="Discord", value=interaction.user.mention, inline=True)
            main_role = stats.get('role', 'Unknown')
            embed.add_field(name="Registered Role", value=main_role, inline=True)
            
            role_data = stats.get(main_role, {}) if isinstance(stats, dict) else {}
            if isinstance(role_data, dict):
                embed.add_field(name="Gear Overview", value=f"Gear: {role_data.get('gear')}\nVice: {role_data.get('vice')}", inline=False)
            
            try:
                await leader.send(embed=embed, view=RequestJoinView(self.bot, party_id, interaction.user.id))
                await interaction.response.send_message("✅ Request sent to the leader!", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("❌ Cannot DM the leader (DM blocked).", ephemeral=True)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            await self.update_lobby(interaction, self.page - 1)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.blurple, row=1)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_lobby(interaction, self.page)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.max_pages - 1:
            await self.update_lobby(interaction, self.page + 1)

    @discord.ui.button(label="🔍 Search DG", style=discord.ButtonStyle.secondary, row=2)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchPartyModal(self.bot))

    @discord.ui.button(label="➕ Create Party", style=discord.ButtonStyle.success, row=2)
    async def create_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        profile = await get_player_profile(interaction.user.id)
        if not profile:
            return await interaction.response.send_message("⚠️ Please set up `/mygear` first!", ephemeral=True)
        if await parties_col.find_one({"members.user_id": interaction.user.id}):
            return await interaction.response.send_message("❌ You are already in a party!", ephemeral=True)
            
        await interaction.response.send_modal(CreatePartyModal(self.bot, profile['ign']))

    @discord.ui.button(label="⚙️ Manage My Party", style=discord.ButtonStyle.primary, row=2)
    async def manage_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"members.user_id": interaction.user.id})
        if not party:
            return await interaction.response.send_message("You are not currently in a party.", ephemeral=True)
        
        embed = create_party_embed(party)
        await interaction.response.send_message(embed=embed, view=ManagePartyView(self.bot, party), ephemeral=True)

    async def update_lobby(self, interaction: discord.Interaction, new_page: int):
        query = {}
        if self.search_term:
            query = {"dg_name": {"$regex": self.search_term, "$options": "i"}}
        fresh_parties = await parties_col.find(query).to_list(length=100)
        
        view = LobbyPaginationView(self.bot, fresh_parties, new_page, self.search_term)
        
        embed = discord.Embed(title="🌐 Party Finder Lobby", description=f"Page {new_page+1}/{view.max_pages}", color=discord.Color.purple())
        for p in fresh_parties[new_page * view.items_per_page : (new_page + 1) * view.items_per_page]:
            embed.add_field(name=f"🎮 {p.get('dg_name', 'Unknown DG')} | Start: {p.get('start_time', 'N/A')}", 
                            value=f"Leader: **{p.get('leader_ign', 'Unknown')}** | Members: {len(p.get('members', []))}/4", inline=False)
            
        if not fresh_parties: embed.description = "No active parties found."

        await interaction.response.edit_message(embed=embed, view=view)

# --- MODALS ---

class SearchPartyModal(discord.ui.Modal, title='Search Parties'):
    search_query = discord.ui.TextInput(label='Dungeon Name', placeholder='Enter at least 3 characters...', min_length=3)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        term = self.search_query.value.lower().replace("dungeon", "").strip()
        parties = await parties_col.find({"dg_name": {"$regex": term, "$options": "i"}}).to_list(length=100)
        
        view = LobbyPaginationView(self.bot, parties, search_term=term)
        embed = discord.Embed(title=f"🔍 Search results for: '{term}'", color=discord.Color.purple())
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class CreatePartyModal(discord.ui.Modal, title='Create New Party'):
    dg_name = discord.ui.TextInput(label='Dungeon Name', placeholder='E.g., Stage of Clown(PIED)', required=True)
    start_time = discord.ui.TextInput(label='Expected Start Time', placeholder='E.g., 20:00 or ASAP', required=True)
    requirements = discord.ui.TextInput(label='Requirements', style=discord.TextStyle.paragraph, required=False)

    def __init__(self, bot, ign):
        super().__init__()
        self.bot = bot
        self.ign = ign

    async def on_submit(self, interaction: discord.Interaction):
        party_doc = {
            "leader_id": interaction.user.id,
            "leader_ign": self.ign,
            "dg_name": self.dg_name.value,
            "start_time": self.start_time.value,
            "requirements": self.requirements.value,
            "members": [{"user_id": interaction.user.id, "ign": self.ign, "role": "Leader"}],
            "broadcasts": [],
            "chat_channel_id": None
        }
        
        result = await parties_col.insert_one(party_doc)
        party_doc["_id"] = result.inserted_id

        await handle_cross_server_chat(self.bot, party_doc, action="create", guild=interaction.guild)

        # KIỂM TRA FIELD DATA DUNGEON: Nếu chưa có thì khởi tạo 1 data mới vào DB
        dg_config = await get_dungeon_config(self.dg_name.value)
        if not dg_config:
            dg_config = {
                "dg_name": self.dg_name.value,
                "ping_role": None, # Chưa có role thì để None để admin setup sau
                "description": "Automatically created config data."
            }
            await dungeon_configs_col.insert_one(dg_config)

        ping_text = f"<@&{dg_config.get('ping_role')}>" if dg_config.get('ping_role') else ""
        
        embed = create_party_embed(party_doc)
        msg = await interaction.channel.send(content=f"📢 **{self.ign}** is looking for a group for **{self.dg_name.value}**! {ping_text}", embed=embed)
        
        await parties_col.update_one({"_id": result.inserted_id}, {"$push": {"broadcasts": {"channel_id": interaction.channel.id, "message_id": msg.id}}})
        await interaction.response.send_message(f"Party created successfully!", ephemeral=True)

class EditReqModal(discord.ui.Modal, title='Edit Party Requirements'):
    requirements = discord.ui.TextInput(label='New Requirements', style=discord.TextStyle.paragraph)

    def __init__(self, bot, party_id):
        super().__init__()
        self.bot = bot
        self.party_id = party_id

    async def on_submit(self, interaction: discord.Interaction):
        await parties_col.update_one({"_id": self.party_id}, {"$set": {"requirements": self.requirements.value}})
        await update_broadcast_messages(self.bot, self.party_id)
        await interaction.response.send_message("Requirements updated!", ephemeral=True)

# --- CHAT SYSTEM ---

async def handle_cross_server_chat(bot, party, user_id=None, action="create", guild=None):
    try:
        if action == "create" and guild:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            leader = guild.get_member(party.get('leader_id', 0))
            if leader: overwrites[leader] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            chat_channel = await guild.create_text_channel(name=f"party-{party.get('leader_ign', 'unknown')}", overwrites=overwrites)
            
            await parties_col.update_one({"_id": party['_id']}, {"$set": {"chat_channel_id": chat_channel.id}})
            webhook = await chat_channel.create_webhook(name="CrossServerRelay")
            await parties_col.update_one({"_id": party['_id']}, {"$set": {"webhook_url": webhook.url}})

        elif action == "add" and user_id:
            channel = bot.get_channel(party.get("chat_channel_id"))
            if channel:
                member = channel.guild.get_member(user_id)
                if member:
                    await channel.set_permissions(member, read_messages=True, send_messages=True)
                    await channel.send(f"👋 {member.mention} has joined the party!")

        elif action == "remove" and user_id:
            channel = bot.get_channel(party.get("chat_channel_id"))
            if channel:
                member = channel.guild.get_member(user_id)
                if member:
                    await channel.set_permissions(member, overwrite=None)
                    await channel.send(f"🚪 A member has left/been kicked from the party.")

        elif action == "delete":
            channel = bot.get_channel(party.get("chat_channel_id"))
            if channel:
                await channel.delete()
    except Exception as e:
        print(f"Chat system error: {e}")

# --- COG SETUP ---

class PartyFinderCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="party_lobby", description="Open the Party Finder Lobby UI")
    async def party_lobby(self, interaction: discord.Interaction):
        # Bảo vệ phản hồi bằng defer đề phòng hệ thống Render xử lý DB chậm quá 3 giây
        await interaction.response.defer(ephemeral=True)
        
        parties = await parties_col.find({}).to_list(length=100)
        
        embed = discord.Embed(title="🌐 Party Finder Lobby", description="Loading data...", color=discord.Color.purple())
        view = LobbyPaginationView(self.bot, parties, page=0)
        
        if not parties:
            embed.description = "No active parties found."
        else:
            embed.description = f"Page 1/{view.max_pages}"
            for p in parties[:5]:
                embed.add_field(name=f"🎮 {p.get('dg_name', 'Unknown DG')} | Start: {p.get('start_time', 'N/A')}", 
                                value=f"Leader: **{p.get('leader_ign', 'Unknown')}** | Members: {len(p.get('members', []))}/4", inline=False)

        # Sử dụng followup.send vì chúng ta đã dùng defer ở trên
        await interaction.followup.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(PartyFinderCog(bot))