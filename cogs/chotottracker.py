import asyncio
from datetime import datetime, timezone
import aiohttp
import discord
from discord.ext import commands, tasks
from pymongo.errors import BulkWriteError
from utils.checks import check_is_owner


def parse_price_string(text: str) -> int:
    """Parse shorthand Vietnamese currency inputs (e.g., 500k, 1.5tr, 8tr5, 2 tỷ) into VND integer."""
    text = text.strip().lower().replace(" ", "").replace(",", ".")
    if not text or text == "0":
        return 0

    suffixes = [
        ("tỷ", 1_000_000_000), ("ty", 1_000_000_000),
        ("triệu", 1_000_000), ("trieu", 1_000_000), ("tr", 1_000_000),
        ("nghìn", 1_000), ("nghin", 1_000), ("k", 1_000),
    ]

    try:
        for suffix, multiplier in suffixes:
            if suffix in text:
                parts = text.split(suffix, 1)
                main_val = float(parts[0]) if parts[0] else 0.0
                if len(parts) > 1 and parts[1]:
                    sub_str = parts[1]
                    sub_val = float(sub_str) / (10 ** len(sub_str))
                    return int((main_val + sub_val) * multiplier)
                return int(main_val * multiplier)

        val = float(text)
        if val < 100:
            return int(val * 1_000_000_000)
        return int(val)
    except ValueError:
        return -1


class PriceModal(discord.ui.Modal, title="💰 Configure Price Filter"):
    """Modal for configuring minimum and maximum price thresholds."""

    min_p = discord.ui.TextInput(label="Minimum Price (e.g., 0, 500k, 1.5tr, 2tr5)", required=True)
    max_p = discord.ui.TextInput(label="Maximum Price (e.g., 8.5tr, 8tr5, 12tr, 3 tỷ)", required=True)

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.min_p.default = view.cog.format_price(view.config.get("min_price", 0))
        self.max_p.default = view.cog.format_price(view.config.get("max_price", 8_500_000))

    async def on_submit(self, interaction: discord.Interaction):
        min_val = parse_price_string(self.min_p.value)
        max_val = parse_price_string(self.max_p.value)
        if min_val < 0 or max_val <= 0 or min_val > max_val:
            return await interaction.response.send_message(
                "❌ Invalid price range! Examples: `0`, `500k`, `2.5tr`, `8tr5`, `1.5 tỷ`.",
                ephemeral=True,
            )

        await self.view.cog.config_col.update_one(
            {"_id": "user_filter_config"},
            {"$set": {"min_price": min_val, "max_price": max_val}},
        )
        await self.view.refresh_dashboard(interaction)


class TextFilterModal(discord.ui.Modal):
    """Modal for editing comma-separated filter lists (areas, keywords, exclusions)."""

    inputs = discord.ui.TextInput(
        label="Values (Comma-separated ',')",
        style=discord.TextStyle.paragraph,
        required=False,
    )

    def __init__(self, view, field_name: str, title: str, placeholder: str):
        super().__init__(title=title)
        self.view = view
        self.field_name = field_name
        self.inputs.placeholder = placeholder
        self.inputs.default = ", ".join(view.config.get(field_name, []))

    async def on_submit(self, interaction: discord.Interaction):
        new_list = [item.strip().lower() for item in self.inputs.value.split(",") if item.strip()]
        await self.view.cog.config_col.update_one(
            {"_id": "user_filter_config"},
            {"$set": {self.field_name: new_list}},
        )
        await self.view.refresh_dashboard(interaction)


