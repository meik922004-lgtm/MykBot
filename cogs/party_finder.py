import discord
from discord.ext import commands
from discord import app_commands
from bson.objectid import ObjectId
from typing import List, Optional
import asyncio

# Import direct collections from your Database.py
from Database import players_col, parties_col, dungeon_configs_col

# --- DATABASE HELPER FUNCTIONS ---

async def get_player_profile(user_id: int):
    return await players_col.find_one({"user_id": user_id})

async def get_dungeon_config(dg_name: str):
    return await dungeon_configs_col.find_one({"dg_name": {"$regex": f"^{dg_name}$", "$options": "i"}})


async def _do_single_edit(channel, message_id, embed):
    try:
        msg = await channel.fetch_message(message_id)
        await msg.edit(embed=embed)
    except Exception:
        pass 

async def update_broadcast_messages(bot, party_id: str):
    party = await parties_col.find_one({"_id": ObjectId(party_id)})
    if not party: 
        return

    embed = create_party_embed(party)
    dg_config = await get_dungeon_config(party.get('dg_name', ''))
    
    tasks = []
    for msg_data in party.get("broadcasts", []):
        channel = bot.get_channel(msg_data["channel_id"])
        if channel:
            tasks.append(_do_single_edit(channel, msg_data["message_id"], embed))
            
    if tasks:
        await asyncio.gather(*tasks)

def create_party_embed(party: dict) -> discord.Embed:
    embed = discord.Embed(title=f"⚔️ Party: {party.get('dg_name', 'Unknown DG')}", color=discord.Color.blue())
    embed.add_field(name="👑 Leader", value=party.get('leader_ign', 'Unknown'), inline=True)
    embed.add_field(name="⏰ Start Time", value=party.get('start_time', 'N/A'), inline=True)
    embed.add_field(name="📋 Requirements", value=party.get('requirements') or "None", inline=False)
    
    members_text = ""
    for idx, member in enumerate(party.get('members', [])):
        raw_role = member.get('role', 'Unknown')
        clean_role = raw_role.split('(')[0].strip().upper() 
        members_text += f"{idx+1}. **{member.get('ign', 'Unknown')}** (Role: {clean_role})\n"
        
    embed.add_field(name=f"👥 Members ({len(party.get('members', []))}/4)", value=members_text or "Empty", inline=False)
    return embed

async def check_gear_requirements(role_name: str, role_gear_data: dict, dg_config: dict) -> tuple[bool, str]:
    """
    Đối chiếu gear/vice/deck của người chơi với các mảng dữ liệu cho phép trong trường 'reqs' của Dungeon.
    """
    if not role_gear_data:
        return False, f"You don't have gear setup for role: {role_name}"

    reqs = dg_config.get("reqs", {})
    if not reqs:
        return True, "Passed (No explicit item requirements configured for this dungeon)"

    p_gear = role_gear_data.get("gear", "").strip()
    p_vice = role_gear_data.get("vice", "").strip()
    p_deck = role_gear_data.get("deck", "").strip()

    allowed_gears = reqs.get("gear", [])
    if allowed_gears and not any(p_gear.lower() == g.lower() for g in allowed_gears):
        return False, f"Your gear (`{p_gear}`) is not qualified for this dungeon."

    allowed_vices = reqs.get("vice", [])
    if allowed_vices and not any(p_vice.lower() == v.lower() for v in allowed_vices):
        return False, f"Your vice (`{p_vice}`) is not qualified for this dungeon."

    allowed_decks = reqs.get("deck", [])
    if allowed_decks and not any(p_deck.lower() == d.lower() for d in allowed_decks):
        return False, f"Your deck (`{p_deck}`) is not qualified for this dungeon."

    return True, "Passed"

def find_flexible_role(guild, dg_name):
    keywords = dg_name.lower().split() 
    for role in guild.roles:
        role_name_lower = role.name.lower()
        if any(keyword in role_name_lower for keyword in keywords):
            return role.mention
    return None 

