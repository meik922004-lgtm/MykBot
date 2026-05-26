import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
from Database import db 

# ==========================================
# 1. VIEW DỊCH THUẬT GIAO DIỆN SỰ KIỆN
# ==========================================
class EventTranslationView(discord.ui.View):
    def __init__(self, original_embed: discord.Embed, event_type: str):
        super().__init__(timeout=None)
        self.original_embed = original_embed
        self.event_type = event_type

    def build_embed(self, lang: str, user_name: str) -> discord.Embed:
        fields = {f.name: f.value for f in self.original_embed.fields}
        embed = discord.Embed(color=discord.Color.blue())
        langs = {
            "en": {"title_bless": "✨ BLESS TOUR STARTING IN 5 MIN! ✨", "title_boss": "🚨 DIGITAL TOUR BOSS ALERT 🚨"},
            "vn": {"title_bless": "✨ BLESS TOUR SẼ BẮT ĐẦU TRONG 5 PHÚT! ✨", "title_boss": "🚨 CẢNH BÁO BOSS DIGITAL TOUR 🚨"},
            "id": {"title_bless": "✨ BLESS TOUR DIMULAI DALAM 5 MENIT! ✨", "title_boss": "🚨 PEMBERITAHUAN DIGITAL TOUR BOSS 🚨"},
            "br": {"title_bless": "✨ BLESS TOUR COMEÇA EM 5 MINUTOS! ✨", "title_boss": "🚨 ALERTA DE DIGITAL TOUR BOSS 🚨"},
            "de": {"title_bless": "✨ BLESS TOUR STARTET IN 5 MINUTEN! ✨", "title_boss": "🚨 DIGITAL TOUR BOSS WARNUNG 🚨"}
        }
        cfg = langs.get(lang, langs["en"])
        embed.title = cfg["title_bless"] if self.event_type == "bless" else cfg["title_boss"]
        if self.original_embed.description: embed.description = self.original_embed.description
        for name, value in fields.items(): embed.add_field(name=name, value=value, inline=False)
        embed.set_footer(text=f"Translated for {user_name}")
        return embed

    @discord.ui.button(label="🇬🇧 EN", style=discord.ButtonStyle.secondary, custom_id="evt_en")
    async def trans_en(self, inter: discord.Interaction, btn: discord.ui.Button): await inter.response.send_message(embed=self.build_embed("en", inter.user.display_name), ephemeral=True)
    @discord.ui.button(label="🇻🇳 VN", style=discord.ButtonStyle.secondary, custom_id="evt_vn")
    async def trans_vn(self, inter: discord.Interaction, btn: discord.ui.Button): await inter.response.send_message(embed=self.build_embed("vn", inter.user.display_name), ephemeral=True)
    @discord.ui.button(label="🇮🇩 ID", style=discord.ButtonStyle.secondary, custom_id="evt_id")
    async def trans_id(self, inter: discord.Interaction, btn: discord.ui.Button): await inter.response.send_message(embed=self.build_embed("id", inter.user.display_name), ephemeral=True)
    @discord.ui.button(label="🇧🇷 BR", style=discord.ButtonStyle.secondary, custom_id="evt_br")
    async def trans_br(self, inter: discord.Interaction, btn: discord.ui.Button): await inter.response.send_message(embed=self.build_embed("br", inter.user.display_name), ephemeral=True)
    @discord.ui.button(label="🇩🇪 DE", style=discord.ButtonStyle.secondary, custom_id="evt_de")
    async def trans_de(self, inter: discord.Interaction, btn: discord.ui.Button): await inter.response.send_message(embed=self.build_embed("de", inter.user.display_name), ephemeral=True)


