import discord
from discord.ext import commands
from discord import app_commands
from bson.objectid import ObjectId
import asyncio
import re 
from datetime import datetime, timedelta, timezone

# Import direct collections từ Database.py
from Database import players_col, parties_col, dungeon_configs_col, world_boss_col, rpg_profiles_col

server_configs_col = players_col.database["server_configs"]

# --- DATABASE HELPER FUNCTIONS ---
def get_discord_timestamp(time_str: str, tz_offset: float = 7.0):
    try:
        user_tz = timezone(timedelta(hours=float(tz_offset)))
        now = datetime.now(user_tz)
        target_time = datetime.strptime(time_str.strip(), "%H:%M").time()
        dt = datetime.combine(now.date(), target_time, tzinfo=user_tz)
        if dt < now: dt += timedelta(days=1)
        unix_ts = int(dt.timestamp())
        return f"<t:{unix_ts}:t> (<t:{unix_ts}:R>)"
    except Exception:
        return time_str

async def get_player_profile(user_id: int):
    return await players_col.find_one({"user_id": user_id})

def is_profile_complete(profile: dict) -> bool:
    if not profile or not profile.get('ign') or profile.get('ign') == "Not Set": return False
    if 'tz_offset' not in profile or not profile.get('my_stats'): return False
    return True

async def _do_single_edit(channel, message_id, embed):
    try:
        msg = await channel.fetch_message(message_id)
        await msg.edit(embed=embed)
    except Exception: pass 

async def update_broadcast_messages(bot, party_id: str):
    party = await parties_col.find_one({"_id": ObjectId(party_id)})
    if not party: return

    embed = create_party_embed(party)
    tasks = []
    for msg_data in party.get("broadcasts", []):
        channel = bot.get_channel(msg_data["channel_id"]) or await bot.fetch_channel(msg_data["channel_id"])
        if channel: tasks.append(_do_single_edit(channel, msg_data["message_id"], embed))
    if tasks: await asyncio.gather(*tasks)

# Cập nhật DM Lobby UI theo thời gian thực
async def update_party_lobby_dms(bot, party_id):
    party = await parties_col.find_one({"_id": ObjectId(party_id)})
    if not party: return
        
    embed = discord.Embed(title=f"🎮 Party Lobby: {party.get('dg_name')}", color=discord.Color.purple())
    embed.add_field(name="👑 Team Leader", value=party.get('leader_ign'), inline=True)
    embed.add_field(name="⏰ Start in", value=party.get('start_time', 'ASAP'), inline=True)
    
    m_text = ""
    for idx, m in enumerate(party.get('members', [])):
        m_text += f"{idx+1}. <@{m['user_id']}> - **{m.get('ign')}**\n"
    embed.add_field(name=f"👥 Thành viên ({len(party.get('members', []))}/4)", value=m_text or "Trống", inline=False)
    
    for m in party.get('members', []):
        if "dm_message_id" in m:
            try:
                user = bot.get_user(m['user_id']) or await bot.fetch_user(m['user_id'])
                dm_channel = user.dm_channel or await user.create_dm()
                msg = await dm_channel.fetch_message(m["dm_message_id"])
                await msg.edit(embed=embed, view=PartyLobbyDMView(bot, party_id))
            except Exception: pass

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

async def broadcast_to_all_servers(bot, embed, party_id_str, dg_config: dict, origin_guild: discord.Guild = None):
    broadcasts = []
    view = BroadcastView(party_id=party_id_str)
    dg_name = dg_config.get("dg_name", "")

    for guild in bot.guilds:
        config = await server_configs_col.find_one({"guild_id": guild.id})
        channel = guild.get_channel(config["party_channel_id"]) if config and config.get("party_channel_id") else discord.utils.get(guild.text_channels, name="party-board")
            
        if channel:
            try:
                content_ping = ""
                if dg_name:
                    keywords = [k for k in re.findall(r'\b\w+\b', dg_name.lower()) if len(k) >= 3 and k not in ['dungeon', 'dg']]
                    matched_roles = [role.mention for role in guild.roles if any(k in role.name.lower() for k in keywords)]
                    if matched_roles: content_ping = " ".join(matched_roles)
                
                msg = await channel.send(content=content_ping, embed=embed, view=view)
                broadcasts.append({"channel_id": channel.id, "message_id": msg.id})
            except Exception: pass
                
    return broadcasts

