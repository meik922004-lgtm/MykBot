import discord
from discord.ext import commands
from discord import app_commands
import uuid
import math
from datetime import datetime, timezone
import asyncio

# Import collections từ Database
from Database import players_col, parties_col, dungeon_configs

# ==========================================
# CƠ CHẾ KIỂM TRA PROFILE & CROSS-SERVER PING
# ==========================================

async def check_profile_validity(user_id: int):
    """Kiểm tra xem User đã đăng ký /mygear chưa"""
    player = await players_col.find_one({"user_id": user_id})
    if not player or "my_stats" not in player or not player["my_stats"].get("gear"):
        return False, None, None
    return True, player.get("ign", "Unknown"), player["my_stats"]["gear"]

def get_cross_server_ping(guild: discord.Guild, dungeon_name: str) -> str:
    """Quét Role theo TÊN trong từng Server riêng biệt để Ping Cross-Server"""
    dungeon_lower = dungeon_name.lower()
    KEYWORDS = ["nanomon", "kimera", "myotismon", "raid"]
    matched_kw = next((k for k in KEYWORDS if k in dungeon_lower), None)
    
    if matched_kw:
        for role in guild.roles:
            if matched_kw in role.name.lower():
                return role.mention
    return ""

async def perform_cross_server_broadcast(client: discord.Client, party: dict):
    """Gửi Broadcast đến TOÀN BỘ server có kênh #party-board"""
    embed = discord.Embed(
        title=f"📢 CROSS-SERVER RECRUITMENT: {party['dungeon'].upper()}",
        description=f"**Leader:** <@{party['leader_id']}>\n"
                    f"**Slots Available:** `{len(party.get('members', []))}/{party.get('slots', 4)}`\n"
                    f"**Start Time:** ⏰ `{party.get('start_time', 'ASAP')}`\n"
                    f"**Requirements:** {party.get('requirements', 'None')}",
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"Party ID: {party['id']} • Cross-Server Network")

    count = 0
    for guild in client.guilds:
        chan = discord.utils.get(guild.text_channels, name="party-board")
        if chan:
            ping = get_cross_server_ping(guild, party['dungeon'])
            view = BroadcastJoinView(party['id'])
            try:
                await chan.send(content=ping, embed=embed, view=view)
                count += 1
            except discord.Forbidden:
                pass
    return count

# ==========================================
# CONSTANTS & HELPER FUNCTIONS
# ==========================================

async def build_lobby_embed(page: int = 1, search_query: str = None):
    query_filter = {}
    if search_query:
        query_filter["dungeon"] = {"$regex": search_query, "$options": "i"}

    total_parties = await parties_col.count_documents(query_filter)
    per_page = 5
    max_pages = max(1, math.ceil(total_parties / per_page))
    
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
        leader_id = party.get('leader_id')
        if not leader_id:
            continue 
            
        count += 1
        embed.add_field(
            name=f"{count}. 🏰 {party['dungeon'].upper()} [ID: {party['id']}]",
            value=f"• **Leader:** <@{leader_id}>\n"
                  f"• **Slots:** `{len(party.get('members', []))}/{party.get('slots', 4)}` | ⏰ `{party.get('start_time', 'ASAP')}`\n"
                  f"• **Requirements:** *{party.get('requirements', 'None')}*",
            inline=False
        )
        
    if count == 0:
        embed.description += "\n\n🛑 *No active parties found matching the criteria.*"

    return embed, max_pages

