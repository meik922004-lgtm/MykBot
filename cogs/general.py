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
        
    def get_translated_embed(self, user_name: str) -> discord.Embed:
        embed = discord.Embed(color=discord.Color.green())
        
        embed.title = "📖 MyK Bot - Command Directory"
        embed.description = (
            "Welcome to MyK Bot! Please ensure you set your profile gear first using "
            "**/mygear** to fully utilize dungeon information and party features.\n\n"
            "⚠️ **Important:** Setting up your gear profile is required for party matchmaking and stats verification."
        )

        # 1. General Commands
        embed.add_field(
            name="📁 General Commands",
            value=(
                "🔹 `/hello`: Say hi to the bot.\n"
                "🔹 `/help`: Open this command menu.\n"
                "🔹 `/schedule`: View spawn times for Raids/Bosses.\n"
                "🔹 `/mygear`: Setup/Update your character gear profile (REQUIRED).\n"
                "🔹 `/dglist`: View list of supported dungeons.\n"
                "🔹 `/party_lobby`: Create or manage your party lobby."
            ),
            inline=False
        )

        # 2. Admin Only
        embed.add_field(
            name="📁 Admin Only",
            value=(
                "🔹 `/setbless [min] [maps]`: Set bless raid timer.\n"
                "🔹 `/setboss [boss] [map] [HH:MM]`: Set digital tour timer.\n"
                "🔹 `/setup_role_panel`: Deploy the server role assignment menu."
            ),
            inline=False
        )

        # 3. Owner Only
        embed.add_field(
            name="📁 Owner Only",
            value="🔹 `/sync`: Sync slash commands with Discord API.",
            inline=False
        )

        embed.set_footer(text=f"Requested by {user_name} | MyK Bot")
        return embed

    # Nút bấm vẫn giữ nguyên để người dùng có thể gọi lại menu nếu cần
    @discord.ui.button(label="Refresh Menu", style=discord.ButtonStyle.primary, custom_id="help_refresh")
    async def refresh_btn(self, inter: discord.Interaction, btn: discord.ui.Button):
        await inter.response.edit_message(embed=self.get_translated_embed(inter.user.display_name), view=self)


# ==========================================
# 2. COG CHUNG (GENERAL COMMANDS)
# ==========================================
class General(commands.Cog, name="Basic command"):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(HelpTranslationView())

    @app_commands.command(name="hello", description="Bot say hello to you")
    async def hello(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"👋 Hello {interaction.user.mention}! Im MyK bot- customed bot for DMW/DMO Wish you have an awesome day gaming! 🦖")

    @app_commands.command(name="help", description="open helper for commands")
    async def help(self, interaction: discord.Interaction):
        view = HelpTranslationView()
        embed = view.get_translated_embed(interaction.user.display_name)
        await interaction.response.send_message(embed=embed, view=view)
    
    @app_commands.command(name="schedule", description="To see scheule spawn time of raid")
    async def schedule(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        utc_now = datetime.now(timezone.utc)
        guild_id = int(interaction.guild_id)
        
        bless_data = await db.bless_tours.find_one({"guild_id": guild_id})
        boss_data = await db.bosses.find_one({"guild_id": guild_id})
        
        embed = discord.Embed(title=f"📅 SCHEDULE", color=discord.Color.blue())
        
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
            embed.add_field(name="📌 Bless Raid timer", value="*didnt set up, use admin command: `/setbless`*", inline=False)

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
                    boss_lines.append(f"Error:boss {b_key}: {e}")
            embed.add_field(name="🚨 Digital Raid timer", value="\n".join(boss_lines), inline=False)
        else:
            embed.add_field(name="🚨 Digital Raid timer", value="*didnt setup, use admin command: `/setboss`*", inline=False)

        await interaction.followup.send(embed=embed)
    
async def setup(bot):
    await bot.add_cog(General(bot))