async def get_formatted_gear_summary(stats, role_entered):
    DPS_GROUPS = ["dps", "ufm", "fm", "future", "ulforce", "future mode", "dps aa", "dps sk", "dpsaa", "dpssk", "aoe", "dps aoe", "dpsaoe"]
    clean_role = role_entered.lower().replace("(", "").replace(")", "").strip()
    is_dps = clean_role in DPS_GROUPS
    
    gear_details = []
    if is_dps:
        for r_key in ["AA", "SK"]:
            data = stats.get(r_key)
            if isinstance(data, dict):
                gear_details.append(f"**{r_key}**: Gear: {data.get('gear', 'N/A')} | Vice: {data.get('vice', 'N/A')} | Deck: {data.get('deck', 'N/A')} | Bracelet: {data.get('bracelet', 'N/A')}")
    else:
        role_key = role_entered.split('(')[0].strip().upper()
        data = stats.get(role_key)
        if isinstance(data, dict):
            gear_details.append(f"**{role_key}**: Gear: {data.get('gear', 'N/A')} | Vice: {data.get('vice', 'N/A')} | Deck: {data.get('deck', 'N/A')} | Bracelet: {data.get('bracelet', 'N/A')}")
            
    return "\n".join(gear_details) if gear_details else "No gear data found."


# --- VIEWS & MODALS ---