def build_manage_embed(party):
    embed = discord.Embed(
        title=f"🛡️ PARTY MANAGEMENT: {party['dungeon'].upper()}",
        description=f"**Party ID:** `{party['id']}`\n**Start Time:** `{party.get('start_time', 'ASAP')}`\n**Requirements:** {party.get('requirements', 'None')}",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc)
    )
    
    leader_id = party.get("leader_id", 0)
    embed.add_field(name="👑 Party Leader", value=f"<@{leader_id}>" if leader_id else "*Unknown*", inline=False)
    
    members_str = ""
    for idx, m in enumerate(party.get("members", []), 1):
        members_str += f"{idx}. <@{m['user_id']}> (IGN: `{m.get('ign', 'Unknown')}`)\n"
    
    embed.add_field(name=f"👥 Members ({len(party.get('members', []))}/{party.get('slots', 4)})", value=members_str or "*Empty*", inline=False)
    
    reqs_str = ""
    for r in party.get("requests", []):
        reqs_str += f"• <@{r['user_id']}> | Role: `{r.get('role', 'DPS')}`\n  ↳ IGN: `{r.get('ign', 'Unknown')}` | Gear: `{r.get('gear', 'Chưa cập nhật')}`\n"
        
    embed.add_field(name=f"⏳ Pending Requests ({len(party.get('requests', []))})", value=reqs_str or "*No pending requests*", inline=False)
    return embed

# ==========================================
# INTERACTIVE MODALS
# ==========================================

class CreatePartyModal(discord.ui.Modal):
    dungeon = discord.ui.TextInput(label="Dungeon Name", placeholder="e.g., Nanomon / Kimera", max_length=50)
    slots = discord.ui.TextInput(label="Max Slots (2-4)", default="4", max_length=1)
    start_time = discord.ui.TextInput(label="Expected Start Time", default="ASAP", max_length=30)
    reqs = discord.ui.TextInput(label="Requirements", required=False, max_length=100)

    def __init__(self, ign: str):
        super().__init__(title="Create New Party")
        self.ign = ign

    async def on_submit(self, interaction: discord.Interaction):
        try:
            max_slots = int(self.slots.value)
            if not (2 <= max_slots <= 4): raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Invalid slots number (2-4).", ephemeral=True)
            return

        user_id = interaction.user.id
        existing = await parties_col.find_one({"leader_id": user_id})
        if existing:
            await interaction.response.send_message("❌ You are already leading another party!", ephemeral=True)
            return

        party_id = str(uuid.uuid4())[:8]
        guild = interaction.guild
        
        # 1. TẠO PHÒNG CHAT KÍN (PRIVATE TEXT CHANNEL)
        channel_id = None
        if guild:
            category = discord.utils.get(guild.categories, name="Raid Parties")
            if not category:
                try:
                    category = await guild.create_category("Raid Parties")
                except discord.Forbidden:
                    category = None
            
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }
            
            try:
                # Format tên kênh: pt-nanomon-a1b2c3d4
                safe_dungeon_name = self.dungeon.value.strip().lower().replace(" ", "-")
                party_channel = await guild.create_text_channel(
                    name=f"pt-{safe_dungeon_name}-{party_id}",
                    category=category,
                    overwrites=overwrites
                )
                channel_id = party_channel.id
                await party_channel.send(f"🛡️ **Khu vực tác chiến kín của tổ đội {self.dungeon.value.strip()}**\nLeader: <@{user_id}>. Thành viên mới sẽ tự động được thêm vào kênh này.")
            except discord.Forbidden:
                pass # Bỏ qua nếu Bot không đủ quyền tạo kênh

        new_party = {
            "id": party_id,
            "leader_id": user_id,
            "guild_id": guild.id if guild else None,
            "channel_id": channel_id,
            "dungeon": self.dungeon.value.strip(),
            "slots": max_slots,
            "start_time": self.start_time.value.strip(),
            "requirements": self.reqs.value.strip() or "None",
            "members": [{"user_id": user_id, "ign": self.ign, "role": "Leader"}],
            "requests": [],
            "created_at": datetime.now(timezone.utc)
        }
        
        await parties_col.insert_one(new_party)
        await perform_cross_server_broadcast(interaction.client, new_party)
        
        embed, _ = await build_lobby_embed(page=1)
        await interaction.response.edit_message(embed=embed, view=LobbyView(page=1))


