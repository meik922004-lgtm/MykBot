import discord
from discord.ext import commands
from discord import app_commands
import uuid
import math
from datetime import datetime, timezone
import asyncio

# Import collections từ Database
from Database import players_col, parties_col, dungeon_configs_col

# ==========================================
# CƠ CHẾ KIỂM TRA PROFILE & ĐIỀU KIỆN (GATEKEEPING)
# ==========================================

async def check_profile_validity(user_id: int):
    """Check Profile based on new DB structure"i"""
    player = await players_col.find_one({"user_id": user_id})
    if not player or "my_stats" not in player:
        return False, None, None
    
    stats = player["my_stats"]
    active_role = stats.get("role", "TANK") # Mặc định là TANK nếu không thấy
    data_source = stats.get(active_role, stats)
    profile_data = {
        "role": stats.get("role", "Unknown"),
        "gear": stats.get("gear", "None"),
        "vice": stats.get("vice", "None"),
        "deck": stats.get("deck", "None")
    }
    return True, player.get("ign", "Unknown"), profile_data
async def check_gear_requirement(profile_data: dict, dungeon_name: str) -> bool:
    """
    So sánh profile của người chơi với danh sách yêu cầu (reqs) trong Database.
    Nếu trang bị của người chơi không nằm trong danh sách cho phép của Dungeon -> Trả về False (Chặn)
    """
    dg_config = await dungeon_configs_col.find_one({"dg_name": {"$regex": f"^{dungeon_name}$", "$options": "i"}})
    
    # Nếu Dungeon không tồn tại hoặc không có setup yêu cầu (reqs), mặc định cho phép vào
    if not dg_config or "reqs" not in dg_config:
        return True 

    reqs = dg_config["reqs"]
    my_stats = profile_data.get("my_stats", {})
    user_gear = profile_data.get("gear", "")
    user_vice = profile_data.get("vice", "")
    user_deck = profile_data.get("deck", "")

    # Kiểm tra GEAR
    # Nếu Dungeon có mảng 'gear' và gear của người chơi không nằm trong mảng đó -> Không đạt
    if "gear" in reqs and isinstance(reqs["gear"], list) and len(reqs["gear"]) > 0:
        if user_gear not in reqs["gear"]:
            return False
            
    # Kiểm tra VICE
    if "vice" in reqs and isinstance(reqs["vice"], list) and len(reqs["vice"]) > 0:
        if user_vice not in reqs["vice"]:
            return False
            
    # Kiểm tra DECK
    if "deck" in reqs and isinstance(reqs["deck"], list) and len(reqs["deck"]) > 0:
        if user_deck not in reqs["deck"]:
            return False

    return True

async def get_dg_ping_role(dungeon_name: str) -> str:
    """Get the Role ID ping directly from dungeon_configs."""
    dg_config = await dungeon_configs_col.find_one({"dg_name": {"$regex": f"^{dungeon_name}$", "$options": "i"}})
    if dg_config and "ping_role" in dg_config:
        return f"<@&{dg_config['ping_role']}>"
    return ""

