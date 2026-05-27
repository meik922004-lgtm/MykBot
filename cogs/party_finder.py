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
    return await dungeon_configs_col.find_one({"dg_name": {"$regex": f"^{dg_name}$", "$options": "i"}})

async def update_broadcast_messages(bot, party_id: str):
    party = await parties_col.find_one({"_id": ObjectId(party_id)})
    if not party: return

    embed = create_party_embed(party)
    # Lấy config để xem có cần ping lại khi update không (tùy chọn)
    dg_config = await get_dungeon_config(party.get('dg_name', ''))
    
    for msg_data in party.get("broadcasts", []):
        try:
            channel = bot.get_channel(msg_data["channel_id"])
            if channel:
                msg = await channel.fetch_message(msg_data["message_id"])
                # Khi edit chỉ update embed và giữ nguyên view, không tạo ping mới tránh làm phiền phiền
                await msg.edit(embed=embed)
        except Exception:
            pass 

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


# --- 1. CẢI TIẾN: LOGIC CHECK TỪ KHÓA GEAR (LESS HARDCORE) ---
async def check_gear_requirements(role_name: str, role_gear_data: dict, dg_config: dict) -> tuple[bool, str]:
    """
    Đối chiếu gear/vice/deck của người chơi với các mảng dữ liệu cho phép trong trường 'reqs' của Dungeon.
    """
    if not role_gear_data:
        return False, f"You don't have gear setup for role: {role_name}"

    # Lấy object reqs từ config của dungeon
    reqs = dg_config.get("reqs", {})
    if not reqs:
        return True, "Passed (No explicit item requirements configured for this dungeon)"

    # Trích xuất thông tin hiện tại của người chơi
    p_gear = role_gear_data.get("gear", "").strip()
    p_vice = role_gear_data.get("vice", "").strip()
    p_deck = role_gear_data.get("deck", "").strip()

    # 1. Kiểm tra mảng Gear
    allowed_gears = reqs.get("gear", [])
    if allowed_gears and not any(p_gear.lower() == g.lower() for g in allowed_gears):
        return False, f"Your gear (`{p_gear}`) is not qualified for this dungeon."

    # 2. Kiểm tra mảng Vice
    allowed_vices = reqs.get("vice", [])
    if allowed_vices and not any(p_vice.lower() == v.lower() for v in allowed_vices):
        return False, f"Your vice (`{p_vice}`) is not qualified for this dungeon."

    # 3. Kiểm tra mảng Deck
    allowed_decks = reqs.get("deck", [])
    if allowed_decks and not any(p_deck.lower() == d.lower() for d in allowed_decks):
        return False, f"Your deck (`{p_deck}`) is not qualified for this dungeon."

    return True, "Passed"
# --- 2. CẢI TIẾN: BROADCAST + PING LIÊN SERVER THEO TÊN ROLE ---
async def broadcast_to_all_servers(bot, embed, party_id_str, dg_config: dict, origin_guild: discord.Guild = None):
    broadcasts = []
    view = BroadcastView(party_id=party_id_str)
    
    # Lấy chuỗi ID từ field 'ping_role' trong database của bạn
    ping_role_id_str = dg_config.get("ping_role")
    target_role_name = None

    # Lấy tên của Role từ Server gốc để làm căn cứ tìm kiếm ở các server khác
    if ping_role_id_str and origin_guild:
        origin_role = origin_guild.get_role(int(ping_role_id_str))
        if origin_role:
            target_role_name = origin_role.name

    for guild in bot.guilds:
        # Quét đúng kênh mang tên 'party-finder' ở từng server
        channel = discord.utils.get(guild.text_channels, name="party-finder")
        if channel:
            try:
                content_ping = ""
                if ping_role_id_str:
                    # 1. Thử tìm bằng ID trực tiếp (sẽ trúng nếu đây là server gốc)
                    role = guild.get_role(int(ping_role_id_str))
                    
                    # 2. Nếu không tìm thấy ID (server khác), thử tìm theo Tên Role trùng lặp
                    if not role and target_role_name:
                        role = discord.utils.get(guild.roles, name=target_role_name)
                    
                    if role:
                        content_ping = f"{role.mention}"
                
                # Tiến hành gửi thông báo kèm theo Ping Role tương ứng
                msg = await channel.send(content=content_ping, embed=embed, view=view)
                broadcasts.append({"channel_id": channel.id, "message_id": msg.id})
            except Exception as e:
                print(f"Cannot broadcast to guild {guild.name}: {e}")
                
    return broadcasts
