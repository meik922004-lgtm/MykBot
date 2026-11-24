import discord
from discord import app_commands
from discord.ext import commands
from Database import players_col, dungeon_configs_col

# ==========================================
# CẤU HÌNH DỮ LIỆU
# ==========================================
GEAR_OPTIONS = [
    "Full fang gear",
    "1 piece of Spiral",
    "2 piece of Spiral",
    "Full Spiral set",
    "1 piece of corrupted",
    "2 piece of corrupted",
    "full set of corrupted",
    "Other",
]
VICE_OPTIONS = {
    "AA": ["D.ark 4", "D,ark 5", "D.ark 6", "D.ark Uncontroll", "Void vice", "Other"],
    "SK": ["Royal Vice", "Truevice", "Truevice(Advance)", "Void vice", "Other"],
    "TANK": ["D.ark 6", "D.ark Chrome", "Void vice", "Other"],
}
DECK_OPTIONS = {
    "AA": ["Divinus", "CrimsonPath/Corrupted Power", "Power of Darkness / Crimson Nexus", "Eclipsed Genesis", "Other"],
    "SK": ["Celesfracture", "Latent Power", "RoyalKnight X/ DemonLord X", "Legendary Core", "Other"],
    "TANK": ["Fortis Magna", "Crown", "Royal Crown", "Eternal Dominion", "Other"],
}
BRACELET_OPTIONS = ["Bracelet 5 stats", "Ygg Bracelet", "Pied Bracelet"]