async def perform_cross_server_broadcast(client: discord.Client, party: dict):
    ping_tag = await get_dg_ping_role(party['dungeon'])
    
    embed = discord.Embed(
        title=f"📢 RECRUITMENT: {party['dungeon'].upper()}",
        description=f"**Leader:** <@{party['leader_id']}>\n"
                    f"**Slots:** `{len(party.get('members', []))}/{party.get('slots', 4)}`\n"
                    f"**Start:** ⏰ `{party.get('start_time', 'ASAP')}`\n"
                    f"**Reqs:** {party.get('requirements', 'None')}",
        color=discord.Color.gold()
    )
    
    # Check trạng thái gatekeeping để hiển thị footer
    is_gatekeep = party.get("gatekeeping_enabled", True)
    if not is_gatekeep:
        embed.set_footer(text="Cross-server Network | No Min Req")
    else:
        embed.set_footer(text=f"Keyword: {party['dungeon']} • Cross-server Network")

    count = 0
    for guild in client.guilds:
        chan = discord.utils.get(guild.text_channels, name="party-board")
        if chan:
            # SỬA Ở ĐÂY: Truyền thêm tham số gatekeeping_enabled vào View
            view = BroadcastJoinView(
                party['id'], 
                party['dungeon'], 
                is_gatekeep
            )
            try:
                await chan.send(content=ping_tag if ping_tag else None, embed=embed, view=view)
                count += 1
            except discord.Forbidden: pass
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

    embed = discord.Embed(title="⚔️ SYSTEM PARTY LOBBY HUB ⚔️", color=discord.Color.blue())
    embed.set_footer(text=f"Page {page}/{max_pages} • Total Parties: {total_parties}")

    for party in active_parties:
        status = "✅ Gatekeep" if party.get("gatekeeping_enabled", True) else "⚠️ Open"
        embed.add_field(
            name=f"🏰 {party['dungeon'].upper()} [{status}]",
            value=f"• **Leader:** <@{party.get('leader_id')}>\n"
                  f"• **Slots:** `{len(party.get('members', []))}/{party.get('slots', 4)}` | ⏰ `{party.get('start_time', 'ASAP')}`",
            inline=False
        )
    return embed, max_pages

def build_manage_embed(party):
    embed = discord.Embed(
        title=f"🛡️ PARTY MANAGEMENT: {party['dungeon'].upper()}",
        description=f"**Start Time:** `{party.get('start_time', 'ASAP')}`\n**Requirements:** {party.get('requirements', 'None')}\n*(Applicant requests are now sent directly to your DMs)*",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc)
    )
    
    leader_id = party.get("leader_id", 0)
    embed.add_field(name="👑 Party Leader", value=f"<@{leader_id}>" if leader_id else "*Unknown*", inline=False)
    
    members_str = ""
    for idx, m in enumerate(party.get("members", []), 1):
        members_str += f"{idx}. <@{m['user_id']}> (IGN: `{m.get('ign', 'Unknown')}` | Role: `{m.get('role', 'Any')}`)\n"
    
    embed.add_field(name=f"👥 Members ({len(party.get('members', []))}/{party.get('slots', 4)})", value=members_str or "*Empty*", inline=False)
    return embed

# ==========================================
# INTERACTIVE MODALS & VIEWS
# ==========================================
async def get_dungeon_match(dungeon_name: str):
    # Loại bỏ từ "dungeon" nếu có, cắt khoảng trắng
    clean_name = dungeon_name.lower().replace("dungeon", "").strip()
    
    # Chỉ tìm nếu input có từ 3 kí tự trở lên
    if len(clean_name) < 3:
        return None
        
    # Tìm kiếm trong database dungeon_configs
    # $regex tìm chuỗi chứa từ khóa, $options: 'i' để không phân biệt hoa thường
    return await dungeon_configs_col.find_one({
        "dg_name": {"$regex": clean_name, "$options": "i"}
    })

