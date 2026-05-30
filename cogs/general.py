import discord
from discord import app_commands
from discord.ext import commands
from Database import db
from datetime import datetime, timezone, timedelta

# ========================================================================
# 1. VIEW & SELECT MENU HỖ TRỢ TRA CỨU LỆNH (HELP SYSTEM)
# ========================================================================

class HelpSelect(discord.ui.Select):
    def __init__(self, user_name: str):
        self.user_name = user_name
        # Khởi tạo các danh mục thả xuống (Select Options)
        options = [
            discord.SelectOption(
                label="🎮 Digimon RPG", 
                description="Hệ thống mini-game nhập vai, thu thập Digimon", 
                emoji="🦖", 
                value="rpg"
            ),
            discord.SelectOption(
                label="⚔️ Dungeon & Party", 
                description="Thiết lập chỉ số Gear, tra cứu Boss và ghép tổ đội", 
                emoji="🛡️", 
                value="party"
            ),
            discord.SelectOption(
                label="🛠️ Admin & Setup", 
                description="Các lệnh cấu hình hệ thống dành riêng cho Quản trị viên", 
                emoji="⚙️", 
                value="admin"
            ),
            discord.SelectOption(
                label="🌍 General Utilities", 
                description="Các lệnh tiện ích cơ bản của bot MyK", 
                emoji="📁", 
                value="general"
            )
        ]
        super().__init__(
            placeholder="📂 Hãy chọn một danh mục lệnh cần tra cứu...", 
            min_values=1, 
            max_values=1, 
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        # Tạo Embed hiển thị nội dung tùy thuộc vào danh mục được chọn
        embed = discord.Embed(color=discord.Color.green())
        embed.set_footer(text=f"Yêu cầu bởi {self.user_name} | MyK Bot", icon_url=interaction.user.display_avatar.url)

        selected_value = self.values[0]

        if selected_value == "rpg":
            embed.title = "🎮 Digimon RPG Commands"
            embed.description = "Hệ thống tính năng Game RPG tự động - Thu thập, ấp trứng và nâng cấp sức mạnh Digimon."
            embed.add_field(
                name="👤 Hồ sơ & Giao dịch", 
                value="🔹 `/rpg_profile`: Xem và quản lý hồ sơ nhân vật/Digimon cá nhân.\n"
                      "🔹 `/hatch`: 🥚 Ấp trứng Digimon mới khi bạn có đủ 5 Hatch Cores.\n"
                      "🔹 `/market`: 🏪 Mở sàn giao dịch vật phẩm toàn cầu giữa các người chơi.", 
                inline=False
            )
            embed.add_field(
                name="⚔️ Hành động & Chiến đấu", 
                value="🔹 `/combat`: 💥 Mở bảng điều khiển tấn công hoặc kiểm tra World Boss.\n"
                      "🔹 `/farm_dungeon`: 🏰 Tham gia phó bản cày cuốc để kiếm nguyên liệu và trang bị quý hiếm.", 
                inline=False
            )

        elif selected_value == "party":
            embed.title = "⚔️ Dungeon & Party Finder Commands"
            embed.description = "Các lệnh hỗ trợ người chơi xây dựng hồ sơ trang bị và tìm kiếm thành viên cùng đi Raid."
            embed.add_field(
                name="📋 Thông tin cá nhân & Trang bị (Gear)", 
                value="🔹 `/mygear`: Cấu hình/Cập nhật chi tiết chỉ số trang bị cá nhân (IGN, Múi giờ, Gear).\n"
                      "🔹 `/showmygear`: Hiển thị công khai thông tin Gear hiện tại của bạn.\n"
                      "🔹 `/set_timezone`: 🌍 Cài đặt múi giờ riêng để hệ thống hiển thị thời gian chính xác.", 
                inline=False
            )
            embed.add_field(
                name="🤝 Quản lý Tổ đội & Lịch trình", 
                value="🔹 `/party_lobby`: 🌐 Truy cập Sảnh Tìm Tổ Đội để tham gia hoặc tạo tổ đội đi Dungeon.\n"
                      "🔹 `/dglist`: Kiểm tra yêu cầu về chỉ số Gear tối thiểu của từng Dungeon.\n"
                      "🔹 `/schedule`: 📅 Xem bộ đếm ngược thời gian hồi/xuất hiện tiếp theo của Bless Raid và Digital Boss.", 
                inline=False
            )

        elif selected_value == "admin":
            embed.title = "🛠️ Admin & Setup Commands"
            embed.description = "Hệ thống lệnh cấu hình Bot nâng cao, yêu cầu quyền **Administrator** (Quản trị viên)."
            embed.add_field(
                name="📺 Cài đặt Kênh thông báo (Channels)", 
                value="🔹 `/setup_party_channel`: Thiết lập kênh nhận thông báo tự động khi có Party mới thành lập.\n"
                      "🔹 `/setup_news_channel`: Thiết lập kênh công bố các tin tức cập nhật mới từ nhà phát triển.\n"
                      "🔹 `/setup_boss_channel`: Thiết lập phòng cổng chat liên server (Relay Webhook) cho sự kiện Boss.", 
                inline=False
            )
            embed.add_field(
                name="🎭 Quản lý Vai trò (Roles) & Sự kiện", 
                value="🔹 `/roles_menu`: Gửi bảng Menu chọn Role tự động cho thành viên trong server.\n"
                      "🔹 `/addrole`: Bổ sung thêm một Role mới vào danh mục của bảng chọn tự động.\n"
                      "🔹 `/removerole`: Loại bỏ một Role ra khỏi danh mục bảng cấu hình.\n"
                      "🔹 `/set_invite_role`: Liên kết mã link mời (Invite Code) với Role để tự động cấp khi thành viên mới tham gia.\n"
                      "🔹 `/setbless` / `/setboss`: Cấu hình mốc thời gian diễn ra sự kiện Bless Tour và Boss định kỳ.", 
                inline=False
            )
            embed.add_field(
                name="💻 Developer Only (Chỉ dành cho chủ sở hữu Bot)", 
                value="🔹 `/ownerbroadcast`: Phát thông báo cập nhật hệ thống trên diện rộng đến tất cả các Server.\n"
                      "🔹 `!reloadall`: Lệnh tiền tố (Prefix) dùng để nạp lại mã nguồn nóng và đồng bộ danh sách Slash Commands với Discord API.", 
                inline=False
            )

        elif selected_value == "general":
            embed.title = "🌍 General Commands"
            embed.description = "Các lệnh tiện ích cơ bản giúp người dùng tương tác nhanh với hệ thống bot."
            embed.add_field(
                name="📁 Lệnh thông dụng", 
                value="🔹 `/help`: Gọi menu danh mục tra cứu lệnh tương tác thông minh này.\n"
                      "🔹 `/hello`: Nhận một lời chào mừng nồng nhiệt kèm trạng thái từ MyK Bot.\n"
                      "🔹 `/setupguide`: Xem tài liệu hướng dẫn từng bước thiết lập nhanh bot cho một server mới hoàn toàn.", 
                inline=False
            )

        # Cập nhật tin nhắn hiện tại với thông tin danh mục mới
        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, user_name: str):
        super().__init__(timeout=180)  # Tự động đóng tương tác sau 3 phút không hoạt động
        self.add_item(HelpSelect(user_name))