async def broadcast_to_all_servers(bot, embed, party_id_str, dg_config: dict, origin_guild: discord.Guild = None):
    broadcasts = []
    view = BroadcastView(party_id=party_id_str)
    dg_name = dg_config.get("dg_name", "")

    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name="party-board")
        if channel:
            try:
                content_ping = ""
                if dg_name:
                    keywords = dg_name.lower().split()
                    keywords = [k for k in keywords if len(k) > 2]
                    
                    for role in guild.roles:
                        role_name_lower = role.name.lower()
                        if any(keyword in role_name_lower for keyword in keywords):
                            content_ping = role.mention
                            break 
                
                msg = await channel.send(content=content_ping, embed=embed, view=view)
                broadcasts.append({"channel_id": channel.id, "message_id": msg.id})
                
            except Exception as e:
                print(f"Cannot broadcast to guild {guild.name}: {e}")
                
    return broadcasts

# --- UI VIEWS ---

async def get_formatted_gear_summary(stats, role_entered):
    DPS_GROUPS = ["dps", "ufm", "fm", "future", "ulforce", "future mode", "dps aa", "dps sk", "dpsaa", "dpssk", "aoe", "dps aoe", "dpsaoe"]
    clean_role = role_entered.lower().replace("(", "").replace(")", "").strip()
    is_dps = clean_role in DPS_GROUPS
    
    gear_details = []
    if is_dps:
        for r_key in ["AA", "SK"]:
            data = stats.get(r_key)
            if isinstance(data, dict):
                gear_details.append(
                    f"**{r_key}**: Gear: {data.get('gear', 'N/A')} | Vice: {data.get('vice', 'N/A')} | Deck: {data.get('deck', 'N/A')}"
                )
    else:
        role_key = role_entered.split('(')[0].strip().upper()
        data = stats.get(role_key)
        if isinstance(data, dict):
            gear_details.append(f"**{role_key}**: Gear: {data.get('gear', 'N/A')} | Vice: {data.get('vice', 'N/A')} | Deck: {data.get('deck', 'N/A')}")
            
    return "\n".join(gear_details) if gear_details else "No gear data found."

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
        
        applicant = self.bot.get_user(self.applicant_id) or await self.bot.fetch_user(self.applicant_id)
        if applicant: 
            await applicant.send(f"🎉 Leader {party.get('leader_ign')} has **ACCEPTED** your request to join {party.get('dg_name')}!")

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="reject_join")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        for child in self.children: child.disabled = True
        await interaction.message.edit(content="❌ Request rejected.", view=self)
        
        applicant = self.bot.get_user(self.applicant_id) or await self.bot.fetch_user(self.applicant_id)
        if applicant and party: 
            await applicant.send(f"💔 Your request to join {party.get('dg_name')} was rejected.")