# UI LOBBY CHO TIN NHẮN TRONG DM
class PartyLobbyDMView(discord.ui.View):
    def __init__(self, bot, party_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.party_id = party_id

    @discord.ui.button(label="Rời Nhóm (Leave)", style=discord.ButtonStyle.danger, custom_id="dm_leave_party", emoji="🚪")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        if not party: return await interaction.followup.send("❌The group does not exist..", ephemeral=True)
        
        is_leader = party.get("leader_id") == interaction.user.id
        if is_leader:
            await parties_col.delete_one({"_id": ObjectId(self.party_id)})
            await interaction.followup.send("❌ You are the Team Leader, the Party has been disbanded..", ephemeral=True)
            await handle_cross_server_chat(self.bot, party, action="delete")
        else:
            await parties_col.update_one({"_id": ObjectId(self.party_id)}, {"$pull": {"members": {"user_id": interaction.user.id}}})
            await interaction.followup.send("✅You have left the group.", ephemeral=True)
            await update_party_lobby_dms(self.bot, self.party_id)
            await update_broadcast_messages(self.bot, self.party_id)
            await handle_cross_server_chat(self.bot, party, interaction.user.id, action="remove")

# HỎI XÁC NHẬN SPAWN BOSS SAU KHI TẠO PARTY
class PartyBossSpawnConfirmView(discord.ui.View):
    def __init__(self, bot, party_id, leader_id, dg_name):
        super().__init__(timeout=60)
        self.bot = bot
        self.party_id = party_id
        self.leader_id = leader_id
        self.dg_name = dg_name

    @discord.ui.button(label="Yes, summon the Boss!", style=discord.ButtonStyle.success, emoji="👹")
    async def confirm_spawn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.leader_id:
            return await interaction.response.send_message("❌ Only leader have permission!", ephemeral=True)
        await interaction.response.defer()
        
        await world_boss_col.insert_one({
            "party_id": self.party_id,
            "name": f"Party Raid Boss ({self.dg_name})",
            "max_hp": 75000,
            "current_hp": 75000,
            "atk": 800,
            "is_active": True,
            "img": "https://digimon.net/cimages/digimon/merukimon.jpg",
            "damage_log": {},
            "active_messages": []
        })
        await interaction.followup.send("🔥 **Party boss summon successfully, use /combat to attack!")
        self.stop()

    @discord.ui.button(label="Không, chỉ đi phó bản thường", style=discord.ButtonStyle.secondary)
    async def cancel_spawn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.leader_id:
            return await interaction.response.send_message("❌ Only the Team Leader has this authority.!", ephemeral=True)
        await interaction.response.send_message("✅ Boss summons have been cancelled..")
        self.stop()


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
        if not party: return await interaction.response.send_message("Party no longer exists.", ephemeral=True)
        if len(party.get('members', [])) >= 4: return await interaction.response.send_message("Party is already full!", ephemeral=True)
        
        applicant = self.bot.get_user(self.applicant_id) or await self.bot.fetch_user(self.applicant_id)
        dm_message_id = None
        
        if applicant:
            try:
                dm_channel = applicant.dm_channel or await applicant.create_dm()
                msg = await dm_channel.send(content=f"🎉 Leader {party.get('leader_ign')} has **ACCEPTED** your request to join {party.get('dg_name')}!")
                dm_message_id = msg.id
            except discord.Forbidden: pass

        new_member = {"user_id": self.applicant_id, "ign": self.applicant_ign, "role": self.applicant_role}
        if dm_message_id: new_member["dm_message_id"] = dm_message_id

        await parties_col.update_one({"_id": ObjectId(self.party_id)}, {"$push": {"members": new_member}})
        await update_broadcast_messages(self.bot, self.party_id)
        await update_party_lobby_dms(self.bot, self.party_id)
        await handle_cross_server_chat(self.bot, party, self.applicant_id, action="add")
        
        for child in self.children: child.disabled = True
        await interaction.message.edit(content="✅ Request accepted.", view=self)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="reject_join")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        for child in self.children: child.disabled = True
        await interaction.message.edit(content="❌ Request rejected.", view=self)
        
        applicant = self.bot.get_user(self.applicant_id) or await self.bot.fetch_user(self.applicant_id)
        if applicant and party: await applicant.send(f"💔 Your request to join {party.get('dg_name')} was rejected.")


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
            embed.add_field(name=f"{m['ign']} ({m['role'].split('(')[0].strip()})", value=gear_info, inline=False)
            
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="✏️ Edit Party Info", style=discord.ButtonStyle.secondary, row=0)
    async def edit_party_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.party.get('leader_id'): return await interaction.response.send_message("Only the leader can edit party details!", ephemeral=True)
        await interaction.response.send_modal(EditPartyInfoModal(self.party, self.bot))


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
            options = [discord.SelectOption(label=f"{p.get('dg_name', 'Unknown')} (Ldr: {p.get('leader_ign', 'Unknown')})", description=f"{len(p.get('members', []))}/4 - {p.get('start_time', 'N/A')}", value=str(p['_id'])) for p in current_parties]
            self.select = discord.ui.Select(placeholder="Select a party to join...", options=options, row=0)
            self.select.callback = self.send_request_callback
            self.add_item(self.select)

    async def send_request_callback(self, interaction: discord.Interaction):
        profile = await get_player_profile(interaction.user.id)
        if not is_profile_complete(profile): return await interaction.response.send_message("❌ **Access Denied!** Your profile is incomplete.", ephemeral=True)
        
        party_id = self.select.values[0]
        if await parties_col.find_one({"members.user_id": interaction.user.id}):
            return await interaction.response.send_message("❌ You are already in a party", ephemeral=True)
            
        await interaction.response.send_modal(JoinPartyModal(self.bot, party_id))

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
        if not is_profile_complete(profile): return await interaction.response.send_message("❌ **Access Denied!** Your profile is incomplete.", ephemeral=True)
        if await parties_col.find_one({"members.user_id": interaction.user.id}): return await interaction.response.send_message("❌ You are already in a party!", ephemeral=True)
            
        await interaction.response.send_modal(CreatePartyModal(self.bot, self, interaction))

    @discord.ui.button(label="⚙️ Manage My Party", style=discord.ButtonStyle.primary, row=2)
    async def manage_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        party = await parties_col.find_one({"members.user_id": interaction.user.id})
        if not party: return await interaction.followup.send("You are not currently in a party.", ephemeral=True)
        
        embed = create_party_embed(party)
        await interaction.followup.send(embed=embed, view=ManagePartyView(self.bot, party), ephemeral=True)

    async def update_lobby(self, target, new_page: int):
        fresh_parties = await parties_col.find({}).to_list(length=100)
        view = LobbyPaginationView(self.bot, fresh_parties, new_page)
        
        rpg_profile = await rpg_profiles_col.find_one({"user_id": target.user.id}) if isinstance(target, discord.Interaction) else None
        is_premium = rpg_profile.get("premium_ui") if rpg_profile else False

        embed = discord.Embed(
            title="🌟 Party Finder Lobby [Premium]" if is_premium else "🌐 Party Finder Lobby", 
            description=f"Page {new_page+1}/{max(1, view.max_pages)}", 
            color=discord.Color.gold() if is_premium else discord.Color.purple()
        )
        
        for p in fresh_parties[new_page * view.items_per_page : (new_page + 1) * view.items_per_page]:
            embed.add_field(name=f"🎮 {p.get('dg_name', 'Unknown')} | Start: {p.get('start_time', 'ASAP')}", value=f"👤 Leader: **{p.get('leader_ign', 'Unknown')}**\n👥 Members: `{len(p.get('members', []))}/4`\n📝 Req: *{p.get('requirements', 'None')}*", inline=False)
            
        if not fresh_parties: embed.description = "No active parties found."
            
        if isinstance(target, discord.Interaction):
            if not target.response.is_done(): await target.response.edit_message(embed=embed, view=view)
            else: await target.edit_original_response(embed=embed, view=view)
        elif isinstance(target, discord.Message):
            await target.edit(embed=embed, view=view)