class CreatePartyModal(discord.ui.Modal):
    dungeon = discord.ui.TextInput(label="Dungeon Name/Keyword", placeholder="e.g., PDG, MDG...", min_length=3)
    slots = discord.ui.TextInput(label="Max Slots (2-4)", default="4", max_length=1)
    start_time = discord.ui.TextInput(label="Start Time", default="ASAP")
    reqs = discord.ui.TextInput(label="Requirements", required=False)

    def __init__(self, ign: str):
        super().__init__(title="Create New Party")
        self.ign = ign

    async def on_submit(self, interaction: discord.Interaction):
        dg_input = self.dungeon.value.strip()
        matched_config = await get_dungeon_match(dg_input)

        # Logic: Tìm thấy -> dùng tên chuẩn & bật gatekeep. Không thấy -> dùng tên nhập & tắt gatekeep
        gatekeeping = False
        dg_name = dg_input.upper() # Mặc định lấy tên người dùng nhập nếu không match
        
        if matched_config:
            dg_name = matched_config["dg_name"] # Lấy tên chuẩn từ DB (VD: "Stage of Clown(PIED)")
            gatekeeping = True

        # Chuẩn bị dữ liệu tạo phòng
        new_party = {
            "id": str(uuid.uuid4())[:8],
            "leader_id": interaction.user.id,
            "dungeon": dg_name,
            "gatekeeping_enabled": gatekeeping, # Lưu flag này để dùng khi check Join
            "slots": int(self.slots.value),
            "start_time": self.start_time.value,
            "requirements": self.reqs.value or "None",
            "members": [{"user_id": interaction.user.id, "ign": self.ign, "role": "Leader"}],
            "connected_channels": [],
            "created_at": datetime.now(timezone.utc)
        }

        # Lưu vào DB
        await parties_col.insert_one(new_party)
        
        # Broadcast ra các channel đã kết nối (nếu có)
        await perform_cross_server_broadcast(interaction.client, new_party)
        
        await interaction.response.send_message(
            f"✅ Party created for **{dg_name}**! (Gatekeep: {'ON' if gatekeeping else 'OFF'})", 
            ephemeral=True
        )

class JoinByKeywordModal(discord.ui.Modal):
    keyword = discord.ui.TextInput(label="Enter Dungeon Keyword", min_length=2, max_length=50)
    
    def __init__(self, ign: str, profile_data: dict):
        super().__init__(title="Join Party by Keyword")
        self.ign = ign
        self.profile_data = profile_data

    async def on_submit(self, interaction: discord.Interaction):
        target_kw = self.keyword.value.strip()
        parties = await parties_col.find({"dungeon": {"$regex": target_kw, "$options": "i"}}).to_list(length=10)
        
        if not parties:
            await interaction.response.send_message("❌ No parties were found recruiting for this Dungeon..", ephemeral=True)
            return
            
        target_party = next((p for p in parties if len(p.get("members", [])) < p.get("slots", 4)), None)
        
        if not target_party:
            await interaction.response.send_message("🛑 All the parties for this Dungeon are full.!", ephemeral=True)
            return

        await handle_join_request(interaction, target_party, self.ign, self.profile_data)


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
# DM APPROVAL SYSTEM & WEBHOOK LOGIC
# ==========================================

async def handle_join_request(interaction: discord.Interaction, party: dict, ign: str, profile_data: dict):
    select_view = discord.ui.View(timeout=60)
    role_select = discord.ui.Select(
        placeholder="Choose your role...",
        options=[
            discord.SelectOption(label="DPS Attacker", value="DPS", emoji="⚔️"),
            discord.SelectOption(label="UFM", value="UFM", emoji="🪃"),
            discord.SelectOption(label="Tanker", value="TANK", emoji="🧱")
        ]
    )
    

    async def select_callback(inter: discord.Interaction):
        selected_role = role_select.values[0]
        leader_id = party['leader_id']
        leader = inter.client.get_user(leader_id) or await inter.client.fetch_user(leader_id)
        
        if leader:
            embed = discord.Embed(
                title=f"📩 NEW: PARTICIPATION REQUIRED {party['dungeon'].upper()}",
                color=discord.Color.orange()
            )
            embed.add_field(name="Player", value=f"<@{inter.user.id}>", inline=True)
            embed.add_field(name="IGN", value=f"`{ign}`", inline=True)
            embed.add_field(name="role", value=f"**{selected_role}**", inline=True)
            embed.add_field(name="Gear profile", value=f"• Gear: `{profile_data['gear']}`\n• Vice: `{profile_data['vice']}`\n• Deck: `{profile_data['deck']}`", inline=False)
            
            dm_view = DMApprovalView(party['id'], inter.user.id, ign, selected_role)
            try:
                await leader.send(embed=embed, view=dm_view)
                await inter.response.send_message("✅Your profile information has been sent to the Leader's DMs.!", ephemeral=True)
            except discord.Forbidden:
                await inter.response.send_message("❌ The leader has locked the DMs, so requests cannot be sent..", ephemeral=True)
        else:
            await inter.response.send_message("❌ Leader could not be found..", ephemeral=True)

    role_select.callback = select_callback
    select_view.add_item(role_select)
    await interaction.response.send_message(f"You are applying to join a `{party['dungeon']}`. Choose your Role.:", view=select_view, ephemeral=True)


