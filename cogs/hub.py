import discord
from discord import app_commands
from discord.ext import commands
from utils.checks import check_is_owner


def build_home_embed(user: discord.abc.User, is_owner: bool) -> discord.Embed:
    embed = discord.Embed(
        title="🎛️ MyKBot — Trung Tâm Điều Khiển",
        description=(
            f"Chào **{user.display_name}**! Chọn một nhóm chức năng ở menu bên dưới "
            "để truy cập nhanh toàn bộ công cụ của MyKBot chỉ với 1 lệnh duy nhất."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="⚔️ Party & Dungeon",
        value="Mở sảnh tìm Party liên server, xem lịch Raid/Event & kiểm tra yêu cầu Dungeon.",
        inline=False,
    )
    embed.add_field(
        name="🛡️ Hồ sơ & Gear",
        value="Cập nhật IGN/Gear (`/mygear`), xem hồ sơ Gear và chỉnh múi giờ cá nhân.",
        inline=False,
    )
    embed.add_field(
        name="🛒 Theo dõi Giá Chợ",
        value="Quản lý Watchlist, bật/tắt cảnh báo DM & vẽ biểu đồ giá (Shop Tracker)"
              + (" + **Chợ Tốt Tracker (Owner)**." if is_owner else "."),
        inline=False,
    )
    embed.add_field(
        name="📢 Tin tức & Role",
        value="Xem bản tóm tắt Patch Note DMW mới nhất (có dịch nhanh) & tự nhận/gỡ Role.",
        inline=False,
    )
    embed.set_footer(text="MyKBot Hub • Menu tự động đóng sau 3 phút không tương tác")
    return embed


class HubSelect(discord.ui.Select):
    def __init__(self, author_id: int, is_owner: bool):
        self.author_id = author_id
        self.is_owner = is_owner
        options = [
            discord.SelectOption(label="Trang chủ", value="home", emoji="🏠", description="Tổng quan toàn bộ chức năng MyKBot"),
            discord.SelectOption(label="Party Finder & Lịch Boss", value="party", emoji="⚔️", description="Tìm Party, xem Dungeon & lịch Raid/Event"),
            discord.SelectOption(label="Hồ sơ & Gear cá nhân", value="profile", emoji="🛡️", description="Setup IGN/Gear, xem Gear & đổi múi giờ"),
            discord.SelectOption(label="Theo dõi Giá Chợ", value="market", emoji="🛒", description="Market Hub, Watchlist & Biểu đồ giá"),
            discord.SelectOption(label="Tin tức & Role", value="community", emoji="📢", description="Patch Summary mới nhất & tự chọn Role"),
        ]
        super().__init__(placeholder="👇 Chọn danh mục chức năng...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Hãy gõ `/menu` để mở bảng điều khiển của riêng bạn!", ephemeral=True)

        choice = self.values[0]
        view: MyKBotHubView = self.view  # type: ignore

        if choice == "home":
            embed = build_home_embed(interaction.user, self.is_owner)
        elif choice == "party":
            embed = discord.Embed(
                title="⚔️ Party Finder & Lịch Raid/Event",
                description="Bấm các nút bên dưới để mở sảnh tìm Party, xem yêu cầu Dungeon hoặc kiểm tra lịch Boss/Event.",
                color=discord.Color.green(),
            )
        elif choice == "profile":
            embed = discord.Embed(
                title="🛡️ Hồ sơ & Gear Cá Nhân",
                description="Cập nhật IGN, chỉ số Gear (AA/SK/TANK) và múi giờ để đồng bộ lịch chính xác.",
                color=discord.Color.blue(),
            )
        elif choice == "market":
            embed = discord.Embed(
                title="🛒 Trung Tâm Theo Dõi Giá Chợ",
                description="Mở **Market Hub** để quản lý danh sách item đang săn, bật/tắt thông báo DM và xem biểu đồ giá.",
                color=discord.Color.gold(),
            )
        else:
            embed = discord.Embed(
                title="📢 Tin Tức & Tự Chọn Role",
                description="Đọc bản tóm tắt Patch Note DMW mới nhất (kèm dịch đa ngôn ngữ) hoặc tự nhận/gỡ Role.",
                color=discord.Color.teal(),
            )

        view.set_section_buttons(choice)
        await interaction.response.edit_message(embed=embed, view=view)


class MyKBotHubView(discord.ui.View):
    def __init__(self, bot: commands.Bot, author_id: int, is_owner: bool, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.author_id = author_id
        self.is_owner = is_owner
        self.add_item(HubSelect(author_id, is_owner))
        self.set_section_buttons("home")

    def set_section_buttons(self, section: str):
        for item in list(self.children):
            if isinstance(item, discord.ui.Button):
                self.remove_item(item)

        if section == "party":
            self.add_item(self._make_btn("Mở Party Lobby", "🌐", discord.ButtonStyle.success, "party_lobby"))
            self.add_item(self._make_btn("Check Dungeon", "🔎", discord.ButtonStyle.primary, "dglist"))
            self.add_item(self._make_btn("Lịch Raid / Event", "📅", discord.ButtonStyle.secondary, "schedule"))

        elif section == "profile":
            self.add_item(self._make_btn("Setup / Sửa Gear", "⚙️", discord.ButtonStyle.success, "mygear"))
            self.add_item(self._make_btn("Xem Gear của tôi", "🛡️", discord.ButtonStyle.primary, "showmygear"))
            self.add_item(self._make_btn("Đổi múi giờ", "🌍", discord.ButtonStyle.secondary, "set_timezone"))

        elif section == "market":
            self.add_item(self._make_btn("Mở Market Hub", "🎯", discord.ButtonStyle.primary, "market_hub"))
            if self.is_owner:
                self.add_item(self._make_btn("Chợ Tốt Tracker", "🏍️", discord.ButtonStyle.secondary, "chotot"))

        elif section == "community":
            self.add_item(self._make_btn("Patch Note mới nhất", "📰", discord.ButtonStyle.primary, "patch_latest"))
            self.add_item(self._make_btn("Nhận / Gỡ Role", "🎭", discord.ButtonStyle.secondary, "roles_panel"))

        close_btn = discord.ui.Button(label="Đóng", emoji="✖️", style=discord.ButtonStyle.danger, row=1)
        close_btn.callback = self._close_cb
        self.add_item(close_btn)

    def _make_btn(self, label: str, emoji: str, style: discord.ButtonStyle, action: str):
        btn = discord.ui.Button(label=label, emoji=emoji, style=style, row=1)

        async def _cb(interaction: discord.Interaction):
            if interaction.user.id != self.author_id:
                return await interaction.response.send_message("Menu này không phải của bạn. Hãy gõ `/menu`!", ephemeral=True)

            if action == "party_lobby":
                cog = self.bot.get_cog("PartyFinderCog")
                if cog:
                    return await cog.open_party_lobby(interaction)

            elif action == "dglist":
                cog = self.bot.get_cog("DungeonStats")
                if cog:
                    return await cog.open_dglist(interaction)

            elif action == "schedule":
                cog = self.bot.get_cog("Basic command")
                if cog:
                    await interaction.response.defer(ephemeral=True)
                    embed = await cog.build_schedule_embed(interaction.guild_id, interaction.user.id)
                    return await interaction.followup.send(embed=embed, ephemeral=True)

            elif action == "mygear":
                cog = self.bot.get_cog("DungeonStats")
                if cog:
                    return await cog.open_mygear(interaction)

            elif action == "showmygear":
                cog = self.bot.get_cog("DungeonStats")
                if cog:
                    return await cog.open_showmygear(interaction, ephemeral=True)

            elif action == "set_timezone":
                cog = self.bot.get_cog("DungeonStats")
                if cog:
                    return await cog.open_set_timezone(interaction)

            elif action == "market_hub":
                cog = self.bot.get_cog("ShopTracker")
                if cog:
                    return await cog.open_market_hub(interaction, ephemeral=True)

            elif action == "chotot":
                cog = self.bot.get_cog("ChototTracker")
                if cog:
                    return await cog.open_chotot_dashboard(interaction, ephemeral=True)

            elif action == "patch_latest":
                cog = self.bot.get_cog("DMWBroadcaster")
                if cog:
                    return await cog.open_latest_patch(interaction)

            elif action == "roles_panel":
                cog = self.bot.get_cog("RolesCog")
                if cog:
                    embed, view = cog.build_roles_panel()
                    return await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

            await interaction.response.send_message("⚠️ Module chức năng này hiện chưa được nạp.", ephemeral=True)

        btn.callback = _cb
        return btn

    async def _close_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Bạn không thể đóng menu của người khác.", ephemeral=True)
        await interaction.message.delete()
        self.stop()


class HubCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="menu", description="Mở trung tâm điều khiển MyKBot (truy cập toàn bộ chức năng)")
    async def menu_command(self, interaction: discord.Interaction):
        is_owner = await check_is_owner(self.bot, interaction.user)
        view = MyKBotHubView(self.bot, interaction.user.id, is_owner)
        await interaction.response.send_message(
            embed=build_home_embed(interaction.user, is_owner),
            view=view,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(HubCog(bot))