# --- UI VIEWS ---

class BroadcastView(discord.ui.View):
    def __init__(self, party_id=None):
        super().__init__(timeout=None) 
        if party_id:
            btn_join = discord.ui.Button(label="📩 Send Request", style=discord.ButtonStyle.success, custom_id=f"bcast_join_{party_id}")
            self.add_item(btn_join)
            
        btn_lobby = discord.ui.Button(label="🌐 Open Lobby UI", style=discord.ButtonStyle.primary, custom_id="bcast_lobby")
        self.add_item(btn_lobby)


class RequestJoinView(discord.ui.View):
    def __init__(self, bot, party_id, applicant_id, applicant_ign, applicant_role):
        super().__init__(timeout=86400) 
        self.bot = bot
        self.party_id = party_id
        self.applicant_id = applicant_id
        self.applicant_ign = applicant_ign
        self.applicant_role = applicant_role

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="accept_join")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        
        if not party:
            return await interaction.response.send_message("Party no longer exists.", ephemeral=True)
        if len(party.get('members', [])) >= 4:
            return await interaction.response.send_message("Party is already full!", ephemeral=True)
        
        new_member = {
            "user_id": self.applicant_id,
            "ign": self.applicant_ign,
            "role": self.applicant_role
        }

        await parties_col.update_one({"_id": ObjectId(self.party_id)}, {"$push": {"members": new_member}})
        await update_broadcast_messages(self.bot, self.party_id)
        
        for child in self.children: child.disabled = True
        await interaction.message.edit(content="✅ Request accepted.", view=self)
        
        await handle_cross_server_chat(self.bot, party, self.applicant_id, action="add")
        
        applicant = self.bot.get_user(self.applicant_id)
        if applicant: await applicant.send(f"🎉 Leader {party.get('leader_ign')} has **ACCEPTED** your request to join {party.get('dg_name')}!")

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="reject_join")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        for child in self.children: child.disabled = True
        await interaction.message.edit(content="❌ Request rejected.", view=self)
        
        applicant = self.bot.get_user(self.applicant_id)
        if applicant and party: await applicant.send(f"💔 Your request to join {party.get('dg_name')} was rejected.")


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

    @discord.ui.button(label="Kick Member", style=discord.ButtonStyle.danger, row=0)
    async def kick_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.party.get('leader_id'):
            return await interaction.response.send_message("Only the leader can kick members!", ephemeral=True)
            
        kickable_members = [m for m in self.party.get('members', []) if m.get('user_id') != interaction.user.id]
        if not kickable_members:
            return await interaction.response.send_message("No members to kick.", ephemeral=True)
            
        options = [discord.SelectOption(label=m.get('ign', 'Unknown'), description=f"Role: {m.get('role')}", value=str(m.get('user_id'))) for m in kickable_members]
        select = discord.ui.Select(placeholder="Select member to kick...", options=options)
        
        async def kick_callback(inter: discord.Interaction):
            target_id = int(select.values[0])
            await parties_col.update_one({"_id": self.party['_id']}, {"$pull": {"members": {"user_id": target_id}}})
            await handle_cross_server_chat(self.bot, self.party, target_id, action="remove")
            await update_broadcast_messages(self.bot, str(self.party['_id']))
            await inter.response.send_message("Kicked successfully.", ephemeral=True)
            
        select.callback = kick_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message("Who do you want to kick?", view=view, ephemeral=True)

    @discord.ui.button(label="Disband / Leave", style=discord.ButtonStyle.secondary, row=1)
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

    @discord.ui.button(label="Broadcast All Servers", style=discord.ButtonStyle.success, row=1)
    async def broadcast(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.party.get('leader_id'):
            return await interaction.response.send_message("Only the leader can broadcast!", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        embed = create_party_embed(self.party)
        dg_config = await get_dungeon_config(self.party.get('dg_name', '')) or {}
        
        new_broadcasts = await broadcast_to_all_servers(self.bot, embed, str(self.party['_id']), dg_config)
        if new_broadcasts:
            await parties_col.update_one({"_id": self.party['_id']}, {"$push": {"broadcasts": {"$each": new_broadcasts}}})
            await interaction.followup.send("Broadcast sent to all servers!", ephemeral=True)
        else:
            await interaction.followup.send("No 'party-finder' channels found to broadcast.", ephemeral=True)


class LobbyPaginationView(discord.ui.View):
    def __init__(self, bot, parties, page=0):
        super().__init__(timeout=None)
        self.bot = bot
        self.parties = parties
        self.page = page
        self.items_per_page = 5
        self.max_pages = max(1, (len(parties) - 1) // self.items_per_page + 1)
        
        current_parties = self.parties[self.page * self.items_per_page : (self.page + 1) * self.items_per_page]
        if current_parties:
            options = [discord.SelectOption(
                label=f"{p.get('dg_name', 'Unknown')} (Ldr: {p.get('leader_ign', 'Unknown')})", 
                description=f"{len(p.get('members', []))}/4 - {p.get('start_time', 'N/A')}", 
                value=str(p['_id'])
            ) for p in current_parties]
            
            self.select = discord.ui.Select(placeholder="Select a party to join...", options=options, row=0)
            self.select.callback = self.send_request_callback
            self.add_item(self.select)

    async def send_request_callback(self, interaction: discord.Interaction):
        party_id = self.select.values[0]
        profile = await get_player_profile(interaction.user.id)
        if not profile:
            return await interaction.response.send_message("⚠️ Please set up `/mygear` first!", ephemeral=True)
        
        existing_party = await parties_col.find_one({"members.user_id": interaction.user.id})
        if existing_party:
            return await interaction.response.send_message("❌ You are already in a party!", ephemeral=True)
            
        await interaction.response.send_modal(JoinPartyModal(self.bot, party_id, profile.get('ign', 'Unknown')))

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0: await self.update_lobby(interaction, self.page - 1)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.blurple, row=1)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_lobby(interaction, self.page)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.max_pages - 1: await self.update_lobby(interaction, self.page + 1)

    @discord.ui.button(label="➕ Create Party", style=discord.ButtonStyle.success, row=2)
    async def create_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        profile = await get_player_profile(interaction.user.id)
        if not profile:
            return await interaction.response.send_message("⚠️ Please set up `/mygear` first!", ephemeral=True)
        if await parties_col.find_one({"members.user_id": interaction.user.id}):
            return await interaction.response.send_message("❌ You are already in a party!", ephemeral=True)
            
        await interaction.response.send_modal(CreatePartyModal(self.bot, profile.get('ign', 'Unknown')))

    @discord.ui.button(label="⚙️ Manage My Party", style=discord.ButtonStyle.primary, row=2)
    async def manage_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"members.user_id": interaction.user.id})
        if not party:
            return await interaction.response.send_message("You are not currently in a party.", ephemeral=True)
        
        embed = create_party_embed(party)
        await interaction.response.send_message(embed=embed, view=ManagePartyView(self.bot, party), ephemeral=True)

    async def update_lobby(self, interaction: discord.Interaction, new_page: int):
        fresh_parties = await parties_col.find({}).to_list(length=100)
        view = LobbyPaginationView(self.bot, fresh_parties, new_page)
        
        embed = discord.Embed(title="🌐 Party Finder Lobby", description=f"Page {new_page+1}/{view.max_pages}", color=discord.Color.purple())
        for p in fresh_parties[new_page * view.items_per_page : (new_page + 1) * view.items_per_page]:
            embed.add_field(name=f"🎮 {p.get('dg_name', 'Unknown')} | Start: {p.get('start_time', 'N/A')}", 
                            value=f"Leader: **{p.get('leader_ign', 'Unknown')}** | Members: {len(p.get('members', []))}/4", inline=False)
            
        if not fresh_parties: embed.description = "No active parties found."
        await interaction.response.edit_message(embed=embed, view=view)


