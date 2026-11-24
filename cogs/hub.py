import discord
from discord import app_commands
from discord.ext import commands
from utils.checks import check_is_owner


def build_home_embed(user: discord.abc.User, is_owner: bool) -> discord.Embed:
    """Build the main landing embed for the /menu central hub."""
    embed = discord.Embed(
        title="🎛️ MyKBot — Central Control Hub",
        description=(
            f"Welcome, **{user.display_name}**! Use the dropdown menu below "
            "to access all MyKBot features from one unified interface."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="⚔️ Party & Schedule",
        value="Browse or create cross-server parties, restore your party DM, and view Raid/Event timers.",
        inline=False,
    )
    embed.add_field(
        name="👤 Profile & Timezone",
        value="Set up or edit your In-Game Name (IGN) and local timezone for accurate party and raid timers.",
        inline=False,
    )
    embed.add_field(
        name="🛒 Market & Community",
        value="Manage your real-time Market Watchlist & price charts, read the latest DMW Patch Notes, and self-assign server roles.",
        inline=False,
    )
    if is_owner:
        embed.add_field(
            name="👑 Owner Control Panel",
            value="Exclusive owner tools: Global Broadcast, Grant Market Slots, Set Raid/Event Timers, and Chotot Tracker.",
            inline=False,
        )
    embed.set_footer(text="MyKBot Hub • Menu times out after 3 minutes of inactivity")
    return embed


class HubSelect(discord.ui.Select):
    """Category selector dropdown inside /menu."""

    def __init__(self, author_id: int, is_owner: bool):
        self.author_id = author_id
        self.is_owner = is_owner

        options = [
            discord.SelectOption(
                label="Home",
                value="home",
                emoji="🏠",
                description="Overview of all MyKBot features",
            ),
            discord.SelectOption(
                label="Party & Schedule",
                value="party",
                emoji="⚔️",
                description="Party Lobby, My Party DM & Raid/Event Timers",
            ),
            discord.SelectOption(
                label="Profile & Timezone",
                value="profile",
                emoji="👤",
                description="Setup/Edit IGN & Local Timezone",
            ),
            discord.SelectOption(
                label="Market & Community",
                value="market_comm",
                emoji="🛒",
                description="Market Hub, Latest Patch Notes & Self-Roles",
            ),
        ]

        if is_owner:
            options.append(
                discord.SelectOption(
                    label="Owner Control Panel",
                    value="owner",
                    emoji="👑",
                    description="Broadcast, Grant Slots, Timers & Chotot Tracker",
                )
            )

        super().__init__(placeholder="👇 Select a category...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message(
                "Please run `/menu` to open your own control panel.",
                ephemeral=True,
            )

        choice = self.values[0]
        view: MyKBotHubView = self.view  # type: ignore

        if choice == "home":
            embed = build_home_embed(interaction.user, self.is_owner)
        elif choice == "party":
            embed = discord.Embed(
                title="⚔️ Party Finder & Schedules",
                description="Choose an action below to find/create a party or check upcoming Raid and Event timers.",
                color=discord.Color.green(),
            )
        elif choice == "profile":
            embed = discord.Embed(
                title="👤 Player Profile & Timezone",
                description="Set your In-Game Name (IGN) and local timezone so party times and raid schedules match your region.",
                color=discord.Color.blue(),
            )
        elif choice == "market_comm":
            embed = discord.Embed(
                title="🛒 Market Tracker & Community",
                description="Track in-game shop prices, read translated DMW patch summaries, or manage your server roles.",
                color=discord.Color.gold(),
            )
        else:
            embed = discord.Embed(
                title="👑 Bot Owner Control Panel",
                description="Administrative controls restricted exclusively to Bot Owners.",
                color=discord.Color.red(),
            )

        view.set_section_buttons(choice)
        await interaction.response.edit_message(embed=embed, view=view)


class MyKBotHubView(discord.ui.View):
    """Unified interactive hub view containing category dropdown and dynamic action buttons."""

    def __init__(self, bot: commands.Bot, author_id: int, is_owner: bool, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.author_id = author_id
        self.is_owner = is_owner
        self.add_item(HubSelect(author_id, is_owner))
        self.set_section_buttons("home")

    def set_section_buttons(self, section: str):
        for item in list(self.children):
            if isinstance(item, discord.ui.Button):
                self.remove_item(item)

        if section == "party":
            self.add_item(self._make_btn("Party Lobby", "🌐", discord.ButtonStyle.success, "party_lobby", row=1))
            self.add_item(self._make_btn("My Party (DM)", "📩", discord.ButtonStyle.primary, "my_party", row=1))
            self.add_item(self._make_btn("Raid / Event Schedule", "📅", discord.ButtonStyle.secondary, "schedule", row=1))

        elif section == "profile":
            self.add_item(self._make_btn("Setup / Edit Profile", "⚙️", discord.ButtonStyle.success, "setup_profile", row=1))
            self.add_item(self._make_btn("View My Profile", "🪪", discord.ButtonStyle.primary, "view_profile", row=1))
            self.add_item(self._make_btn("Change Timezone", "🌍", discord.ButtonStyle.secondary, "set_timezone", row=1))

        elif section == "market_comm":
            self.add_item(self._make_btn("Market Hub", "🎯", discord.ButtonStyle.success, "market_hub", row=1))
            self.add_item(self._make_btn("Latest Patch Notes", "📰", discord.ButtonStyle.primary, "patch_latest", row=1))
            self.add_item(self._make_btn("Self-Assign Roles", "🎭", discord.ButtonStyle.secondary, "roles_panel", row=1))

        elif section == "owner" and self.is_owner:
            self.add_item(self._make_btn("Global Broadcast", "📢", discord.ButtonStyle.danger, "owner_broadcast", row=1))
            self.add_item(self._make_btn("Grant Market Slots", "🎟️", discord.ButtonStyle.primary, "owner_addslot", row=1))
            self.add_item(self._make_btn("Set Raid/Event Timer", "⏰", discord.ButtonStyle.secondary, "owner_settimer", row=1))
            self.add_item(self._make_btn("Chotot Tracker", "🏍️", discord.ButtonStyle.secondary, "owner_chotot", row=1))

        close_btn = discord.ui.Button(label="Close", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
        close_btn.callback = self._close_cb
        self.add_item(close_btn)

    def _make_btn(self, label: str, emoji: str, style: discord.ButtonStyle, action: str, row: int = 1):
        btn = discord.ui.Button(label=label, emoji=emoji, style=style, row=row)

        async def _cb(interaction: discord.Interaction):
            if interaction.user.id != self.author_id:
                return await interaction.response.send_message(
                    "This menu does not belong to you. Run `/menu` to open your own.",
                    ephemeral=True,
                )

            # Party & Schedule actions
            if action == "party_lobby":
                cog = self.bot.get_cog("PartyFinderCog")
                if cog:
                    return await cog.open_party_lobby(interaction)

            elif action == "my_party":
                cog = self.bot.get_cog("PartyFinderCog")
                if cog:
                    return await cog.open_my_party(interaction)

            elif action == "schedule":
                cog = self.bot.get_cog("General")
                if cog:
                    await interaction.response.defer(ephemeral=True)
                    embed = await cog.build_schedule_embed(interaction.guild_id, interaction.user.id)
                    return await interaction.followup.send(embed=embed, ephemeral=True)

            # Profile & Timezone actions
            elif action == "setup_profile":
                cog = self.bot.get_cog("DungeonStats")
                if cog:
                    return await cog.open_profile_setup(interaction)

            elif action == "view_profile":
                cog = self.bot.get_cog("DungeonStats")
                if cog:
                    return await cog.open_view_profile(interaction, ephemeral=True)

            elif action == "set_timezone":
                cog = self.bot.get_cog("DungeonStats")
                if cog:
                    return await cog.open_set_timezone(interaction)

            # Market & Community actions
            elif action == "market_hub":
                cog = self.bot.get_cog("ShopTracker")
                if cog:
                    return await cog.open_market_hub(interaction, ephemeral=True)

            elif action == "patch_latest":
                cog = self.bot.get_cog("DMWBroadcaster")
                if cog:
                    return await cog.open_latest_patch(interaction)

            elif action == "roles_panel":
                cog = self.bot.get_cog("RolesCog")
                if cog:
                    embed, view = cog.build_roles_panel()
                    return await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

            # Owner-only actions
            elif action.startswith("owner_"):
                if not await check_is_owner(self.bot, interaction.user):
                    return await interaction.response.send_message("⛔ Bot Owner permission required.", ephemeral=True)

                if action == "owner_broadcast":
                    cog = self.bot.get_cog("NewsSystemCog")
                    if cog:
                        return await cog.open_broadcast_modal(interaction)
                elif action == "owner_addslot":
                    cog = self.bot.get_cog("ShopTracker")
                    if cog:
                        return await cog.open_grant_slot_modal(interaction)
                elif action == "owner_settimer":
                    cog = self.bot.get_cog("General")
                    if cog:
                        return await cog.open_set_timer_modal(interaction)
                elif action == "owner_chotot":
                    cog = self.bot.get_cog("ChototTracker")
                    if cog:
                        return await cog.open_chotot_dashboard(interaction, ephemeral=True)

            await interaction.response.send_message("⚠️ This module is currently unavailable.", ephemeral=True)

        btn.callback = _cb
        return btn

    async def _close_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("You cannot close someone else's menu.", ephemeral=True)
        await interaction.message.delete()
        self.stop()


class HubCog(commands.Cog):
    """Provides the single unified /menu slash command for all users."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="menu", description="Open the MyKBot Central Control Hub")
    async def menu_command(self, interaction: discord.Interaction):
        is_owner = await check_is_owner(self.bot, interaction.user)
        view = MyKBotHubView(self.bot, interaction.user.id, is_owner)
        await interaction.response.send_message(
            embed=build_home_embed(interaction.user, is_owner),
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(HubCog(bot))