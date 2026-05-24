import discord
from discord import app_commands
from discord.ext import commands
from Database import db
from datetime import datetime, timezone, timedelta

# ==========================================
# 1. VIEW DỊCH THUẬT MENU HELP
# ==========================================
class HelpTranslationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    def get_translated_embed(self, lang: str, user_name: str) -> discord.Embed:
        embed = discord.Embed(color=discord.Color.green())
    
        if lang == "en":
            embed.title = "📖 MyK Bot - Command Directory"
            embed.description = "List of all functional categories currently operating within this bot:"
            embed.add_field(name="📁 Monster Timer Setup (Admin)", value="🔹 `/setbless [minute] [maps]`: Set bless raid timer\n🔹 `/setboss [boss] [map] [HH:MM]`: Set digital tour timer", inline=False)
            embed.add_field(name="📁 Dungeons Stat Check", value="🔹 `/dglist`: See the list of supported dungeons\n🔹 `/dgcheck [dg_name]`: Update and check your stats against requirements\n🔹 `/raid [dg_name]`: Find party for specific dungeon\n🔹 `/setstd [dg_name]` *(Admin)*: Set standard stats for dungeons", inline=False)
            embed.add_field(name="📁 Basic Commands", value="🔹 `/hello`: Bot says hi to you\n🔹 `/help`: Open command menu\n🔹 `/schedule`: Open timer schedule", inline=False)
            embed.add_field(name="📁 Role Management", value="🔹 `/setup_role_panel` *(Admin)*: Create role assignment panel", inline=False)
            embed.set_footer(text=f"Translated for {user_name}")
            
        elif lang == "id":
            embed.title = "📖 MyK Bot - Panduan Perintah"
            embed.description = "Berikut adalah detail fungsi dan cara menggunakan perintah saat ini:"
            embed.add_field(name="📁 Pengaturan Waktu Monster (Admin)", value="🔹 `/setbless`: Atur pengatur waktu serangan berkah\n🔹 `/setboss`: Atur pengatur waktu tur digital", inline=False)
            embed.add_field(name="📁 Pengecekan statistik Dungeon", value="🔹 `/dglist`: Lihat daftar dungeon yang didukung\n🔹 `/dgcheck`: Membandingkan statistik Anda dengan persyaratan minimum\n🔹 `/raid`: Cari party untuk dungeon\n🔹 `/setstd` *(Admin)*: Atur standar untuk dungeon", inline=False)
            embed.add_field(name="📁 Sistem Perintah Dasar", value="🔹 `/hello`: Bot menyapa Anda\n🔹 `/help`: Buka menu perintah\n🔹 `/schedule`: Buka jadwal pengatur waktu", inline=False)
            embed.add_field(name="📁 Manajemen Peran", value="🔹 `/setup_role_panel` *(Admin)*: Buat panel peran", inline=False)
            embed.set_footer(text=f"Terjemahan dibuat untuk {user_name}")
            
        elif lang == "br":
            embed.title = "📖 MyK Bot - Guia de Comandos"
            embed.description = "Aqui estão os detalhes e como usar os comandos atuais:"
            embed.add_field(name="📁 Horário de aparição do monstro (Admin)", value="🔹 `/setbless`: Defina o cronômetro da bless raid\n🔹 `/setboss`: Defina o cronômetro da visita digital", inline=False)
            embed.add_field(name="📁 Verificação de estatísticas de masmorras", value="🔹 `/dglist`: Veja a lista de masmorras compatíveis\n🔹 `/dgcheck`: Comparar suas estatísticas atuais com os requisitos\n🔹 `/raid`: Encontrar equipe para masmorra\n🔹 `/setstd` *(Admin)*: Define o padrão para masmorras", inline=False)
            embed.add_field(name="📁 Sistema de Comandos Básicos", value="🔹 `/hello`: O bot manda um oi para você\n🔹 `/help`: Abrir menu de comandos\n🔹 `/schedule`: Abrir cronômetro", inline=False)
            embed.add_field(name="📁 Gerenciamento de Cargos", value="🔹 `/setup_role_panel` *(Admin)*: Criar painel de funções", inline=False)
            embed.set_footer(text=f"Tradução gerada para {user_name}")
            
        elif lang == "de":
            embed.title = "📖 MyK Bot - Befehlsübersicht"
            embed.description = "Hier sind die Details und die Verwendung der aktuellen Befehle:"
            embed.add_field(name="📁 Erscheinungszeit des Monsters (Admin)", value="🔹 `/setbless`: Segens-Raid-Timer einstellen\n🔹 `/setboss`: Digitalen Tourtimer einstellen", inline=False)
            embed.add_field(name="📁 Dungeons-Statistikprüfung", value="🔹 `/dglist`: Liste der unterstützten DGS\n🔹 `/dgcheck`: Werte mit Mindestanforderungen vergleichen\n🔹 `/raid`: Party für Dungeon finden\n🔹 `/setstd` *(Admin)*: Standard für DGS festlegen", inline=False)
            embed.add_field(name="📁 Basis-Befehlssystem", value="🔹 `/hello`: Der Bot sagt hallo zu dir\n🔹 `/help`: Befehlsmenü öffnen\n🔹 `/schedule`: Zeitschaltuhr öffnen", inline=False)
            embed.add_field(name="📁 Rollenverwaltung", value="🔹 `/setup_role_panel` *(Admin)*: Rollenpanel erstellen", inline=False)
            embed.set_footer(text=f"Übersetzung generiert für {user_name}")
            
        else:  # vn
            embed.title = "📖 MyK Bot - Hướng Dẫn Sử Dụng Lệnh"
            embed.description = "Chi tiết ý nghĩa và cách sử dụng các lệnh Slash (/) hiện tại:"
            embed.add_field(name="📁 Cài đặt thời gian quái vật (Admin)", value="🔹 `/setbless [phút] [map]`: Đặt giờ Bless Tour\n🔹 `/setboss [tên] [map] [HH:MM]`: Đặt giờ Boss Digital", inline=False)
            embed.add_field(name="📁 Kiểm tra chỉ số hầm ngục", value="🔹 `/dglist`: Xem danh sách hầm ngục hỗ trợ\n🔹 `/dgcheck [tên_dg]`: Cập nhật và kiểm tra chỉ số theo chuẩn\n🔹 `/raid [tên_dg]`: Tìm tổ đội đi hầm ngục\n🔹 `/setstd [tên_dg]` *(Admin)*: Đặt tiêu chuẩn cho hầm ngục", inline=False)
            embed.add_field(name="📁 Hệ Thống Lệnh Cơ Bản", value="🔹 `/hello`: Gửi lời chào từ bot\n🔹 `/help`: Mở danh mục lệnh này\n🔹 `/schedule`: Xem lịch trình xuất hiện của Boss/Bless", inline=False)
            embed.add_field(name="📁 Quản Lý Vai Trò", value="🔹 `/setup_role_panel` *(Admin)*: Tạo bảng nhận role tự động", inline=False)
            embed.set_footer(text=f"Bản dịch dành riêng cho {user_name}")
            
        return embed

    @discord.ui.button(label="🇬🇧 EN", style=discord.ButtonStyle.secondary, custom_id="help_en")
    async def trans_en(self, inter: discord.Interaction, btn: discord.ui.Button):
        await inter.response.send_message(embed=self.get_translated_embed("en", inter.user.display_name), ephemeral=True)

    @discord.ui.button(label="🇮🇩 Indo", style=discord.ButtonStyle.secondary, custom_id="help_id")
    async def trans_id(self, inter: discord.Interaction, btn: discord.ui.Button):
        await inter.response.send_message(embed=self.get_translated_embed("id", inter.user.display_name), ephemeral=True)

    @discord.ui.button(label="🇧🇷 Brazil", style=discord.ButtonStyle.secondary, custom_id="help_br")
    async def trans_br(self, inter: discord.Interaction, btn: discord.ui.Button):
        await inter.response.send_message(embed=self.get_translated_embed("br", inter.user.display_name), ephemeral=True)

    @discord.ui.button(label="🇻🇳 Tiếng Việt", style=discord.ButtonStyle.secondary, custom_id="help_vn")
    async def trans_vn(self, inter: discord.Interaction, btn: discord.ui.Button):
        await inter.response.send_message(embed=self.get_translated_embed("vn", inter.user.display_name), ephemeral=True)

    @discord.ui.button(label="🇩🇪 Deutsch", style=discord.ButtonStyle.secondary, custom_id="help_de")
    async def trans_de(self, inter: discord.Interaction, btn: discord.ui.Button):
        await inter.response.send_message(embed=self.get_translated_embed("de", inter.user.display_name), ephemeral=True)