# --- MODALS ---

class JoinPartyModal(discord.ui.Modal, title='Role Selection'):
    ign = discord.ui.TextInput(label='In-game Name', required=True)
    role = discord.ui.TextInput(label='Your Role (e.g., DPS, TANK, UFM)', placeholder='Type your role exactly...', required=True)

    def __init__(self, bot, party_id, current_ign):
        super().__init__()
        self.bot = bot
        self.party_id = party_id
        self.ign.default = current_ign

    async def on_submit(self, interaction: discord.Interaction):
        party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        profile = await get_player_profile(interaction.user.id)
        
        if not party or not profile:
            return await interaction.response.send_message("Party or Profile not found.", ephemeral=True)

        role_entered = self.role.value.strip()
        stats = profile.get("my_stats", {})
        
        role_gear_data = None
        for key, data in stats.items():
            if key.lower() == role_entered.lower():
                role_gear_data = data
                break

        if not role_gear_data:
            return await interaction.response.send_message(f"❌ Could not find gear data for Role: **{role_entered}** in your `/mygear` profile.", ephemeral=True)

        # Kiểm tra điều kiện chứa Từ Khóa
        dg_config = await get_dungeon_config(party.get('dg_name'))
        if dg_config:
            is_valid, reason = await check_gear_requirements(role_entered, role_gear_data, dg_config)
            if not is_valid:
                return await interaction.response.send_message(f"⛔ **Requirements not met:** {reason}", ephemeral=True)

        leader = self.bot.get_user(party.get('leader_id', 0))
        if leader:
            embed = discord.Embed(title="📩 Join Request Received!", color=discord.Color.green())
            embed.add_field(name="Applicant", value=self.ign.value, inline=True)
            embed.add_field(name="Discord", value=interaction.user.mention, inline=True)
            embed.add_field(name="Role Selected", value=role_entered, inline=True)
            embed.add_field(name="Extracted Gear Profile", 
                            value=f"**Gear:** {role_gear_data.get('gear', 'N/A')}\n**Vice:** {role_gear_data.get('vice', 'N/A')}\n**Deck:** {role_gear_data.get('deck', 'N/A')}", 
                            inline=False)
            
            try:
                await leader.send(embed=embed, view=RequestJoinView(self.bot, self.party_id, interaction.user.id, self.ign.value, role_entered))
                await interaction.response.send_message("✅ Request sent to the leader with your verified gear!", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("❌ Cannot DM the leader (DM blocked).", ephemeral=True)


class CreatePartyModal(discord.ui.Modal, title='Create New Party'):
    dg_name = discord.ui.TextInput(label='Dungeon Name', placeholder='E.g., Stage of Clown(PIED)', required=True)
    role = discord.ui.TextInput(label='Your Role as Leader (e.g., DPS, TANK)', required=True)
    start_time = discord.ui.TextInput(label='Expected Start Time', placeholder='E.g., 20:00 or ASAP', required=True)
    requirements = discord.ui.TextInput(label='Requirements', style=discord.TextStyle.paragraph, required=False)

    def __init__(self, bot, ign):
        super().__init__()
        self.bot = bot
        self.ign = ign

    async def on_submit(self, interaction: discord.Interaction):
        profile = await get_player_profile(interaction.user.id)
        role_entered = self.role.value.strip()
        
        role_gear_data = None
        for k, v in profile.get("my_stats", {}).items():
            if k.lower() == role_entered.lower(): role_gear_data = v; break

        if not role_gear_data:
            return await interaction.response.send_message(f"❌ You do not have gear setup for **{role_entered}**.", ephemeral=True)

        dg_config = await get_dungeon_config(self.dg_name.value)
        if not dg_config:
            # Tạo mới bản ghi nếu chưa có
            dg_config = {
                "dg_name": self.dg_name.value,
                "ping_role_name": self.dg_name.value,  # Đặt mặc định tên Role cần ping trùng tên Dungeon
                "req_keywords": [self.dg_name.value],  # Mặc định yêu cầu từ khóa trùng tên Dungeon
                "description": "Automatically created config data."
            }
            await dungeon_configs_col.insert_one(dg_config)
            
        is_valid, reason = await check_gear_requirements(role_entered, role_gear_data, dg_config)
        if not is_valid:
            return await interaction.response.send_message(f"⛔ **You don't meet requirements to create this party:** {reason}", ephemeral=True)

        party_doc = {
            "leader_id": interaction.user.id,
            "leader_ign": self.ign,
            "dg_name": self.dg_name.value,
            "start_time": self.start_time.value,
            "requirements": self.requirements.value,
            "members": [{"user_id": interaction.user.id, "ign": self.ign, "role": role_entered}],
            "broadcasts": [],
            "chat_channel_id": None
        }
        
        result = await parties_col.insert_one(party_doc)
        party_doc["_id"] = result.inserted_id

        await handle_cross_server_chat(self.bot, party_doc, action="create", guild=interaction.guild)

        # Broadcast Liên Server kèm theo Ping tự động quét theo Role Name
        embed = create_party_embed(party_doc)
        broadcast_records = await broadcast_to_all_servers(self.bot, embed, str(result.inserted_id), dg_config, interaction.guild)
        
        if broadcast_records:
            await parties_col.update_one({"_id": result.inserted_id}, {"$set": {"broadcasts": broadcast_records}})
            
        await interaction.response.send_message(f"Party created & Broadcasted with ping successfully!", ephemeral=True)

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
            if channel: await channel.delete()
    except Exception as e: print(f"Chat error: {e}")

# --- COG SETUP ---

class PartyFinderCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if not interaction.data: return
        custom_id = interaction.data.get("custom_id", "")
        
        if custom_id.startswith("bcast_join_"):
            party_id_str = custom_id.replace("bcast_join_", "")
            profile = await get_player_profile(interaction.user.id)
            
            if not profile:
                return await interaction.response.send_message("⚠️ Please set up `/mygear` first!", ephemeral=True)
                
            existing_party = await parties_col.find_one({"members.user_id": interaction.user.id})
            if existing_party:
                return await interaction.response.send_message("❌ You are already in a party!", ephemeral=True)
                
            await interaction.response.send_modal(JoinPartyModal(self.bot, party_id_str, profile.get('ign', 'Unknown')))
            
        elif custom_id == "bcast_lobby":
            await interaction.response.defer(ephemeral=True)
            parties = await parties_col.find({}).to_list(length=100)
            view = LobbyPaginationView(self.bot, parties, page=0)
            
            embed = discord.Embed(title="🌐 Party Finder Lobby", description=f"Page 1/{view.max_pages}", color=discord.Color.purple())
            for p in parties[:5]:
                embed.add_field(name=f"🎮 {p.get('dg_name', 'Unknown')} | Start: {p.get('start_time', 'N/A')}", 
                                value=f"Leader: **{p.get('leader_ign', 'Unknown')}** | Members: {len(p.get('members', []))}/4", inline=False)
            if not parties: embed.description = "No active parties found."
            
            await interaction.followup.send(embed=embed, view=view)


    @app_commands.command(name="party_lobby", description="Open the Party Finder Lobby UI")
    async def party_lobby(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        parties = await parties_col.find({}).to_list(length=100)
        
        embed = discord.Embed(title="🌐 Party Finder Lobby", description="Loading...", color=discord.Color.purple())
        view = LobbyPaginationView(self.bot, parties, page=0)
        
        if not parties:
            embed.description = "No active parties found."
        else:
            embed.description = f"Page 1/{view.max_pages}"
            for p in parties[:5]:
                embed.add_field(name=f"🎮 {p.get('dg_name', 'Unknown')} | Start: {p.get('start_time', 'N/A')}", 
                                value=f"Leader: **{p.get('leader_ign', 'Unknown')}** | Members: {len(p.get('members', []))}/4", inline=False)

        await interaction.followup.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(PartyFinderCog(bot))