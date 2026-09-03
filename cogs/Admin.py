import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
from database import db
news_channel_col = db["server_configs"]



# ==========================================
# 3. COG ADMIN (QUẢN TRỊ HỆ THỐNG)
# ==========================================
# GIAO DIỆN MODAL NHẬP THÔNG BÁO BẰNG PHÍM ENTER
# ==========================================
class BroadcastModal(discord.ui.Modal):
    def __init__(self, cog):
        # Đặt tiêu đề cho bảng nhập liệu
        super().__init__(title="📢 Broadcast")
        self.cog = cog

    # Khai báo ô nhập văn bản dạng dài (Paragraph/Long)
    message_input = discord.ui.TextInput(
        label="Nội dung thông báo",
        style=discord.TextStyle.long,
        placeholder="Nhập nội dung thông báo tại đây. Bấm phím Enter để xuống dòng thoải mái, hỗ trợ cả Markdown...",
        required=True,
        max_length=4000
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Defer tại đây vì quá trình gửi tin tới nhiều server sẽ mất thời gian
        await interaction.response.defer(ephemeral=True)
        # Lấy nội dung trực tiếp từ Modal (đã có sẵn các dấu xuống dòng thực tế)
        message = self.message_input.value
        # Lấy toàn bộ danh sách channel từ database
        cursor = news_channel_col.find({})
        channels_data = await cursor.to_list(length=None) 
        success_count = 0
        fail_count = 0
        # Xử lý tiêu đề ngày tháng theo thiết kế
        utc_now = datetime.now(timezone.utc)
        day = utc_now.day
        if 11 <= day <= 13:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
            
        date_title = f"📢 {utc_now.strftime('%B')} {day}{suffix} {utc_now.year}"

        # Vòng lặp gửi tin nhắn đến các server
        for data in channels_data:
            channel_id = data.get("channel_id")
            if not channel_id:
                continue
                
            try:
                channel = self.cog.bot.get_channel(channel_id) or await self.cog.bot.fetch_channel(channel_id)
                
                if channel:
                    embed = discord.Embed(
                        title=date_title,
                        description=message, # Không cần .replace("\\n") nữa vì text từ modal giữ nguyên cấu trúc dòng
                        color=discord.Color.from_str("#2ecc71"),
                        timestamp=utc_now
                    )
                    embed.set_footer(text="Global System Announcement")
                    
                    await channel.send(embed=embed)
                    success_count += 1
                else:
                    fail_count += 1
            except discord.Forbidden:
                fail_count += 1
            except Exception as e:
                print(f"Lỗi khi gửi broadcast tới kênh {channel_id}: {e}")
                fail_count += 1

        # Trả về kết quả báo cáo sau khi hoàn tất gửi qua mockup follow-up
        summary = (
            f"✅ **Hoàn tất quá trình gửi tin Broadcast qua Modal!**\n"
            f"🟢 Thành công: `{success_count}` server\n"
            f"🔴 Thất bại: `{fail_count}` server (Do bot bị kick hoặc thiếu quyền gửi tin nhắn)"
        )
        await interaction.followup.send(summary, ephemeral=True)



class NewsSystemCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # CHÚ Ý: Thay ID của bạn vào mảng này
        self.OWNER_IDS = [1283689737567211581] 

    # ========================================================================
    # LỆNH 1: SETUP NEWS CHANNEL (Dành cho Admin Server)
    # ========================================================================
    @app_commands.command(name="setup_news_channel", description="Subscribe to the channel to receive news and updates from Bot.")
    @app_commands.describe(channel="Select the channel you want the bot to send notifications to.")
    # ĐÃ XÓA decorator check permission ở đây để tự xử lý linh hoạt bên trong
    async def setup_news_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        
        # 1. KIỂM TRA QUYỀN HẠN: Cho phép nếu là Admin server HOẶC là Bot Owner
        is_admin = interaction.permissions.manage_guild if interaction.guild else False
        if not (is_admin or interaction.user.id in self.OWNER_IDS):
            return await interaction.response.send_message("❌ Access denied! You need Server Administrator privileges to use this command..", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id
        channel_id = channel.id

        # 2. Lưu vào database
        await news_channel_col.update_one(
            {"guild_id": guild_id},
            {"$set": {"channel_id": channel_id}},
            upsert=True
        )

        embed = discord.Embed(
            title="✅ Setup Successful",
            description=f"This server has been subscribed to receive updates on this channel. {channel.mention}.",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ========================================================================
    # LỆNH 2: OWNER BROADCAST (Chỉ dành cho Developer/Owner)
    # ========================================================================
    # ========================================================================
    # LỆNH 2: OWNER BROADCAST (Mở Modal nhập liệu)
    # ========================================================================
    @app_commands.command(name="ownerbroadcast", description="Mở bảng soạn thông báo gửi đến các server")
    async def ownerbroadcast(self, interaction: discord.Interaction):
        # 1. Kiểm tra xem người dùng có phải là Owner không
        if interaction.user.id not in self.OWNER_IDS:
            return await interaction.response.send_message("❌ Lệnh này chỉ dành cho Developer.", ephemeral=True)

        # 2. Gọi hiển thị Modal ngay lập tức (KHÔNG sử dụng defer trước dòng này)
        await interaction.response.send_modal(BroadcastModal(self))
class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Lệnh quản trị hệ thống - VẪN DÙNG PREFIX (!) ĐỂ AN TOÀN
    @commands.command(name="reloadall")
    @commands.is_owner() 
    async def reload_all(self, ctx):
        await ctx.typing()
        reloaded = []
        errors = []
        extensions = list(self.bot.extensions.keys())

        for ext in extensions:
            try:
                await self.bot.reload_extension(ext)
                reloaded.append(ext.split('.')[-1]) 
            except Exception as e:
                errors.append(f"**{ext.split('.')[-1]}**: {str(e)}")
        
        # Gọi sync tree thủ công để cập nhật lại Slash Commands nếu có thay đổi code
        try:
            await self.bot.tree.sync()
            reloaded.append("🔄 Đồng bộ Slash Commands thành công!")
        except Exception as e:
            errors.append(f"Sync Tree: {str(e)}")

        embed = discord.Embed(title="🔄 System Reload", color=discord.Color.green())
        if reloaded:
            embed.add_field(name="Thành công", value="\n".join(reloaded), inline=False)
        if errors:
            embed.color = discord.Color.red()
            embed.add_field(name="Lỗi", value="\n".join(errors), inline=False)
        await ctx.send(embed=embed)

        
async def setup(bot):
    await bot.add_cog(NewsSystemCog(bot))
    await bot.add_cog(Admin(bot))
    