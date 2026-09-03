import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
import json
import os
import re
from database import db, news_channel_col

CONFIG_PATH = "roles_config.json"

def load_config():
    if not os.path.exists(CONFIG_PATH):
        default = {
            "stage": ["Endgame stage", "Newbie stage", "Midgame stage"],
            "general": ["Member", "Tourist", "PIED", "Mugen", "MDG"],
            "combat": ["DPS SK/AA", "UFM", "TANK"]
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f: json.dump(default, f, indent=4, ensure_ascii=False)
        return default
    with open(CONFIG_PATH, "r", encoding="utf-8") as f: return json.load(f)

def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f: json.dump(config, f, indent=4, ensure_ascii=False)

def get_next_spawn(base_time_str: str, interval_minutes: int) -> datetime:
    now = datetime.now(timezone.utc)
    h, m = map(int, base_time_str.split(':'))
    base_dt = (now - timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)
    delta_minutes = (now - base_dt).total_seconds() / 60.0
    cycles = int(delta_minutes // interval_minutes)
    return base_dt + timedelta(minutes=(cycles + 1) * interval_minutes)

async def get_schedule_embed(guild_id: int, user_id: int) -> discord.Embed:
    user_profile = await db.players.find_one({"user_id": user_id})
    user_offset = float(user_profile.get("tz_offset", 0)) if user_profile else 0
    tz_label = f"UTC{'+' if user_offset >= 0 else ''}{user_offset}"
    user_tz = timezone(timedelta(hours=user_offset))

    embed = discord.Embed(title=f"📅 LỊCH RAID & EVENT ({tz_label})", color=discord.Color.blue())
    boss_lines = []

    async for raid in db.raid_bosses.find({"guild_id": guild_id}):
        next_spawn_utc = get_next_spawn(raid['base_time'], raid['interval_minutes'])
        unix_boss = int(next_spawn_utc.timestamp())
        user_time = next_spawn_utc.astimezone(user_tz).strftime("%H:%M")
        boss_lines.append(f"**[RAID] {raid['name']}** tại {raid['map']}:\n🔹 Đếm ngược: <t:{unix_boss}:t> (<t:{unix_boss}:R>)\n🔹 Giờ địa phương: **{user_time}**")

    async for event_item in db.events.find({"guild_id": guild_id}):
        next_spawn_utc = get_next_spawn(event_item['base_time'], event_item.get('interval_minutes', 180))
        unix_event = int(next_spawn_utc.timestamp())
        user_time = next_spawn_utc.astimezone(user_tz).strftime("%H:%M")
        boss_lines.append(f"**[EVENT] {event_item['name']}** tại {event_item['map']}:\n🔹 Đếm ngược: <t:{unix_event}:t> (<t:{unix_event}:R>)\n🔹 Giờ địa phương: **{user_time}**")

    embed.add_field(name="🚨 Timers Đang Hoạt Động", value="\n\n".join(boss_lines) if boss_lines else "*Chưa thiết lập Boss/Event nào.*", inline=False)
    return embed

class BroadcastModal(discord.ui.Modal, title="📢 Broadcast Thông Báo"):
    message_input = discord.ui.TextInput(label="Nội dung thông báo", style=discord.TextStyle.long, required=True, max_length=4000)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        message = self.message_input.value
        cursor = news_channel_col.find({})
        channels_data = await cursor.to_list(length=None)
        success_count, fail_count = 0, 0
        utc_now = datetime.now(timezone.utc)

        for data in channels_data:
            c_id = data.get("channel_id")
            if not c_id: continue
            try:
                channel = self.cog.bot.get_channel(c_id) or await self.cog.bot.fetch_channel(c_id)
                if channel:
                    embed = discord.Embed(title=f"📢 Thông Báo Hệ Thống - {utc_now.strftime('%d/%m/%Y')}", description=message, color=discord.Color.green(), timestamp=utc_now)
                    await channel.send(embed=embed)
                    success_count += 1
                else: fail_count += 1
            except Exception: fail_count += 1

        await interaction.followup.send(f"✅ **Đã gửi Broadcast!**\n🟢 Thành công: `{success_count}` | 🔴 Thất bại: `{fail_count}`", ephemeral=True)

class AddRoleSelect(discord.ui.Select):
    def __init__(self, category_name, options_list, is_stage=False):
        options = [discord.SelectOption(label=n, value=n) for n in options_list[:25]]
        super().__init__(placeholder=f"Chọn Role {category_name} (Thêm)...", min_values=1, max_values=1 if is_stage else len(options), options=options)
        self.is_stage = is_stage

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild, member, config = interaction.guild, interaction.user, load_config()
        if self.is_stage:
            sel = self.values[0]
            target = discord.utils.get(guild.roles, name=sel)
            if not target: return await interaction.followup.send(f"❌ Role **{sel}** không tồn tại!", ephemeral=True)
            await member.add_roles(target)
            await interaction.followup.send(f"✅ Đã cập nhật Role Stage thành: **{sel}**", ephemeral=True)
        else:
            roles_add = [discord.utils.get(guild.roles, name=n) for n in self.values if discord.utils.get(guild.roles, name=n)]
            if roles_add: await member.add_roles(*roles_add)
            await interaction.followup.send(f"➕ Đã thêm {len(roles_add)} role thành công!", ephemeral=True)

class MainRolesMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Thêm Role", style=discord.ButtonStyle.success, custom_id="main_menu:add_role")
    async def btn_add_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = load_config()
        view = discord.ui.View(timeout=300)
        if config.get("stage"): view.add_item(AddRoleSelect("Stage", config["stage"], is_stage=True))
        if config.get("general"): view.add_item(AddRoleSelect("General", config["general"]))
        if config.get("combat"): view.add_item(AddRoleSelect("Combat", config["combat"]))
        await interaction.response.send_message("Chọn các role bạn muốn lấy:", view=view, ephemeral=True)

class SettingMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

class NewsSystemCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.invite_cache = {}
        self.raid_notifier.start()

    def cog_unload(self):
        self.raid_notifier.cancel()

    @tasks.loop(seconds=30)
    async def raid_notifier(self):
        now = datetime.now(timezone.utc)
        try:
            async for raid in db.raid_bosses.find():
                c_id = raid.get('channel_id')
                next_spawn = get_next_spawn(raid.get('base_time'), raid.get('interval_minutes'))
                notify_time = next_spawn - timedelta(minutes=4)
                if notify_time <= now < (next_spawn - timedelta(minutes=3)):
                    spawn_ts = int(next_spawn.timestamp())
                    if raid.get('last_notified_spawn') == spawn_ts: continue
                    await db.raid_bosses.update_one({'_id': raid['_id']}, {'$set': {'last_notified_spawn': spawn_ts}})
                    channel = self.bot.get_channel(c_id)
                    if channel:
                        embed = discord.Embed(title=f"🚨 Boss Raid {raid.get('name')} sắp xuất hiện!", color=discord.Color.red())
                        embed.add_field(name="Thời gian", value=f"<t:{spawn_ts}:t> (<t:{spawn_ts}:R>)")
                        await channel.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            if guild.me.guild_permissions.manage_guild:
                invs = await guild.invites()
                self.invite_cache[guild.id] = {i.code: i.uses for i in invs}

async def setup(bot):
    bot.add_view(MainRolesMenuView())
    await bot.add_cog(NewsSystemCog(bot))