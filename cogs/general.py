import discord
from Database import db
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta

class HelpTranslationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    def get_translated_embed(self, lang: str, user_name: str) -> discord.Embed:
        embed = discord.Embed(color=discord.Color.green())
    
        if lang == "en":
            embed.title = "📖 MyK Bot - Command Directory"
            embed.description = "List of all functional categories currently operating within this bot:"
            embed.add_field(name="📁 set monster timer", value="🔹 `!setbless:[min] [map]: Set bless raid timer`\n🔹 `!setboss:[boss map hour(xx:xx)]: Set digital tour timer`", inline=False)
            embed.add_field(name="📁 Dungeons stat check", value="🔹 `!dglist: See the list of dgs supporting`.*\n🔹 `!raid[!raid name]:to compare your current stat to dg's min requirement`\n🔹 `!setstd:[!setstd name](admin):set standart for dgs. `*", inline=False)
            embed.add_field(name="📁 Basic Commands", value="🔹 `!hello: Bot say hi with you`.*\n🔹 `!help: Open command menu`\n🔹 `!schedule: Open timer.`", inline=False)
            embed.add_field(name="📁 Role Management", value="🔹 `!setup_role_panel`\n↳ *Admin: Create role panel.*", inline=False)
            embed.set_footer(text=f"Translated for {user_name}")
            
        elif lang == "id":
            embed.title = "📖 MyK Bot - Panduan Perintah"
            embed.description = "Berikut adalah detail fungsi dan cara menggunakan perintah saat ini:"
            embed.add_field(name="📁 Waktu kemunculan monster", value="🔹 `!setbless: [min map]Atur pengatur waktu serangan berkah`\n🔹 `!setboss: [boss map hour(xx:xx)]: Atur pengatur waktu tur digital ", inline=False)
            embed.add_field(name="📁 Pengecekan statistik Dungeon", value="🔹 `!dglist: Lihat daftar dungeon yang didukung`.*\n🔹 `!raid[!raid name]:untuk membandingkan statistik Anda saat ini dengan persyaratan minimum dungeon`\n🔹 `!setstd:[!setstd name](admin):atur standar untuk dungeon.`*", inline=False)
            embed.add_field(name="📁 Sistem Perintah Dasar", value="🔹 `!hello: Bot menyapa Anda`\n🔹 `!help: Buka menu perintah`\n🔹 `!schedule: Pengatur waktu terbuka.`", inline=False)
            embed.add_field(name="📁 Manajemen Peran & Hak Akses", value="🔹 `!setup_role_panel: (Admin)Buat panel peran`", inline=False)
            embed.set_footer(text=f"Terjemahan dibuat untuk {user_name}")
            
        elif lang == "br":
            embed.title = "📖 MyK Bot - Guia de Comandos"
            embed.description = "Aqui estão os detalhes e como usar os comandos atuais:"
            embed.add_field(name="📁 Horário de aparição do monstro", value="🔹 `!setbless:[min map]: Criar painel de funções`\n🔹 `!setboss:[boss map hour (xx:xx)]: Defina o cronômetro da visita digital`", inline=False)
            embed.add_field(name="📁 Verificação de estatísticas de masmorras", value="🔹 `!dglist: Veja a lista de masmorras compatíveis`.*\n🔹 `!raid[!raid name]:para comparar suas estatísticas atuais com os requisitos mínimos da masmorra`\n🔹 `!setstd:[!setstd name](admin):define o padrão para masmorras.`*", inline=False)
            embed.add_field(name="📁 Sistema de Comandos Básicos", value="🔹 `!hello: O bot manda um oi para você.`\n🔹 `!help: Abrir menu de comandos`\n🔹 `!schedule: Abrir cronômetro.`", inline=False)
            embed.add_field(name="📁 Gerenciamento de Cargos", value="🔹 `!setup_role_panel: (Admin) Criar painel de funções`", inline=False)
            embed.set_footer(text=f"Tradução gerada para {user_name}")
            
        elif lang == "de":
            embed.title = "📖 MyK Bot - Befehlsübersicht"
            embed.description = "Hier sind die Details und die Verwendung der aktuellen Befehle:"
            embed.add_field(name="📁 Erscheinungszeit des Monsters", value="🔹 `!setbless:[min map]: Segens-Raid-Timer einstellen`\n🔹 `!setboss:[boss map hour xx:xx]: Digitalen Tourtimer einstellen`", inline=False)
            embed.add_field(name="📁 Dungeons-Statistikprüfung", value="🔹 `!dglist: Siehe die Liste der unterstützten DGS.`.*\n🔹 `!raid[!raid name]:um deine aktuellen Werte mit den Mindestanforderungen des Spielleiters zu vergleichen`\n🔹 `!setstd:[!setstd name](admin):Standard für DGS festlegen.`*", inline=False)
            embed.add_field(name="📁 Basis-Befehlssystem", value="🔹 `!hello: Der Bot sagt hallo zu dir`\n🔹 `!help: Befehlsmenü öffnen`\n🔹 `!schedule:Zeitschaltuhr öffnen`", inline=False)
            embed.add_field(name="📁 Rollenverwaltung", value="🔹 `!setup_role_panel(admin):Rollenpanel erstellen`", inline=False)
            embed.set_footer(text=f"Übersetzung generiert für {user_name}")
            
        else:  # vn
            embed.title = "📖 MyK Bot - Hướng Dẫn Sử Dụng Lệnh"
            embed.description = "Chi tiết ý nghĩa và cách sử dụng các câu lệnh hiện tại:"
            embed.add_field(name="📁 chỉnh thời gian quái vật xuất hiện", value="🔹 `!setbless [phút map]: đặt giờ bless tour`\n🔹 `!setboss:[boss map hour(xx:xx)]:đặt giờ boss digital`", inline=False)
            embed.add_field(name="📁 Kiểm tra chỉ số hầm ngục", value="🔹 `!dglist: Xem danh sách các hầm ngục hỗ trợ`.*\n🔹 `!raid[!tên raid]:để so sánh chỉ số hiện tại của bạn với yêu cầu tối thiểu của hầm ngục`\n🔹 `!setstd:[!tên setstd](admin):đặt tiêu chuẩn cho hầm ngục.`*", inline=False)
            embed.add_field(name="📁 Hệ Thống Lệnh Cơ Bản", value="🔹 `!hello: Bot chào `\n🔹 `!help: Mở danh mục command`\n🔹 `!schedule: Xem lịch boss đã đặt.`", inline=False)
            embed.add_field(name="📁 Quản Lý Vai Trò", value="🔹 `!setup_role_panel: (admin) đặt vai trò`", inline=False)
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


