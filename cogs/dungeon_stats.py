import discord
from discord.ext import commands
from Database import players_col

TIMEZONE_OFFSETS = [-8, -5, -3, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def format_utc_offset(offset: float) -> str:
    """Format a numeric timezone offset into a readable UTC string (e.g., UTC+7, UTC-5)."""
    sign = "+" if offset >= 0 else ""
    return f"UTC{sign}{offset:g}"


class TimezoneSelect(discord.ui.Select):
    """Dropdown selector for choosing a user's local timezone."""

    def __init__(self, user_id: int, current_ign: str | None = None):
        self.user_id = user_id
        self.current_ign = current_ign
        options = [
            discord.SelectOption(label=format_utc_offset(i), value=str(i))
            for i in TIMEZONE_OFFSETS
        ]
        super().__init__(placeholder="🌍 Select your local timezone...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(
                "This selector does not belong to you.",
                ephemeral=True,
            )

        offset = float(self.values[0])
        await players_col.update_one(
            {"user_id": self.user_id},
            {"$set": {"tz_offset": offset, "timezone": offset}},
            upsert=True,
        )
        tz_label = format_utc_offset(offset)
        ign_line = f"\n🪪 **In-Game Name:** `{self.current_ign}`" if self.current_ign else ""
        await interaction.response.edit_message(
            content=f"✅ Profile updated!{ign_line}\n🌍 **Timezone:** `{tz_label}`",
            embed=None,
            view=None,
        )


class TimezoneView(discord.ui.View):
    """View wrapper for the timezone dropdown."""

    def __init__(self, user_id: int, current_ign: str | None = None, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.add_item(TimezoneSelect(user_id, current_ign))


class ProfileIGNModal(discord.ui.Modal, title="⚙️ Setup Player Profile"):
    """Modal for entering or updating the player's In-Game Name (IGN)."""

    ign = discord.ui.TextInput(
        label="In-Game Name (IGN)",
        placeholder="Enter your exact character name...",
        required=True,
        max_length=30,
    )

    def __init__(self, current_ign: str | None = None):
        super().__init__()
        if current_ign and current_ign != "Not Set":
            self.ign.default = current_ign

    async def on_submit(self, interaction: discord.Interaction):
        ign_value = self.ign.value.strip()
        if not ign_value:
            return await interaction.response.send_message(
                "❌ In-Game Name cannot be empty.",
                ephemeral=True,
            )

        await players_col.update_one(
            {"user_id": interaction.user.id},
            {"$set": {"ign": ign_value}},
            upsert=True,
        )

        embed = discord.Embed(
            title="🌍 Step 2: Select Your Timezone",
            description=(
                f"✅ In-Game Name saved as: **{ign_value}**\n\n"
                "Now select your local timezone below so party start times and raid timers match your clock:"
            ),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=TimezoneView(interaction.user.id, current_ign=ign_value),
            ephemeral=True,
        )


class ProfileQuickView(discord.ui.View):
    """Quick action buttons attached to the View Profile embed."""

    def __init__(self, user_id: int, current_ign: str | None):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.current_ign = current_ign

    @discord.ui.button(label="Edit IGN & Timezone", emoji="✏️", style=discord.ButtonStyle.primary)
    async def btn_edit_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This profile card is not yours.", ephemeral=True)
        await interaction.response.send_modal(ProfileIGNModal(self.current_ign))


class DungeonStats(commands.Cog):
    """Manages player profiles (In-Game Name and Timezone only)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def open_profile_setup(self, interaction: discord.Interaction):
        """Open the IGN modal (pre-filled if already set), followed by timezone selection."""
        player = await players_col.find_one({"user_id": interaction.user.id}, {"ign": 1})
        current_ign = player.get("ign") if player else None
        await interaction.response.send_modal(ProfileIGNModal(current_ign))

    async def open_set_timezone(self, interaction: discord.Interaction):
        """Open only the timezone selector dropdown."""
        player = await players_col.find_one({"user_id": interaction.user.id}, {"ign": 1})
        current_ign = player.get("ign") if player and player.get("ign") != "Not Set" else None
        embed = discord.Embed(
            title="🌍 Configure Local Timezone",
            description="Select your timezone so the bot can synchronize Party and Raid schedules for you.",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=TimezoneView(interaction.user.id, current_ign=current_ign),
            ephemeral=True,
        )

    async def open_view_profile(self, interaction: discord.Interaction, ephemeral: bool = True):
        """Display the player's current IGN and Timezone."""
        player = await players_col.find_one({"user_id": interaction.user.id})
        if not player or not player.get("ign") or player.get("ign") == "Not Set":
            return await interaction.response.send_message(
                "❌ Your profile is not set up yet! Click **Setup / Edit Profile** to register your IGN and Timezone.",
                ephemeral=True,
            )

        ign = player.get("ign", "Not Set")
        raw_tz = player.get("tz_offset", player.get("timezone"))
        tz_display = format_utc_offset(float(raw_tz)) if raw_tz is not None else "Not Set"

        embed = discord.Embed(
            title=f"🪪 Player Profile — {interaction.user.display_name}",
            color=discord.Color.blue(),
        )
        embed.add_field(name="🎮 In-Game Name (IGN)", value=f"**{ign}**", inline=True)
        embed.add_field(name="🌍 Local Timezone", value=f"**{tz_display}**", inline=True)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        await interaction.response.send_message(
            embed=embed,
            view=ProfileQuickView(interaction.user.id, ign),
            ephemeral=ephemeral,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(DungeonStats(bot))