class JoinPartyModal(discord.ui.Modal, title='Role Selection'):
    role = discord.ui.TextInput(label='Your Role (e.g., DPS, TANK, UFM)', required=True)

    def __init__(self, bot, party_id):
        super().__init__()
        self.bot = bot
        self.party_id = party_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        profile = await get_player_profile(interaction.user.id)
        
        if not party or not is_profile_complete(profile): return await interaction.followup.send("Party or Profile not found.", ephemeral=True)

        applicant_ign = profile.get('ign')
        role_entered = self.role.value.strip()
        gear_summary = await get_formatted_gear_summary(profile.get("my_stats", {}), role_entered)

        leader = self.bot.get_user(party.get('leader_id', 0)) or await self.bot.fetch_user(party.get('leader_id', 0))
        if leader:
            embed = discord.Embed(title="📩 Join Request Received!", color=discord.Color.green())
            embed.add_field(name="Applicant", value=applicant_ign, inline=True)
            embed.add_field(name="Role Selected", value=role_entered.upper(), inline=True)
            embed.add_field(name="Gear profile", value=gear_summary, inline=False)
            try:
                await leader.send(embed=embed, view=RequestJoinView(self.bot, self.party_id, interaction.user.id, applicant_ign, role_entered))
                await interaction.followup.send("✅ Request sent!", ephemeral=True)
            except discord.Forbidden: await interaction.followup.send("❌ Cannot DM the leader.", ephemeral=True)


class CreatePartyModal(discord.ui.Modal, title='Create New Party'):
    dg_name = discord.ui.TextInput(label='Dungeon Name', placeholder='E.g., Stage of Clown(PIED)', required=True)
    role = discord.ui.TextInput(label='Your Role as Leader (e.g., DPS, TANK)', required=True)
    start_time = discord.ui.TextInput(label='Expected Start Time', placeholder='Please use HH:MM in your timezone', required=True)
    requirements = discord.ui.TextInput(label='Requirements', style=discord.TextStyle.paragraph, required=False)

    def __init__(self, bot, lobby_view, parent_interaction: discord.Interaction):
        super().__init__()
        self.bot = bot
        self.lobby_view = lobby_view
        self.parent_interaction = parent_interaction

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await get_player_profile(interaction.user.id)
        
        if not is_profile_complete(profile): return await interaction.followup.send("⚠️ Please setup your profile first.", ephemeral=True)
            
        formatted_time = get_discord_timestamp(self.start_time.value.strip(), float(profile.get('tz_offset', 7.0)))
        leader_ign, role_entered = profile.get('ign'), self.role.value.strip()
        
        # Gửi DM Lobby cho chính Trưởng nhóm
        dm_message_id = None
        try:
            dm_channel = interaction.user.dm_channel or await interaction.user.create_dm()
            msg = await dm_channel.send("Đang khởi tạo Lobby...")
            dm_message_id = msg.id
        except discord.Forbidden: pass

        party_doc = {
            "leader_id": interaction.user.id,
            "leader_ign": leader_ign, 
            "dg_name": self.dg_name.value,
            "start_time": formatted_time,
            "requirements": self.requirements.value,
            "members": [{"user_id": interaction.user.id, "ign": leader_ign, "role": role_entered, "dm_message_id": dm_message_id}], 
            "broadcasts": []
        }
        
        result = await parties_col.insert_one(party_doc)
        party_doc["_id"] = result.inserted_id

        await update_party_lobby_dms(self.bot, result.inserted_id)
        await handle_cross_server_chat(self.bot, party_doc, action="create", guild=interaction.guild)

        embed = create_party_embed(party_doc)
        broadcast_records = await broadcast_to_all_servers(self.bot, embed, str(result.inserted_id), {"dg_name": self.dg_name.value}, interaction.guild)
        if broadcast_records: await parties_col.update_one({"_id": result.inserted_id}, {"$set": {"broadcasts": broadcast_records}})
            
        await interaction.followup.send("✅ Party created! Please check your DMs (Private Messages)..", view=PartyBossSpawnConfirmView(self.bot, str(result.inserted_id), interaction.user.id, self.dg_name.value), ephemeral=True)
        await self.lobby_view.update_lobby(self.parent_interaction, self.lobby_view.page)


