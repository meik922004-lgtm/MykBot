import discord
from discord.ext import commands
from discord import app_commands
import motor.motor_asyncio
from bson.objectid import ObjectId
from typing import List, Optional
from Database import db

# --- CÁC HÀM HỖ TRỢ DATABASE & TIỆN ÍCH ---

async def get_player_profile(db, user_id: int):
    return await db.players.find_one({"user_id": user_id})

async def get_dungeon_config(db, dg_name: str):
    # Tìm kiếm không phân biệt hoa thường
    return await db.dungeon_configs.find_one({"dg_name": {"$regex": f"^{dg_name}$", "$options": "i"}})

async def update_broadcast_messages(bot, db, party_id: str):
    party = await db.parties.find_one({"_id": ObjectId(party_id)})
    if not party: return

    embed = create_party_embed(party)
    for msg_data in party.get("broadcasts", []):
        try:
            channel = bot.get_channel(msg_data["channel_id"])
            if channel:
                msg = await channel.fetch_message(msg_data["message_id"])
                await msg.edit(embed=embed)
        except Exception:
            pass # Bỏ qua nếu tin nhắn bị xóa

def create_party_embed(party: dict) -> discord.Embed:
    embed = discord.Embed(title=f"⚔️ Tổ Đội: {party['dg_name']}", color=discord.Color.blue())
    embed.add_field(name="👑 Leader", value=party['leader_ign'], inline=True)
    embed.add_field(name="⏰ Bắt đầu lúc", value=party['start_time'], inline=True)
    embed.add_field(name="📋 Yêu cầu", value=party['requirements'] or "Không có", inline=False)
    
    members_text = ""
    for idx, member in enumerate(party['members']):
        members_text += f"{idx+1}. **{member['ign']}** (Role: {member['role']})\n"
    
    embed.add_field(name=f"👥 Thành viên ({len(party['members'])}/4)", value=members_text or "Chưa có", inline=False)
    return embed

# --- VIEWS (GIAO DIỆN NÚT BẤM) ---

class RequestJoinView(discord.ui.View):
    def __init__(self, bot, db, party_id, applicant_id):
        super().__init__(timeout=86400) # Timeout 1 ngày
        self.bot = bot
        self.db = db
        self.party_id = party_id
        self.applicant_id = applicant_id

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="accept_join")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await self.db.parties.find_one({"_id": ObjectId(self.party_id)})
        applicant_profile = await get_player_profile(self.db, self.applicant_id)
        
        if not party or not applicant_profile:
            return await interaction.response.send_message("Party hoặc người chơi không còn tồn tại.", ephemeral=True)
        
        if len(party['members']) >= 4:
            return await interaction.response.send_message("Party đã đầy!", ephemeral=True)

        # Trích xuất role mạnh nhất hoặc mặc định
        stats = applicant_profile.get("my_stats", {})
        main_role = stats.get("role", "Unknown") 
        
        new_member = {
            "user_id": self.applicant_id,
            "ign": applicant_profile.get("ign", "Unknown"),
            "role": main_role
        }

        # Cập nhật DB
        await self.db.parties.update_one({"_id": ObjectId(self.party_id)}, {"$push": {"members": new_member}})
        await update_broadcast_messages(self.bot, self.db, self.party_id)
        
        # Disable buttons
        for child in self.children: child.disabled = True
        await interaction.message.edit(content="✅ Bạn đã chấp nhận người chơi này.", view=self)
        
        # Thêm vào group chat/webhook
        await handle_cross_server_chat(self.bot, self.db, party, self.applicant_id, action="add")
        
        # Báo cho người xin
        applicant = self.bot.get_user(self.applicant_id)
        if applicant: await applicant.send(f"🎉 Leader {party['leader_ign']} đã **CHẤP NHẬN** yêu cầu vào party {party['dg_name']} của bạn!")

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="reject_join")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await self.db.parties.find_one({"_id": ObjectId(self.party_id)})
        for child in self.children: child.disabled = True
        await interaction.message.edit(content="❌ Bạn đã từ chối người chơi này.", view=self)
        
        applicant = self.bot.get_user(self.applicant_id)
        if applicant and party: await applicant.send(f"💔 Yêu cầu vào party {party['dg_name']} của bạn đã bị từ chối.")