class JoinByIdModal(discord.ui.Modal):
    party_id = discord.ui.TextInput(label="Enter Party ID to Join", min_length=4, max_length=10)
    
    def __init__(self, ign: str, gear: str):
        super().__init__(title="Join Party by ID")
        self.ign = ign
        self.gear = gear

    async def on_submit(self, interaction: discord.Interaction):
        target_id = self.party_id.value.strip()
        party = await parties_col.find_one({"id": target_id})
        
        if not party:
            await interaction.response.send_message("❌ Party ID không tồn tại hoặc đã giải tán.", ephemeral=True)
            return

        if len(party.get("members", [])) >= party.get("slots", 4):
            await interaction.response.send_message("🛑 Phòng này đã đầy slot!", ephemeral=True)
            return

        select_view = discord.ui.View(timeout=60)
        role_select = discord.ui.Select(
            placeholder="Choose your combat role...",
            options=[
                discord.SelectOption(label="DPS Attacker", value="DPS", emoji="⚔️"),
                discord.SelectOption(label="Utility / Flex", value="UFM", emoji="🪃"),
                discord.SelectOption(label="Tanker", value="TANK", emoji="🧱")
            ]
        )

        async def select_callback(inter: discord.Interaction):
            new_request = {
                "user_id": inter.user.id, 
                "ign": self.ign, 
                "role": role_select.values[0], 
                "gear": self.gear, 
                "timestamp": datetime.now(timezone.utc)
            }
            await parties_col.update_one({"id": target_id}, {"$push": {"requests": new_request}})
            await inter.response.send_message("✅ Đã gửi yêu cầu tham gia tới Leader!", ephemeral=True)

        role_select.callback = select_callback
        select_view.add_item(role_select)
        await interaction.response.send_message(f"Bạn đang xin vào phòng `{party['dungeon']}`. Hãy chọn Role:", view=select_view, ephemeral=True)


class EditNeedModal(discord.ui.Modal):
    recruitment = discord.ui.TextInput(label="New requirements", max_length=100)
    def __init__(self, party_id: str):
        super().__init__(title="Update Requirements")
        self.party_id = party_id
    async def on_submit(self, interaction: discord.Interaction):
        new_req = self.recruitment.value.strip() or "None"
        await parties_col.update_one({"id": self.party_id}, {"$set": {"requirements": new_req}})
        party = await parties_col.find_one({"id": self.party_id})
        embed = build_manage_embed(party)
        await interaction.response.edit_message(embed=embed, view=ManagePartyView(self.party_id, interaction.user.id))

# ==========================================
# PUBLIC VIEWS (BROADCAST & LOBBY)
# ==========================================