class General(commands.Cog, name="Basic command"):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(HelpTranslationView())

    @commands.command(name="hello")
    async def hello(self, ctx):
        await ctx.send(f"👋 Hello {ctx.author.mention}! Wish you have an awesome day gaming! 🦖")

    @commands.command(name="help")
    async def help(self, ctx):
        embed = self.bot.cogs["Basic command"].bot.add_view
        embed = discord.Embed(
            title="📖 MyK Bot - Command Directory",
            description="List of all functional categories currently operating within this bot:",
            color=discord.Color.blue()
        )
        for cog_name, cog in self.bot.cogs.items():
            cog_commands = cog.get_commands()
            if not cog_commands: continue
            command_list = ", ".join([f"`!{c.name}`" for c in cog_commands])
            display_name = getattr(cog, "qualified_name", cog_name)
            embed.add_field(name=f"📁 {display_name}", value=command_list, inline=False)

        embed.set_footer(text="MyK Bot • Specialized modular architecture system")
        await ctx.send(embed=embed, view=HelpTranslationView())
    
    @commands.command(name="schedule")
    async def schedule(self, ctx):
        await ctx.typing()
        utc_now = datetime.now(timezone.utc)
        guild_id = int(ctx.guild.id)
        
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
            embed.add_field(name="📌 Bless Raid timer", value="*Chưa thiết lập, dùng lệnh !setbless [phút] [map]*", inline=False)

        # 2. Hiển thị Digital Raid
        if boss_data and "bosses" in boss_data:
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
            embed.add_field(name="🚨 Digital Raid timer", value="*Chưa thiết lập, dùng lệnh !setboss [tên] [map] [HH:MM]*", inline=False)

        await ctx.send(embed=embed)
    
async def setup(bot):
    await bot.add_cog(General(bot))