import discord
from discord import app_commands
from discord.ext import commands

OWNER_IDS = [1283689737567211581]

class HubView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder="🚀 Chọn chức năng bạn muốn truy cập...",
        custom_id="persistent_hub:select_menu",
        min_values=1,
        max_values=1,
        options=[
            # Thêm option này vào danh sách options của HubView trong cogs/hub.py:
            discord.SelectOption(label="📊 Market Tracker", description="Tra cứu giá thị trường & Cài đặt cảnh báo giá", value="market"),
            discord.SelectOption(label="⚙️ Profile Gear của tôi", description="Cấu hình IGN, Timezone và Trang bị", value="mygear"),
            discord.SelectOption(label="🛡️ Xem Profile Gear", description="Hiển thị thông số trang bị hiện tại", value="showgear"),
            discord.SelectOption(label="🌐 Party Finder Lobby", description="Tìm đội hoặc tạo phòng đi Dungeon", value="lobby"),
            discord.SelectOption(label="📩 Quản lý Party của tôi", description="Gửi lại UI quản lý party vào DM", value="my_party"),
            discord.SelectOption(label="📍 Kiểm tra Yêu cầu Dungeon", description="Tra cứu yêu cầu gear cho từng Dungeon", value="dglist"),
            discord.SelectOption(label="📅 Lịch Raid & Event", description="Xem đếm ngược thời gian Boss/Event spawn", value="schedule"),
            discord.SelectOption(label="🎭 Tự lấy / Xóa Role", description="Menu đăng ký danh hiệu & role tự động", value="roles"),
            discord.SelectOption(label="🛠️ Admin Setup", description="Thiết lập Kênh & Setup (Chỉ Admin)", value="admin_setup"),
            discord.SelectOption(label="👑 Owner Tools", description="Broadcast & Quản trị (Chỉ Owner)", value="owner_tools"),
        ]
    )
    async def on_select_category(self, interaction: discord.Interaction, select: discord.ui.Select):
        from database import db, players_col, parties_col
        from cogs.party_dungeon import MyGearWizard, MyGearIGNModal, DungeonListView, LobbyPaginationView, create_party_embed, PartyLobbyDMView
        from cogs.management import MainRolesMenuView, SettingMenuView, get_schedule_embed

        val = select.values[0]
        user = interaction.user
        guild = interaction.guild
        is_owner = user.id in OWNER_IDS
        is_admin = is_owner or (guild and user.guild_permissions.administrator)

        if val == "mygear":
            p = await players_col.find_one({"user_id": user.id})
            if not p or not p.get("ign") or p.get("ign") == "Not Set":
                await interaction.response.send_modal(MyGearIGNModal(interaction.client))
            else:
                embed = discord.Embed(title="⚙️ Setup MyGear", description=f"Profile hiện tại: **{p.get('ign')}**\nChọn role để cài đặt gear:", color=discord.Color.blue())
                await interaction.response.send_message(embed=embed, view=MyGearWizard(user.id, p), ephemeral=True)

        elif val == "showgear":
            p = await players_col.find_one({"user_id": user.id})
            if not p or "my_stats" not in p or not p["my_stats"]:
                return await interaction.response.send_message("❌ Dữ liệu gear của bạn đang trống!", ephemeral=True)
            ign_in_db = p.get('ign', 'Not Set')
            embed = discord.Embed(title=f"🛡️ Profile của {ign_in_db}", color=discord.Color.blue())
            for role_name, stats in p["my_stats"].items():
                if isinstance(stats, dict):
                    embed.add_field(name=f"Role: {role_name}", value=f"Gear: {stats.get('gear', 'N/A')}\nVice: {stats.get('vice', 'N/A')}\nDeck: {stats.get('deck', 'N/A')}\nBracelet: {stats.get('bracelet', 'N/A')}", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif val == "lobby":
            await interaction.response.defer(ephemeral=True)
            parties = await parties_col.find({}).to_list(length=100)
            view = LobbyPaginationView(interaction.client, parties, page=0)
            embed = discord.Embed(title="🌐 Party Finder Lobby", description=f"Trang 1/{max(1, view.max_pages)}", color=discord.Color.purple())
            for p in parties[:view.items_per_page]:
                embed.add_field(name=f"🎮 {p.get('dg_name')} | Start: {p.get('start_time')}", value=f"👤 Leader: **{p.get('leader_ign')}**\n👥 Thành viên: `{len(p.get('members', []))}/4`\n📝 Yêu cầu: *{p.get('requirements', 'Không') if p.get('requirements') else 'Không'}*", inline=False)
            if not parties:
                embed.description = "Hiện chưa có đội nào đang tìm thành viên."
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        elif val == "my_party":
            await interaction.response.defer(ephemeral=True)
            party = await parties_col.find_one({"members.user_id": user.id})
            if not party:
                return await interaction.followup.send("❌ Bạn chưa tham gia đội nào.", ephemeral=True)
            try:
                dm_channel = user.dm_channel or await user.create_dm()
                embed = create_party_embed(party)
                view = PartyLobbyDMView(interaction.client, str(party['_id']), user_id=user.id, leader_id=party.get('leader_id'))
                msg = await dm_channel.send(embed=embed, view=view)
                await parties_col.update_one({"_id": party['_id'], "members.user_id": user.id}, {"$set": {"members.$.dm_message_id": msg.id}})
                await interaction.followup.send("✅ Đã gửi giao diện Quản lý Party vào DM của bạn!", ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send("❌ Không thể gửi DM. Vui lòng mở khoá DM từ thành viên cùng server.", ephemeral=True)

        elif val == "dglist":
            await interaction.response.defer(ephemeral=True)
            dungeons = await db.dungeon_configs.find({}).to_list(length=25)
            if not dungeons:
                return await interaction.followup.send("❌ Cơ sở dữ liệu Dungeon trống.", ephemeral=True)
            await interaction.followup.send("📍 Vui lòng chọn Dungeon để kiểm tra:", view=DungeonListView(dungeons), ephemeral=True)

        elif val == "schedule":
            await interaction.response.defer(ephemeral=True)
            embed = await get_schedule_embed(interaction.guild_id, user.id)
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif val == "roles":
            embed = discord.Embed(
                title="🎭 HỆ THỐNG TỰ ĐỘNG NHẬN ROLE",
                description="Sử dụng nút dưới đây để nhận/xóa role tự động:",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, view=MainRolesMenuView(), ephemeral=True)

        elif val == "admin_setup":
            if not is_admin:
                return await interaction.response.send_message("❌ Bạn không có quyền truy cập bảng Admin!", ephemeral=True)
            embed = discord.Embed(title="🛠️ BANG ĐIỀU KHIỂN ADMIN", description="Chọn các thiết lập hệ thống bên dưới:", color=discord.Color.gold())
            await interaction.response.send_message(embed=embed, view=AdminSetupView(), ephemeral=True)

        elif val == "owner_tools":
            if not is_owner:
                return await interaction.response.send_message("❌ Bạn không phải Owner của Bot!", ephemeral=True)
            embed = discord.Embed(title="👑 BẢNG QUẢN TRỊ OWNER", description="Công cụ quản trị hệ thống cao cấp:", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, view=OwnerToolsView(), ephemeral=True)
        elif val == "market":
            from cogs.market_tracker import MarketTrackerView
            embed = discord.Embed(
                title="📊 HỆ THỐNG MARKET TRACKER",
                description="Tra cứu biến động giá vật phẩm, xem danh sách hot và cài đặt nhận thông báo giá tự động.",
                color=discord.Color.gold()
                )
            await interaction.response.send_message(embed=embed, view=MarketTrackerView(), ephemeral=True)

class AdminSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📢 Set Kênh Thông Báo News", style=discord.ButtonStyle.primary, custom_id="admin_setup:set_news")
    async def set_news(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetChannelModal("news"))

    @discord.ui.button(label="⚔️ Set Kênh Party Board", style=discord.ButtonStyle.primary, custom_id="admin_setup:set_party")
    async def set_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetChannelModal("party"))

    @discord.ui.button(label="⚙️ Quản lý Menu Roles", style=discord.ButtonStyle.secondary, custom_id="admin_setup:config_roles")
    async def config_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.management import SettingMenuView
        embed = discord.Embed(title="⚙️ QUẢN LÝ TỰ ĐỘNG ROLE MENU", description="Thêm hoặc xóa role khỏi hệ thống cấu hình:", color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, view=SettingMenuView(), ephemeral=True)


class OwnerToolsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📢 Gửi Broadcast Toàn Hệ Thống", style=discord.ButtonStyle.success, custom_id="owner_tools:broadcast")
    async def broadcast(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.management import NewsSystemCog, BroadcastModal
        cog = interaction.client.get_cog("NewsSystemCog")
        await interaction.response.send_modal(BroadcastModal(cog))

    @discord.ui.button(label="🔄 Reload All Cogs", style=discord.ButtonStyle.danger, custom_id="owner_tools:reload")
    async def reload_cogs(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        reloaded, errors = [], []
        for ext in list(interaction.client.extensions.keys()):
            try:
                await interaction.client.reload_extension(ext)
                reloaded.append(ext.split('.')[-1])
            except Exception as e:
                errors.append(f"{ext.split('.')[-1]}: {str(e)}")
        try:
            await interaction.client.tree.sync()
            reloaded.append("🔄 Đồng bộ Slash Commands!")
        except Exception as e:
            errors.append(f"Sync Tree: {str(e)}")

        embed = discord.Embed(title="🔄 Kết Quả Reload", color=discord.Color.green() if not errors else discord.Color.red())
        if reloaded: embed.add_field(name="Thành công", value="\n".join(reloaded), inline=False)
        if errors: embed.add_field(name="Lỗi", value="\n".join(errors), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)


class SetChannelModal(discord.ui.Modal, title="Thiết lập Kênh Hệ Thống"):
    channel_id = discord.ui.TextInput(label="Channel ID", placeholder="Nhập ID kênh văn bản...", required=True)

    def __init__(self, target_type: str):
        super().__init__()
        self.target_type = target_type

    async def on_submit(self, interaction: discord.Interaction):
        from database import db
        try:
            c_id = int(self.channel_id.value.strip())
            channel = interaction.guild.get_channel(c_id)
            if not channel:
                return await interaction.response.send_message("❌ ID kênh không hợp lệ hoặc không thuộc Server này!", ephemeral=True)

            if self.target_type == "news":
                await db["server_configs"].update_one({"guild_id": interaction.guild_id}, {"$set": {"channel_id": c_id}}, upsert=True)
            else:
                await db["server_configs"].update_one({"guild_id": interaction.guild_id}, {"$set": {"party_channel_id": c_id}}, upsert=True)

            await interaction.response.send_message(f"✅ Đã cấu hình kênh thành công: {channel.mention}", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ ID phải là định dạng số!", ephemeral=True)


class HubCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="hub", description="Trung tâm điều khiển và truy cập tất cả chức năng MyK Bot")
    async def hub_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎮 MYK BOT - CENTRAL HUB",
            description="Chào mừng bạn đến với trung tâm điều khiển!\nVui lòng chọn chức năng bạn cần từ menu thả xuống bên dưới.",
            color=discord.Color.blurple()
        )
        if self.bot.user and self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        await interaction.response.send_message(embed=embed, view=HubView(), ephemeral=True)


async def setup(bot):
    # Đăng ký các View Vĩnh Viễn vào Bot
    bot.add_view(HubView())
    bot.add_view(AdminSetupView())
    bot.add_view(OwnerToolsView())
    await bot.add_cog(HubCog(bot))