class ManagePartyView(discord.ui.View):
    def __init__(self, bot, party):
        super().__init__(timeout=None)
        self.bot = bot
        self.party = party
        
    @discord.ui.button(label="View Party Profiles", style=discord.ButtonStyle.primary, row=2)
    async def view_profiles(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        party_data = await parties_col.find_one({"_id": self.party['_id']})
        members = party_data.get("members", [])
        
        embed = discord.Embed(title=f"📋 Party Profiles - {self.party.get('dg_name')}", color=discord.Color.blue())
        
        for m in members:
            profile = await get_player_profile(m['user_id'])
            stats = profile.get("my_stats", {}) if profile else {}
            gear_info = await get_formatted_gear_summary(stats, m['role'])
            clean_role = m['role'].split('(')[0].strip()
            
            embed.add_field(
                name=f"{m['ign']} ({clean_role})",
                value=gear_info,
                inline=False
            )
            
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Edit Dungeon Name", style=discord.ButtonStyle.secondary)
    async def edit_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditDungeonModal(self.party, interaction.client))

    @discord.ui.button(label="Edit Requirements", style=discord.ButtonStyle.secondary)
    async def edit_reqs(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditReqModal(self.party, interaction.client))

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
            await inter.response.defer(ephemeral=True)
            target_id = int(select.values[0])
            
            await parties_col.update_one({"_id": self.party['_id']}, {"$pull": {"members": {"user_id": target_id}}})
            await handle_cross_server_chat(self.bot, self.party, target_id, action="remove")
            await update_broadcast_messages(self.bot, str(self.party['_id']))
            
            # GIẢI PHÁP SỬA LỖI 1: Fetch user toàn server để gửi DM thông báo kick
            user = self.bot.get_user(target_id)
            if not user:
                try:
                    user = await self.bot.fetch_user(target_id)
                except Exception:
                    user = None

            if user:
                try:
                    embed = discord.Embed(
                        title="⛔ You have been kicked",
                        description=f"You have been removed from the party for **{self.party.get('dg_name', 'this dungeon')}**.",
                        color=discord.Color.red()
                    )
                    await user.send(embed=embed)
                except discord.Forbidden:
                    pass 

            await inter.followup.send(f"✅ Successfully kicked {user.name if user else 'user'} and notified them.", ephemeral=True)

        select.callback = kick_callback

    @discord.ui.button(label="Disband / Leave", style=discord.ButtonStyle.secondary, row=1)
    async def disband_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)        
        if interaction.user.id == self.party.get('leader_id'):
            # GIẢI PHÁP SỬA LỖI 4: Lưu danh sách members và thông tin trước khi xóa
            members = self.party.get('members', [])
            dg_name = self.party.get('dg_name', 'Unknown DG')

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
            
            # Tiến hành gửi DM thông báo hủy nhóm đến mọi thành viên
            disband_embed = discord.Embed(
                title="❌ Party Disbanded",
                description=f"The party for **{dg_name}** has been disbanded by the leader.",
                color=discord.Color.red()
            )
            for m in members:
                m_id = m.get('user_id')
                if m_id and m_id != interaction.user.id:
                    user = self.bot.get_user(m_id)
                    if not user:
                        try:
                            user = await self.bot.fetch_user(m_id)
                        except:
                            user = None
                    if user:
                        try:
                            await user.send(embed=disband_embed)
                        except discord.Forbidden:
                            pass

            await interaction.followup.send("Party has been disbanded!", ephemeral=True)
        else:
            await parties_col.update_one({"_id": self.party['_id']}, {"$pull": {"members": {"user_id": interaction.user.id}}})
            await update_broadcast_messages(self.bot, self.party['_id'])
            await handle_cross_server_chat(self.bot, self.party, interaction.user.id, action="remove")
            # ĐÃ SỬA: Dùng followup thay vì response.send_message tránh crash bot
            await interaction.followup.send("You have left the party.", ephemeral=True)

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
            await interaction.followup.send("No 'party-board' channels found to broadcast.", ephemeral=True)


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
        profile = await get_player_profile(interaction.user.id)
        if not profile:
            # GIẢI PHÁP SỬA LỖI 2: Đồng bộ câu thông báo profile
            return await interaction.response.send_message("⚠️ Pls set up your gear profile(/mygear) first before use this function", ephemeral=True)
        
        party_id = self.select.values[0]
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
            return await interaction.response.send_message("⚠️ Pls set up your gear profile(/mygear) first before use this function", ephemeral=True)
        if await parties_col.find_one({"members.user_id": interaction.user.id}):
            return await interaction.response.send_message("❌ You are already in a party!", ephemeral=True)
            
        # GIẢI PHÁP SỬA LỖI 3: Truyền thêm 'interaction' vào modal làm parent_interaction
        await interaction.response.send_modal(CreatePartyModal(self.bot, profile.get('ign', 'Unknown'), self, interaction))

    @discord.ui.button(label="⚙️ Manage My Party", style=discord.ButtonStyle.primary, row=2)
    async def manage_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        party = await parties_col.find_one({"members.user_id": interaction.user.id})
        if not party:
            return await interaction.followup.send("You are not currently in a party.", ephemeral=True)
        
        embed = create_party_embed(party)
        await interaction.followup.send(embed=embed, view=ManagePartyView(self.bot, party), ephemeral=True)

    async def update_lobby(self, target, new_page: int):
        fresh_parties = await parties_col.find({}).to_list(length=100)
        view = LobbyPaginationView(self.bot, fresh_parties, new_page)
        
        max_pages = max(1, view.max_pages)
        embed = discord.Embed(title="🌐 Party Finder Lobby", description=f"Page {new_page+1}/{max_pages}", color=discord.Color.purple())
        
        for p in fresh_parties[new_page * view.items_per_page : (new_page + 1) * view.items_per_page]:
            dg_name = p.get('dg_name', 'Unknown')
            start_time = p.get('start_time', 'ASAP')
            leader = p.get('leader_ign', 'Unknown')
            reqs = p.get('requirements', 'No specific requirements')
            members_count = len(p.get('members', []))
            
            embed.add_field(
                name=f"🎮 {dg_name} | Start: {start_time}", 
                value=f"👤 Leader: **{leader}**\n👥 Members: `{members_count}/4`\n📝 Req: *{reqs}*", 
                inline=False
            )
            
        if not fresh_parties: 
            embed.description = "No active parties found."
            
        if isinstance(target, discord.Interaction):
            if not target.response.is_done():
                await target.response.edit_message(embed=embed, view=view)
            else:
                await target.edit_original_response(embed=embed, view=view)
        elif isinstance(target, discord.Message):
            await target.edit(embed=embed, view=view)