# ==========================================
# 2. COG CHUNG (GENERAL COMMANDS)
# ==========================================
class General(commands.Cog, name="Basic command"):
    def __init__(self, bot):
        self.bot = bot
        # Đăng ký view để nút bấm luôn hoạt động ngay cả khi bot khởi động lại
        self.bot.add_view(HelpTranslationView())

    @app_commands.command(name="hello", description="Bot sẽ gửi lời chào thân thiện đến bạn")
    async def hello(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"👋 Hello {interaction.user.mention}! Wish you have an awesome day gaming! 🦖")

    @app_commands.command(name="help", description="Mở danh sách hướng dẫn sử dụng bot")
    async def help(self, interaction: discord.Interaction):
        # Khởi tạo view và lấy embed tiếng Anh làm mặc định
        view = HelpTranslationView()
        embed = view.get_translated_embed("en", interaction.user.display_name)
        await interaction.response.send_message(embed=embed, view=view)
    
    @app_commands.command(name="schedule", description="Xem lịch trình Boss và Bless Raid hiện tại")
    async def schedule(self, interaction: discord.Interaction):
        # Tránh lỗi timeout khi truy vấn DB
        await interaction.response.defer()
        
        utc_now = datetime.now(timezone.utc)
        guild_id = int(interaction.guild_id)
        
        bless_data = await db.bless_tours.find_one({"guild_id": guild_id})
        boss_data = await db.bosses.find_one({"guild_id": guild_id})
        
        embed = discord.Embed(title=f"📅 SCHEDULE", color=discord.Color.blue())
        
        # 1. Hiển thị Bless Raid
        if bless_data:
            bless_minute = bless_data.get("minute", 0)
            maps_str = ", ".join(bless_data.get("maps", ["Forest of Beginning"]))
            
            target_bless = utc_now.replace(minute=bless_minute, second=0, microsecond=0)
            if target_bless <= utc_now:
                target_bless += timedelta(hours=1)
                
            unix_bless = int(target_bless.timestamp())
            
            bless_text = (
                f"**Map:** {maps_str}\n"
                f"**Time:** Next <t:{unix_bless}:R> (<t:{unix_bless}:t>)"
            )
            embed.add_field(name="📌 Bless Raid timer", value=bless_text, inline=False)
        else:
            embed.add_field(name="📌 Bless Raid timer", value="*Chưa thiết lập, admin dùng lệnh `/setbless`*", inline=False)

        # 2. Hiển thị Digital Raid
        if boss_data and "bosses" in boss_data and boss_data["bosses"]:
            boss_lines = []
            for b_key, b in boss_data["bosses"].items():
                try:
                    h, m = map(int, b.get("base_server_time", "00:00").split(":"))
                    target_boss = utc_now.replace(hour=h, minute=m, second=0, microsecond=0)
                    
                    while target_boss <= utc_now:
                        target_boss += timedelta(minutes=90)
                    
                    unix_boss = int(target_boss.timestamp())
                    
                    boss_lines.append(
                        f"**Boss:** {b['name']}\n"
                        f"**Map:** {b['map']}\n"
                        f"**Time:** Next <t:{unix_boss}:R> (<t:{unix_boss}:t>)\n"
                        f"------------------"
                    )
                except Exception as e:
                    boss_lines.append(f"Lỗi xử lý boss {b_key}: {e}")
            
            embed.add_field(name="🚨 Digital Raid timer", value="\n".join(boss_lines), inline=False)
        else:
            embed.add_field(name="🚨 Digital Raid timer", value="*Chưa thiết lập, admin dùng lệnh `/setboss`*", inline=False)

        await interaction.followup.send(embed=embed)
    
async def setup(bot):
    await bot.add_cog(General(bot))