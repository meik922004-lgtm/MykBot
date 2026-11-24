import re
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands, tasks
from Database import db, players_col


def parse_hhmm(time_str: str) -> tuple[int, int] | None:
    """Validate and parse an HH:MM string (00:00 - 23:59)."""
    if not re.match(r"^\d{1,2}:\d{2}$", time_str.strip()):
        return None
    h, m = map(int, time_str.strip().split(":"))
    if 0 <= h <= 23 and 0 <= m <= 59:
        return h, m
    return None


def get_next_spawn(base_time_str: str, interval_minutes: int) -> datetime:
    """Calculate the next UTC spawn datetime given a base HH:MM and interval."""
    now = datetime.now(timezone.utc)
    parsed = parse_hhmm(base_time_str)
    if not parsed:
        return now + timedelta(minutes=interval_minutes)
    h, m = parsed

    base_dt = (now - timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)
    delta_minutes = (now - base_dt).total_seconds() / 60.0
    cycles_completed = int(delta_minutes // interval_minutes)
    return base_dt + timedelta(minutes=(cycles_completed + 1) * interval_minutes)


class SetTimerModal(discord.ui.Modal, title="⏰ Configure Raid / Event Timer"):
    """Owner modal (invoked from /menu) to register a Raid (120m / 90m) or Event (180m) timer in the current channel."""

    timer_type = discord.ui.TextInput(
        label="Type (raid120 / raid90 / event)",
        placeholder="Enter: raid120, raid90, or event",
        required=True,
        max_length=10,
    )
    name = discord.ui.TextInput(
        label="Boss / Event Name",
        placeholder="e.g., Orochi, World Event...",
        required=True,
        max_length=60,
    )
    map_name = discord.ui.TextInput(
        label="Map / Location",
        placeholder="e.g., Forest Area, DATS Center...",
        required=True,
        max_length=60,
    )
    time_str = discord.ui.TextInput(
        label="Base Server Time (HH:MM in UTC+0)",
        placeholder="e.g., 00:00 or 14:30",
        required=True,
        max_length=5,
    )

    async def on_submit(self, interaction: discord.Interaction):
        t_type = self.timer_type.value.strip().lower()
        t_time = self.time_str.value.strip()

        if t_type not in ("raid120", "raid90", "event"):
            return await interaction.response.send_message(
                "❌ Invalid type! Please enter `raid120`, `raid90`, or `event`.",
                ephemeral=True,
            )

        if not parse_hhmm(t_time):
            return await interaction.response.send_message(
                "❌ Invalid time format! Please use `HH:MM` (00:00 – 23:59 UTC+0).",
                ephemeral=True,
            )

        if t_type == "event":
            await db.events.update_one(
                {"guild_id": interaction.guild_id, "name": self.name.value.strip()},
                {
                    "$set": {
                        "channel_id": interaction.channel_id,
                        "map": self.map_name.value.strip(),
                        "base_time": t_time,
                        "interval_minutes": 180,
                        "last_notified_spawn": 0,
                    }
                },
                upsert=True,
            )
            return await interaction.response.send_message(
                f"🎉 **Event Timer Saved!** **{self.name.value.strip()}** at **{self.map_name.value.strip()}** "
                f"(every 3h from `{t_time} UTC+0`) in <#{interaction.channel_id}>.",
                ephemeral=True,
            )

        interval = 120 if t_type == "raid120" else 90
        await db.raid_bosses.update_one(
            {"guild_id": interaction.guild_id, "name": self.name.value.strip()},
            {
                "$set": {
                    "channel_id": interaction.channel_id,
                    "map": self.map_name.value.strip(),
                    "base_time": t_time,
                    "interval_minutes": interval,
                    "last_notified_spawn": 0,
                }
            },
            upsert=True,
        )
        await interaction.response.send_message(
            f"✅ **Raid Timer Saved!** **{self.name.value.strip()}** at **{self.map_name.value.strip()}** "
            f"(every {interval}m from `{t_time} UTC+0`) in <#{interaction.channel_id}>.",
            ephemeral=True,
        )


class General(commands.Cog):
    """Background Raid/Event notifier tasks and schedule embed builder."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.raid_notifier.start()
        self.event_notifier.start()

    def cog_unload(self):
        self.raid_notifier.cancel()
        self.event_notifier.cancel()

    async def open_set_timer_modal(self, interaction: discord.Interaction):
        """Helper invoked from /menu Owner Control Panel."""
        await interaction.response.send_modal(SetTimerModal())

    @tasks.loop(seconds=20)
    async def raid_notifier(self):
        """Send Raid Boss alerts 4 minutes before spawn."""
        now = datetime.now(timezone.utc)
        try:
            async for raid in db.raid_bosses.find():
                next_spawn = get_next_spawn(raid["base_time"], raid["interval_minutes"])
                notify_start = next_spawn - timedelta(minutes=4)
                notify_end = next_spawn - timedelta(minutes=3)

                if notify_start <= now < notify_end:
                    spawn_ts = int(next_spawn.timestamp())
                    if raid.get("last_notified_spawn") == spawn_ts:
                        continue

                    await db.raid_bosses.update_one(
                        {"_id": raid["_id"]},
                        {"$set": {"last_notified_spawn": spawn_ts}},
                    )
                    channel = self.bot.get_channel(raid.get("channel_id"))
                    if not channel:
                        continue

                    embed = discord.Embed(title="🚨 Raid Boss Incoming!", color=discord.Color.red())
                    embed.add_field(name="Boss Name", value=f"**{raid['name']}**", inline=True)
                    embed.add_field(name="Location / Map", value=f"**{raid['map']}**", inline=True)
                    embed.add_field(name="Spawn Time", value=f"⏰ <t:{spawn_ts}:t> (<t:{spawn_ts}:R>)", inline=False)

                    raid_role = discord.utils.get(channel.guild.roles, name="Raid")
                    mention_text = raid_role.mention if raid_role else "⚠️ *(Create a role named `Raid` to enable pings)*"

                    next_next_ts = int((next_spawn + timedelta(minutes=raid["interval_minutes"])).timestamp())
                    await channel.send(content=mention_text, embed=embed)
                    await channel.send(
                        embed=discord.Embed(
                            description=f"⏭️ **Next Spawn:** **{raid['name']}** at <t:{next_next_ts}:t> (<t:{next_next_ts}:R>)",
                            color=discord.Color.blue(),
                        )
                    )
        except Exception as e:
            print(f"[raid_notifier] Error: {e}", flush=True)

    @raid_notifier.before_loop
    async def before_raid_notifier(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=20)
    async def event_notifier(self):
        """Send Event alerts 3 minutes before start."""
        now = datetime.now(timezone.utc)
        try:
            async for ev in db.events.find():
                interval = ev.get("interval_minutes", 180)
                next_spawn = get_next_spawn(ev["base_time"], interval)
                notify_start = next_spawn - timedelta(minutes=3)
                notify_end = next_spawn - timedelta(minutes=2)

                if notify_start <= now < notify_end:
                    spawn_ts = int(next_spawn.timestamp())
                    if ev.get("last_notified_spawn") == spawn_ts:
                        continue

                    await db.events.update_one(
                        {"_id": ev["_id"]},
                        {"$set": {"last_notified_spawn": spawn_ts}},
                    )
                    channel = self.bot.get_channel(ev.get("channel_id"))
                    if not channel:
                        continue

                    embed = discord.Embed(title="🎉 Event Starting Soon!", color=discord.Color.gold())
                    embed.add_field(name="Event Name", value=f"**{ev['name']}**", inline=True)
                    embed.add_field(name="Location / Map", value=f"**{ev['map']}**", inline=True)
                    embed.add_field(name="Starts At", value=f"⏰ <t:{spawn_ts}:t> (<t:{spawn_ts}:R>)", inline=False)

                    event_role = discord.utils.get(channel.guild.roles, name="EVENT")
                    mention_text = event_role.mention if event_role else "⚠️ *(Create a role named `EVENT` to enable pings)*"

                    next_next_ts = int((next_spawn + timedelta(minutes=interval)).timestamp())
                    await channel.send(content=f"🔔 {mention_text}", embed=embed)
                    await channel.send(
                        embed=discord.Embed(
                            description=f"⏭️ **Next Wave:** **{ev['name']}** at <t:{next_next_ts}:t> (<t:{next_next_ts}:R>)",
                            color=discord.Color.orange(),
                        )
                    )
        except Exception as e:
            print(f"[event_notifier] Error: {e}", flush=True)

    @event_notifier.before_loop
    async def before_event_notifier(self):
        await self.bot.wait_until_ready()

    async def build_schedule_embed(self, guild_id: int, user_id: int) -> discord.Embed:
        """Build the Raid & Event schedule embed adjusted to the user's saved timezone."""
        user_profile = (
            await players_col.find_one({"user_id": user_id}, {"timezone": 1, "tz_offset": 1})
            or await db.profiles.find_one({"user_id": user_id}, {"timezone": 1})
        )

        user_offset = 0.0
        tz_label = "UTC+0 (Server)"
        if user_profile:
            raw_tz = user_profile.get("tz_offset", user_profile.get("timezone"))
            if raw_tz is not None:
                match = re.search(r"([+-]?\d+(?:\.\d+)?)", str(raw_tz))
                if match:
                    user_offset = float(match.group(1))
                    sign = "+" if user_offset >= 0 else ""
                    tz_label = f"UTC{sign}{user_offset:g}"

        user_tz = timezone(timedelta(hours=user_offset))
        embed = discord.Embed(title=f"📅 Raid & Event Schedule ({tz_label})", color=discord.Color.blue())
        embed.set_footer(text="💡 Update your timezone via /menu → Profile & Gear → Set Timezone")

        lines = []
        async for raid in db.raid_bosses.find({"guild_id": guild_id}):
            next_utc = get_next_spawn(raid["base_time"], raid["interval_minutes"])
            unix_ts = int(next_utc.timestamp())
            interval_str = "2h" if raid["interval_minutes"] == 120 else f"{raid['interval_minutes']}m"
            user_time = next_utc.astimezone(user_tz).strftime("%H:%M")
            lines.append(
                f"**[RAID] {raid['name']}** — {raid['map']} (every {interval_str})\n"
                f"🔹 <t:{unix_ts}:t> (<t:{unix_ts}:R>) | Local time: **{user_time}**"
            )

        async for ev in db.events.find({"guild_id": guild_id}):
            next_utc = get_next_spawn(ev["base_time"], ev.get("interval_minutes", 180))
            unix_ts = int(next_utc.timestamp())
            user_time = next_utc.astimezone(user_tz).strftime("%H:%M")
            lines.append(
                f"**[EVENT] {ev['name']}** — {ev['map']} (every 3h)\n"
                f"🔹 <t:{unix_ts}:t> (<t:{unix_ts}:R>) | Local time: **{user_time}**"
            )

        embed.add_field(
            name="🚨 Active Timers",
            value="\n\n".join(lines) if lines else "*No raid or event timers configured for this server yet.*",
            inline=False,
        )
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))