TIMEZONE_OFFSETS = [-8, -5, -3, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


class MyGearIGNModal(discord.ui.Modal, title="Setup Profile - IGN"):
    ign = discord.ui.TextInput(
        label="In-Game Name (IGN)",
        placeholder="Nhập tên nhân vật trong game...",
        required=True,
        max_length=30,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ign_value = self.ign.value.strip()
        await players_col.update_one(
            {"user_id": interaction.user.id},
            {"$set": {"ign": ign_value}},
            upsert=True,
        )
        embed = discord.Embed(
            title="⚙️ Setup MyGear",
            description=f"Đã lưu IGN của bạn: **{ign_value}**\nHãy chọn các thông số bên dưới:",
            color=discord.Color.blue(),
        )
        await interaction.followup.send(embed=embed, view=MyGearWizard(interaction.user.id, {}), ephemeral=True)


class MyGearWizard(discord.ui.View):
    def __init__(self, user_id: int, player_data: dict | None = None):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.player_data = player_data or {}
        self.data = {
            "tz_offset": float(self.player_data.get("tz_offset", 7.0)),
            "role": None,
            "gear": None,
            "vice": None,
            "deck": None,
            "bracelet": None,
        }
        self.step = 1 if "tz_offset" in self.player_data else 0
        self.refresh_menu()

    def refresh_menu(self):
        self.clear_items()
        if self.step == 0:
            options = [
                discord.SelectOption(label=f"UTC{'+' if i >= 0 else ''}{i}", value=str(i))
                for i in TIMEZONE_OFFSETS
            ]
            select = discord.ui.Select(placeholder="🌍 Chọn múi giờ của bạn", options=options)

            async def tz_callback(interaction: discord.Interaction):
                self.data["tz_offset"] = float(select.values[0])
                self.step = 1
                await self.next_step(interaction)

            select.callback = tz_callback
            self.add_item(select)

        elif self.step == 1:
            select = discord.ui.Select(
                placeholder="1️⃣ Chọn Role (AA / SK / TANK)",
                options=[discord.SelectOption(label=r) for r in ("AA", "SK", "TANK")],
            )

            async def role_callback(interaction: discord.Interaction):
                self.data["role"] = select.values[0]
                self.step = 2
                await self.next_step(interaction)

            select.callback = role_callback
            self.add_item(select)

        elif self.step == 2:
            select = discord.ui.Select(
                placeholder="2️⃣ Chọn Gear",
                options=[discord.SelectOption(label=g) for g in GEAR_OPTIONS],
            )

            async def gear_callback(interaction: discord.Interaction):
                self.data["gear"] = select.values[0]
                self.step = 3
                await self.next_step(interaction)

            select.callback = gear_callback
            self.add_item(select)

        elif self.step == 3:
            select = discord.ui.Select(
                placeholder="3️⃣ Chọn Vice",
                options=[discord.SelectOption(label=v) for v in VICE_OPTIONS[self.data["role"]]],
            )

            async def vice_callback(interaction: discord.Interaction):
                self.data["vice"] = select.values[0]
                self.step = 4
                await self.next_step(interaction)

            select.callback = vice_callback
            self.add_item(select)

        elif self.step == 4:
            select = discord.ui.Select(
                placeholder="4️⃣ Chọn Deck",
                options=[discord.SelectOption(label=d) for d in DECK_OPTIONS[self.data["role"]]],
            )

            async def deck_callback(interaction: discord.Interaction):
                self.data["deck"] = select.values[0]
                self.step = 5
                await self.next_step(interaction)

            select.callback = deck_callback
            self.add_item(select)

        elif self.step == 5:
            select = discord.ui.Select(
                placeholder="5️⃣ Chọn Bracelet",
                options=[discord.SelectOption(label=b) for b in BRACELET_OPTIONS],
            )

            async def bracelet_callback(interaction: discord.Interaction):
                self.data["bracelet"] = select.values[0]
                self.step = 6
                await self.next_step(interaction)

            select.callback = bracelet_callback
            self.add_item(select)

    async def next_step(self, interaction: discord.Interaction):
        if self.step < 6:
            self.refresh_menu()
            tz = self.data["tz_offset"]
            tz_str = f"+{tz:g}" if tz >= 0 else f"{tz:g}"
            embed = discord.Embed(title="⚙️ Setup MyGear", color=discord.Color.blue())
            embed.add_field(
                name="Thông số đang chọn",
                value=(
                    f"🌍 **Timezone:** UTC{tz_str}\n"
                    f"🛡️ **Role:** {self.data.get('role') or '...'}\n"
                    f"👕 **Gear:** {self.data.get('gear') or '...'}\n"
                    f"📱 **Vice:** {self.data.get('vice') or '...'}\n"
                    f"🃏 **Deck:** {self.data.get('deck') or '...'}\n"
                    f"💍 **Bracelet:** {self.data.get('bracelet') or '...'}"
                ),
            )
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            role = self.data["role"]
            stats_data = {k: v for k, v in self.data.items() if k != "tz_offset"}
            await players_col.update_one(
                {"user_id": self.user_id},
                {
                    "$set": {
                        "tz_offset": self.data["tz_offset"],
                        "timezone": self.data["tz_offset"],  # Đồng bộ với /schedule
                        f"my_stats.{role}": stats_data,
                    }
                },
                upsert=True,
            )
            await interaction.response.edit_message(
                content=f"✅ Đã lưu cấu hình Gear cho role **{role}** thành công!",
                embed=None,
                view=None,
            )
            self.stop()


class DungeonListView(discord.ui.View):
    def __init__(self, dungeons: list[dict]):
        super().__init__(timeout=120)
        for dg in dungeons[:25]:
            dg_name = dg.get("dg_name")
            if not dg_name:
                continue
            button = discord.ui.Button(label=dg_name.upper(), style=discord.ButtonStyle.primary)
            button.callback = self.create_callback(dg_name)
            self.add_item(button)

    def create_callback(self, dg_name: str):
        async def callback(interaction: discord.Interaction):
            await DungeonStats._perform_check(interaction, dg_name)
        return callback


class DungeonStats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    async def _perform_check(interaction: discord.Interaction, dg_name: str):
        await interaction.response.defer(ephemeral=True)
        player = await players_col.find_one({"user_id": interaction.user.id})
        cfg = await dungeon_configs_col.find_one({"dg_name": dg_name})

        if not cfg:
            return await interaction.followup.send(f"❌ Không tìm thấy dữ liệu yêu cầu cho `{dg_name}`.", ephemeral=True)
        if not player or not player.get("my_stats"):
            return await interaction.followup.send("❌ Vui lòng thiết lập hồ sơ bằng `/mygear` trước!", ephemeral=True)

        req = cfg.get("reqs", {})
        has_any_passed = False
        embed = discord.Embed(title=f"🔎 Check Gear: {dg_name.upper()}")

        for role_name, stats in player["my_stats"].items():
            if not isinstance(stats, dict):
                continue
            results = []
            is_role_ok = True

            for cat in ("gear", "vice", "deck", "bracelet"):
                u_val = stats.get(cat)
                allowed = req.get(cat, [])
                if u_val in allowed:
                    results.append(f"✅ **{cat.upper()}:** {u_val}")
                else:
                    req_text = ", ".join(allowed) if allowed else "None"
                    results.append(f"❌ **{cat.upper()}:** {u_val} *(Req: {req_text})*")
                    is_role_ok = False

            if is_role_ok:
                has_any_passed = True
            embed.add_field(
                name=f"Role: {role_name} [{'✅ PASS' if is_role_ok else '❌ FAIL'}]",
                value="\n".join(results),
                inline=False,
            )

        embed.color = discord.Color.green() if has_any_passed else discord.Color.red()
        if not embed.fields:
            return await interaction.followup.send("❌ Chưa có thông tin Gear hợp lệ, hãy cập nhật lại bằng `/mygear`!", ephemeral=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # --- HELPER CHO CẢ SLASH COMMAND & HUB /menu ---
    async def open_mygear(self, interaction: discord.Interaction):
        p = await players_col.find_one({"user_id": interaction.user.id})
        if not p or not p.get("ign") or p.get("ign") == "Not Set":
            await interaction.response.send_modal(MyGearIGNModal(self.bot))
        else:
            embed = discord.Embed(
                title="⚙️ Setup MyGear",
                description=f"Hồ sơ hiện tại: **{p.get('ign')}**\nChọn role bên dưới để cập nhật Gear:",
                color=discord.Color.blue(),
            )
            await interaction.response.send_message(embed=embed, view=MyGearWizard(interaction.user.id, p), ephemeral=True)

    async def open_showmygear(self, interaction: discord.Interaction, ephemeral: bool = False):
        p = await players_col.find_one({"user_id": interaction.user.id})
        if not p or not p.get("my_stats"):
            return await interaction.response.send_message("❌ Bạn chưa thiết lập Gear! Hãy dùng `/mygear` trước.", ephemeral=True)

        ign_in_db = p.get("ign", "Not Set")
        player_ign = f"⚠️ {interaction.user.name} (Chưa đặt IGN)" if ign_in_db == "Not Set" else ign_in_db

        embed = discord.Embed(title=f"🛡️ Hồ sơ Gear — {player_ign}", color=discord.Color.blue())
        for role_name, stats in p["my_stats"].items():
            if isinstance(stats, dict):
                embed.add_field(
                    name=f"Role: {role_name}",
                    value=(
                        f"**Gear:** {stats.get('gear', 'N/A')}\n"
                        f"**Vice:** {stats.get('vice', 'N/A')}\n"
                        f"**Deck:** {stats.get('deck', 'N/A')}\n"
                        f"**Bracelet:** {stats.get('bracelet', 'N/A')}"
                    ),
                    inline=True,
                )
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)

    async def open_dglist(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        dungeons = await dungeon_configs_col.find({}).to_list(length=25)
        if not dungeons:
            return await interaction.followup.send("❌ Chưa có cấu hình Dungeon nào trong Database.", ephemeral=True)
        await interaction.followup.send("📍 Chọn Dungeon bạn muốn kiểm tra yêu cầu Gear:", view=DungeonListView(dungeons), ephemeral=True)

    async def open_set_timezone(self, interaction: discord.Interaction):
        options = [
            discord.SelectOption(label=f"UTC{'+' if i >= 0 else ''}{i}", value=str(i))
            for i in TIMEZONE_OFFSETS
        ]
        select = discord.ui.Select(placeholder="🌍 Chọn múi giờ của bạn...", options=options)

        async def tz_callback(inter: discord.Interaction):
            offset = float(select.values[0])
            await players_col.update_one(
                {"user_id": inter.user.id},
                {"$set": {"tz_offset": offset, "timezone": offset}},
                upsert=True,
            )
            tz_str = f"+{offset:g}" if offset >= 0 else f"{offset:g}"
            await inter.response.edit_message(content=f"✅ Đã lưu múi giờ **UTC{tz_str}** thành công.", view=None, embed=None)

        select.callback = tz_callback
        view = discord.ui.View(timeout=120)
        view.add_item(select)
        embed = discord.Embed(
            title="🌍 Cấu hình múi giờ",
            description="Chọn múi giờ của bạn để đồng bộ thời gian Party và lịch Raid/Event chính xác.",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # --- SLASH COMMANDS ---
    @app_commands.command(name="mygear", description="Thiết lập hoặc cập nhật hồ sơ IGN & Gear của bạn")
    async def mygear(self, interaction: discord.Interaction):
        await self.open_mygear(interaction)

    @app_commands.command(name="set_timezone", description="🌍 Cài đặt múi giờ cá nhân")
    async def set_timezone(self, interaction: discord.Interaction):
        await self.open_set_timezone(interaction)

    @app_commands.command(name="showmygear", description="Hiển thị bảng thông số Gear hiện tại của bạn")
    async def showmygear(self, interaction: discord.Interaction):
        await self.open_showmygear(interaction, ephemeral=False)

    @app_commands.command(name="dglist", description="Kiểm tra yêu cầu Gear cho các Dungeon")
    async def dglist(self, interaction: discord.Interaction):
        await self.open_dglist(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(DungeonStats(bot))