class BroadcastJoinView(discord.ui.View):
    def __init__(self, party_id: str):
        super().__init__(timeout=None)
        self.party_id = party_id
        self.join_req_trigger.custom_id = f"btn_join_req:{party_id}"

    @discord.ui.button(label="Join Request", style=discord.ButtonStyle.primary)
    async def join_req_trigger(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_valid, ign, gear = await check_profile_validity(interaction.user.id)
        if not is_valid:
            await interaction.response.send_message("❌ **Truy cập bị từ chối:** Bạn phải thiết lập thông tin Profile thông qua lệnh `/mygear` trước khi xin gia nhập Party!", ephemeral=True)
            return

        party = await parties_col.find_one({"id": self.party_id})
        if not party:
            await interaction.response.send_message("❌ This party has already been disbanded.", ephemeral=True)
            return

        if len(party.get("members", [])) >= party.get("slots", 4):
            await interaction.response.send_message("🛑 This party is already full!", ephemeral=True)
            return

        select_view = discord.ui.View(timeout=60)
        role_select = discord.ui.Select(
            placeholder="Choose your combat role...",
            options=[
                discord.SelectOption(label="DPS Attacker", value="DPS", emoji="⚔️"),
                discord.SelectOption(label="Utility / Flex", value="UFM", emoji="🪃"),
                discord.SelectOption(label="Tanker", value="TANK", emoji="🧱")
            ]
        )

        async def select_callback(inter: discord.Interaction):
            new_request = {
                "user_id": inter.user.id, 
                "ign": ign, 
                "role": role_select.values[0], 
                "gear": gear, 
                "timestamp": datetime.now(timezone.utc)
            }
            await parties_col.update_one({"id": self.party_id}, {"$push": {"requests": new_request}})
            await inter.response.send_message("✅ Đã gửi yêu cầu tham gia tới Leader!", ephemeral=True)

        role_select.callback = select_callback
        select_view.add_item(role_select)
        await interaction.response.send_message("Select your role preference:", view=select_view, ephemeral=True)


class SearchDungeonModal(discord.ui.Modal):
    query = discord.ui.TextInput(label="Enter dungeon keyword", required=False)
    def __init__(self, current_page: int):
        super().__init__(title="Search For Parties")
        self.current_page = current_page
    async def on_submit(self, interaction: discord.Interaction):
        search_str = self.query.value.strip() or None
        embed, _ = await build_lobby_embed(page=1, search_query=search_str)
        await interaction.response.edit_message(embed=embed, view=LobbyView(page=1, search_query=search_str))


class LobbyView(discord.ui.View):
    def __init__(self, page: int = 1, search_query: str = None):
        super().__init__(timeout=None)
        self.page = page
        self.search_query = search_query

    @discord.ui.button(label="◀️ Prev", style=discord.ButtonStyle.secondary, row=0, custom_id="lobby_prev")
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 1:
            self.page -= 1
            embed, _ = await build_lobby_embed(self.page, self.search_query)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.send_message("You are already on the first page!", ephemeral=True)

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.secondary, row=0, custom_id="lobby_next")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed, max_pages = await build_lobby_embed(self.page, self.search_query)
        if self.page < max_pages:
            self.page += 1
            embed, _ = await build_lobby_embed(self.page, self.search_query)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.send_message("You are already on the last page!", ephemeral=True)

    @discord.ui.button(label="🔍 Filter", style=discord.ButtonStyle.primary, row=0, custom_id="lobby_filter")
    async def filter_dungeon(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchDungeonModal(self.page))

    @discord.ui.button(label="➕ Create Party", style=discord.ButtonStyle.success, row=0, custom_id="lobby_create")
    async def create_party_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_valid, ign, _ = await check_profile_validity(interaction.user.id)
        if not is_valid:
            await interaction.response.send_message("❌ **Từ chối:** Bạn chưa cập nhật Gear! Vui lòng dùng lệnh `/mygear` trước khi tạo phòng.", ephemeral=True)
            return
        await interaction.response.send_modal(CreatePartyModal(ign))

    @discord.ui.button(label="⚙️ Manage My Party", style=discord.ButtonStyle.danger, row=0, custom_id="lobby_manage")
    async def manage_party_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        party = await parties_col.find_one({"$or": [{"leader_id": user_id}, {"members.user_id": user_id}]})
        if not party:
            await interaction.response.send_message("❌ Bạn chưa tham gia bất kỳ tổ đội nào.", ephemeral=True)
            return
        embed = build_manage_embed(party)
        await interaction.response.send_message(embed=embed, view=ManagePartyView(party["id"], user_id), ephemeral=True)

    @discord.ui.button(label="📝 Join Party", style=discord.ButtonStyle.primary, row=1, custom_id="lobby_join")
    async def direct_join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_valid, ign, gear = await check_profile_validity(interaction.user.id)
        if not is_valid:
            await interaction.response.send_message("❌ **Từ chối:** Bạn chưa cập nhật Gear! Vui lòng dùng lệnh `/mygear` trước khi xin gia nhập.", ephemeral=True)
            return
        await interaction.response.send_modal(JoinByIdModal(ign, gear))


# ==========================================
# INTERNAL PRIVATE CONTROL PANEL VIEW
# ==========================================