class ManagePartyView(discord.ui.View):
    def __init__(self, bot, db, party):
        super().__init__(timeout=None)
        self.bot = bot
        self.db = db
        self.party = party

    @discord.ui.button(label="Edit Requirements", style=discord.ButtonStyle.primary, row=0)
    async def edit_reqs(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.party['leader_id']:
            return await interaction.response.send_message("Chỉ Leader mới được sửa thông tin!", ephemeral=True)
        await interaction.response.send_modal(EditReqModal(self.bot, self.db, self.party['_id']))

    @discord.ui.button(label="View Gear", style=discord.ButtonStyle.secondary, row=0)
    async def view_gear(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Trả về một dropdown để chọn thành viên muốn xem
        options = [discord.SelectOption(label=m['ign'], value=str(m['user_id'])) for m in self.party['members']]
        select = discord.ui.Select(placeholder="Chọn thành viên để xem gear...", options=options)
        
        async def select_callback(inter: discord.Interaction):
            profile = await get_player_profile(self.db, int(select.values[0]))
            stats = profile.get("my_stats", {})
            embed = discord.Embed(title=f"Gear Profile: {profile.get('ign')}", color=discord.Color.gold())
            # Format gear theo Data Model hình 1
            for role, data in stats.items():
                if isinstance(data, dict) and "gear" in data:
                    embed.add_field(name=f"Role: {role}", value=f"**Gear:** {data.get('gear')}\n**Vice:** {data.get('vice')}\n**Deck:** {data.get('deck')}", inline=False)
            await inter.response.send_message(embed=embed, ephemeral=True)
            
        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message("Chọn thành viên:", view=view, ephemeral=True)

    @discord.ui.button(label="Disband / Leave", style=discord.ButtonStyle.danger, row=0)
    async def disband_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.party['leader_id']:
            await self.db.parties.delete_one({"_id": self.party['_id']})
            await handle_cross_server_chat(self.bot, self.db, self.party, action="delete")
            # Update msg to show disbanded
            embed = discord.Embed(title="❌ Party đã giải tán", color=discord.Color.red())
            for msg_data in self.party.get("broadcasts", []):
                channel = self.bot.get_channel(msg_data["channel_id"])
                if channel:
                    try:
                        msg = await channel.fetch_message(msg_data["message_id"])
                        await msg.edit(embed=embed, view=None)
                    except: pass
            await interaction.response.send_message("Đã giải tán Party!", ephemeral=True)
        else:
            # Leave logic
            await self.db.parties.update_one({"_id": self.party['_id']}, {"$pull": {"members": {"user_id": interaction.user.id}}})
            await update_broadcast_messages(self.bot, self.db, self.party['_id'])
            await handle_cross_server_chat(self.bot, self.db, self.party, interaction.user.id, action="remove")
            await interaction.response.send_message("Bạn đã rời Party.", ephemeral=True)

    @discord.ui.button(label="Broadcast Again", style=discord.ButtonStyle.success, row=1)
    async def broadcast(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.party['leader_id']:
            return await interaction.response.send_message("Chỉ Leader mới được Broadcast!", ephemeral=True)
        
        # Ping role if exists
        dg_config = await get_dungeon_config(self.db, self.party['dg_name'])
        ping_text = f"<@&{dg_config['ping_role']}>" if dg_config and "ping_role" in dg_config else ""
        
        embed = create_party_embed(self.party)
        msg = await interaction.channel.send(content=f"📢 Tuyển người cho **{self.party['dg_name']}**! {ping_text}", embed=embed)
        
        await self.db.parties.update_one({"_id": self.party['_id']}, {"$push": {"broadcasts": {"channel_id": interaction.channel.id, "message_id": msg.id}}})
        await interaction.response.send_message("Đã gửi lại thông báo tuyển người!", ephemeral=True)


class LobbyPaginationView(discord.ui.View):
    def __init__(self, bot, db, parties, page=0, search_term=None):
        super().__init__(timeout=None)
        self.bot = bot
        self.db = db
        self.parties = parties
        self.page = page
        self.search_term = search_term
        self.items_per_page = 5
        self.max_pages = max(1, (len(parties) - 1) // self.items_per_page + 1)
        
        # Add Select Menu for "Send Request" (Linear style)
        current_parties = self.parties[self.page * self.items_per_page : (self.page + 1) * self.items_per_page]
        if current_parties:
            options = [discord.SelectOption(label=f"{p['dg_name']} (Ldr: {p['leader_ign']})", description=f"{len(p['members'])}/4 - {p['start_time']}", value=str(p['_id'])) for p in current_parties]
            self.select = discord.ui.Select(placeholder="Chọn Party để gửi Request...", options=options, row=0)
            self.select.callback = self.send_request_callback
            self.add_item(self.select)

    async def send_request_callback(self, interaction: discord.Interaction):
        party_id = self.select.values[0]
        applicant = await get_player_profile(self.db, interaction.user.id)
        if not applicant:
            return await interaction.response.send_message("⚠️ Bạn phải tạo profile bằng `/mygear` trước khi join party!", ephemeral=True)
        
        party = await self.db.parties.find_one({"_id": ObjectId(party_id)})
        
        # Check rule 3: Cannot join if already in a party
        existing_party = await self.db.parties.find_one({"members.user_id": interaction.user.id})
        if existing_party:
            return await interaction.response.send_message("❌ Bạn đang ở trong một party rồi!", ephemeral=True)

        # Gửi DM cho leader
        leader = self.bot.get_user(party['leader_id'])
        if leader:
            stats = applicant.get("my_stats", {})
            embed = discord.Embed(title="📩 Yêu cầu gia nhập Party!", color=discord.Color.green())
            embed.add_field(name="Người xin", value=applicant.get('ign'), inline=True)
            embed.add_field(name="Discord", value=interaction.user.mention, inline=True)
            main_role = stats.get('role', 'Unknown')
            embed.add_field(name="Role Đăng ký", value=main_role, inline=True)
            
            # Add gear info (tóm tắt)
            role_data = stats.get(main_role, {}) if isinstance(stats, dict) else {}
            if isinstance(role_data, dict):
                embed.add_field(name="Gear Overview", value=f"Gear: {role_data.get('gear')}\nVice: {role_data.get('vice')}", inline=False)
            
            try:
                await leader.send(embed=embed, view=RequestJoinView(self.bot, self.db, party_id, interaction.user.id))
                await interaction.response.send_message("✅ Đã gửi request đến Leader!", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("❌ Không thể DM leader (Họ khóa DM).", ephemeral=True)

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
        await interaction.response.send_modal(SearchPartyModal(self.bot, self.db))

    @discord.ui.button(label="➕ Create Party", style=discord.ButtonStyle.success, row=2)
    async def create_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if already in party & has profile
        profile = await get_player_profile(self.db, interaction.user.id)
        if not profile:
            return await interaction.response.send_message("⚠️ Bạn phải setup `/mygear` trước!", ephemeral=True)
        if await self.db.parties.find_one({"members.user_id": interaction.user.id}):
            return await interaction.response.send_message("❌ Bạn đang ở trong 1 party rồi!", ephemeral=True)
            
        await interaction.response.send_modal(CreatePartyModal(self.bot, self.db, profile['ign']))

    @discord.ui.button(label="⚙️ Manage My Party", style=discord.ButtonStyle.primary, row=2)
    async def manage_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        party = await self.db.parties.find_one({"members.user_id": interaction.user.id})
        if not party:
            return await interaction.response.send_message("Bạn chưa gia nhập party nào.", ephemeral=True)
        
        embed = create_party_embed(party)
        await interaction.response.send_message(embed=embed, view=ManagePartyView(self.bot, self.db, party), ephemeral=True)

    async def update_lobby(self, interaction: discord.Interaction, new_page: int):
        # Fetch fresh data
        query = {}
        if self.search_term:
            query = {"dg_name": {"$regex": self.search_term, "$options": "i"}}
        fresh_parties = await self.db.parties.find(query).to_list(length=100)
        
        view = LobbyPaginationView(self.bot, self.db, fresh_parties, new_page, self.search_term)
        
        embed = discord.Embed(title="🌐 Party Finder Lobby", description=f"Trang {new_page+1}/{view.max_pages}", color=discord.Color.purple())
        for p in fresh_parties[new_page * view.items_per_page : (new_page + 1) * view.items_per_page]:
            embed.add_field(name=f"🎮 {p['dg_name']} | Bắt đầu: {p['start_time']}", 
                            value=f"Leader: **{p['leader_ign']}** | Đã có: {len(p['members'])}/4 người", inline=False)
            
        if not fresh_parties: embed.description = "Hiện không có Party nào."

        await interaction.response.edit_message(embed=embed, view=view)


# --- MODALS (FORM NHẬP LIỆU) ---

class SearchPartyModal(discord.ui.Modal, title='Tìm kiếm Party'):
    search_query = discord.ui.TextInput(label='Tên Dungeon', placeholder='Nhập ít nhất 3 kí tự (VD: ahm, apo)...', min_length=3)

    def __init__(self, bot, db):
        super().__init__()
        self.bot = bot
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        # Lọc chữ "dungeon" ra khỏi từ khóa
        term = self.search_query.value.lower().replace("dungeon", "").strip()
        parties = await self.db.parties.find({"dg_name": {"$regex": term, "$options": "i"}}).to_list(length=100)
        
        view = LobbyPaginationView(self.bot, self.db, parties, search_term=term)
        embed = discord.Embed(title=f"🔍 Kết quả tìm kiếm: '{term}'", color=discord.Color.purple())
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class CreatePartyModal(discord.ui.Modal, title='Tạo Party Mới'):
    dg_name = discord.ui.TextInput(label='Tên Dungeon (DG)', placeholder='Ví dụ: Stage of Clown(PIED)', required=True)
    start_time = discord.ui.TextInput(label='Thời gian bắt đầu (Expect Start Time)', placeholder='Ví dụ: 20:00 hoặc ASAP', required=True)
    requirements = discord.ui.TextInput(label='Yêu cầu (Requirements)', style=discord.TextStyle.paragraph, required=False)

    def __init__(self, bot, db, ign):
        super().__init__()
        self.bot = bot
        self.db = db
        self.ign = ign

    async def on_submit(self, interaction: discord.Interaction):
        # Tạo party object
        party_doc = {
            "leader_id": interaction.user.id,
            "leader_ign": self.ign,
            "dg_name": self.dg_name.value,
            "start_time": self.start_time.value,
            "requirements": self.requirements.value,
            "members": [{"user_id": interaction.user.id, "ign": self.ign, "role": "Leader"}],
            "broadcasts": [],
            "chat_channel_id": None # Dành cho Advanced Chat
        }
        
        result = await self.db.parties.insert_one(party_doc)
        party_doc["_id"] = result.inserted_id

        # Tạo Advanced Group Chat (Private Thread)
        await handle_cross_server_chat(self.bot, self.db, party_doc, action="create", guild=interaction.guild)

        # Tự động Broadcast và Ping
        dg_config = await get_dungeon_config(self.db, self.dg_name.value)
        ping_text = f"<@&{dg_config['ping_role']}>" if dg_config and "ping_role" in dg_config else ""
        
        embed = create_party_embed(party_doc)
        msg = await interaction.channel.send(content=f"📢 **{self.ign}** đang tìm người cho **{self.dg_name.value}**! {ping_text}", embed=embed)
        
        # Lưu broadcast
        await self.db.parties.update_one({"_id": result.inserted_id}, {"$push": {"broadcasts": {"channel_id": interaction.channel.id, "message_id": msg.id}}})
        
        await interaction.response.send_message(f"Tạo party thành công! Sử dụng Lobby để quản lý.", ephemeral=True)

class EditReqModal(discord.ui.Modal, title='Sửa yêu cầu Party'):
    requirements = discord.ui.TextInput(label='Yêu cầu mới', style=discord.TextStyle.paragraph)

    def __init__(self, bot, db, party_id):
        super().__init__()
        self.bot = bot
        self.db = db
        self.party_id = party_id

    async def on_submit(self, interaction: discord.Interaction):
        await self.db.parties.update_one({"_id": self.party_id}, {"$set": {"requirements": self.requirements.value}})
        await update_broadcast_messages(self.bot, self.db, self.party_id)
        await interaction.response.send_message("Đã cập nhật yêu cầu!", ephemeral=True)


# --- HỆ THỐNG CROSS-SERVER CHAT (ADVANCED CHAT) ---
# Cách hoạt động: Tạo một Private Thread trong một kênh cố định để party chat.
# Tự động add/remove người dùng dựa trên trạng thái DB.

async def handle_cross_server_chat(bot, db, party, user_id=None, action="create", guild=None):
    """ Xử lý tạo nhóm chat sử dụng Private Thread """
    try:
        if action == "create" and guild:
            # Tạo private thread (Yêu cầu server có Server Boost Tier 2 hoặc Forum/Text channel phù hợp)
            # Cấu trúc đơn giản: Dùng Text Channel riêng biệt cho từng party để dễ quản lý quyền
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            leader = guild.get_member(party['leader_id'])
            if leader: overwrites[leader] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            # Tạo channel
            chat_channel = await guild.create_text_channel(name=f"party-{party['leader_ign']}", overwrites=overwrites)
            
            # Lưu lại ID vào DB
            await db.parties.update_one({"_id": party['_id']}, {"$set": {"chat_channel_id": chat_channel.id}})
            
            webhook = await chat_channel.create_webhook(name="CrossServerRelay")
            await db.parties.update_one({"_id": party['_id']}, {"$set": {"webhook_url": webhook.url}})

        elif action == "add" and user_id:
            channel = bot.get_channel(party.get("chat_channel_id"))
            if channel:
                member = channel.guild.get_member(user_id)
                if member:
                    await channel.set_permissions(member, read_messages=True, send_messages=True)
                    await channel.send(f"👋 {member.mention} đã tham gia Party!")

        elif action == "remove" and user_id:
            channel = bot.get_channel(party.get("chat_channel_id"))
            if channel:
                member = channel.guild.get_member(user_id)
                if member:
                    await channel.set_permissions(member, overwrite=None)
                    await channel.send(f"🚪 Một thành viên đã rời/bị kick khỏi Party.")

        elif action == "delete":
            channel = bot.get_channel(party.get("chat_channel_id"))
            if channel:
                await channel.delete()
    except Exception as e:
        print(f"Lỗi chat system: {e}")


# --- COG SETUP LỆNH KHỞI TẠO LOBBY ---

class PartyFinderCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db  # Instance MongoDB từ bot root

    @app_commands.command(name="party_lobby", description="Mở giao diện Party Finder (Lobby UI)")
    async def party_lobby(self, interaction: discord.Interaction):
        # Lấy trang đầu tiên
        parties = await self.db.parties.find({}).to_list(length=100)
        
        embed = discord.Embed(title="🌐 Party Finder Lobby", description="Đang tải dữ liệu...", color=discord.Color.purple())
        view = LobbyPaginationView(self.bot, self.db, parties, page=0)
        
        # Populate initial embed
        if not parties:
            embed.description = "Hiện không có Party nào đang mở."
        else:
            embed.description = f"Trang 1/{view.max_pages}"
            for p in parties[:5]:
                embed.add_field(name=f"🎮 {p['dg_name']} | Bắt đầu: {p['start_time']}", 
                                value=f"Leader: **{p['leader_ign']}** | Đã có: {len(p['members'])}/4 người", inline=False)

        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(PartyFinderCog(bot))