# ========================================================================
# 2. COG CHỨA CÁC LỆNH TIỆN ÍCH CHUNG (GENERAL COG)
# ========================================================================

class General(commands.Cog, name="Basic command"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="hello", description="Bot say hello to you")
    async def hello(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"👋 Hello {interaction.user.mention}! I'm MyK bot - customed bot for DMW/DMO. Wish you have an awesome day gaming! 🦖"
        )

    @app_commands.command(name="help", description="Open helper for commands with categories")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📖 MyK Bot - Command Directory", 
            description="Welcome to the MyK Bot Help Center.\n\n"

"⚠️ **Important Note:** You need to create and update your personal profile via the `/mygear` command before you can use the Party Finder feature or join RPGs.\n\n"

"👇 **Please click on the dropdown menu below to select the command category you need to view:**",
            color=discord.Color.blurple()
        )
        # Thiết lập ảnh đại diện của Bot làm hình thu nhỏ nếu có dữ liệu
        if self.bot.user and self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            
        view = HelpView(interaction.user.display_name)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="setupguide", description="View the step-by-step setup guide for the bot")
    async def setupguide(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📋 Bot Setup Guide", color=discord.Color.gold())
        embed.description = (
            "**Step 1:** You need to set up your profile first using `/mygear`.\n\n"
            "**Step 2:** Make a new channel (or choose an existing one) to receive party finder notifications using `/setup_party_channel`.\n\n"
            "**Step 3:** Make a new channel (or choose an existing one) to receive new notifications about updates, etc., from the bot, use `/setup_news_channel`."
             "**Step 4:** Make a new channel (or choose an existing one) to join into our global chat, use  `/setup_boss_channel "  )   
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="schedule", description="To see schedule spawn time of raid")
    async def schedule(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        utc_now = datetime.now(timezone.utc)
        guild_id = int(interaction.guild_id)
        
        bless_data = await db.bless_tours.find_one({"guild_id": guild_id})
        boss_data = await db.bosses.find_one({"guild_id": guild_id})
        
        embed = discord.Embed(title="📅 SCHEDULE TIMERS", color=discord.Color.blue())
        
        # 1. Tính toán thời gian Bless Raid
        if bless_data:
            bless_minute = bless_data.get("minute", 0)
            maps_str = ", ".join(bless_data.get("maps", ["Forest of Beginning"]))
            target_bless = utc_now.replace(minute=bless_minute, second=0, microsecond=0)
            if target_bless <= utc_now:
                target_bless += timedelta(hours=1)
            unix_bless = int(target_bless.timestamp())
            
            bless_text = f"**Map:** {maps_str}\n**Time:** Next <t:{unix_bless}:R> (<t:{unix_bless}:t>)"
            embed.add_field(name="📌 Bless Raid timer", value=bless_text, inline=False)
        else:
            embed.add_field(name="📌 Bless Raid timer", value="*didn't set up, use admin command: `/setbless`*", inline=False)

        # 2. Tính toán lịch spawn của các Boss
        if boss_data and "bosses" in boss_data and boss_data["bosses"]:
            boss_lines = []
            for b_key, b in boss_data["bosses"].items():
                try:
                    h, m = map(int, b.get("base_server_time", "00:00").split(":"))
                    target_boss = utc_now.replace(hour=h, minute=m, second=0, microsecond=0)
                    while target_boss <= utc_now:
                        target_boss += timedelta(minutes=90)
                    unix_boss = int(target_boss.timestamp())
                    boss_lines.append(f"**Boss:** {b['name']}\n**Map:** {b['map']}\n**Time:** Next <t:{unix_boss}:R> (<t:{unix_boss}:t>)\n------------------")
                except Exception as e:
                    boss_lines.append(f"Error boss {b_key}: {e}")
            embed.add_field(name="🚨 Digital Raid timer", value="\n".join(boss_lines), inline=False)
        else:
            embed.add_field(name="🚨 Digital Raid timer", value="*didn't setup, use admin command: `/setboss`*", inline=False)

        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(General(bot))