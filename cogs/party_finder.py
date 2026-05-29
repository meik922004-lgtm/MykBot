import discord
from discord.ext import commands
from discord import app_commands
from bson.objectid import ObjectId
from typing import List, Optional, Union
import asyncio
import re 
from datetime import datetime, timedelta, timezone

# Import direct collections từ Database.py
from Database import players_col, parties_col, dungeon_configs_col

# Khởi tạo động server_configs từ database sẵn có để lưu cấu hình channel
server_configs_col = players_col.database["server_configs"]

# --- DATABASE HELPER FUNCTIONS ---
def get_discord_timestamp(time_str: str, tz_offset: float = 7.0):
    """Chuyển chuỗi HH:MM thành định dạng chuẩn của Discord dựa trên múi giờ của User."""
    try:
        user_tz = timezone(timedelta(hours=float(tz_offset)))
        now = datetime.now(user_tz)
        
        target_time = datetime.strptime(time_str.strip(), "%H:%M").time()
        dt = datetime.combine(now.date(), target_time, tzinfo=user_tz)
        
        if dt < now:
            dt += timedelta(days=1)
            
        unix_ts = int(dt.timestamp())
        return f"<t:{unix_ts}:t> (<t:{unix_ts}:R>)"
    except Exception as e:
        print(f"Lỗi parse time: {e}")
        return time_str

async def get_player_profile(user_id: int):
    return await players_col.find_one({"user_id": user_id})

def is_profile_complete(profile: dict) -> bool:
    """Hàm kiểm tra người chơi đã setup đủ IGN, Timezone và Gears chưa."""
    if not profile: 
        return False
    if not profile.get('ign') or profile.get('ign') == "Not Set": 
        return False
    if 'tz_offset' not in profile: 
        return False
    if not profile.get('my_stats') or len(profile.get('my_stats')) == 0: 
        return False
    return True

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
    
    tasks = []
    for msg_data in party.get("broadcasts", []):
        channel = bot.get_channel(msg_data["channel_id"])
        if not channel:
            try:
                channel = await bot.fetch_channel(msg_data["channel_id"])
            except:
                pass
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

