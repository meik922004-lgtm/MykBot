import asyncio
import json
import logging
import os
import random
import re
import statistics
import time
from collections import OrderedDict
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any, Optional

import aiohttp
import discord
from discord.ext import tasks

from Database import db
from utils.checks import check_is_owner

logger = logging.getLogger("MyKBot.MarketLive")

# MongoDB collections in database0
market_history_col = db["market_history"]
shop_subscriptions_col = db["shop_subscriptions"]
user_slots_col = db["user_slots"]

# Discord Gateway & source channels (configured via environment variables)
DISCORD_GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
SHOP_OPEN_CHANNEL_ID = int(os.getenv("DMW_SHOP_OPEN_CHANNEL_ID", "1371914477070712900"))
SHOP_SOLD_CHANNEL_ID = int(os.getenv("DMW_SHOP_SOLD_CHANNEL_ID", "1468567492267081789"))

# Anomaly detection & RAM-safe cache limits (Render Free tier)
WHALE_SPIKE_RATIO = 1.35          # +35% sold price above 7-day normal price
DUMP_DROP_RATIO = 0.70            # -30% listing price below 7-day normal price
MIN_ANOMALY_PRICE = 500_000       # Ignore cheap items under 100M (100,000 Bits)
MIN_HISTORY_SAMPLES = 5           # Minimum 7-day data points to prevent noise
ALERT_COOLDOWN_SECONDS = 12 * 3600
MAX_ALERT_CACHE_SIZE = 200

# Daily Market Digest schedule: 21:00 Vietnam Time (UTC+7) == 14:00 UTC
DIGEST_TIME_UTC = dt_time(hour=14, minute=0, second=0)

# Precompiled regex patterns matching DMW shop table format
SHOP_HEADER_PATTERN = re.compile(r"Shop Name:\s*(.*)\nOwner:\s*(.*)\nMap:\s*(.*)")
SHOP_ITEM_PATTERN = re.compile(r"\|\s*([^|]+?)\s*\|\s*([\d,]+)\s*\|\s*([\d,]+)\s*\|")


def parse_dmw_shop_message(content: str, update_type: str) -> Optional[dict[str, Any]]:
    """Parse DMW shop_open / shop_sold message text into a structured dictionary."""
    if not content:
        return None

    shop_match = SHOP_HEADER_PATTERN.search(content)
    if not shop_match:
        return None

    shop_name, owner, map_name = shop_match.groups()
    items: list[dict[str, Any]] = []

    for line in content.split("\n"):
        if "---" in line or ("Item" in line and "Cost" in line):
            continue
        match = SHOP_ITEM_PATTERN.search(line)
        if not match:
            continue

        item_name = match.group(1).strip()
        try:
            cost = int(match.group(2).replace(",", ""))
            quantity = int(match.group(3).replace(",", ""))
        except ValueError:
            continue

        if item_name and cost > 0:
            items.append({
                "item_name": item_name,
                "cost": cost,
                "quantity": quantity,
            })

    if not items:
        return None

    return {
        "type": update_type,  # "open" or "sold"
        "shop_name": shop_name.strip(),
        "owner": owner.strip(),
        "map": map_name.strip(),
        "items": items,
    }