# --- MODALS ---

class JoinPartyModal(discord.ui.Modal, title='Role Selection'):
    ign = discord.ui.TextInput(label='In-game Name', required=True)
    role = discord.ui.TextInput(label='Your Role (e.g., DPS, TANK, UFM)', placeholder='Type your role...', required=True)

    def __init__(self, bot, party_id, current_ign):
        super().__init__()
        self.bot = bot
        self.party_id = party_id
        self.ign.default = current_ign

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        profile = await get_player_profile(interaction.user.id)
        
        if not party or not profile:
            return await interaction.followup.send("Party or Profile not found.", ephemeral=True)

        role_entered = self.role.value.strip()
        stats = profile.get("my_stats", {})
        
        gear_summary = await get_formatted_gear_summary(stats, role_entered)

        leader = self.bot.get_user(party.get('leader_id', 0)) or await self.bot.fetch_user(party.get('leader_id', 0))
        if leader:
            embed = discord.Embed(title="📩 Join Request Received!", color=discord.Color.green())
            embed.add_field(name="Applicant", value=self.ign.value, inline=True)
            embed.add_field(name="Role Selected", value=role_entered.upper(), inline=True)
            embed.add_field(name="Gear profile", value=gear_summary, inline=False)
            
            try:
                await leader.send(embed=embed, view=RequestJoinView(self.bot, self.party_id, interaction.user.id, self.ign.value, role_entered))
                await interaction.followup.send("✅ Request sent!", ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send("❌ Cannot DM the leader.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Leader not found.", ephemeral=True)


class CreatePartyModal(discord.ui.Modal, title='Create New Party'):
    ign_input = discord.ui.TextInput(label='Your In-game Name', placeholder='Type your IGN here...', required=True)
    dg_name = discord.ui.TextInput(label='Dungeon Name', placeholder='E.g., Stage of Clown(PIED)', required=True)
    role = discord.ui.TextInput(label='Your Role as Leader (e.g., DPS, TANK)', required=True)
    start_time = discord.ui.TextInput(label='Expected Start Time', placeholder='E.g., 20:00 or ASAP', required=True)
    requirements = discord.ui.TextInput(label='Requirements', style=discord.TextStyle.paragraph, required=False)

    # ĐÃ SỬA: Nhận thêm biến parent_interaction từ Lobby view gửi qua
    def __init__(self, bot, current_ign, lobby_view, parent_interaction: discord.Interaction):
        super().__init__()
        self.bot = bot
        self.lobby_view = lobby_view
        self.parent_interaction = parent_interaction
        self.ign_input.default = str(current_ign) if current_ign else "Unknown" 

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await get_player_profile(interaction.user.id)
        role_entered = self.role.value.strip()
        stats = profile.get("my_stats", {}) if profile else {}
        
        leader_ign = self.ign_input.value.strip()

        dg_config = await get_dungeon_config(self.dg_name.value)
        if not dg_config:
            dg_config = {
                "dg_name": self.dg_name.value,
                "ping_role": None,  
                "reqs": {"gear": [], "vice": [], "deck": []} 
            }
            await dungeon_configs_col.insert_one(dg_config)

        ROLE_ALIASES = {
            "dps": ["aa", "sk"], "ufm": ["aa", "sk"], "fm": ["aa", "sk"],
            "future": ["aa", "sk"], "ulforce": ["aa", "sk"], "future mode": ["aa", "sk"]
        }
        
        search_keys = ROLE_ALIASES.get(role_entered.lower(), [role_entered.lower()])
        available_roles = [k for k, v in stats.items() if isinstance(v, dict)]
        
        passed_gear_data = None
        passed_actual_role = None
        error_msgs = []

        for key in search_keys:
            gear_data = next((v for k, v in stats.items() if isinstance(v, dict) and k.lower() == key), None)
            actual_db_key = next((k for k, v in stats.items() if isinstance(v, dict) and k.lower() == key), key.upper())
            
            if not gear_data:
                error_msgs.append(f"- `{actual_db_key}`: No gear setup found in /mygear.")
                continue
                
            is_valid, reason = await check_gear_requirements(actual_db_key, gear_data, dg_config)
            if is_valid:
                passed_gear_data = gear_data
                passed_actual_role = actual_db_key
                break
            else:
                error_msgs.append(f"- `{actual_db_key}`: {reason}")

        if not passed_gear_data:
            roles_str = ", ".join(available_roles) if available_roles else "None"
            errors = "\n".join(error_msgs)
            return await interaction.followup.send(f"⛔ **You don't meet requirements to create this party as `{role_entered}`:**\n{errors}\n💡 **Your available roles are:** `{roles_str}`", ephemeral=True)

        display_role = f"{role_entered} ({passed_actual_role})" if role_entered.lower() != passed_actual_role.lower() else passed_actual_role

        party_doc = {
            "leader_id": interaction.user.id,
            "leader_ign": leader_ign, 
            "dg_name": self.dg_name.value,
            "start_time": self.start_time.value,
            "requirements": self.requirements.value,
            "members": [{"user_id": interaction.user.id, "ign": leader_ign, "role": display_role}], 
            "broadcasts": [],
            "chat_channel_id": None
        }
        
        result = await parties_col.insert_one(party_doc)
        party_doc["_id"] = result.inserted_id

        await handle_cross_server_chat(self.bot, party_doc, action="create", guild=interaction.guild)

        embed = create_party_embed(party_doc)
        broadcast_records = await broadcast_to_all_servers(self.bot, embed, str(result.inserted_id), dg_config, interaction.guild)
        
        if broadcast_records:
            await parties_col.update_one({"_id": result.inserted_id}, {"$set": {"broadcasts": broadcast_records}})
            
        await interaction.followup.send(f"Party created successfully! Verified via your **{passed_actual_role}** profile.", ephemeral=True)
        
        # GIẢI PHÁP SỬA LỖI 3: Dùng parent_interaction để ép giao diện Lobby gốc phải tự động edit/refresh lại dữ liệu mới
        await self.lobby_view.update_lobby(self.parent_interaction, self.lobby_view.page)
            
class EditDungeonModal(discord.ui.Modal, title='Edit Dungeon Name'):
    new_name = discord.ui.TextInput(label='New Dungeon Name', required=True)

    def __init__(self, party, bot):
        super().__init__()
        self.party = party
        self.bot = bot
        self.new_name.default = party.get('dg_name')

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await parties_col.update_one({"_id": self.party['_id']}, {"$set": {"dg_name": self.new_name.value}})
        asyncio.create_task(update_broadcast_messages(self.bot, str(self.party['_id'])))
        await interaction.followup.send("✅ Dungeon name updated!", ephemeral=True)

class EditReqModal(discord.ui.Modal, title='Edit Requirements'):
    new_req = discord.ui.TextInput(label='New Requirements', style=discord.TextStyle.paragraph, required=True)

    def __init__(self, party, bot):
        super().__init__()
        self.party = party
        self.bot = bot
        self.new_req.default = party.get('requirements')

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await parties_col.update_one({"_id": self.party['_id']}, {"$set": {"requirements": self.new_req.value}})
        asyncio.create_task(update_broadcast_messages(self.bot, str(self.party['_id'])))    
        await interaction.followup.send("✅ Requirements updated!", ephemeral=True)
# --- CHAT SYSTEM ---
async def handle_cross_server_chat(bot, party, user_id=None, action="create", guild=None):
    try:
        dg_name = party.get('dg_name', 'Unknown DG')
        
        if action == "create":
            leader = bot.get_user(party.get('leader_id', 0))
            if not leader:
                try: leader = await bot.fetch_user(party.get('leader_id', 0))
                except: pass
            
            if leader:
                await leader.send(f"✅ **Party Chat Started!** You are now in the party for **{dg_name}**.\n💬 *Tips: Any message you send to me here will be forwarded to your party members.*")

        elif action == "add" and user_id:
            # Thông báo cho người mới vào
            member = bot.get_user(user_id)
            if not member:
                try: member = await bot.fetch_user(user_id)
                except: pass
            
            if member:
                await member.send(f"👋 **Party Chat Joined!** You are now in the party for **{dg_name}**.\n💬 *Tips: Any message you send to me here will be forwarded to your party members.*")
            
            # Thông báo cho các thành viên cũ biết có người mới vào chat
            for m in party.get('members', []):
                if m['user_id'] != user_id:
                    other = bot.get_user(m['user_id'])
                    if not other:
                        try: other = await bot.fetch_user(m['user_id'])
                        except: pass
                    if other:
                        await other.send(f"📥 **{member.name if member else 'A new member'}** has joined the party chat!")

        elif action == "remove" and user_id:
            # Thông báo cho các thành viên còn lại biết có người rời đi
            for m in party.get('members', []):
                if m['user_id'] != user_id:
                    other = bot.get_user(m['user_id'])
                    if not other:
                        try: other = await bot.fetch_user(m['user_id'])
                        except: pass
                    if other:
                        await other.send(f"🚪 **A member** has left the party chat.")
                        
    except Exception as e: 
        print(f"Chat Relay error: {e}")
# --- COG SETUP ---

class PartyFinderCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- HỆ THỐNG LẮNG NGHE VÀ CHUYỂN TIẾP TIN NHẮN (DM RELAY) ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 1. Bỏ qua nếu tin nhắn là của bot hoặc gửi trên kênh của server (chỉ nhận tin nhắn DM)
        if message.author.bot or message.guild is not None:
            return

        # 2. Kiểm tra xem người dùng này có đang trong party nào không
        party = await parties_col.find_one({"members.user_id": message.author.id})
        if not party:
            return # Không ở trong party thì bot bỏ qua tin nhắn này

        # 3. Lấy tên IGN in-game của người gửi
        sender_ign = "Unknown"
        for m in party.get('members', []):
            if m['user_id'] == message.author.id:
                sender_ign = m.get('ign', message.author.name)
                break

        # 4. Định dạng tin nhắn gửi đi bằng Embed
        embed = discord.Embed(description=message.content, color=discord.Color.green())
        embed.set_author(name=f"{sender_ign}", icon_url=message.author.display_avatar.url)
        embed.set_footer(text=f"Party: {party.get('dg_name')}")

        # Xử lý nếu người dùng gửi kèm hình ảnh
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)

        # 5. Chuyển tiếp tin nhắn cho các thành viên CÒN LẠI trong party
        for m in party.get('members', []):
            if m['user_id'] != message.author.id:
                # Tìm user trên toàn bộ hệ thống bot
                target_user = self.bot.get_user(m['user_id'])
                if not target_user:
                    try:
                        target_user = await self.bot.fetch_user(m['user_id'])
                    except Exception:
                        continue # Nếu lỗi không tìm thấy user thì bỏ qua người này
                
                # Gửi DM cho user
                if target_user:
                    try:
                        await target_user.send(embed=embed)
                    except discord.Forbidden:
                        pass # Bỏ qua nếu người đó đã block DM của bot

    # --- CÁC TƯƠNG TÁC GIAO DIỆN CŨ CỦA BẠN ---
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if not interaction.data: return
        custom_id = interaction.data.get("custom_id", "")
        
        if custom_id.startswith("bcast_join_"):
            party_id_str = custom_id.replace("bcast_join_", "")
            profile = await get_player_profile(interaction.user.id)
            
            if not profile:
                return await interaction.response.send_message("⚠️ Pls set up your gear profile(/mygear) first before use this function", ephemeral=True)
                
            existing_party = await parties_col.find_one({"members.user_id": interaction.user.id})
            if existing_party:
                return await interaction.response.send_message("❌ You are already in a party!", ephemeral=True)
                
            await interaction.response.send_modal(JoinPartyModal(self.bot, party_id_str, profile.get('ign', 'Unknown')))
            
        elif custom_id == "bcast_lobby":
            await interaction.response.defer(ephemeral=True)
            
            # GIẢI PHÁP SỬA LỖI 2: Check profile tại nút bấm liên kết Lobby UI ngoài server
            profile = await get_player_profile(interaction.user.id)
            if not profile:
                return await interaction.followup.send("⚠️ Pls set up your gear profile(/mygear) first before use this function", ephemeral=True)

            parties = await parties_col.find({}).to_list(length=100)
            view = LobbyPaginationView(self.bot, parties, page=0)
            
            embed = discord.Embed(title="🌐 Party Finder Lobby", description=f"Page 1/{view.max_pages}", color=discord.Color.purple())
            for p in parties[:view.items_per_page]:
                dg_name = p.get('dg_name', 'Unknown')
                start_time = p.get('start_time', 'N/A')
                leader = p.get('leader_ign', 'Unknown')
                reqs = p.get('requirements', 'No specific requirements')
                members_count = len(p.get('members', []))

                embed.add_field(
                    name=f"🎮 {dg_name} | Start: {start_time}", 
                    value=f"👤 Leader: **{leader}**\n👥 Members: `{members_count}/4`\n📝 Req: *{reqs}*", 
                    inline=False
                )
            if not parties: embed.description = "No active parties found."
            
            await interaction.followup.send(embed=embed, view=view)


    @app_commands.command(name="party_lobby", description="Open the Party Finder Lobby UI")
    async def party_lobby(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # GIẢI PHÁP SỬA LỖI 2: Check profile tại lệnh slash command /party_lobby
        profile = await get_player_profile(interaction.user.id)
        if not profile:
            return await interaction.followup.send("⚠️ Pls set up your gear profile(/mygear) first before use this function", ephemeral=True)

        parties = await parties_col.find({}).to_list(length=100)
        embed = discord.Embed(title="🌐 Party Finder Lobby", color=discord.Color.purple())
        view = LobbyPaginationView(self.bot, parties, page=0)
        
        if not parties:
            embed.description = "No active parties found."
        else:
            embed.description = f"Page 1/{max(1, view.max_pages)}"
            for p in parties[:view.items_per_page]:
                dg_name = p.get('dg_name', 'Unknown')
                start_time = p.get('start_time', 'N/A')
                leader = p.get('leader_ign', 'Unknown')
                reqs = p.get('requirements', 'No requirements')
                member_count = len(p.get('members', []))
                
                embed.add_field(
                    name=f"🎮 {dg_name} | Start: {start_time}", 
                    value=f"👤 Leader: **{leader}**\n👥 Members: `{member_count}/4`\n📝 Req: *{reqs}*", 
                    inline=False
                )
        
        await interaction.followup.send(embed=embed, view=view)
async def setup(bot):
    await bot.add_cog(PartyFinderCog(bot))