class DMApprovalView(discord.ui.View):
    def __init__(self, party_id: str, applicant_id: int, applicant_ign: str, role: str):
        super().__init__(timeout=None) 
        self.party_id = party_id
        self.applicant_id = applicant_id
        self.applicant_ign = applicant_ign
        self.role = role

    @discord.ui.button(label="✅Accept", style=discord.ButtonStyle.success)
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        curr_party = await parties_col.find_one({"id": self.party_id})
        if not curr_party:
            await interaction.response.send_message("❌ This party has disbanded..", ephemeral=True)
            return

        if len(curr_party.get("members", [])) >= curr_party.get("slots", 4):
            await interaction.response.send_message("❌ Unacceptable, the party is already full.!", ephemeral=True)
            return

        applicant = interaction.client.get_user(self.applicant_id) or await interaction.client.fetch_user(self.applicant_id)
        
        # Kiểm tra xem Applicant có ở chung Server với Leader không
        leader_guild_id = curr_party.get("guild_id")
        leader_guild = interaction.client.get_guild(leader_guild_id) if leader_guild_id else None
        applicant_in_leader_guild = False
        member_in_leader_guild = None

        if leader_guild:
            try:
                member_in_leader_guild = leader_guild.get_member(self.applicant_id) or await leader_guild.fetch_member(self.applicant_id)
                if member_in_leader_guild: applicant_in_leader_guild = True
            except:
                pass

        new_connected_node = None
        instruction_msg = "Check out the Party channel.!"

        # NẾU CÙNG SERVER: Cấp quyền trực tiếp vào kênh chính
        if applicant_in_leader_guild and curr_party.get("channel_id"):
            main_chan = leader_guild.get_channel(curr_party["channel_id"])
            if main_chan:
                try:
                    await main_chan.set_permissions(member_in_leader_guild, read_messages=True, send_messages=True)
                    instruction_msg = f"Please go to channel <#{main_chan.id}> on the server.**{leader_guild.name}**."
                except Exception as e:
                    print(f"Lỗi phân quyền: {e}")

        # NẾU KHÁC SERVER (CROSS-SERVER): Tạo Private Thread
        else:
            applicant_guild = None
            base_channel = None
            for g in interaction.client.guilds:
                if g.id == leader_guild_id: continue # Bỏ qua server của Leader
                if g.get_member(self.applicant_id):
                    ch = discord.utils.get(g.text_channels, name="party-board")
                    if ch:
                        applicant_guild = g
                        base_channel = ch
                        break
            
            if applicant_guild and base_channel:
                try:
                    thread = await base_channel.create_thread(
                        name=f"pt-{curr_party['dungeon'].lower()}-{self.party_id}",
                        type=discord.ChannelType.private_thread,
                        invitable=False
                    )
                    applicant_member = applicant_guild.get_member(self.applicant_id)
                    await thread.add_user(applicant_member)
                    await thread.send(f"🎉 <@{self.applicant_id}>Welcome! Messages in this thread will be synchronized to the Leader's group via Webhook.")
                    
                    new_connected_node = {"guild_id": applicant_guild.id, "channel_id": thread.id}
                    instruction_msg = f"Connected! Please chat in the thread **{thread.name}** on the Server.**{applicant_guild.name}**."
                except Exception as e:
                    print(f"Thread creation error: {e}")

        # Cập nhật Database
        update_query = {"$push": {"members": {"user_id": self.applicant_id, "ign": self.applicant_ign, "role": self.role}}}
        if new_connected_node:
            update_query["$push"]["connected_channels"] = new_connected_node

        await parties_col.update_one({"id": self.party_id}, update_query)

        # Thông báo cho Leader
        if leader_guild and curr_party.get("channel_id"):
            channel = leader_guild.get_channel(curr_party["channel_id"])
            if channel:
                msg = "same server" if applicant_in_leader_guild else "another server (Cross-server Webhook)"
                await channel.send(f"🎉 <@{self.applicant_id}> (`{self.applicant_ign}` - {self.role}) đã tham gia Party từ {msg}!")

        # Gửi DM cho người xin
        if applicant:
            try:
                await applicant.send(f"🎉Congratulations, your request to join **{curr_party['dungeon'].upper()}** has been accepted.!\n🔗 **{instruction_msg}**")
            except discord.Forbidden:
                pass 

        button.disabled = True
        self.children[1].disabled = True
        await interaction.response.edit_message(content="✅ **ACCEPTED**", view=self)

    @discord.ui.button(label="❌ reject", style=discord.ButtonStyle.danger)
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        curr_party = await parties_col.find_one({"id": self.party_id})
        dg_name = curr_party['dungeon'].upper() if curr_party else "a Party"
        
        applicant = interaction.client.get_user(self.applicant_id) or await interaction.client.fetch_user(self.applicant_id)
        if applicant:
            try:
                await applicant.send(f"💔 Unfortunately, your request to join **{dg_name}** has been denied (Slot is full or does not fit the team)..")
            except discord.Forbidden:
                pass

        button.disabled = True
        self.children[0].disabled = True
        await interaction.response.edit_message(content="❌ **REJECTED**", view=self)