class MarketLiveEngineMixin:
    """
    Mixin for ShopTracker providing:
    1. 24/7 Discord Gateway listener via pure aiohttp (no local PC or webhook needed).
    2. Real-time Cheap Deal & Price Spike DM alerts with native DMW currency formatting.
    3. Automated Nightly Market Digest (24h summary) sent via DM to opted-in subscribers.
    4. User opt-in DM subscriptions & custom item keyword filters.
    """

    def _init_market_live_engine(self):
        self._gateway_task: Optional[asyncio.Task] = None
        self._market_alert_cooldowns: OrderedDict[str, float] = OrderedDict()
        self._dm_alert_dedup: OrderedDict[str, float] = OrderedDict()

    def _start_market_live_engine(self):
        if not self.daily_market_digest.is_running():
            self.daily_market_digest.start()

        clone_token = os.getenv("DMW_CLONE_TOKEN", "").strip()
        if clone_token and (self._gateway_task is None or self._gateway_task.done()):
            self._gateway_task = asyncio.create_task(
                self._run_clone_gateway_loop(clone_token),
                name="dmw_shop_gateway_listener",
            )
            logger.info("[MarketLive] 24/7 Gateway listener started.")
        elif not clone_token:
            logger.warning(
                "[MarketLive] DMW_CLONE_TOKEN is not set. "
                "Live 24/7 listener disabled (using bridge fallback only)."
            )

    def _stop_market_live_engine(self):
        if self.daily_market_digest.is_running():
            self.daily_market_digest.cancel()
        if self._gateway_task and not self._gateway_task.done():
            self._gateway_task.cancel()

    # =========================================================================
    # 1. 24/7 PURE-AIOHTTP DISCORD GATEWAY LISTENER
    # =========================================================================

    async def _run_clone_gateway_loop(self, token: str):
        """Maintain a resilient WebSocket connection to Discord Gateway with auto-reconnect."""
        backoff = 5
        while not self.bot.is_closed():
            try:
                await self._connect_gateway_once(token)
                backoff = 5
            except asyncio.CancelledError:
                logger.info("[MarketLive] Gateway listener cancelled cleanly.")
                raise
            except Exception as exc:
                logger.warning(
                    "[MarketLive] Gateway disconnected (%s). Reconnecting in %ds...",
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _connect_gateway_once(self, token: str):
        seq: Optional[int] = None
        ack_received = True
        heartbeat_task: Optional[asyncio.Task] = None

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                DISCORD_GATEWAY_URL,
                max_msg_size=0,
                heartbeat=None,
            ) as ws:
                async def send_heartbeat_loop(interval_sec: float):
                    nonlocal ack_received
                    await asyncio.sleep(interval_sec * random.uniform(0.1, 0.5))
                    while not ws.closed:
                        if not ack_received:
                            logger.warning("[MarketLive] Missed Heartbeat ACK. Closing socket.")
                            await ws.close(code=4000)
                            return
                        ack_received = False
                        await ws.send_json({"op": 1, "d": seq})
                        await asyncio.sleep(interval_sec)

                try:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            payload = json.loads(msg.data)
                            op = payload.get("op")
                            event_type = payload.get("t")
                            data = payload.get("d")

                            if payload.get("s") is not None:
                                seq = payload["s"]

                            if op == 10:  # Hello
                                interval_ms = data["heartbeat_interval"]
                                heartbeat_task = asyncio.create_task(
                                    send_heartbeat_loop(interval_ms / 1000.0)
                                )
                                await ws.send_json({
                                    "op": 2,  # Identify
                                    "d": {
                                        "token": token,
                                        "capabilities": 16381,
                                        "properties": {
                                            "os": "Windows",
                                            "browser": "Chrome",
                                            "device": "",
                                        },
                                        "presence": {
                                            "status": "invisible",
                                            "since": 0,
                                            "activities": [],
                                            "afk": True,
                                        },
                                        "compress": False,
                                    },
                                })

                            elif op == 11:  # Heartbeat ACK
                                ack_received = True

                            elif op == 1:  # Immediate heartbeat request
                                await ws.send_json({"op": 1, "d": seq})

                            elif op in (7, 9):  # Reconnect / Invalid Session
                                logger.info("[MarketLive] Gateway requested reconnect (op=%s).", op)
                                await ws.close()
                                break

                            elif op == 0:  # Dispatch
                                if event_type == "READY":
                                    user = data.get("user", {})
                                    logger.info(
                                        "[MarketLive] Gateway READY as %s",
                                        user.get("username", "unknown"),
                                    )
                                elif event_type == "MESSAGE_CREATE":
                                    await self._on_gateway_message(data)

                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                finally:
                    if heartbeat_task and not heartbeat_task.done():
                        heartbeat_task.cancel()

    async def _on_gateway_message(self, data: dict[str, Any]):
        """Filter target shop channels and process live shop payloads."""
        try:
            channel_id = int(data.get("channel_id", 0))
        except (ValueError, TypeError):
            return

        if channel_id == SHOP_OPEN_CHANNEL_ID:
            update_type = "open"
        elif channel_id == SHOP_SOLD_CHANNEL_ID:
            update_type = "sold"
        else:
            return

        parsed = parse_dmw_shop_message(data.get("content", ""), update_type)
        if not parsed:
            return

        await self.process_live_shop_payload(parsed)

    async def process_live_shop_payload(self, shop_data: dict[str, Any]):
        """Fallback pipeline if not overridden by ShopTracker."""
        doc = {
            **shop_data,
            "timestamp": datetime.now(timezone.utc),
        }
        await market_history_col.insert_one(doc)
        await self.check_market_anomalies(shop_data)

    # =========================================================================
    # 2. REAL-TIME CHEAP DEAL & PRICE SPIKE DM ALERTS
    # =========================================================================

    def _is_anomaly_on_cooldown(self, cooldown_key: str) -> bool:
        now = time.monotonic()
        last_ts = self._market_alert_cooldowns.get(cooldown_key)
        if last_ts is not None and (now - last_ts) < ALERT_COOLDOWN_SECONDS:
            return True

        self._market_alert_cooldowns[cooldown_key] = now
        self._market_alert_cooldowns.move_to_end(cooldown_key)
        if len(self._market_alert_cooldowns) > MAX_ALERT_CACHE_SIZE:
            self._market_alert_cooldowns.popitem(last=False)
        return False

    @staticmethod
    def _extract_item_price(item: dict[str, Any]) -> float:
        for key in ("cost", "price", "unit_price"):
            val = item.get(key)
            if isinstance(val, (int, float)) and val > 0:
                return float(val)
        return 0.0

    @staticmethod
    def _format_currency(amount: float) -> str:
        """Format raw DMW Bit values into native Tera (T), Mega (M), and Bit (B)."""
        if amount >= 1_000_000:
            tera = amount / 1_000_000
            return f"{tera:.2f}T".rstrip("0").rstrip(".")
        if amount >= 1_000:
            mega = amount / 1_000
            return f"{mega:.1f}M".rstrip("0").rstrip(".")
        return f"{amount:,.0f}B"

    async def check_market_anomalies(self, shop_data: dict[str, Any]):
        """
        Detect notable price drops (Cheap Deals) and high-value buyouts (Price Spikes)
        and send Direct Messages exclusively to opted-in users.
        """
        update_type = shop_data.get("type", "open")
        item_map: dict[str, dict[str, Any]] = {}

        for item in shop_data.get("items", []):
            raw_name = str(item.get("item_name", "")).strip()
            price = self._extract_item_price(item)
            if not raw_name or price <= 0:
                continue
            key = raw_name.lower()
            if key not in item_map:
                item_map[key] = {"display_name": raw_name.title(), "price": price}
            else:
                if update_type == "open" and price < item_map[key]["price"]:
                    item_map[key]["price"] = price
                elif update_type == "sold" and price > item_map[key]["price"]:
                    item_map[key]["price"] = price

        if not item_map:
            return

        candidate_keys = list(item_map.keys())
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        ten_mins_ago = datetime.now(timezone.utc) - timedelta(minutes=10)

        pipeline = [
            {"$match": {"timestamp": {"$gte": seven_days_ago, "$lt": ten_mins_ago}}},
            {"$unwind": "$items"},
            {
                "$project": {
                    "item_key": {"$toLower": "$items.item_name"},
                    "price": {
                        "$ifNull": [
                            "$items.cost",
                            {"$ifNull": ["$items.price", "$items.unit_price"]},
                        ]
                    },
                }
            },
            {"$match": {"item_key": {"$in": candidate_keys}, "price": {"$gt": 0}}},
            {"$group": {"_id": "$item_key", "prices": {"$push": "$price"}}},
        ]

        alerts: list[tuple[str, str, float, float, float]] = []
        async for row in market_history_col.aggregate(pipeline):
            key = row["_id"]
            hist_prices = [float(p) for p in row.get("prices", []) if p and p > 0]
            if len(hist_prices) < MIN_HISTORY_SAMPLES or key not in item_map:
                continue

            median_price = statistics.median(hist_prices)
            cur_price = item_map[key]["price"]

            # Ignore low-value items (e.g., 2M-4M cards) to prevent noisy alerts
            if max(cur_price, median_price) < MIN_ANOMALY_PRICE or median_price <= 0:
                continue

            ratio = cur_price / median_price
            pct_change = (ratio - 1.0) * 100

            if update_type == "sold" and ratio >= WHALE_SPIKE_RATIO:
                if not self._is_anomaly_on_cooldown(f"whale:{key}"):
                    alerts.append(("SPIKE", item_map[key]["display_name"], cur_price, median_price, pct_change))
            elif update_type == "open" and ratio <= DUMP_DROP_RATIO:
                if not self._is_anomaly_on_cooldown(f"dump:{key}"):
                    alerts.append(("DEAL", item_map[key]["display_name"], cur_price, median_price, pct_change))

        if not alerts:
            return

        alerts.sort(key=lambda x: abs(x[4]), reverse=True)
        top_alerts = alerts[:3]

        shop_name = shop_data.get("shop_name", "Unknown")
        owner = shop_data.get("owner", "Unknown")
        map_name = shop_data.get("map", "Unknown")

        embed = discord.Embed(
            title="📢 Personal Market Price Alert",
            description=f"🏪 **{shop_name}** • Seller: `{owner}` • Location: `{map_name}`",
            color=discord.Color.green() if update_type == "open" else discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )

        for kind, name, cur_p, med_p, pct in top_alerts:
            cur_str = self._format_currency(cur_p)
            med_str = self._format_currency(med_p)

            if kind == "DEAL":
                discount = abs(pct)
                tag = f"💸 **CHEAP DEAL ({discount:.0f}% OFF)**"
                value_text = f"• Listed At: **{cur_str}** (Normal price: ~`{med_str}`)"
            else:
                tag = f"🔥 **BOUGHT HIGH (+{pct:.0f}%)**"
                value_text = f"• Sold For: **{cur_str}** (Normal price: ~`{med_str}`)"

            embed.add_field(
                name=f"{tag} — {name}",
                value=value_text,
                inline=False,
            )

        if update_type == "open":
            embed.add_field(name="⌨️ Quick Copy", value=f"```/shop {shop_name}```", inline=False)

        embed.set_footer(
            text="To turn off or edit alerts: /menu -> Market & Community -> Market Hub -> Deal & Digest Alerts"
        )
        await self._dispatch_anomaly_dms(embed, [a[1].lower() for a in top_alerts])

    # =========================================================================
    # 3. AUTOMATED NIGHTLY MARKET DIGEST & OWNER CONTROL PANEL
    # =========================================================================

    async def build_daily_digest_embed(self) -> Optional[discord.Embed]:
        """Build the 24h Market Digest Embed via MongoDB aggregation."""
        now = datetime.now(timezone.utc)
        day_1_start = now - timedelta(hours=24)
        day_2_start = now - timedelta(hours=48)

        pipeline = [
            {"$match": {"timestamp": {"$gte": day_2_start}}},
            {"$unwind": "$items"},
            {
                "$project": {
                    "item_name": "$items.item_name",
                    "item_key": {"$toLower": "$items.item_name"},
                    "price": {
                        "$ifNull": [
                            "$items.cost",
                            {"$ifNull": ["$items.price", "$items.unit_price"]},
                        ]
                    },
                    "period": {
                        "$cond": [{"$gte": ["$timestamp", day_1_start]}, "today", "yesterday"]
                    },
                }
            },
            {"$match": {"price": {"$gt": 0}}},
            {
                "$group": {
                    "_id": {"key": "$item_key", "period": "$period"},
                    "display_name": {"$first": "$item_name"},
                    "avg_price": {"$avg": "$price"},
                    "min_price": {"$min": "$price"},
                    "listings": {"$sum": 1},
                }
            },
        ]

        stats_by_item: dict[str, dict[str, Any]] = {}
        async for row in market_history_col.aggregate(pipeline):
            key = row["_id"]["key"]
            period = row["_id"]["period"]
            entry = stats_by_item.setdefault(key, {"name": row["display_name"]})
            entry[period] = {
                "avg": float(row["avg_price"]),
                "min": float(row["min_price"]),
                "count": int(row["listings"]),
            }

        movers = []
        most_listed = []
        for entry in stats_by_item.values():
            today = entry.get("today")
            yesterday = entry.get("yesterday")
            if today:
                most_listed.append((entry["name"], today["count"], today["min"]))
            if today and yesterday and yesterday["avg"] > 0 and today["count"] >= 2:
                pct = ((today["avg"] - yesterday["avg"]) / yesterday["avg"]) * 100
                movers.append((entry["name"], pct, today["min"]))

        if not movers and not most_listed:
            return None

        movers.sort(key=lambda x: x[1], reverse=True)
        top_gainers = [m for m in movers if m[1] > 3][:3]
        top_losers = sorted([m for m in movers if m[1] < -3], key=lambda x: x[1])[:3]
        most_listed.sort(key=lambda x: x[1], reverse=True)
        top_volume = most_listed[:3]

        embed = discord.Embed(
            title="📊 Nightly Market Digest (24h Report)",
            description="Automated price movement summary across DMW shops:",
            color=discord.Color.blurple(),
            timestamp=now,
        )

        gainers_text = "\n".join(
            f"• **{name.title()}**: **+{pct:.1f}%** (Lowest: `{self._format_currency(floor)}`)"
            for name, pct, floor in top_gainers
        ) or "No significant price spikes today."

        losers_text = "\n".join(
            f"• **{name.title()}**: **{pct:.1f}%** (Lowest: `{self._format_currency(floor)}`)"
            for name, pct, floor in top_losers
        ) or "No major price drops today."

        volume_text = "\n".join(
            f"• **{name.title()}**: `{count}` listings (Lowest: `{self._format_currency(floor)}`)"
            for name, count, floor in top_volume
        ) or "Insufficient volume data."

        embed.add_field(name="📈 Top Price Gainers", value=gainers_text, inline=False)
        embed.add_field(name="📉 Best Bargains / Drops", value=losers_text, inline=False)
        embed.add_field(name="🔥 Most Active Volume", value=volume_text, inline=False)
        embed.set_footer(
            text="To turn off Nightly Digest DMs: /menu -> Market & Community -> Market Hub -> Deal & Digest Alerts"
        )
        return embed

    @tasks.loop(time=DIGEST_TIME_UTC)
    async def daily_market_digest(self):
        """Send the scheduled 24h market report via DM to opted-in subscribers."""
        embed = await self.build_daily_digest_embed()
        if embed is None:
            return
        await self._dispatch_digest_dms(embed)

    @daily_market_digest.before_loop
    async def _before_daily_digest(self):
        await self.bot.wait_until_ready()

    async def open_market_live_control(self, interaction: discord.Interaction):
        """Owner-only control panel to inspect 24/7 Gateway status and test/send Market Digest DMs."""
        if not await check_is_owner(self.bot, interaction.user):
            await interaction.response.send_message(
                "⛔ Bot Owner permission required.", ephemeral=True
            )
            return

        has_token = bool(os.getenv("DMW_CLONE_TOKEN", "").strip())
        gw_running = bool(self._gateway_task and not self._gateway_task.done())
        if gw_running:
            gw_status = "🟢 Running (24/7 Live)"
        elif has_token:
            gw_status = "🔴 Stopped / Reconnecting"
        else:
            gw_status = "⚪ Disabled (`DMW_CLONE_TOKEN` not set)"

        next_run = self.daily_market_digest.next_iteration
        next_run_str = f"<t:{int(next_run.timestamp())}:R>" if next_run else "Not scheduled"

        embed = discord.Embed(
            title="📡 Market Live Engine — Owner Control",
            color=discord.Color.dark_teal(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="24/7 Gateway Listener", value=gw_status, inline=False)
        embed.add_field(name="Next Auto Digest", value=next_run_str, inline=True)
        embed.add_field(
            name="Tracked Channels",
            value=f"Open: `{SHOP_OPEN_CHANNEL_ID}`\nSold: `{SHOP_SOLD_CHANNEL_ID}`",
            inline=True,
        )

        view = _MarketDigestControlView(self)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # =========================================================================
    # 4. USER DEAL & DIGEST SUBSCRIPTION ENGINE (OPT-IN / CUSTOM KEYWORDS)
    # =========================================================================

    async def get_user_deal_prefs(self, user_id: int) -> dict[str, Any]:
        """Fetch user's market news & custom deal alert preferences from user_slots."""
        doc = await user_slots_col.find_one(
            {"_id": user_id},
            {"deal_alert_mode": 1, "digest_dm_enabled": 1, "deal_items": 1},
        )
        if not doc:
            return {"deal_alert_mode": "off", "digest_dm_enabled": False, "deal_items": []}
        return {
            "deal_alert_mode": doc.get("deal_alert_mode", "off"),
            "digest_dm_enabled": bool(doc.get("digest_dm_enabled", False)),
            "deal_items": [str(x).lower().strip() for x in doc.get("deal_items", []) if x],
        }

    async def _dispatch_anomaly_dms(self, embed: discord.Embed, triggered_item_keys: list[str]):
        """Send DM alerts to users subscribed to 'all' or matching 'watchlist' keywords."""
        if not triggered_item_keys:
            return

        watchlist_user_ids: set[int] = set()
        sub_cursor = shop_subscriptions_col.find(
            {"_id": {"$in": triggered_item_keys}},
            {"subscribers.user_id": 1},
        )
        async for sub_doc in sub_cursor:
            for sub in sub_doc.get("subscribers", []):
                if sub.get("user_id"):
                    watchlist_user_ids.add(int(sub["user_id"]))

        cursor = user_slots_col.find(
            {"deal_alert_mode": {"$in": ["all", "watchlist"]}},
            {"_id": 1, "deal_alert_mode": 1, "deal_items": 1},
        )

        target_users: list[int] = []
        async for doc in cursor:
            uid = int(doc["_id"])
            mode = doc.get("deal_alert_mode", "off")
            if mode == "all":
                target_users.append(uid)
            elif mode == "watchlist":
                keywords = [
                    str(k).lower().strip()
                    for k in doc.get("deal_items", [])
                    if len(str(k).strip()) >= 3
                ]
                matched_kw = any(kw in item_key for kw in keywords for item_key in triggered_item_keys)
                if matched_kw or uid in watchlist_user_ids:
                    target_users.append(uid)

        for uid in target_users:
            user = self.bot.get_user(uid)
            if user is None:
                try:
                    user = await self.bot.fetch_user(uid)
                except discord.HTTPException:
                    continue
            try:
                await user.send(
                    content=(
                        "🔔 **Personal Market Alert**\n"
                        "*(To turn off or edit alerts, type `/menu` → **Market & Community** → **Market Hub** → **Deal & Digest Alerts**)*"
                    ),
                    embed=embed,
                )
                await asyncio.sleep(0.25)
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def _dispatch_digest_dms(self, embed: discord.Embed):
        """Send the 24h Nightly Market Digest via DM to opted-in subscribers."""
        cursor = user_slots_col.find({"digest_dm_enabled": True}, {"_id": 1})
        async for doc in cursor:
            uid = int(doc["_id"])
            user = self.bot.get_user(uid)
            if user is None:
                try:
                    user = await self.bot.fetch_user(uid)
                except discord.HTTPException:
                    continue
            try:
                await user.send(
                    content=(
                        "📊 **Your Subscribed Nightly Market Report**\n"
                        "*(To turn off this daily DM, type `/menu` → **Market & Community** → **Market Hub** → **Deal & Digest Alerts**)*"
                    ),
                    embed=embed,
                )
                await asyncio.sleep(0.25)
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def open_deal_alert_preferences(self, interaction: discord.Interaction):
        """Open the interactive personal Market Deal & Digest subscription panel."""
        prefs = await self.get_user_deal_prefs(interaction.user.id)
        embed = _build_deal_prefs_embed(prefs)
        view = DealAlertPrefsView(self, interaction.user.id, prefs)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# =============================================================================
# UI VIEWS & MODALS
# =============================================================================

class _MarketDigestControlView(discord.ui.View):
    """Ephemeral Owner buttons to preview or send the 24h Market Digest to DM subscribers."""

    def __init__(self, cog: MarketLiveEngineMixin):
        super().__init__(timeout=180)
        self.cog = cog

    @discord.ui.button(label="Preview Digest (Private)", style=discord.ButtonStyle.secondary, emoji="👁️")
    async def preview_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embed = await self.cog.build_daily_digest_embed()
        if embed is None:
            await interaction.followup.send(
                "Not enough `market_history` data in the last 48 hours to generate a digest.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            content="**Preview only (not sent to subscribers):**",
            embed=embed,
            ephemeral=True,
        )

    @discord.ui.button(label="Send Digest to DM Subscribers", style=discord.ButtonStyle.primary, emoji="📨")
    async def broadcast_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embed = await self.cog.build_daily_digest_embed()
        if embed is None:
            await interaction.followup.send(
                "Cannot send: insufficient `market_history` data in the last 48 hours.",
                ephemeral=True,
            )
            return
        await self.cog._dispatch_digest_dms(embed)
        await interaction.followup.send(
            "✅ Nightly Market Digest sent via DM to all subscribed users.",
            ephemeral=True,
        )


def _build_deal_prefs_embed(prefs: dict[str, Any]) -> discord.Embed:
    mode = prefs.get("deal_alert_mode", "off")
    digest_on = prefs.get("digest_dm_enabled", False)
    items: list[str] = prefs.get("deal_items", [])

    mode_labels = {
        "all": "🌐 **All Major Deals & Spikes** (100M+ items)",
        "watchlist": "🎯 **My Selected Items Only** (+ My Watchlist)",
        "off": "🔕 **OFF** (No Deal Alert DMs)",
    }

    embed = discord.Embed(
        title="🔔 Market Deal & Digest Alert Settings",
        description=(
            "Customize how **MyKBot** notifies you via Direct Message (DM) "
            "when big discounts or market spikes happen:\n\n"
            f"**⚡ Live Deal Alerts:** {mode_labels.get(mode, mode_labels['off'])}\n"
            f"**📊 Nightly Digest (21:00 VN):** `{'🟢 ON' if digest_on else '🔴 OFF'}`"
        ),
        color=discord.Color.gold(),
    )

    if items:
        formatted = ", ".join(f"`{i.title()}`" for i in items[:15])
        embed.add_field(
            name=f"🎯 Custom Alert Keywords ({len(items)}/15)",
            value=f"{formatted}\n*(Partial keywords match any variant, e.g., `fanglongmon`)*",
            inline=False,
        )
    else:
        embed.add_field(
            name="🎯 Custom Alert Keywords (0/15)",
            value="No custom keywords set. Click **➕ Add Items** below to track specific items.",
            inline=False,
        )

    embed.set_footer(text="Make sure your Server Privacy Settings allow DMs from server members.")
    return embed


class MarketAlertSubscribeView(discord.ui.View):
    """Persistent 1-click button kept for backwards compatibility on older messages."""

    def __init__(self, cog: MarketLiveEngineMixin):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Alert Settings / Subscribe DM",
        style=discord.ButtonStyle.secondary,
        emoji="🔔",
        custom_id="myk_market_deal_prefs_v1",
    )
    async def open_prefs_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.open_deal_alert_preferences(interaction)