def find_flexible_role(guild, dg_name):
    raw_words = re.findall(r'\b\w+\b', dg_name.lower())
    keywords = [w for w in raw_words if len(w) >= 3 and w not in ['dungeon', 'dg']]
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
        channel = None
        config = await server_configs_col.find_one({"guild_id": guild.id})
        if config and config.get("party_channel_id"):
            channel = guild.get_channel(config["party_channel_id"])
            if not channel:
                try: channel = await bot.fetch_channel(config["party_channel_id"])
                except: pass
        
        if not channel:
            channel = discord.utils.get(guild.text_channels, name="party-board")
            
        if channel:
            try:
                content_ping = ""
                if dg_name:
                    raw_words = re.findall(r'\b\w+\b', dg_name.lower())
                    keywords = [k for k in raw_words if len(k) >= 3 and k not in ['dungeon', 'dg']]
                    
                    matched_roles = []
                    for role in guild.roles:
                        role_name_lower = role.name.lower()
                        if any(keyword in role_name_lower for keyword in keywords):
                            matched_roles.append(role.mention)
                    
                    if matched_roles:
                        content_ping = " ".join(matched_roles)
                
                msg = await channel.send(content=content_ping, embed=embed, view=view)
                broadcasts.append({"channel_id": channel.id, "message_id": msg.id})
                
            except Exception as e:
                print(f"Cannot broadcast to guild {guild.name}: {e}")
                
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
                gear_details.append(
                    f"**{r_key}**: Gear: {data.get('gear', 'N/A')} | Vice: {data.get('vice', 'N/A')} | Deck: {data.get('deck', 'N/A')} | Bracelet: {data.get('bracelet', 'N/A')}"
                )
    else:
        role_key = role_entered.split('(')[0].strip().upper()
        data = stats.get(role_key)
        if isinstance(data, dict):
            gear_details.append(
                f"**{role_key}**: Gear: {data.get('gear', 'N/A')} | Vice: {data.get('vice', 'N/A')} | Deck: {data.get('deck', 'N/A')} | Bracelet: {data.get('bracelet', 'N/A')}"
            )
            
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

    @discord.ui.button(label="✏️ Edit Party Info", style=discord.ButtonStyle.secondary, row=0)
    async def edit_party_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.party.get('leader_id'):
            return await interaction.response.send_message("Only the leader can edit party details!", ephemeral=True)
        await interaction.response.send_modal(EditPartyInfoModal(self.party, self.bot))

    @discord.ui.button(label="Kick Member", style=discord.ButtonStyle.danger, row=1)
    async def kick_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.party.get('leader_id'):
            return await interaction.response.send_message("Only the leader can kick members!", ephemeral=True)
            
        party_data = await parties_col.find_one({"_id": self.party['_id']})
        if not party_data:
            return await interaction.response.send_message("Party no longer exists.", ephemeral=True)
            
        kickable_members = [m for m in party_data.get('members', []) if m.get('user_id') != interaction.user.id]
        if not kickable_members:
            return await interaction.response.send_message("No members to kick.", ephemeral=True)
            
        options = [
            discord.SelectOption(
                label=m.get('ign', 'Unknown'), 
                description=f"Role: {m.get('role')}", 
                value=str(m.get('user_id'))
            ) for m in kickable_members
        ]
        select = discord.ui.Select(placeholder="Select member to kick...", options=options)
        
        async def kick_callback(inter: discord.Interaction):
            await inter.response.defer(ephemeral=True)
            target_id = int(select.values[0])
            
            await parties_col.update_one({"_id": self.party['_id']}, {"$pull": {"members": {"user_id": target_id}}})
            await handle_cross_server_chat(self.bot, self.party, target_id, action="remove")
            await update_broadcast_messages(self.bot, str(self.party['_id']))
            
            user = self.bot.get_user(target_id)
            if not user:
                try: user = await self.bot.fetch_user(target_id)
                except Exception: user = None

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

            select.disabled = True
            await inter.edit_original_response(
                content=f"✅ Successfully kicked **{user.name if user else 'user'}** and notified them.", 
                view=kick_view
            )

        select.callback = kick_callback
        kick_view = discord.ui.View()
        kick_view.add_item(select)
        
        await interaction.response.send_message(content="Vui lòng chọn thành viên bạn muốn trục xuất khỏi nhóm:", view=kick_view, ephemeral=True)

    @discord.ui.button(label="Disband / Leave", style=discord.ButtonStyle.secondary, row=1)
    async def disband_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)        
        if interaction.user.id == self.party.get('leader_id'):
            members = self.party.get('members', [])
            dg_name = self.party.get('dg_name', 'Unknown DG')

            await parties_col.delete_one({"_id": self.party['_id']})
            await handle_cross_server_chat(self.bot, self.party, action="delete")
            
            embed = discord.Embed(title="❌ Party Disbanded", color=discord.Color.red())
            for msg_data in self.party.get("broadcasts", []):
                channel = self.bot.get_channel(msg_data["channel_id"])
                if not channel:
                    try: channel = await self.bot.fetch_channel(msg_data["channel_id"])
                    except: pass
                if channel:
                    try:
                        msg = await channel.fetch_message(msg_data["message_id"])
                        await msg.edit(embed=embed, view=None)
                    except: pass
            
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
                        try: user = await self.bot.fetch_user(m_id)
                        except: user = None
                    if user:
                        try: await user.send(embed=disband_embed)
                        except discord.Forbidden: pass

            await interaction.followup.send("Party has been disbanded!", ephemeral=True)
        else:
            await parties_col.update_one({"_id": self.party['_id']}, {"$pull": {"members": {"user_id": interaction.user.id}}})
            await update_broadcast_messages(self.bot, self.party['_id'])
            await handle_cross_server_chat(self.bot, self.party, interaction.user.id, action="remove")
            await interaction.followup.send("You have left the party.", ephemeral=True)

    @discord.ui.button(label="Broadcast All Servers", style=discord.ButtonStyle.success, row=1)
    async def broadcast(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.party.get('leader_id'):
            return await interaction.response.send_message("Only the leader can broadcast!", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        embed = create_party_embed(self.party)
        dg_config = {"dg_name": self.party.get('dg_name', '')}
        
        new_broadcasts = await broadcast_to_all_servers(self.bot, embed, str(self.party['_id']), dg_config)
        if new_broadcasts:
            await parties_col.update_one({"_id": self.party['_id']}, {"$push": {"broadcasts": {"$each": new_broadcasts}}})
            await interaction.followup.send("Broadcast sent to all servers!", ephemeral=True)
        else:
            await interaction.followup.send("No party channels found to broadcast.", ephemeral=True)


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
        if not is_profile_complete(profile):
            return await interaction.response.send_message(
                "❌ **Access Denied!** Your profile is incomplete.\n"
                "👉 Please use `/mygear` to set up your **IGN, Timezone, and Gears** before using this function.", 
                ephemeral=True
            )
        
        party_id = self.select.values[0]
        existing_party = await parties_col.find_one({"members.user_id": interaction.user.id})
        if existing_party:
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
        if not is_profile_complete(profile):
            return await interaction.response.send_message(
                "❌ **Access Denied!** Your profile is incomplete.\n"
                "👉 Please use `/mygear` to set up your **IGN, Timezone, and Gears** before creating a party.", 
                ephemeral=True
            )
            
        if await parties_col.find_one({"members.user_id": interaction.user.id}):
            return await interaction.response.send_message("❌ You are already in a party!", ephemeral=True)
            
        await interaction.response.send_modal(CreatePartyModal(self.bot, self, interaction))

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
    role = discord.ui.TextInput(label='Your Role (e.g., DPS, TANK, UFM)', placeholder='Type your role...', required=True)

    def __init__(self, bot, party_id):
        super().__init__()
        self.bot = bot
        self.party_id = party_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        profile = await get_player_profile(interaction.user.id)
        
        if not party or not is_profile_complete(profile):
            return await interaction.followup.send("Party or Profile not found. Please setup your profile completely using `/mygear`.", ephemeral=True)

        applicant_ign = profile.get('ign')
        role_entered = self.role.value.strip()
        stats = profile.get("my_stats", {})
        gear_summary = await get_formatted_gear_summary(stats, role_entered)

        leader = self.bot.get_user(party.get('leader_id', 0)) or await self.bot.fetch_user(party.get('leader_id', 0))
        if leader:
            embed = discord.Embed(title="📩 Join Request Received!", color=discord.Color.green())
            embed.add_field(name="Applicant", value=applicant_ign, inline=True)
            embed.add_field(name="Role Selected", value=role_entered.upper(), inline=True)
            embed.add_field(name="Gear profile", value=gear_summary, inline=False)
            
            try:
                await leader.send(embed=embed, view=RequestJoinView(self.bot, self.party_id, interaction.user.id, applicant_ign, role_entered))
                await interaction.followup.send("✅ Request sent!", ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send("❌ Cannot DM the leader.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Leader not found.", ephemeral=True)


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
        
        if not is_profile_complete(profile):
            return await interaction.followup.send("⚠️ Please setup your profile completely using `/mygear` first.", ephemeral=True)
            
        time_val = self.start_time.value.strip()
        tz_offset = float(profile.get('tz_offset', 7.0))
        formatted_time = get_discord_timestamp(time_val, tz_offset)
        
        leader_ign = profile.get('ign')
        role_entered = self.role.value.strip()

        party_doc = {
            "leader_id": interaction.user.id,
            "leader_ign": leader_ign, 
            "dg_name": self.dg_name.value,
            "start_time": formatted_time,
            "requirements": self.requirements.value,
            "members": [{"user_id": interaction.user.id, "ign": leader_ign, "role": role_entered}], 
            "broadcasts": [],
            "chat_channel_id": None
        }
        
        result = await parties_col.insert_one(party_doc)
        party_doc["_id"] = result.inserted_id

        await handle_cross_server_chat(self.bot, party_doc, action="create", guild=interaction.guild)

        embed = create_party_embed(party_doc)
        dg_config = {"dg_name": self.dg_name.value}
        broadcast_records = await broadcast_to_all_servers(self.bot, embed, str(result.inserted_id), dg_config, interaction.guild)
        
        if broadcast_records:
            await parties_col.update_one({"_id": result.inserted_id}, {"$set": {"broadcasts": broadcast_records}})
            
        await interaction.followup.send("✅ Created party!", ephemeral=True)
        await self.lobby_view.update_lobby(self.parent_interaction, self.lobby_view.page)


class EditPartyInfoModal(discord.ui.Modal, title='Edit Party Information'):
    new_name = discord.ui.TextInput(
        label='Dungeon Name', 
        required=True
    )
    new_time = discord.ui.TextInput(
        label='Start Time (HH:MM) - Leave blank to keep', 
        placeholder='E.g., 21:30 (Để trống nếu không muốn đổi giờ)', 
        required=False
    )
    new_req = discord.ui.TextInput(
        label='Requirements', 
        style=discord.TextStyle.paragraph, 
        required=False
    )

    def __init__(self, party, bot):
        super().__init__()
        self.party = party
        self.bot = bot
        self.new_name.default = party.get('dg_name', '')
        self.new_req.default = party.get('requirements', '')

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        update_data = {
            "dg_name": self.new_name.value.strip(),
            "requirements": self.new_req.value.strip()
        }
        
        time_val = self.new_time.value.strip()
        if time_val:
            profile = await get_player_profile(interaction.user.id)
            tz_offset = float(profile.get('tz_offset', 7.0)) if profile else 7.0
            formatted_time = get_discord_timestamp(time_val, tz_offset)
            update_data["start_time"] = formatted_time
            
        await parties_col.update_one({"_id": self.party['_id']}, {"$set": update_data})
        asyncio.create_task(update_broadcast_messages(self.bot, str(self.party['_id'])))
        await interaction.followup.send("✅ Party information updated successfully!", ephemeral=True)


class NewOwnerBroadcastModal(discord.ui.Modal, title='Global Update Announcement'):
    announcement_title = discord.ui.TextInput(
        label="Announcement Title",
        placeholder="Example: New feature update v2.0....",
        required=True,
        max_length=256
    )
    
    announcement_content = discord.ui.TextInput(
        label="Detail content",
        style=discord.TextStyle.paragraph,
        placeholder="Enter the details of your update or announcement here..",
        required=True,
        max_length=4000
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        embed = discord.Embed(
            title=f"📢 {self.announcement_title.value}",
            description=self.announcement_content.value,
            color=discord.Color.brand_green(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Global System Announcement")
        
        success_count = 0
        failed_count = 0
        
        async for config in server_configs_col.find({"news_channel_id": {"$exists": True}}):
            channel_id = config.get("news_channel_id")
            if not channel_id:
                continue
                
            channel = self.bot.get_channel(channel_id)
            if not channel:
                try: 
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception: 
                    pass
            
            if channel:
                try:
                    await channel.send(embed=embed)
                    success_count += 1
                    continue
                except Exception:
                    pass 
            
            failed_count += 1
            
        await interaction.followup.send(
            f"✅ **Phát sóng hoàn tất!**\n"
            f"• Thành công: **{success_count}** server.\n"
            f"• Thất bại (Không có quyền/Mất kênh): **{failed_count}** server.", 
            ephemeral=True
        )

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
            member = bot.get_user(user_id)
            if not member:
                try: member = await bot.fetch_user(user_id)
                except: pass
            
            if member:
                await member.send(f"👋 **Party Chat Joined!** You are now in the party for **{dg_name}**.\n💬 *Tips: Any message you send to me here will be forwarded to your party members.*")
            
            new_member_ign = "A new member"
            for m in party.get('members', []):
                if m['user_id'] == user_id:
                    new_member_ign = m.get('ign', 'A new member')
                    break
                    
            for m in party.get('members', []):
                if m['user_id'] != user_id:
                    other = bot.get_user(m['user_id'])
                    if not other:
                        try: other = await bot.fetch_user(m['user_id'])
                        except: pass
                    if other:
                        await other.send(f"📥 **{new_member_ign if new_member_ign != 'A new member' else (member.name if member else 'Someone')}** has joined the party chat!")

        elif action == "remove" and user_id:
            left_ign = "A member"
            for m in party.get('members', []):
                if m.get('user_id') == user_id:
                    left_ign = m.get('ign', 'Unknown')
                    break
                    
            for m in party.get('members', []):
                if m['user_id'] != user_id:
                    other = bot.get_user(m['user_id'])
                    if not other:
                        try: other = await bot.fetch_user(m['user_id'])
                        except: pass
                    if other:
                        await other.send(f"🚪 **{left_ign}** has left the party chat.")
                        
    except Exception as e: 
        print(f"Chat Relay error: {e}")


# --- COG SETUP ---

class PartyFinderCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is not None:
            return

        party = await parties_col.find_one({"members.user_id": message.author.id})
        if not party:
            return 

        sender_ign = "Unknown"
        for m in party.get('members', []):
            if m['user_id'] == message.author.id:
                sender_ign = m.get('ign', message.author.name)
                break

        msg_content = message.content
        
        if "@everyone" in msg_content or "@all" in msg_content:
            mentions = " ".join([f"<@{m['user_id']}>" for m in party.get('members', [])])
            msg_content = msg_content.replace("@everyone", mentions).replace("@all", mentions)
        else:
            for m in party.get('members', []):
                m_ign = m.get('ign')
                if m_ign:
                    pattern = re.compile(rf"@{re.escape(m_ign)}(?!\w)", re.IGNORECASE)
                    msg_content = pattern.sub(f"<@{m['user_id']}>", msg_content)

        dg_name = party.get('dg_name', 'Unknown DG')
        chat_content = f"**[{dg_name}] {sender_ign}**: {msg_content}"
        
        if message.attachments:
            attachment_urls = "\n".join([att.url for att in message.attachments])
            chat_content += f"\n{attachment_urls}"

        for m in party.get('members', []):
            if m['user_id'] != message.author.id:
                target_user = self.bot.get_user(m['user_id'])
                if not target_user:
                    try: target_user = await self.bot.fetch_user(m['user_id'])
                    except Exception: continue 
                
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
            
            if not is_profile_complete(profile):
                return await interaction.response.send_message(
                    "❌ **Access Denied!** Your profile is incomplete.\n"
                    "👉 Please use `/mygear` to set up your **IGN, Timezone, and Gears** before using this function.", 
                    ephemeral=True
                )
                
            existing_party = await parties_col.find_one({"members.user_id": interaction.user.id})
            if existing_party:
                return await interaction.response.send_message("❌ You are already in a party!", ephemeral=True)
                
            await interaction.response.send_modal(JoinPartyModal(self.bot, party_id_str))
            
        elif custom_id == "bcast_lobby":
            await interaction.response.defer(ephemeral=True)
            profile = await get_player_profile(interaction.user.id)
            
            if not is_profile_complete(profile):
                return await interaction.followup.send(
                    "❌ **Access Denied!** Your profile is incomplete.\n"
                    "👉 Please use `/mygear` to set up your **IGN, Timezone, and Gears** before using this function.", 
                    ephemeral=True
                )

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
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="setup_party_channel", description="Configure Channel ID to receive Party Board notifications for this server.")
    @app_commands.describe(channel="Select a text channel to receive public party-seeking posts")
    async def setup_party_channel(self, interaction: discord.Interaction, channel: discord.abc.GuildChannel):
        try:
            await interaction.response.defer(ephemeral=True)
            if not interaction.user.guild_permissions.administrator:
                return await interaction.followup.send("❌ You need administrator privileges!", ephemeral=True)
            
            await server_configs_col.update_one(
                {"guild_id": interaction.guild_id},
                {"$set": {"party_channel_id": channel.id}},
                upsert=True
            )
            await interaction.followup.send(f"✅ {channel.mention} will receive party notifications.", ephemeral=True)
        except Exception as e:
            print(f"Error setup_party_channel: {e}")
            await interaction.followup.send("❌ An error occurred during setup. Please check if the bot has View/Send permissions in that channel.", ephemeral=True)

    @app_commands.command(name="setup_news_channel", description="Select channel to receive update/bot annoucement")
    @app_commands.describe(channel="Select a text channel to receive bot updates")
    async def setup_news_channel(self, interaction: discord.Interaction, channel: discord.abc.GuildChannel):
        try:
            await interaction.response.defer(ephemeral=True)
            if not interaction.user.guild_permissions.administrator:
                return await interaction.followup.send("❌ You need administrator privileges!", ephemeral=True)
            
            await server_configs_col.update_one(
                {"guild_id": interaction.guild_id},
                {"$set": {"news_channel_id": channel.id}},
                upsert=True
            )
            await interaction.followup.send(f"✅ The News/Update channel has been set up at: {channel.mention}", ephemeral=True)
        except Exception as e:
            print(f"Error setup_news_channel: {e}")
            await interaction.followup.send("❌ An error occurred during setup. Please check if the bot has View/Send permissions in that channel.", ephemeral=True)



    @app_commands.command(name="ownerbroadcast", description="Send bot update notifications to all News channels (Owner only)")
    async def ownerbroadcast(self, interaction: discord.Interaction):
        if not await self.bot.is_owner(interaction.user):
            return await interaction.response.send_message("❌ You do not have permission to use Developer commands.!", ephemeral=True)
        
        await interaction.response.send_modal(NewOwnerBroadcastModal(self.bot))

    @app_commands.command(name="party_lobby", description="Open the Party Finder Lobby UI")
    async def party_lobby(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await get_player_profile(interaction.user.id)
        
        if not is_profile_complete(profile):
            return await interaction.followup.send(
                "❌ **Access Denied!** Your profile is incomplete.\n"
                "👉 Please use `/mygear` to fully set up your **IGN, Timezone, and Gears** before entering the Lobby.", 
                ephemeral=True
            )

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
        
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(PartyFinderCog(bot))