# ==========================================
# PUBLIC VIEWS (BROADCAST & LOBBY)
# ==========================================
class PartySelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(
            placeholder="👥 Chọn phòng muốn tham gia...",
            min_values=1,
            max_values=1,
            options=options,
            row=2
        )

    async def callback(self, interaction: discord.Interaction):
        # Lấy ID của party mà người dùng vừa chọn từ dropdown
        party_id = self.values[0]
        
        # 1. Lấy dữ liệu party từ DB
        party = await parties_col.find_one({"id": party_id})
        if not party:
            await interaction.response.send_message("❌ This party no longer exist.", ephemeral=True)
            return

        # 2. Kiểm tra profile người dùng
        is_valid, ign, profile_data = await check_profile_validity(interaction.user.id)
        if not is_valid:
            await interaction.response.send_message("❌ please update your gear profile (/mygear) first.", ephemeral=True)
            return
            
        # 3. Kiểm tra gatekeep (dựa trên logic cũ của bạn)
        if party.get("gatekeeping_enabled", True):
            meets_req = await check_gear_requirement(profile_data, party['dungeon'])
            if not meets_req:
                await interaction.response.send_message("🛑 Your gear isnt reach the min requirement for this dg yet.", ephemeral=True)
                return

        # 4. Thực hiện hàm join (Sử dụng lại hàm handle_join_request bạn đã có)
        await handle_join_request(interaction, party, ign, profile_data)