class ChototDashboardView(discord.ui.View):
    """Owner-only interactive dashboard for managing Chotot listing filters."""

    def __init__(self, cog, config: dict):
        super().__init__(timeout=300)
        self.cog = cog
        self.config = config
        self.update_buttons_label()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if await check_is_owner(interaction.client, interaction.user):
            return True
        await interaction.response.send_message("⛔ Only **Bot Owners** can manage the Chotot Tracker.", ephemeral=True)
        return False

    def update_buttons_label(self):
        is_active = self.config.get("is_active", True)
        self.btn_toggle.label = "Status: ON 🟢" if is_active else "Status: OFF 🔴"
        self.btn_toggle.style = discord.ButtonStyle.success if is_active else discord.ButtonStyle.danger

    async def refresh_dashboard(self, interaction: discord.Interaction):
        self.config = await self.cog.config_col.find_one({"_id": "user_filter_config"})
        self.update_buttons_label()
        embed = self.cog.create_status_embed(self.config)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Status", row=0)
    async def btn_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_status = self.config.get("is_active", True)
        await self.cog.config_col.update_one(
            {"_id": "user_filter_config"},
            {"$set": {"is_active": not current_status, "channel_id": interaction.channel_id}},
        )
        await self.refresh_dashboard(interaction)

    @discord.ui.button(label="💰 Edit Price Range", style=discord.ButtonStyle.primary, row=0)
    async def btn_price(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PriceModal(self))

    @discord.ui.button(label="📍 Edit Areas", style=discord.ButtonStyle.primary, row=1)
    async def btn_areas(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            TextFilterModal(self, "areas", "📍 Target Areas", "e.g., gò vấp, quận 12, bình thạnh...")
        )

    @discord.ui.button(label="🔑 Required Keywords", style=discord.ButtonStyle.primary, row=1)
    async def btn_keywords(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            TextFilterModal(self, "keywords", "🔑 Required Keywords", "e.g., phòng trọ, full nội thất, ban công...")
        )

    @discord.ui.button(label="🚫 Exclude Keywords", style=discord.ButtonStyle.secondary, row=2)
    async def btn_exclude(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            TextFilterModal(self, "exclude_keywords", "🚫 Excluded Keywords", "e.g., cần mua, cần thuê, pass đồ...")
        )

    @discord.ui.button(label="🧹 Clear Seen Cache", style=discord.ButtonStyle.danger, row=2)
    async def btn_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.seen_ads_col.delete_many({})
        await interaction.response.send_message("🧹 Cleared all cached seen listing IDs!", ephemeral=True)


