import discord
from discord import app_commands
from discord.ext import commands, tasks
from database import db
from datetime import datetime, timezone, timedelta
import re

# ========================================================================
# HÀM TÍNH TOÁN THỜI GIAN NEXT SPAWN CHUẨN XÁC
# ========================================================================
def get_next_spawn(base_time_str: str, interval_minutes: int) -> datetime:
    now = datetime.now(timezone.utc)
    h, m = map(int, base_time_str.split(':'))
    
    base_dt = (now - timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)
    delta_minutes = (now - base_dt).total_seconds() / 60.0
    
    cycles_completed = int(delta_minutes // interval_minutes)
    next_spawn = base_dt + timedelta(minutes=(cycles_completed + 1) * interval_minutes)
    
    return next_spawn


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
            embed.add_field(name="🤝 Party & Schedule", value="🔹 `/party_lobby`: 🌐 Join or create a dungeon party.\n🔹 `/dglist`: View gear requirements for dungeons.\n🔹 `/schedule`: 📅 Check upcoming Boss Raid timers.", inline=False)

        elif selected_value == "admin":
            embed.title = "🛠️ Admin Commands"
            embed.description = "Configuration tools restricted to Administrators."
            embed.add_field(name="📺 Channel Setup", value="🔹 `/setup_party_channel`: Set up party notification channel.\n🔹 `/setup_news_channel`: Set up news/update channel.\n🔹 `/setup_boss_channel`: Set up cross-server boss chat relay.", inline=False)
            embed.add_field(name="🎭 Roles & Events", value="🔹 `/roles_menu`: Post the automated role selection menu.\n🔹 `/addrole` / `/removerole`: Add or remove roles from the menu.\n🔹 `/set_invite_role`: Link invite codes to specific roles.\n🔹 `/setraid` / `/setraid90` / `/setevent`: Configure automatic schedules.", inline=False)

        elif selected_value == "general":
            embed.title = "🌍 General Utilities"
            embed.add_field(name="📁 Basic Commands", value="🔹 `/help`: Open this command directory.\n🔹 `/hello`: Get a friendly greeting from the bot.\n🔹 `/setupguide`: View step-by-step bot setup instructions.", inline=False)

        await interaction.response.edit_message(embed=embed, view=self.view)

class HelpView(discord.ui.View):
    def __init__(self, user_name: str):
        super().__init__(timeout=180)
        self.add_item(HelpSelect(user_name))


# ========================================================================
# 2. GENERAL COG (HỖ TRỢ ĐA MÚI GIỜ)
# ========================================================================
class General(commands.Cog, name="Basic command"):
    def __init__(self, bot):
        self.bot = bot
        self.raid_notifier.start()
        self.event_notifier.start()

    def cog_unload(self):
        self.raid_notifier.cancel()
        self.event_notifier.cancel()

    # --- TASK THÔNG BÁO RAID BOSS (RAID ROLE) ---
    @tasks.loop(seconds=15)
    async def raid_notifier(self):
        now = datetime.now(timezone.utc)
        
        try:
            async for raid in db.raid_bosses.find():
                channel_id = raid.get('channel_id')
                name = raid.get('name')
                map_name = raid.get('map')
                base_time = raid.get('base_time')
                interval = raid.get('interval_minutes')
                last_notified = raid.get('last_notified_spawn', 0)
                
                next_spawn = get_next_spawn(base_time, interval)
                notify_time = next_spawn - timedelta(minutes=4)
                
                if notify_time <= now < (next_spawn - timedelta(minutes=3)):
                    spawn_timestamp = int(next_spawn.timestamp())
                    if last_notified == spawn_timestamp:
                        continue
                    
                    await db.raid_bosses.update_one({'_id': raid['_id']}, {'$set': {'last_notified_spawn': spawn_timestamp}})
                    
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        embed = discord.Embed(title="🚨 Raid incoming!", color=discord.Color.red())
                        embed.add_field(name="Name", value=f"**{name}**", inline=True)
                        embed.add_field(name="Map", value=f"**{map_name}**", inline=True)
                        embed.add_field(
                            name="Spawn time (your region)", 
                            value=f"⏰ <t:{spawn_timestamp}:t> (còn <t:{spawn_timestamp}:R>)", 
                            inline=False
                        )
                        
                        raid_role = discord.utils.get(channel.guild.roles, name="Raid")
                        mention_text = raid_role.mention if raid_role else "⚠️ (Vui lòng tạo role có tên chính xác là `Raid` để bot có thể ping)"
                        
                        await channel.send(content=mention_text, embed=embed)
                        
                        next_next_spawn = next_spawn + timedelta(minutes=interval)
                        embed2 = discord.Embed(color=discord.Color.blue())
                        embed2.description = f"⏭️ **Information:** Boss **{name}** Next spawn at: <t:{int(next_next_spawn.timestamp())}:t> (còn <t:{int(next_next_spawn.timestamp())}:R>)"
                        await channel.send(embed=embed2)
                        
        except Exception as e:
            print(f"Error in raid_notifier: {e}")

    @raid_notifier.before_loop
    async def before_raid_notifier(self):
        await self.bot.wait_until_ready()

    # --- TASK THÔNG BÁO EVENT 3 TIẾNG (EVENT ROLE - PING BÁO TRƯỚC 3 PHÚT) ---
    @tasks.loop(seconds=15)
    async def event_notifier(self):
        now = datetime.now(timezone.utc)
        
        try:
            async for event_data in db.events.find():
                channel_id = event_data.get('channel_id')
                name = event_data.get('name')
                map_name = event_data.get('map')
                base_time = event_data.get('base_time')
                interval = event_data.get('interval_minutes', 180) # Mặc định 180p (3 tiếng)
                last_notified = event_data.get('last_notified_spawn', 0)
                
                next_spawn = get_next_spawn(base_time, interval)
                # Báo trước 3 phút: từ 3:00 đến 2:45 trước giờ spawn
                notify_time = next_spawn - timedelta(minutes=3)
                
                if notify_time <= now < (next_spawn - timedelta(minutes=2, seconds=45)):
                    spawn_timestamp = int(next_spawn.timestamp())
                    if last_notified == spawn_timestamp:
                        continue
                    
                    await db.events.update_one({'_id': event_data['_id']}, {'$set': {'last_notified_spawn': spawn_timestamp}})
                    
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        embed = discord.Embed(title="🎉 EVENT IS STARTING SOON!", color=discord.Color.gold())
                        embed.add_field(name="Event Name", value=f"**{name}**", inline=True)
                        embed.add_field(name="Location / Map", value=f"**{map_name}**", inline=True)
                        embed.add_field(
                            name="Starts At", 
                            value=f"⏰ <t:{spawn_timestamp}:t> (còn <t:{spawn_timestamp}:R>)", 
                            inline=False
                        )
                        
                        # Tim role "EVENT" trong server
                        event_role = discord.utils.get(channel.guild.roles, name="EVENT")
                        mention_text = event_role.mention if event_role else "⚠️ (Vui lòng tạo role có tên chính xác là `EVENT` để bot có thể ping)"
                        
                        await channel.send(content=f"🔔 {mention_text}", embed=embed)
                        
                        # Embed thông báo lượt tiếp theo
                        next_next_spawn = next_spawn + timedelta(minutes=interval)
                        embed2 = discord.Embed(color=discord.Color.orange())
                        embed2.description = f"⏭️ **Next Event Wave:** **{name}** will spawn again at: <t:{int(next_next_spawn.timestamp())}:t> (<t:{int(next_next_spawn.timestamp())}:R>)"
                        await channel.send(embed=embed2)
                        
        except Exception as e:
            print(f"Error in event_notifier: {e}")

    @event_notifier.before_loop
    async def before_event_notifier(self):
        await self.bot.wait_until_ready()

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
    
    @app_commands.command(name="schedule", description="See upcoming raid and event spawn times")
    async def schedule(self, interaction: discord.Interaction):
        await interaction.response.defer()
        guild_id = int(interaction.guild_id)
        user_id = int(interaction.user.id)
        
        user_profile = await db.profiles.find_one({"user_id": user_id}) or await db.users.find_one({"user_id": user_id})
        
        user_offset = 0
        tz_label = "UTC+0 (Server)"
        
        if user_profile and "timezone" in user_profile:
            tz_val = user_profile["timezone"]
            try:
                user_offset = float(tz_val)
                tz_label = f"UTC{'+' if user_offset >= 0 else ''}{tz_val}"
            except ValueError:
                match = re.search(r'([+-]?\d+)', str(tz_val))
                if match:
                    user_offset = float(match.group(1))
                    tz_label = f"UTC{'+' if user_offset >= 0 else ''}{user_offset}"

        user_tz = timezone(timedelta(hours=user_offset))
        
        embed = discord.Embed(title=f"📅 RAID & EVENT SCHEDULE TIMERS ({tz_label})", color=discord.Color.blue())
        embed.set_footer(text="💡 Set your time zone using the command /mygear or /set_timezone")
        
        boss_lines = []
        async for raid in db.raid_bosses.find({"guild_id": guild_id}):
            next_spawn_utc = get_next_spawn(raid['base_time'], raid['interval_minutes'])
            unix_boss = int(next_spawn_utc.timestamp())
            interval_str = "2 Hours" if raid['interval_minutes'] == 120 else "1h30p"
            
            next_spawn_user = next_spawn_utc.astimezone(user_tz)
            user_time_text = next_spawn_user.strftime("%H:%M")
            
            boss_lines.append(
                f"**[RAID] {raid['name']}** at {raid['map']} (every {interval_str}):\n"
                f"🔹 Countdown: <t:{unix_boss}:t> (<t:{unix_boss}:R>)\n"
                f"🔹 Text time ({tz_label}): **{user_time_text}**"
            )

        async for event_item in db.events.find({"guild_id": guild_id}):
            next_spawn_utc = get_next_spawn(event_item['base_time'], event_item.get('interval_minutes', 180))
            unix_event = int(next_spawn_utc.timestamp())
            
            next_spawn_user = next_spawn_utc.astimezone(user_tz)
            user_time_text = next_spawn_user.strftime("%H:%M")
            
            boss_lines.append(
                f"**[EVENT] {event_item['name']}** at {event_item['map']} (every 3 Hours):\n"
                f"🔹 Countdown: <t:{unix_event}:t> (<t:{unix_event}:R>)\n"
                f"🔹 Text time ({tz_label}): **{user_time_text}**"
            )
            
        if boss_lines:
            embed.add_field(name="🚨 Active Timers", value="\n\n".join(boss_lines), inline=False)
        else:
            embed.add_field(name="🚨 Active Timers", value="*No raid or event has been set up yet.*", inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="setraid", description="Set up a 2-hour raid boss (Bot Owner only)")
    @app_commands.describe(name="Boss name", map_name="Map name", time_str="Server time format: HH:MM (UTC+0)")
    async def setraid(self, interaction: discord.Interaction, name: str, map_name: str, time_str: str):
        if not await self.bot.is_owner(interaction.user):
            return await interaction.response.send_message("❌ Only the Bot Owner has the right to use this command.!", ephemeral=True)
            
        if not re.match(r'^\d{1,2}:\d{2}$', time_str):
            return await interaction.response.send_message("❌ Incorrect time format. Please enter the time in `HH:MM` format (e.g., `00:00` or `14:00`)..", ephemeral=True)
            
        await db.raid_bosses.update_one(
            {"guild_id": interaction.guild_id, "name": name},
            {"$set": {
                "channel_id": interaction.channel_id,
                "map": map_name,
                "base_time": time_str,
                "interval_minutes": 120,
                "last_notified_spawn": 0
            }},
            upsert=True
        )
        await interaction.response.send_message(f"✅ Boss has been set up. **{name}** at **{map_name}**.\n⏳ **Every 2 hours** from `Base Time: {time_str} UTC+0`.\n📢 Notifications will ping role **Raid** at: <#{interaction.channel_id}>")

    @app_commands.command(name="setraid90", description="Set up a 1.5-hour raid boss (Bot Owner only)")
    @app_commands.describe(name="Tên Boss", map_name="Tên Map", time_str="Giờ server định dạng HH:MM (UTC+0)")
    async def setraid90(self, interaction: discord.Interaction, name: str, map_name: str, time_str: str):
        if not await self.bot.is_owner(interaction.user):
            return await interaction.response.send_message("❌ Only the Bot Owner has the right to use this command.!", ephemeral=True)
            
        if not re.match(r'^\d{1,2}:\d{2}$', time_str):
            return await interaction.response.send_message("❌ Please format the time as `HH:MM` (e.g., `01:30` or `13:00`).", ephemeral=True)
            
        await db.raid_bosses.update_one(
            {"guild_id": interaction.guild_id, "name": name},
            {"$set": {
                "channel_id": interaction.channel_id,
                "map": map_name,
                "base_time": time_str,
                "interval_minutes": 90,
                "last_notified_spawn": 0
            }},
            upsert=True
        )
        await interaction.response.send_message(f"✅ Boss has been set up. **{name}** at **{map_name}**.\n⏳ **Every 1.5 hours** from `Base Time: {time_str} UTC+0`.\n📢 Notifications will ping role **Raid** at: <#{interaction.channel_id}>")

    @app_commands.command(name="setevent", description="Set up a 3-hour Event schedule with EVENT role ping (Bot Owner only)")
    @app_commands.describe(name="Event Name", map_name="Map / Location Name", time_str="Server base time format: HH:MM (UTC+0)")
    async def setevent(self, interaction: discord.Interaction, name: str, map_name: str, time_str: str):
        if not await self.bot.is_owner(interaction.user):
            return await interaction.response.send_message("❌ Only the Bot Owner has the right to use this command!", ephemeral=True)
            
        if not re.match(r'^\d{1,2}:\d{2}$', time_str):
            return await interaction.response.send_message("❌ Incorrect time format. Please use `HH:MM` format (e.g., `00:00` or `03:00`).", ephemeral=True)
            
        await db.events.update_one(
            {"guild_id": interaction.guild_id, "name": name},
            {"$set": {
                "channel_id": interaction.channel_id,
                "map": map_name,
                "base_time": time_str,
                "interval_minutes": 180, # 3 tiếng
                "last_notified_spawn": 0
            }},
            upsert=True
        )
        await interaction.response.send_message(f"🎉 **Event Schedule Set!** **{name}** at **{map_name}**.\n⏳ **Every 3 hours** starting from `Base Time: {time_str} UTC+0`.\n📢 Bot will ping role **EVENT** 3 minutes prior at <#{interaction.channel_id}>.")

async def setup(bot):
    await bot.add_cog(General(bot))