import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import datetime
import re
import random

# Hàm hỗ trợ parse thời gian từ chuỗi (vd: 10m, 2h, 1d) sang giây
def parse_duration(duration_str: str) -> int:
    regex = r"^(\d+)([smhd])$"
    match = re.match(regex, duration_str.lower().strip())
    if not match:
        return None
    
    amount, unit = match.groups()
    amount = int(amount)
    
    units = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400
    }
    return amount * units[unit]


# View chứa nút bấm tham gia/thoát Giveaway
class GiveawayView(discord.ui.View):
    def __init__(self, duration_seconds: int):
        super().__init__(timeout=duration_seconds)
        self.participants = set() # Lưu trữ ID người tham gia để tránh trùng lặp

    @discord.ui.button(label="Tham gia 🎉", style=discord.ButtonStyle.primary, custom_id="join_giveaway")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        
        if user_id in self.participants:
            self.participants.remove(user_id)
            await interaction.response.send_message("❌ Bạn đã **rút khỏi** Giveaway này!", ephemeral=True)
        else:
            self.participants.add(user_id)
            await interaction.response.send_message("✅ Bạn đã **tham gia** Giveaway thành công!", ephemeral=True)


# Modal nhận dữ liệu đầu vào từ người tạo
class GiveawayModal(discord.ui.Modal, title="Tạo Giveaway Mới"):
    title_input = discord.ui.TextInput(
        label="Tên / Tiêu đề Giveaway",
        placeholder="Ví dụ: Giveaway Nitro tháng 8",
        required=True
    )
    prize_input = discord.ui.TextInput(
        label="Phần thưởng",
        placeholder="Ví dụ: 1x Discord Nitro 1 Month",
        required=True
    )
    winners_input = discord.ui.TextInput(
        label="Số lượng người thắng",
        placeholder="Ví dụ: 1",
        default="1",
        required=True
    )
    duration_input = discord.ui.TextInput(
        label="Thời gian (s: giây, m: phút, h: giờ, d: ngày)",
        placeholder="Ví dụ: 10m, 2h, 1d",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Validate số lượng người thắng
        try:
            winners_count = int(self.winners_input.value)
            if winners_count <= 0:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("❌ Số lượng người thắng phải là một số nguyên dương!", ephemeral=True)

        # Validate thời gian
        duration_seconds = parse_duration(self.duration_input.value)
        if not duration_seconds or duration_seconds <= 0:
            return await interaction.response.send_message("❌ Định dạng thời gian không hợp lệ! Hãy dùng dạng `10s`, `10m`, `2h`, hoặc `1d`.", ephemeral=True)

        # Tính thời điểm kết thúc theo dạng Unix Timestamp để hiển thị giờ địa phương
        end_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=duration_seconds)
        end_timestamp = int(end_time.timestamp())

        # Tạo Embed thông báo bắt đầu
        embed = discord.Embed(
            title=f"🎉 GIVEAWAY: {self.title_input.value} 🎉",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.add_field(name="🎁 Phần thưởng", value=f"**{self.prize_input.value}**", inline=False)
        embed.add_field(name="🏆 Số người thắng", value=f"**{winners_count}**", inline=True)
        embed.add_field(name="👑 Người tạo", value=interaction.user.mention, inline=True)
        # Sử dụng format <t:timestamp:R> để Discord tự hiển thị thời gian còn lại theo local timezone người xem
        embed.add_field(name="⏰ Kết thúc vào", value=f"<t:{end_timestamp}:F> (<t:{end_timestamp}:R>)", inline=False)
        embed.set_footer(text="Bấm vào nút bên dưới để tham gia/thoát!")

        view = GiveawayView(duration_seconds=duration_seconds)
        
        # Gửi thông báo bắt đầu Giveaway
        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()

        # Đợi hết thời gian giveaway
        await asyncio.sleep(duration_seconds)

        # Đóng nút bấm sau khi hết giờ
        for child in view.children:
            child.disabled = True
        
        # Xử lý kết quả
        participants = list(view.participants)
        
        if not participants:
            end_embed = discord.Embed(
                title=f"🎉 GIVEAWAY KẾT THÚC: {self.title_input.value} 🎉",
                description="❌ **Không thể chọn người thắng vì không có ai tham gia!**",
                color=discord.Color.red()
            )
            await message.edit(embed=end_embed, view=view)
            await message.reply("😭 Giveaway đã kết thúc nhưng không có ai tham gia.")
            return

        # Chọn người chiến thắng ngẫu nhiên
        actual_winners_count = min(winners_count, len(participants))
        winner_ids = random.sample(participants, actual_winners_count)
        winners_mentions = [f"<@{w_id}>" for w_id in winner_ids]
        winners_str = ", ".join(winners_mentions)

        # Cập nhật Embed kết thúc
        end_embed = discord.Embed(
            title=f"🎉 GIVEAWAY KẾT THÚC: {self.title_input.value} 🎉",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        end_embed.add_field(name="🎁 Phần thưởng", value=f"**{self.prize_input.value}**", inline=False)
        end_embed.add_field(name="🏆 Người chiến thắng", value=winners_str, inline=False)
        end_embed.add_field(name="👑 Người tạo", value=interaction.user.mention, inline=True)
        end_embed.set_footer(text="Chúc mừng người chiến thắng!")

        await message.edit(embed=end_embed, view=view)
        
        # Thông báo công khai và Ping người thắng
        await message.reply(f"🎊 Chúc mừng {winners_str}! Bạn đã trúng phần thưởng **{self.prize_input.value}** từ giveaway **{self.title_input.value}**!")


# Cog chứa Slash Command
class GiveawayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="giveaway", description="Tạo một chương trình giveaway mới")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def create_giveaway(self, interaction: discord.Interaction):
        """Hiển thị Form Modal để nhập thông tin Giveaway"""
        await interaction.response.send_modal(GiveawayModal())

    @create_giveaway.error
    async def giveaway_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Bạn cần có quyền `Manage Messages` để tạo Giveaway!", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GiveawayCog(bot))