class ManagePartyView(discord.ui.View):
    def __init__(self, party_id: str, user_id: int):
        super().__init__(timeout=600)
        self.party_id = party_id
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        party = await parties_col.find_one({"id": self.party_id})
        if not party:
            await interaction.response.send_message("❌ Party no longer active.", ephemeral=True)
            return False
        
        is_leader = (party.get("leader_id") == interaction.user.id)
        is_member = any(m["user_id"] == interaction.user.id for m in party.get("members", []))
        
        if not (is_leader or is_member):
            await interaction.response.send_message("❌ Bạn không có quyền truy cập bảng điều khiển này.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, row=0)
    async def approve_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"id": self.party_id})
        if party.get("leader_id") != interaction.user.id:
            await interaction.response.send_message("❌ Chỉ Leader mới được duyệt.", ephemeral=True)
            return

        if not party.get("requests", []):
            await interaction.response.send_message("⚠️ Không có yêu cầu nào đang chờ.", ephemeral=True)
            return

        select_view = discord.ui.View(timeout=60)
        options = [discord.SelectOption(label=f"{r['ign']} ({r['role']})", value=str(r['user_id'])) for r in party["requests"][:25]]
        user_select = discord.ui.Select(placeholder="Select applicant to approve...", options=options)

        async def approve_callback(inter: discord.Interaction):
            target_id = int(user_select.values[0])
            curr_party = await parties_col.find_one({"id": self.party_id})
            
            if len(curr_party.get("members", [])) >= curr_party.get("slots", 4):
                await inter.response.send_message("❌ Không thể duyệt: Phòng đã đầy!", ephemeral=True)
                return

            target_req = next((r for r in curr_party["requests"] if r["user_id"] == target_id), None)
            if target_req:
                await parties_col.update_one(
                    {"id": self.party_id},
                    {
                        "$pull": {"requests": {"user_id": target_id}},
                        "$push": {"members": {"user_id": target_id, "ign": target_req["ign"], "role": target_req["role"]}}
                    }
                )
                
                # Cấp quyền vào KÊNH KÍN
                guild = inter.client.get_guild(curr_party.get("guild_id", 0))
                if guild and curr_party.get("channel_id"):
                    channel = guild.get_channel(curr_party["channel_id"])
                    if channel:
                        try:
                            # Fetch user đảm bảo lấy được object Member ngay cả khi chưa cache
                            target_member = guild.get_member(target_id) or await guild.fetch_member(target_id)
                            if target_member:
                                await channel.set_permissions(target_member, read_messages=True, send_messages=True)
                                await channel.send(f"🎉 Chào mừng <@{target_id}> đã gia nhập đội hình tác chiến!")
                        except (discord.Forbidden, discord.NotFound):
                            pass

                # Gửi DM
                user = inter.client.get_user(target_id) or await inter.client.fetch_user(target_id)
                if user:
                    try:
                        await user.send(f"🎉 Chúc mừng! Đơn xin gia nhập phòng Raid **{curr_party['dungeon'].upper()}** đã được Leader chấp nhận!")
                    except discord.Forbidden:
                        pass 

            updated = await parties_col.find_one({"id": self.party_id})
            await inter.response.edit_message(embed=build_manage_embed(updated), view=ManagePartyView(self.party_id, self.user_id))

        user_select.callback = approve_callback
        select_view.add_item(user_select)
        await interaction.response.send_message("Chọn người cần duyệt:", view=select_view, ephemeral=True)

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger, row=0)
    async def reject_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"id": self.party_id})
        if party.get("leader_id") != interaction.user.id:
            await interaction.response.send_message("❌ Chỉ Leader mới được thao tác.", ephemeral=True)
            return

        if not party.get("requests", []):
            await interaction.response.send_message("⚠️ Không có yêu cầu nào.", ephemeral=True)
            return

        select_view = discord.ui.View(timeout=60)
        options = [discord.SelectOption(label=r["ign"], value=str(r["user_id"])) for r in party["requests"][:25]]
        user_select = discord.ui.Select(placeholder="Select applicant to reject...", options=options)

        async def reject_callback(inter: discord.Interaction):
            target_id = int(user_select.values[0])
            curr_party = await parties_col.find_one({"id": self.party_id})
            
            await parties_col.update_one({"id": self.party_id}, {"$pull": {"requests": {"user_id": target_id}}})
            
            user = inter.client.get_user(target_id) or await inter.client.fetch_user(target_id)
            if user:
                try:
                    await user.send(f"💔 Rất tiếc, đơn xin gia nhập phòng Raid **{curr_party['dungeon'].upper()}** của bạn đã bị Leader từ chối.")
                except discord.Forbidden:
                    pass

            updated = await parties_col.find_one({"id": self.party_id})
            await inter.response.edit_message(embed=build_manage_embed(updated), view=ManagePartyView(self.party_id, self.user_id))

        user_select.callback = reject_callback
        select_view.add_item(user_select)
        await interaction.response.send_message("Chọn người cần loại bỏ:", view=select_view, ephemeral=True)

    @discord.ui.button(label="📝 Edit Needs", style=discord.ButtonStyle.secondary, row=0)
    async def edit_requirements(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"id": self.party_id})
        if party.get("leader_id") != interaction.user.id:
            await interaction.response.send_message("❌ Only leader can edit.", ephemeral=True)
            return
        await interaction.response.send_modal(EditNeedModal(self.party_id))

    @discord.ui.button(label="📢 Broadcast", style=discord.ButtonStyle.primary, row=1)
    async def manual_broadcast(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"id": self.party_id})
        if party.get("leader_id") != interaction.user.id:
            await interaction.response.send_message("❌ Chỉ Leader mới được phát Broadcast.", ephemeral=True)
            return
            
        await interaction.response.defer(ephemeral=True)
        count = await perform_cross_server_broadcast(interaction.client, party)
        await interaction.followup.send(f"✅ Đã phát loa truy tìm thành viên trên **{count}** máy chủ.", ephemeral=True)

    @discord.ui.button(label="💥 Disband / Leave", style=discord.ButtonStyle.danger, row=1)
    async def leave_or_disband(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"id": self.party_id})
        
        # Kết nối tới Kênh Kín (nếu có)
        guild = interaction.client.get_guild(party.get("guild_id", 0))
        channel = guild.get_channel(party.get("channel_id", 0)) if guild else None

        if party.get("leader_id") == interaction.user.id:
            # === LEADER DISBAND (TỰ ĐỘNG XÓA GROUP CHAT) ===
            if channel:
                try:
                    await channel.delete(reason="Party disbanded by Leader")
                except discord.Forbidden:
                    pass
            await parties_col.delete_one({"id": self.party_id})
            await interaction.response.edit_message(content="💥 *Phòng đã bị giải tán và kênh chat kín đã được thu hồi.*", embed=None, view=None)
        
        else:
            # === MEMBER LEAVE (TỰ ĐỘNG KICK KHỎI GROUP CHAT) ===
            if channel:
                try:
                    member = guild.get_member(interaction.user.id) or await guild.fetch_member(interaction.user.id)
                    if member:
                        await channel.set_permissions(member, overwrite=None) # Xóa quyền xem
                        await channel.send(f"🏃 <@{interaction.user.id}> đã rời khỏi tổ đội.")
                except (discord.Forbidden, discord.NotFound):
                    pass
            
            await parties_col.update_one({"id": self.party_id}, {"$pull": {"members": {"user_id": interaction.user.id}}})
            updated = await parties_col.find_one({"id": self.party_id})
            await interaction.response.edit_message(embed=build_manage_embed(updated), view=self)


# ==========================================
# MAIN COMMANDS EXTENSION COG CLASS
# ==========================================

class PartyFinder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="party_lobby", description="Open the system dungeon matchmaking party hub interface panel")
    async def party_lobby(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            embed, _ = await build_lobby_embed(page=1)
            view = LobbyView(page=1)
            await interaction.followup.send(embed=embed, view=view)
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Lỗi hệ thống: {e}", ephemeral=True)
            except discord.errors.NotFound:
                pass

    @app_commands.command(name="manage_party", description="Open your current active party group panel dashboard")
    async def manage_party(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        party = await parties_col.find_one({"$or": [{"leader_id": user_id}, {"members.user_id": user_id}]})
        
        if not party:
            await interaction.response.send_message("❌ Bạn chưa tham gia phòng Raid nào.", ephemeral=True)
            return
            
        embed = build_manage_embed(party)
        view = ManagePartyView(party["id"], user_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(PartyFinder(bot))