# ==========================================
# 2. COG QUẢN LÝ LỊCH TRÌNH BOSS & BLESS
# ==========================================
class DigitalTour(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.notified_bosses = set()
        self.notified_bless = set()
        self.boss_schedule_loop.start() 

    def cog_unload(self):
        self.boss_schedule_loop.cancel()

    @tasks.loop(minutes=1)
    async def boss_schedule_loop(self):
        await self.bot.wait_until_ready()
        try:
            utc_now = datetime.now(timezone.utc)
            
            # Xử lý Bless Tour (Lặp mỗi giờ)
            try:
                cursor_bless = db.bless_tours.find({})
                async for bless_cfg in cursor_bless:
                    bless_minute = bless_cfg.get("minute")
                    if bless_minute is None: continue
                    
                    guild = self.bot.get_guild(bless_cfg["guild_id"])
                    if not guild: continue

                    target_bless = utc_now.replace(minute=bless_minute, second=0, microsecond=0)
                    if target_bless <= utc_now:
                        target_bless += timedelta(hours=1)
                    
                    diff_bless = (target_bless - utc_now).total_seconds()
                    event_id_bless = f"{guild.id}_bless_{target_bless.timestamp()}"

                    if 240 <= diff_bless < 300:
                        if event_id_bless not in self.notified_bless:
                            await self.send_bless_alert(guild, bless_cfg, target_bless)
                            self.notified_bless.add(event_id_bless)
                    else:
                        if event_id_bless in self.notified_bless:
                            self.notified_bless.remove(event_id_bless)
            except Exception as e:
                print(f"[ERROR] Bless Tour: {e}")

            # Xử lý Digital Raid Boss (Chu kỳ 90 phút)
            try:
                cursor_boss = db.bosses.find({})
                async for guild_data in cursor_boss:
                    guild = self.bot.get_guild(guild_data['guild_id'])
                    if not guild: continue
                    
                    for boss_key, boss in guild_data.get("bosses", {}).items():
                        try:
                            base_h, base_m = map(int, boss["base_server_time"].split(":"))
                            target_boss = utc_now.replace(hour=base_h, minute=base_m, second=0, microsecond=0)
                            
                            while target_boss <= utc_now:
                                target_boss += timedelta(minutes=90)
                            
                            diff_boss = (target_boss - utc_now).total_seconds()
                            event_id_boss = f"{guild.id}_{boss_key}_{target_boss.timestamp()}"

                            if 240 <= diff_boss < 300:
                                if event_id_boss not in self.notified_bosses:
                                    await self.send_boss_alert(guild, boss, target_boss)
                                    self.notified_bosses.add(event_id_boss)
                            else:
                                if event_id_boss in self.notified_bosses:
                                    self.notified_bosses.remove(event_id_boss)
                        except Exception as e:
                            print(f"Error stucture of boss {boss_key}: {e}")
                            continue
            except Exception as e:
                print(f"[ERROR] Digital Raid: {e}")

        except Exception as e:
            print(f"[CRITICAL] error loop system: {e}")

    async def send_boss_alert(self, guild, boss, target_dt):
        channel = discord.utils.get(guild.text_channels, name="raid-timer")
        role = discord.utils.get(guild.roles, name="Tourist")
        if channel and role:
            unix_ts = int(target_dt.timestamp())
            embed = discord.Embed(title=f" DIGITAL BOSS ALERT", color=discord.Color.red())
            embed.add_field(name="Boss", value=boss['name'], inline=True)
            embed.add_field(name="Map", value=boss['map'], inline=True)
            embed.add_field(name="Time", value=f"<t:{unix_ts}:t> (<t:{unix_ts}:R>)", inline=False)
            await channel.send(content=f"{role.mention} Digital Raid is spawning soon!", embed=embed, view=EventTranslationView(embed, "boss"))

    async def send_bless_alert(self, guild, bless_cfg, target_dt):
        channel = discord.utils.get(guild.text_channels, name="raid-timer")
        role = discord.utils.get(guild.roles, name="Tourist")
        if channel and role:
            unix_ts = int(target_dt.timestamp())
            maps_str = ", ".join(bless_cfg.get("maps", []))
            embed = discord.Embed(title="✨ BLESS TOUR REMAINING! ✨", color=discord.Color.gold())
            embed.add_field(name="Map", value=maps_str, inline=False)
            embed.add_field(name="Time", value=f"<t:{unix_ts}:t> (<t:{unix_ts}:R>)", inline=False)
            await channel.send(content=f"{role.mention} Bless Tour starts in 5 mins!", embed=embed, view=EventTranslationView(embed, "bless"))

    # Lệnh Slash: Cài đặt Bless
    @app_commands.command(name="setbless", description="Setup bless time")
    @app_commands.default_permissions(administrator=True)
    async def setbless(self, interaction: discord.Interaction, minute: int, maps: str):
        guild_id = int(interaction.guild_id)
        map_list = [m.strip() for m in maps.split("|")]
        await db.bless_tours.update_one(
            {"guild_id": guild_id}, 
            {"$set": {"minute": minute, "maps": map_list}}, 
            upsert=True
        )
        await interaction.response.send_message(f"✅ Tinme saved at  **:{minute:02d}** every hour. Map: {', '.join(map_list)}")

    # Lệnh Slash: Cài đặt Boss
    @app_commands.command(name="setboss", description="Setup Digital tour time")
    @app_commands.default_permissions(administrator=True)
    async def setboss(self, interaction: discord.Interaction, b_name: str, m_name: str, s_time: str):
        guild_id = int(interaction.guild_id)
        await db.bosses.update_one(
            {"guild_id": guild_id},
            {"$set": {f"bosses.{b_name.lower()}": {"name": b_name, "map": m_name, "base_server_time": s_time}}},
            upsert=True
        )
        await interaction.response.send_message(f"✅ Saved boss **{b_name}** at Map **{m_name}** to database!")


# ==========================================
# 3. COG ADMIN (QUẢN TRỊ HỆ THỐNG)
# ==========================================
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
        @app_commands.command(name="debug_cog", description="Công cụ ép load Cog để bắt tận tay lỗi ẩn")
    async def debug_cog(self, interaction: discord.Interaction, cog_name: str):
        await interaction.response.defer(ephemeral=True)
        import traceback
        
        try:
            # Thử load file cog
            await self.bot.load_extension(f"cogs.{cog_name}")
            await self.bot.tree.sync() # Sync lệnh ngay lập tức
            await interaction.followup.send(f"✅ Đã tải và đồng bộ thành công file `{cog_name}`!")
            
        except commands.ExtensionAlreadyLoaded:
            # Nếu file đã tồn tại nhưng kẹt, thử reload lại
            try:
                await self.bot.reload_extension(f"cogs.{cog_name}")
                await self.bot.tree.sync()
                await interaction.followup.send(f"✅ Đã làm mới (reload) thành công `{cog_name}`!")
            except Exception as e:
                err = traceback.format_exc()
                await interaction.followup.send(f"❌ **LỖI KHI RELOAD FILE {cog_name}:**\n


async def setup(bot):
    await bot.add_cog(Admin(bot))
    await bot.add_cog(DigitalTour(bot))