class ChototTracker(commands.Cog):
    """Background Chotot listing scanner managed from the /menu Owner Control Panel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config_col = self.bot.db["chotot_config"]
        self.seen_ads_col = self.bot.db["chotot_seen_ads"]
        self._session: aiohttp.ClientSession | None = None
        self.is_first_run = True
        self.scan_market.start()

    async def cog_load(self):
        try:
            await self.seen_ads_col.create_index("at", expireAfterSeconds=1209600)
        except Exception:
            pass

    async def cog_unload(self):
        self.scan_market.cancel()
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        return self._session

    def format_price(self, price_vnd: int) -> str:
        if price_vnd >= 1_000_000_000:
            return f"{price_vnd / 1_000_000_000:.2f}B VND"
        if price_vnd >= 1_000_000:
            return f"{price_vnd / 1_000_000:.1f}M VND"
        return f"{price_vnd:,} VND"

    def create_status_embed(self, config: dict) -> discord.Embed:
        status_text = "ACTIVE 🟢" if config.get("is_active", True) else "PAUSED 🔴"
        channel_id = config.get("channel_id")
        channel_mention = f"<#{channel_id}>" if channel_id else "`Not Configured`"

        embed = discord.Embed(
            title="🎯 CHOTOT SMART TRACKER CONTROL PANEL",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="⚙️ Scanner Status", value=f"**{status_text}**", inline=True)
        embed.add_field(name="📍 Alert Channel", value=channel_mention, inline=True)
        embed.add_field(
            name="💰 Price Range",
            value=f"`{self.format_price(config.get('min_price', 0))}` → `{self.format_price(config.get('max_price', 8_500_000))}`",
            inline=False,
        )
        embed.add_field(
            name="🗺️ Target Areas",
            value=f"`{', '.join(config.get('areas', []))}`" if config.get("areas") else "_Nationwide (No filter)_",
            inline=False,
        )
        embed.add_field(
            name="🔑 Required Keywords",
            value=f"`{', '.join(config.get('keywords', []))}`" if config.get("keywords") else "_Any listing_",
            inline=False,
        )
        embed.add_field(
            name="🚫 Excluded Keywords",
            value=f"`{', '.join(config.get('exclude_keywords', []))}`" if config.get("exclude_keywords") else "_None_",
            inline=False,
        )
        return embed

    async def open_chotot_dashboard(self, interaction: discord.Interaction, ephemeral: bool = True):
        """Invoked from /menu Owner Control Panel."""
        if not await check_is_owner(self.bot, interaction.user):
            return await interaction.response.send_message("⛔ Only **Bot Owners** can access Chotot Tracker.", ephemeral=True)

        config = await self.config_col.find_one({"_id": "user_filter_config"})
        if not config:
            config = {
                "_id": "user_filter_config",
                "channel_id": interaction.channel_id,
                "is_active": True,
                "min_price": 0,
                "max_price": 8_500_000,
                "areas": [],
                "keywords": [],
                "exclude_keywords": ["cần mua", "cần thuê"],
            }
            await self.config_col.insert_one(config)
        else:
            await self.config_col.update_one(
                {"_id": "user_filter_config"},
                {"$set": {"channel_id": interaction.channel_id}},
            )
            config["channel_id"] = interaction.channel_id

        embed = self.create_status_embed(config)
        await interaction.response.send_message(embed=embed, view=ChototDashboardView(self, config), ephemeral=ephemeral)

    @tasks.loop(minutes=5)
    async def scan_market(self):
        config = await self.config_col.find_one({"_id": "user_filter_config"})
        if not config or not config.get("is_active", True):
            return

        channel = self.bot.get_channel(config.get("channel_id"))
        if not channel:
            return

        url = "https://gateway.chotot.com/v1/public/ad-listing?cg=1000&limit=50"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        try:
            session = await self._get_session()
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return
                ads = (await resp.json()).get("ads", [])
        except Exception as e:
            print(f"[Chotot] API request failed: {e}", flush=True)
            return

        ad_ids = [ad["list_id"] for ad in ads if ad.get("list_id")]
        if not ad_ids:
            return

        existing_docs = await self.seen_ads_col.find({"_id": {"$in": ad_ids}}, {"_id": 1}).to_list(length=None)
        seen_set = {doc["_id"] for doc in existing_docs}

        now_utc = datetime.now(timezone.utc)
        filter_areas = config.get("areas", [])
        filter_keywords = config.get("keywords", [])
        filter_excludes = config.get("exclude_keywords", [])
        min_price = config.get("min_price", 0)
        max_price = config.get("max_price", 100_000_000_000)

        to_mark_seen = []
        matched_ads = []

        for ad in ads:
            ad_id = ad.get("list_id")
            if not ad_id or ad_id in seen_set:
                continue

            to_mark_seen.append({"_id": ad_id, "at": now_utc})

            price = int(ad.get("price", 0))
            if price == 0 or not (min_price <= price <= max_price):
                continue

            subject = ad.get("subject", "").lower()
            body = ad.get("body", "").lower()
            full_loc = f"{ad.get('ward_name', '')} {ad.get('area_name', '')} {ad.get('region_name', '')}".lower()

            if any(ex in subject or ex in body for ex in filter_excludes):
                continue
            if filter_areas and not any(area in full_loc for area in filter_areas):
                continue
            if filter_keywords and not any(kw in subject or kw in body for kw in filter_keywords):
                continue

            matched_ads.append(ad)

        if to_mark_seen:
            try:
                await self.seen_ads_col.insert_many(to_mark_seen, ordered=False)
            except BulkWriteError:
                pass

        if self.is_first_run:
            self.is_first_run = False
            print("[Chotot Tracker] Initial baseline sync completed.", flush=True)
            return

        for ad in matched_ads:
            ad_id = ad["list_id"]
            desc = ad.get("body", "No detailed description provided.")
            if len(desc) > 350:
                desc = desc[:350] + "..."
            loc_display = f"{ad.get('ward_name', '')}, {ad.get('area_name', '')}, {ad.get('region_name', '')}".strip(", ")

            embed = discord.Embed(
                title=ad.get("subject", "Untitled Listing"),
                url=f"https://www.nhatot.com/vi/{ad_id}.htm",
                description=desc,
                color=discord.Color.green(),
                timestamp=now_utc,
            )
            embed.add_field(name="💰 Price", value=f"**{self.format_price(int(ad.get('price', 0)))}**", inline=True)
            embed.add_field(name="📍 Location", value=loc_display or "Unknown", inline=True)
            if ad.get("image"):
                embed.set_image(url=f"https://cdn.chotot.com/{ad['image']}")
            embed.set_footer(text=f"Chotot Tracker • Listing ID: {ad_id}")

            try:
                await channel.send(embed=embed)
                await asyncio.sleep(1.2)
            except Exception as e:
                print(f"[Chotot] Failed to send listing {ad_id}: {e}", flush=True)

    @scan_market.before_loop
    async def before_scan_market(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(ChototTracker(bot))