import re
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from discord.ext import commands, tasks
from Database import db, players_col
from utils.checks import is_bot_owner_slash


def parse_hhmm(time_str: str) -> tuple[int, int] | None:
    if not re.match(r"^\d{1,2}:\d{2}$", time_str.strip()):
        return None
    h, m = map(int, time_str.strip().split(":"))
    if 0 <= h <= 23 and 0 <= m <= 59:
        return h, m
    return None


def get_next_spawn(base_time_str: str, interval_minutes: int) -> datetime:
    now = datetime.now(timezone.utc)
    parsed = parse_hhmm(base_time_str)
    if not parsed:
        return now + timedelta(minutes=interval_minutes)
    h, m = parsed

    base_dt = (now - timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)
    delta_minutes = (now - base_dt).total_seconds() / 60.0
    cycles_completed = int(delta_minutes // interval_minutes)
    return base_dt + timedelta(minutes=(cycles_completed + 1) * interval_minutes)


class HelpSelect(discord.ui.Select):
    def __init__(self, user_name: str):
        self.user_name = user_name
        options = [
            discord.SelectOption(label="⚔️ Dungeon & Party", description="Quản lý Gear, tìm Party và lịch Raid/Event", emoji="🛡️", value="party"),
            discord.SelectOption(label="🛒 Theo dõi Chợ", description="Shop Tracker & Chợ Tốt Tracker", emoji="🏷️", value="market"),
            discord.SelectOption(label="🛠️ Admin & Setup", description="Cấu hình kênh, Role và lịch tự động", emoji="⚙️", value="admin"),
            discord.SelectOption(label="🌍 Tiện ích chung", description="Bảng điều khiển /menu và lệnh cơ bản", emoji="📁", value="general"),
        ]
        super().__init__(placeholder="📂 Chọn nhóm lệnh muốn xem...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        embed = discord.Embed(color=discord.Color.green())
        embed.set_footer(text=f"Requested by {self.user_name} | MyKBot", icon_url=interaction.user.display_avatar.url)
        val = self.values[0]

        if val == "party":
            embed.title = "⚔️ Dungeon & Party Commands"
            embed.add_field(
                name="📋 Hồ sơ cá nhân",
                value="🔹 `/mygear`: Cập nhật IGN, Timezone & Gear.\n🔹 `/showmygear`: Xem chỉ số Gear hiện tại.\n🔹 `/set_timezone`: Đặt múi giờ cá nhân.",
                inline=False,
            )
            embed.add_field(
                name="🤝 Party & Lịch trình",
                value="🔹 `/party_lobby`: Tạo hoặc tham gia Party Dungeon.\n🔹 `/dglist`: Xem yêu cầu Gear các Dungeon.\n🔹 `/schedule`: Xem đếm ngược Raid Boss & Event.",
                inline=False,
            )
        elif val == "market":
            embed.title = "🛒 Theo dõi Giá Chợ"
            embed.description = "Sử dụng `/menu` -> **Shop & Chợ Tốt Tracker** để quản lý danh sách theo dõi nhanh chóng."
        elif val == "admin":
            embed.title = "🛠️ Admin & Setup (Admin / Bot Owner)"
            embed.add_field(
                name="📺 Cấu hình Kênh & Role",
                value=(
                    "🔹 `/setup_party_channel`: Kênh thông báo Party.\n"
                    "🔹 `/setup_news_channel`: Kênh nhận tin tức từ Bot.\n"
                    "🔹 `/roles_menu`: Gửi bảng chọn Role tự động.\n"
                    "🔹 `/set_invite_role`: Gắn Role theo link mời."
                ),
                inline=False,
            )
            embed.add_field(
                name="⏰ Lịch tự động (Bot Owner)",
                value="🔹 `/setraid` / `/setraid90` / `/setevent`: Cài lịch báo Raid & Event.",
                inline=False,
            )
        else:
            embed.title = "🌍 Tiện ích chung"
            embed.add_field(
                name="📁 Lệnh cơ bản",
                value="🔹 `/menu`: Mở trung tâm điều khiển 1 chạm (khuyên dùng).\n🔹 `/help`: Xem danh mục lệnh.\n🔹 `/setupguide`: Hướng dẫn cài đặt bot.\n🔹 `/hello`: Chào bot.",
                inline=False,
            )

        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, user_name: str):
        super().__init__(timeout=180)
        self.add_item(HelpSelect(user_name))


class General(commands.Cog, name="Basic command"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.raid_notifier.start()
        self.event_notifier.start()

    def cog_unload(self):
        self.raid_notifier.cancel()
        self.event_notifier.cancel()

    @tasks.loop(seconds=20)
    async def raid_notifier(self):
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

                    embed = discord.Embed(title="🚨 Raid incoming!", color=discord.Color.red())
                    embed.add_field(name="Name", value=f"**{raid['name']}**", inline=True)
                    embed.add_field(name="Map", value=f"**{raid['map']}**", inline=True)
                    embed.add_field(name="Spawn time", value=f"⏰ <t:{spawn_ts}:t> (<t:{spawn_ts}:R>)", inline=False)

                    raid_role = discord.utils.get(channel.guild.roles, name="Raid")
                    mention_text = raid_role.mention if raid_role else "⚠️ (Chưa có role `Raid`)"

                    next_next_ts = int((next_spawn + timedelta(minutes=raid["interval_minutes"])).timestamp())
                    embed.set_footer(text=f"Lượt kế tiếp sau đó: cách {raid['interval_minutes']} phút")
                    await channel.send(content=mention_text, embed=embed)
                    await channel.send(
                        embed=discord.Embed(
                            description=f"⏭️ **Next spawn:** **{raid['name']}** lúc <t:{next_next_ts}:t> (<t:{next_next_ts}:R>)",
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
        now = datetime.now(timezone.utc)
        try:
            async for ev in db.events.find():
                interval = ev.get("interval_minutes", 180)
                next_spawn = get_next_spawn(ev["base_time"], interval)
                # Mở rộng khung lên 1 phút (từ phút thứ 3 đến phút thứ 2) để không bao giờ bị hụt
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

                    embed = discord.Embed(title="🎉 EVENT IS STARTING SOON!", color=discord.Color.gold())
                    embed.add_field(name="Event Name", value=f"**{ev['name']}**", inline=True)
                    embed.add_field(name="Location / Map", value=f"**{ev['map']}**", inline=True)
                    embed.add_field(name="Starts At", value=f"⏰ <t:{spawn_ts}:t> (<t:{spawn_ts}:R>)", inline=False)

                    event_role = discord.utils.get(channel.guild.roles, name="EVENT")
                    mention_text = event_role.mention if event_role else "⚠️ (Chưa có role `EVENT`)"

                    next_next_ts = int((next_spawn + timedelta(minutes=interval)).timestamp())
                    await channel.send(content=f"🔔 {mention_text}", embed=embed)
                    await channel.send(
                        embed=discord.Embed(
                            description=f"⏭️ **Next Event Wave:** **{ev['name']}** lúc <t:{next_next_ts}:t> (<t:{next_next_ts}:R>)",
                            color=discord.Color.orange(),
                        )
                    )
        except Exception as e:
            print(f"[event_notifier] Error: {e}", flush=True)

    @event_notifier.before_loop
    async def before_event_notifier(self):
        await self.bot.wait_until_ready()

    async def build_schedule_embed(self, guild_id: int, user_id: int) -> discord.Embed:
        user_profile = (
            await players_col.find_one({"user_id": user_id}, {"timezone": 1})
            or await db.profiles.find_one({"user_id": user_id}, {"timezone": 1})
        )

        user_offset = 0.0
        tz_label = "UTC+0 (Server)"
        if user_profile and "timezone" in user_profile:
            tz_val = str(user_profile["timezone"])
            match = re.search(r"([+-]?\d+(?:\.\d+)?)", tz_val)
            if match:
                user_offset = float(match.group(1))
                sign = "+" if user_offset >= 0 else ""
                tz_label = f"UTC{sign}{user_offset:g}"

        user_tz = timezone(timedelta(hours=user_offset))
        embed = discord.Embed(title=f"📅 LỊCH RAID & EVENT ({tz_label})", color=discord.Color.blue())
        embed.set_footer(text="💡 Đổi múi giờ cá nhân bằng /mygear hoặc /set_timezone")

        lines = []
        async for raid in db.raid_bosses.find({"guild_id": guild_id}):
            next_utc = get_next_spawn(raid["base_time"], raid["interval_minutes"])
            unix_ts = int(next_utc.timestamp())
            interval_str = "2 giờ" if raid["interval_minutes"] == 120 else f"{raid['interval_minutes']} phút"
            user_time = next_utc.astimezone(user_tz).strftime("%H:%M")
            lines.append(
                f"**[RAID] {raid['name']}** — {raid['map']} (mỗi {interval_str})\n"
                f"🔹 <t:{unix_ts}:t> (<t:{unix_ts}:R>) | Giờ của bạn: **{user_time}**"
            )

        async for ev in db.events.find({"guild_id": guild_id}):
            next_utc = get_next_spawn(ev["base_time"], ev.get("interval_minutes", 180))
            unix_ts = int(next_utc.timestamp())
            user_time = next_utc.astimezone(user_tz).strftime("%H:%M")
            lines.append(
                f"**[EVENT] {ev['name']}** — {ev['map']} (mỗi 3 giờ)\n"
                f"🔹 <t:{unix_ts}:t> (<t:{unix_ts}:R>) | Giờ của bạn: **{user_time}**"
            )

        embed.add_field(
            name="🚨 Lịch đang hoạt động",
            value="\n\n".join(lines) if lines else "*Chưa có Raid hoặc Event nào được thiết lập.*",
            inline=False,
        )
        return embed

    @app_commands.command(name="hello", description="Chào MyKBot")
    async def hello(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"👋 Xin chào {interaction.user.mention}! Gõ `/menu` để mở toàn bộ chức năng của MyKBot nhé!")

    @app_commands.command(name="help", description="Mở danh mục hướng dẫn lệnh")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📖 MyKBot — Trung Tâm Hướng Dẫn",
            description="💡 **Mẹo:** Bạn chỉ cần gõ **`/menu`** để truy cập nhanh mọi chức năng bằng nút bấm.\n\n👇 Hoặc chọn danh mục bên dưới để xem danh sách lệnh:",
            color=discord.Color.blurple(),
        )
        if self.bot.user and self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, view=HelpView(interaction.user.display_name))

    @app_commands.command(name="setupguide", description="Xem hướng dẫn thiết lập nhanh")
    async def setupguide(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📋 Hướng Dẫn Thiết Lập MyKBot",
            description=(
                "**Bước 1:** Thiết lập hồ sơ cá nhân với `/mygear`.\n"
                "**Bước 2:** Cài kênh tìm Party bằng `/setup_party_channel`.\n"
                "**Bước 3:** Cài kênh nhận tin tức bằng `/setup_news_channel`.\n"
                "**Bước 4:** Mở bảng chức năng trung tâm bất cứ lúc nào bằng `/menu`."
            ),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="schedule", description="Xem lịch xuất hiện Raid Boss và Event sắp tới")
    async def schedule(self, interaction: discord.Interaction):
        await interaction.response.defer()
        embed = await self.build_schedule_embed(interaction.guild_id, interaction.user.id)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="setraid", description="[Bot Owner] Cài lịch Raid Boss chu kỳ 2 tiếng")
    @app_commands.describe(name="Tên Boss", map_name="Tên Map", time_str="Giờ server HH:MM (UTC+0)")
    @is_bot_owner_slash()
    async def setraid(self, interaction: discord.Interaction, name: str, map_name: str, time_str: str):
        if not parse_hhmm(time_str):
            return await interaction.response.send_message("❌ Sai định dạng giờ! Hãy nhập `HH:MM` hợp lệ (VD: `00:00`, `14:30`).", ephemeral=True)
        await db.raid_bosses.update_one(
            {"guild_id": interaction.guild_id, "name": name},
            {"$set": {"channel_id": interaction.channel_id, "map": map_name, "base_time": time_str.strip(), "interval_minutes": 120, "last_notified_spawn": 0}},
            upsert=True,
        )
        await interaction.response.send_message(f"✅ Đã cài Raid **{name}** ({map_name}) — mỗi **2 giờ** từ `{time_str} UTC+0` tại <#{interaction.channel_id}>.")

    @app_commands.command(name="setraid90", description="[Bot Owner] Cài lịch Raid Boss chu kỳ 1.5 tiếng")
    @app_commands.describe(name="Tên Boss", map_name="Tên Map", time_str="Giờ server HH:MM (UTC+0)")
    @is_bot_owner_slash()
    async def setraid90(self, interaction: discord.Interaction, name: str, map_name: str, time_str: str):
        if not parse_hhmm(time_str):
            return await interaction.response.send_message("❌ Sai định dạng giờ! Hãy nhập `HH:MM` hợp lệ (VD: `01:30`, `13:00`).", ephemeral=True)
        await db.raid_bosses.update_one(
            {"guild_id": interaction.guild_id, "name": name},
            {"$set": {"channel_id": interaction.channel_id, "map": map_name, "base_time": time_str.strip(), "interval_minutes": 90, "last_notified_spawn": 0}},
            upsert=True,
        )
        await interaction.response.send_message(f"✅ Đã cài Raid **{name}** ({map_name}) — mỗi **1.5 giờ** từ `{time_str} UTC+0` tại <#{interaction.channel_id}>.")

    @app_commands.command(name="setevent", description="[Bot Owner] Cài lịch Event chu kỳ 3 tiếng")
    @app_commands.describe(name="Tên Event", map_name="Tên Map", time_str="Giờ server HH:MM (UTC+0)")
    @is_bot_owner_slash()
    async def setevent(self, interaction: discord.Interaction, name: str, map_name: str, time_str: str):
        if not parse_hhmm(time_str):
            return await interaction.response.send_message("❌ Sai định dạng giờ! Hãy nhập `HH:MM` hợp lệ (VD: `00:00`, `03:00`).", ephemeral=True)
        await db.events.update_one(
            {"guild_id": interaction.guild_id, "name": name},
            {"$set": {"channel_id": interaction.channel_id, "map": map_name, "base_time": time_str.strip(), "interval_minutes": 180, "last_notified_spawn": 0}},
            upsert=True,
        )
        await interaction.response.send_message(f"🎉 Đã cài Event **{name}** ({map_name}) — mỗi **3 giờ** từ `{time_str} UTC+0`, báo trước 3 phút tại <#{interaction.channel_id}>.")


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))