class EditPartyInfoModal(discord.ui.Modal, title='Edit Party Information'):
    new_name = discord.ui.TextInput(label='Dungeon Name', required=True)
    new_time = discord.ui.TextInput(label='Start Time (HH:MM) - Leave blank to keep', required=False)
    new_req = discord.ui.TextInput(label='Requirements', style=discord.TextStyle.paragraph, required=False)

    def __init__(self, party, bot):
        super().__init__()
        self.party = party
        self.bot = bot
        self.new_name.default = party.get('dg_name', '')
        self.new_req.default = party.get('requirements', '')

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        update_data = {"dg_name": self.new_name.value.strip(), "requirements": self.new_req.value.strip()}
        if self.new_time.value.strip():
            profile = await get_player_profile(interaction.user.id)
            update_data["start_time"] = get_discord_timestamp(self.new_time.value.strip(), float(profile.get('tz_offset', 7.0)) if profile else 7.0)
            
        await parties_col.update_one({"_id": self.party['_id']}, {"$set": update_data})
        asyncio.create_task(update_broadcast_messages(self.bot, str(self.party['_id'])))
        await update_party_lobby_dms(self.bot, str(self.party['_id']))
        await interaction.followup.send("✅ Party information updated successfully!", ephemeral=True)

# --- CHAT SYSTEM ---
async def handle_cross_server_chat(bot, party, user_id=None, action="create", guild=None, msg_override=None):
    try:
        dg_name = party.get('dg_name', 'Unknown DG')
        
        if msg_override:
            for m in party.get('members', []):
                u = bot.get_user(m['user_id']) or await bot.fetch_user(m['user_id'])
                if u: await u.send(msg_override)
            return

        if action == "create":
            leader = bot.get_user(party.get('leader_id', 0)) or await bot.fetch_user(party.get('leader_id', 0))
            if leader: await leader.send(f"✅ **Party Chat Started!** You are now in the party for **{dg_name}**.")

        elif action == "add" and user_id:
            member = bot.get_user(user_id) or await bot.fetch_user(user_id)
            if member: await member.send(f"👋 **Party Chat Joined!** You are now in the party for **{dg_name}**.")
            
            new_member_ign = next((m.get('ign') for m in party.get('members', []) if m['user_id'] == user_id), "A new member")
            for m in party.get('members', []):
                if m['user_id'] != user_id:
                    other = bot.get_user(m['user_id']) or await bot.fetch_user(m['user_id'])
                    if other: await other.send(f"📥 **{new_member_ign}** has joined the party chat!")

        elif action == "remove" and user_id:
            left_ign = next((m.get('ign') for m in party.get('members', []) if m.get('user_id') == user_id), "A member")
            for m in party.get('members', []):
                if m['user_id'] != user_id:
                    other = bot.get_user(m['user_id']) or await bot.fetch_user(m['user_id'])
                    if other: await other.send(f"🚪 **{left_ign}** has left the party chat.")
    except Exception as e: print(f"Chat Relay error: {e}")

