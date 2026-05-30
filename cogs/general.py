import discord
from discord import app_commands
from discord.ext import commands
from Database import db
from datetime import datetime, timezone, timedelta

# ========================================================================
# 1. HELP MENU WITH SELECT DROPDOWN
# ========================================================================

class HelpSelect(discord.ui.Select):
    def __init__(self, user_name: str):
        self.user_name = user_name
        options = [
            discord.SelectOption(
                label="🎮 Digimon RPG", 
                description="RPG system, Digimon collection and leveling", 
                emoji="🦖", 
                value="rpg"
            ),
            discord.SelectOption(
                label="⚔️ Dungeon & Party", 
                description="Gear management, raid party finder, and schedules", 
                emoji="🛡️", 
                value="party"
            ),
            discord.SelectOption(
                label="🛠️ Admin & Setup", 
                description="System configuration and administrative tools", 
                emoji="⚙️", 
                value="admin"
            ),
            discord.SelectOption(
                label="🌍 General Utilities", 
                description="Basic bot commands and information", 
                emoji="📁", 
                value="general"
            )
        ]
        super().__init__(placeholder="📂 Please select a command category...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        embed = discord.Embed(color=discord.Color.green())
        embed.set_footer(text=f"Requested by {self.user_name} | MyK Bot", icon_url=interaction.user.display_avatar.url)

        selected_value = self.values[0]

        if selected_value == "rpg":
            embed.title = "🎮 Digimon RPG Commands"
            embed.description = "Automated RPG system - Collect, hatch, and level up your Digimon."
            embed.add_field(name="👤 Profile & Trading", value="🔹 `/rpg_profile`: View and manage your Digimon profile.\n🔹 `/hatch`: 🥚 Hatch a new Digimon (Requires 5 Hatch Cores).\n🔹 `/market`: 🏪 Open the global marketplace.", inline=False)
            embed.add_field(name="⚔️ Combat", value="🔹 `/combat`: 💥 Attack World Bosses.\n🔹 `/farm_dungeon`: 🏰 Enter dungeons for materials and gear.", inline=False)

        elif selected_value == "party":
            embed.title = "⚔️ Dungeon & Party Commands"
            embed.description = "Manage your gear profile and find raid parties."
            embed.add_field(name="📋 Personal Profile", value="🔹 `/mygear`: Setup/Update your IGN, Timezone, and Gear.\n🔹 `/showmygear`: Display your current gear stats.\n🔹 `/set_timezone`: 🌍 Set your personal timezone.", inline=False)
            embed.add_field(name="🤝 Party & Schedule", value="🔹 `/party_lobby`: 🌐 Join or create a dungeon party.\n🔹 `/dglist`: View gear requirements for dungeons.\n🔹 `/schedule`: 📅 Check upcoming Boss/Bless Raid timers.", inline=False)

        elif selected_value == "admin":
            embed.title = "🛠️ Admin Commands"
            embed.description = "Configuration tools restricted to Administrators."
            embed.add_field(name="📺 Channel Setup", value="🔹 `/setup_party_channel`: Set up party notification channel.\n🔹 `/setup_news_channel`: Set up news/update channel.\n🔹 `/setup_boss_channel`: Set up cross-server boss chat relay.", inline=False)
            embed.add_field(name="🎭 Roles & Events", value="🔹 `/roles_menu`: Post the automated role selection menu.\n🔹 `/addrole` / `/removerole`: Add or remove roles from the menu.\n🔹 `/set_invite_role`: Link invite codes to specific roles.\n🔹 `/setbless` / `/setboss`: Configure event schedules.", inline=False)

        elif selected_value == "general":
            embed.title = "🌍 General Utilities"
            embed.add_field(name="📁 Basic Commands", value="🔹 `/help`: Open this command directory.\n🔹 `/hello`: Get a friendly greeting from the bot.\n🔹 `/setupguide`: View step-by-step bot setup instructions.", inline=False)

        await interaction.response.edit_message(embed=embed, view=self.view)

class HelpView(discord.ui.View):
    def __init__(self, user_name: str):
        super().__init__(timeout=180)
        self.add_item(HelpSelect(user_name))

# ========================================================================
# 2. GENERAL COG
# ========================================================================

class General(commands.Cog, name="Basic command"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="hello", description="Bot says hello to you")
    async def hello(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"👋 Hello {interaction.user.mention}! I'm MyK bot. Have an awesome day gaming! 🦖")

    @app_commands.command(name="help", description="Open help menu with categories")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📖 MyK Bot - Command Directory", 
            description="Welcome to the MyK Bot help center.\n\n⚠️ **Important:** Please set up your profile via `/mygear` before using party matching or RPG functions.\n\n👇 **Select a category below to view commands:**",
            color=discord.Color.blurple()
        )
        if self.bot.user and self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        view = HelpView(interaction.user.display_name)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="setupguide", description="View the step-by-step setup guide")
    async def setupguide(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📋 Bot Setup Guide", color=discord.Color.gold())
        embed.description = ("**Step 1:** Setup profile using `/mygear`.\n**Step 2:** Set up party channel using `/setup_party_channel`.\n**Step 3:** Set up news channel using `/setup_news_channel`.")
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="schedule", description="See upcoming raid spawn times")
    async def schedule(self, interaction: discord.Interaction):
        await interaction.response.defer()
        utc_now = datetime.now(timezone.utc)
        guild_id = int(interaction.guild_id)
        bless_data = await db.bless_tours.find_one({"guild_id": guild_id})
        boss_data = await db.bosses.find_one({"guild_id": guild_id})
        
        embed = discord.Embed(title="📅 SCHEDULE TIMERS", color=discord.Color.blue())
        
        if bless_data:
            bless_minute = bless_data.get("minute", 0)
            target_bless = utc_now.replace(minute=bless_minute, second=0, microsecond=0)
            if target_bless <= utc_now: target_bless += timedelta(hours=1)
            unix_bless = int(target_bless.timestamp())
            embed.add_field(name="📌 Bless Raid timer", value=f"Next <t:{unix_bless}:R> (<t:{unix_bless}:t>)", inline=False)
        else:
            embed.add_field(name="📌 Bless Raid timer", value="*Not set up. Use `/setbless`*", inline=False)

        if boss_data and "bosses" in boss_data:
            boss_lines = []
            for b_key, b in boss_data["bosses"].items():
                h, m = map(int, b.get("base_server_time", "00:00").split(":"))
                target_boss = utc_now.replace(hour=h, minute=m, second=0, microsecond=0)
                while target_boss <= utc_now: target_boss += timedelta(minutes=90)
                unix_boss = int(target_boss.timestamp())
                boss_lines.append(f"**{b['name']}** ({b['map']}): Next <t:{unix_boss}:R>")
            embed.add_field(name="🚨 Digital Raid timer", value="\n".join(boss_lines), inline=False)
        else:
            embed.add_field(name="🚨 Digital Raid timer", value="*Not set up. Use `/setboss`*", inline=False)

        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(General(bot))