class BroadcastJoinView(discord.ui.View):
    def __init__(self, party_id: str, dungeon_name: str, gatekeeping_enabled: bool):
        super().__init__(timeout=None)
        self.party_id = party_id
        self.dungeon_name = dungeon_name
        self.gatekeeping_enabled = gatekeeping_enabled

    @discord.ui.button(label="Join Request", style=discord.ButtonStyle.primary, custom_id="join_req")
    async def join_req_trigger(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_valid, ign, profile_data = await check_profile_validity(interaction.user.id)
        if not is_valid:
            await interaction.response.send_message("❌ Use `/mygear` first.", ephemeral=True)
            return

        # Chỉ check gear nếu gatekeeping_enabled là True
        if self.gatekeeping_enabled:
            meets_req = await check_gear_requirement(profile_data, self.dungeon_name)
            if not meets_req:
                await interaction.response.send_message("🛑 Your gear does not meet the requirements.", ephemeral=True)
                return

        party = await parties_col.find_one({"id": self.party_id})
        await handle_join_request(interaction, party, ign, profile_data)
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
    async def get_party_options(self):
    # Lấy 25 party mới nhất
        cursor = parties_col.find({}).sort("created_at", -1).limit(25)
        options = []

        async for party in cursor:
            # Sử dụng 'id' thay vì '_id' nếu bạn lưu custom ID ở bước tạo
            party_id = str(party.get("id"))
            
            # Tạo label hiển thị: Dungeon + Leader
            label = f"{party.get('dungeon', 'Unknown')} - {party.get('leader_name', 'Leader')}"
            # Hiển thị số slot: 2/4
            description = f"Slots: {len(party.get('members', []))}/{party.get('slots', 4)}"
            
            options.append(discord.SelectOption(
                label=label,
                description=description,
                value=party_id
            ))
        
        return options

    

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
            await interaction.response.send_message("❌ **Auto reject:** Please use `/mygear` to set up your profile before creating a Party..", ephemeral=True)
            return
        await interaction.response.send_modal(CreatePartyModal(ign))

    @discord.ui.button(label="⚙️ Manage My Party", style=discord.ButtonStyle.danger, row=0, custom_id="lobby_manage")
    async def manage_party_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        party = await parties_col.find_one({"$or": [{"leader_id": user_id}, {"members.user_id": user_id}]})
        if not party:
            await interaction.response.send_message("❌ You dont have any active party right now.", ephemeral=True)
            return
        embed = build_manage_embed(party)
        await interaction.response.send_message(embed=embed, view=ManagePartyView(party["id"], user_id), ephemeral=True)


    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="lobby_refresh")
    async def refresh_lobby(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Gọi lại hàm xây dựng embed để lấy dữ liệu mới nhất từ DB
        embed, max_pages = await build_lobby_embed(page=self.page)
        
        # Cập nhật thông điệp hiện tại với embed mới
        await interaction.response.edit_message(embed=embed, view=self)
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
            await interaction.response.send_message("❌ You dont have permission to access this UI.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📝 Edit Needs", style=discord.ButtonStyle.secondary, row=0)
    async def edit_requirements(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"id": self.party_id})
        if party.get("leader_id") != interaction.user.id:
            await interaction.response.send_message("❌ Only the new Leader can edit the information..", ephemeral=True)
            return
        await interaction.response.send_modal(EditNeedModal(self.party_id))

    @discord.ui.button(label="📢 Broadcast Again", style=discord.ButtonStyle.primary, row=0)
    async def manual_broadcast(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"id": self.party_id})
        if party.get("leader_id") != interaction.user.id:
            await interaction.response.send_message("❌ Only Leaders are allowed to send Broadcasts..", ephemeral=True)
            return
            
        await interaction.response.defer(ephemeral=True)
        count = await perform_cross_server_broadcast(interaction.client, party)
        await interaction.followup.send(f"✅ resubmitted the party recuit to the **{count}** server..", ephemeral=True)

    @discord.ui.button(label="💥 Disband / Leave", style=discord.ButtonStyle.danger, row=0)
    async def leave_or_disband(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await parties_col.find_one({"id": self.party_id})
        
        # Nếu Leader bấm -> Giải tán Party và Xóa tất cả các kênh/thread đã tạo
        if party.get("leader_id") == interaction.user.id:
            for node in party.get("connected_channels", []):
                try:
                    g = interaction.client.get_guild(node["guild_id"])
                    if g:
                        ch = g.get_channel(node["channel_id"]) or g.get_thread(node["channel_id"])
                        if ch: await ch.delete(reason="Party disbanded by Leader")
                except Exception:
                    pass
            
            await parties_col.delete_one({"id": self.party_id})
            await interaction.response.edit_message(content="💥 *The group has disbanded, and all chat threads have been deleted.*", embed=None, view=None)
        
        # Nếu Member bấm -> Rời nhóm
        else:
            guild = interaction.client.get_guild(party.get("guild_id", 0))
            channel = guild.get_channel(party.get("channel_id", 0)) if guild else None

            if channel:
                try:
                    member = guild.get_member(interaction.user.id) or await guild.fetch_member(interaction.user.id)
                    if member:
                        await channel.set_permissions(member, overwrite=None) 
                        await channel.send(f"🏃 <@{interaction.user.id}> has left the group.")
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

    async def get_or_create_webhook(self, channel: discord.TextChannel):
        """Lấy webhook có sẵn của bot hoặc tạo mới nếu chưa có"""
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.name == "Party_Relay_Bot" and wh.token:
                return wh
        return await channel.create_webhook(name="Party_Relay_Bot", reason="Serving Cross-server Parties")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Không tự relay tin nhắn của bot để tránh lặp vô hạn
        if message.author.bot or not message.guild:
            return

        # Tìm xem kênh/thread hiện tại có đang nằm trong nhóm party nào không
        party = await parties_col.find_one({"connected_channels.channel_id": message.channel.id})
        if not party:
            return

        connected_nodes = party.get("connected_channels", [])
        
        for node in connected_nodes:
            if node["channel_id"] == message.channel.id:
                continue # Bỏ qua kênh gốc vừa chat

            target_guild = self.bot.get_guild(node["guild_id"])
            if not target_guild: continue

            target_channel = target_guild.get_channel(node["channel_id"]) or target_guild.get_thread(node["channel_id"])
            if not target_channel: continue

            if isinstance(target_channel, discord.Thread):
                parent_channel = target_channel.parent
                webhook = await self.get_or_create_webhook(parent_channel)
                thread_kwarg = {"thread": target_channel}
            else:
                webhook = await self.get_or_create_webhook(target_channel)
                thread_kwarg = {}

            try:
                avatar_url = message.author.avatar.url if message.author.avatar else message.author.default_avatar.url
                
                files = []
                for attachment in message.attachments:
                    files.append(await attachment.to_file())

                await webhook.send(
                    content=message.content,
                    username=f"{message.author.display_name} (Cross-server)",
                    avatar_url=avatar_url,
                    files=files,
                    **thread_kwarg
                )
            except Exception as e:
                print(f"[Webhook Relay Error]: {e}")

    @app_commands.command(name="party_lobby", description="Open the lobby to search for teams.")
    async def party_lobby(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            embed, _ = await build_lobby_embed(page=1)
            view = LobbyView(page=1)
            options = await view.get_party_options()
            print(f"DEBUG: Số lượng party tìm thấy: {len(options)}") # Xem terminal bot
            if options:
                view.add_item(PartySelect(options))
            else:
                view.add_item(discord.ui.Select(
                    placeholder="Hiện chưa có party nào...",
                    disabled=True,
                    options=[discord.SelectOption(label="Trống", value="none")]
                    ))
            await interaction.followup.send(embed=embed, view=view)
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ System error: {e}", ephemeral=True)
            except discord.errors.NotFound:
                pass

    @app_commands.command(name="manage_party", description="Open your party manage panel.")
    async def manage_party(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        party = await parties_col.find_one({"$or": [{"leader_id": user_id}, {"members.user_id": user_id}]})
        
        if not party:
            await interaction.response.send_message("❌ You haven't joined or created any Parties yet..", ephemeral=True)
            return
            
        embed = build_manage_embed(party)
        view = ManagePartyView(party["id"], user_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(PartyFinder(bot))