class _AddDealKeywordsModal(discord.ui.Modal, title="🎯 Add Market Deal Keywords"):
    """Modal allowing users to add up to 15 item keywords (comma-separated)."""

    keywords_input = discord.ui.TextInput(
        label="Item Name(s) — separate by comma",
        placeholder="e.g., fanglongmon, evoluter, backup disk",
        required=True,
        max_length=200,
    )

    def __init__(self, parent_view: "DealAlertPrefsView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        raw_parts = [p.strip().lower() for p in self.keywords_input.value.split(",")]
        valid_new = [p for p in raw_parts if len(p) >= 3]

        if not valid_new:
            return await interaction.response.send_message(
                "❌ Each keyword must be at least 3 characters long.", ephemeral=True
            )

        current_items = list(self.parent_view.prefs.get("deal_items", []))
        for kw in valid_new:
            if kw not in current_items and len(current_items) < 15:
                current_items.append(kw)

        new_mode = self.parent_view.prefs.get("deal_alert_mode", "off")
        if new_mode == "off":
            new_mode = "watchlist"

        await user_slots_col.update_one(
            {"_id": self.parent_view.user_id},
            {"$set": {"deal_items": current_items, "deal_alert_mode": new_mode}},
            upsert=True,
        )
        self.parent_view.prefs["deal_items"] = current_items
        self.parent_view.prefs["deal_alert_mode"] = new_mode
        self.parent_view._refresh_components()

        await interaction.response.edit_message(
            embed=_build_deal_prefs_embed(self.parent_view.prefs),
            view=self.parent_view,
        )


class _RemoveDealKeywordSelect(discord.ui.Select):
    """Dropdown to remove a tracked deal keyword."""

    def __init__(self, parent_view: "DealAlertPrefsView", items: list[str]):
        self.parent_view = parent_view
        options = [
            discord.SelectOption(label=kw.title()[:100], value=kw, emoji="🗑️")
            for kw in items[:15]
        ]
        super().__init__(placeholder="🗑️ Select a keyword to remove...", options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        to_remove = self.values[0]
        updated = [kw for kw in self.parent_view.prefs.get("deal_items", []) if kw != to_remove]

        await user_slots_col.update_one(
            {"_id": self.parent_view.user_id},
            {"$set": {"deal_items": updated}},
            upsert=True,
        )
        self.parent_view.prefs["deal_items"] = updated
        self.parent_view._refresh_components()

        await interaction.response.edit_message(
            embed=_build_deal_prefs_embed(self.parent_view.prefs),
            view=self.parent_view,
        )


class DealAlertPrefsView(discord.ui.View):
    """Interactive ephemeral panel for managing Market Deal & Nightly Digest DM subscriptions."""

    def __init__(self, cog: MarketLiveEngineMixin, user_id: int, prefs: dict[str, Any]):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.prefs = prefs
        self._refresh_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⛔ This panel belongs to another user.", ephemeral=True)
            return False
        return True

    def _refresh_components(self):
        self.clear_items()
        mode = self.prefs.get("deal_alert_mode", "off")
        digest_on = self.prefs.get("digest_dm_enabled", False)
        items = self.prefs.get("deal_items", [])

        btn_all = discord.ui.Button(
            label="All Deals",
            emoji="🌐",
            style=discord.ButtonStyle.success if mode == "all" else discord.ButtonStyle.secondary,
            row=0,
        )
        btn_all.callback = lambda i: self._set_mode(i, "all")

        btn_watch = discord.ui.Button(
            label="My Items Only",
            emoji="🎯",
            style=discord.ButtonStyle.success if mode == "watchlist" else discord.ButtonStyle.secondary,
            row=0,
        )
        btn_watch.callback = lambda i: self._set_mode(i, "watchlist")

        btn_off = discord.ui.Button(
            label="Turn Off",
            emoji="🔕",
            style=discord.ButtonStyle.danger if mode == "off" else discord.ButtonStyle.secondary,
            row=0,
        )
        btn_off.callback = lambda i: self._set_mode(i, "off")

        self.add_item(btn_all)
        self.add_item(btn_watch)
        self.add_item(btn_off)

        btn_digest = discord.ui.Button(
            label=f"Digest DM: {'ON' if digest_on else 'OFF'}",
            emoji="📊",
            style=discord.ButtonStyle.primary if digest_on else discord.ButtonStyle.secondary,
            row=1,
        )
        btn_digest.callback = self._toggle_digest

        btn_add = discord.ui.Button(
            label="Add Items",
            emoji="➕",
            style=discord.ButtonStyle.success,
            disabled=(len(items) >= 15),
            row=1,
        )
        btn_add.callback = lambda i: i.response.send_modal(_AddDealKeywordsModal(self))

        self.add_item(btn_digest)
        self.add_item(btn_add)

        if items:
            self.add_item(_RemoveDealKeywordSelect(self, items))

    async def _set_mode(self, interaction: discord.Interaction, new_mode: str):
        await user_slots_col.update_one(
            {"_id": self.user_id},
            {"$set": {"deal_alert_mode": new_mode}},
            upsert=True,
        )
        self.prefs["deal_alert_mode"] = new_mode
        self._refresh_components()
        await interaction.response.edit_message(embed=_build_deal_prefs_embed(self.prefs), view=self)

    async def _toggle_digest(self, interaction: discord.Interaction):
        new_val = not self.prefs.get("digest_dm_enabled", False)
        await user_slots_col.update_one(
            {"_id": self.user_id},
            {"$set": {"digest_dm_enabled": new_val}},
            upsert=True,
        )
        self.prefs["digest_dm_enabled"] = new_val
        self._refresh_components()
        await interaction.response.edit_message(embed=_build_deal_prefs_embed(self.prefs), view=self)