# --- COG SETUP ---
class PartyFinderCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is not None: return
        party = await parties_col.find_one({"members.user_id": message.author.id})
        if not party: return 

        sender_ign = next((m.get('ign', message.author.name) for m in party.get('members', []) if m['user_id'] == message.author.id), "Unknown")
        msg_content = message.content
        chat_content = f"**[{party.get('dg_name', 'Unknown')}] {sender_ign}**: {msg_content}"
        if message.attachments: chat_content += "\n" + "\n".join([att.url for att in message.attachments])

        for m in party.get('members', []):
            if m['user_id'] != message.author.id:
                target_user = self.bot.get_user(m['user_id']) or await self.bot.fetch_user(m['user_id'])
                if target_user:
                    try: await target_user.send(content=chat_content)
                    except discord.Forbidden: pass

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if not interaction.data: return
        custom_id = interaction.data.get("custom_id", "")
        
        if custom_id.startswith("bcast_join_"):
            party_id_str = custom_id.replace("bcast_join_", "")
            profile = await get_player_profile(interaction.user.id)
            if not is_profile_complete(profile): return await interaction.response.send_message("❌ Your profile is incomplete.", ephemeral=True)
            if await parties_col.find_one({"members.user_id": interaction.user.id}): return await interaction.response.send_message("❌ You are already in a party!", ephemeral=True)
            await interaction.response.send_modal(JoinPartyModal(self.bot, party_id_str))
            
        elif custom_id == "bcast_lobby":
            await interaction.response.defer(ephemeral=True)
            profile = await get_player_profile(interaction.user.id)
            if not is_profile_complete(profile): return await interaction.followup.send("❌ Your profile is incomplete.", ephemeral=True)

            parties = await parties_col.find({}).to_list(length=100)
            view = LobbyPaginationView(self.bot, parties, page=0)
            
            rpg_profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
            is_premium = rpg_profile.get("premium_ui") if rpg_profile else False

            embed = discord.Embed(title="🌟 Party Finder Lobby [Premium]" if is_premium else "🌐 Party Finder Lobby", description=f"Page 1/{view.max_pages}", color=discord.Color.gold() if is_premium else discord.Color.purple())
            for p in parties[:view.items_per_page]:
                embed.add_field(name=f"🎮 {p.get('dg_name')} | Start: {p.get('start_time')}", value=f"👤 Leader: **{p.get('leader_ign')}**\n👥 Members: `{len(p.get('members', []))}/4`\n📝 Req: *{p.get('requirements', 'None')}*", inline=False)
            if not parties: embed.description = "No active parties found."
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="setup_party_channel", description="Configure Party Board")
    async def setup_party_channel(self, interaction: discord.Interaction, channel: discord.TextChannel): 
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator: return await interaction.followup.send("❌ Access Denied!", ephemeral=True)
        await server_configs_col.update_one({"guild_id": interaction.guild_id}, {"$set": {"party_channel_id": channel.id}}, upsert=True)
        await interaction.followup.send(f"✅ Set up Party channel at: {channel.mention}", ephemeral=True)

    @app_commands.command(name="party_lobby", description="Open the Party Finder Lobby UI")
    async def party_lobby(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await get_player_profile(interaction.user.id)
        if not is_profile_complete(profile): return await interaction.followup.send("❌ Your profile is incomplete.", ephemeral=True)

        parties = await parties_col.find({}).to_list(length=100)
        view = LobbyPaginationView(self.bot, parties, page=0)
        
        rpg_profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        is_premium = rpg_profile.get("premium_ui") if rpg_profile else False

        embed = discord.Embed(title="🌟 Party Finder Lobby [Premium]" if is_premium else "🌐 Party Finder Lobby", description=f"Page 1/{view.max_pages}", color=discord.Color.gold() if is_premium else discord.Color.purple())
        for p in parties[:view.items_per_page]:
            embed.add_field(name=f"🎮 {p.get('dg_name')} | Start: {p.get('start_time')}", value=f"👤 Leader: **{p.get('leader_ign')}**\n👥 Members: `{len(p.get('members', []))}/4`\n📝 Req: *{p.get('requirements', 'None')}*", inline=False)
        if not parties: embed.description = "No active parties found."
        
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(PartyFinderCog(bot))