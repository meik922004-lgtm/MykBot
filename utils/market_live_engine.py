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
from utils.checks import check_is_owner
import aiohttp
import discord
from discord.ext import tasks

from Database import db

logger = logging.getLogger("MyKBot.MarketLive")

# MongoDB collections in database0
market_history_col = db["market_history"]
shop_subscriptions_col = db["shop_subscriptions"]
user_slots_col = db["user_slots"]
server_configs_col = db["server_configs"]

# Discord Gateway & source channels (configured via environment variables)
DISCORD_GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
SHOP_OPEN_CHANNEL_ID = int(os.getenv("DMW_SHOP_OPEN_CHANNEL_ID", "1371914477070712900"))
SHOP_SOLD_CHANNEL_ID = int(os.getenv("DMW_SHOP_SOLD_CHANNEL_ID", "1468567492267081789"))

# Anomaly detection & RAM-safe cache limits (Render Free tier)
WHALE_SPIKE_RATIO = 1.35          # +35% sold price above 7-day median
DUMP_DROP_RATIO = 0.70            # -30% listing price below 7-day median
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
    2. Real-time Whale Buyout & Fire Sale anomaly alerts.
    3. Automated Nightly Market Digest (24h summary).
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
                backoff = 5  # Reset backoff after a clean session
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
        """Persist shop snapshot to MongoDB, notify watchlist subscribers, and detect anomalies."""
        doc = {
            **shop_data,
            "timestamp": datetime.now(timezone.utc),
        }
        await market_history_col.insert_one(doc)

        # 1. Notify personal Watchlist DM subscribers on new open shops
        if shop_data.get("type") == "open":
            await self._notify_watchlist_subscribers(shop_data)

        # 2. Run Whale Buyout / Fire Sale anomaly detection
        await self.check_market_anomalies(shop_data)

    # =========================================================================
    # 2. WATCHLIST DM ALERTS (COMPATIBLE WITH EXISTING SCHEMA)
    # =========================================================================

    async def _notify_watchlist_subscribers(self, shop_data: dict[str, Any]):
        """Match newly opened shop items against shop_subscriptions and DM eligible users."""
        items_by_key: dict[str, dict[str, Any]] = {}
        for item in shop_data.get("items", []):
            name = str(item.get("item_name", "")).strip()
            cost = self._extract_item_price(item)
            if not name or cost <= 0:
                continue
            key = name.lower()
            if key not in items_by_key or cost < items_by_key[key]["cost"]:
                items_by_key[key] = {
                    "item_name": name,
                    "cost": cost,
                    "quantity": item.get("quantity", 1),
                }

        if not items_by_key:
            return

        sub_cursor = shop_subscriptions_col.find({"_id": {"$in": list(items_by_key.keys())}})
        pending_matches: list[tuple[int, dict[str, Any], float]] = []
        candidate_user_ids: set[int] = set()

        async for sub_doc in sub_cursor:
            item_key = sub_doc["_id"]
            item_info = items_by_key.get(item_key)
            if not item_info:
                continue
            for sub in sub_doc.get("subscribers", []):
                uid = sub.get("user_id")
                max_price = float(sub.get("max_price", 0))
                if uid and max_price > 0 and item_info["cost"] <= max_price:
                    pending_matches.append((int(uid), item_info, max_price))
                    candidate_user_ids.add(int(uid))

        if not pending_matches:
            return

        # Batch-check alerts_enabled from user_slots (default True if no doc)
        disabled_users: set[int] = set()
        slot_cursor = user_slots_col.find(
            {"_id": {"$in": list(candidate_user_ids)}, "alerts_enabled": False},
            {"_id": 1},
        )
        async for slot_doc in slot_cursor:
            disabled_users.add(int(slot_doc["_id"]))

        now = time.monotonic()
        for uid, item_info, max_price in pending_matches:
            if uid in disabled_users:
                continue

            # Deduplicate same user + item + shop within 15 minutes
            dedup_key = f"{uid}:{item_info['item_name'].lower()}:{shop_data.get('owner', '')}"
            if dedup_key in self._dm_alert_dedup and (now - self._dm_alert_dedup[dedup_key]) < 900:
                continue
            self._dm_alert_dedup[dedup_key] = now
            self._dm_alert_dedup.move_to_end(dedup_key)
            if len(self._dm_alert_dedup) > 500:
                self._dm_alert_dedup.popitem(last=False)

            user = self.bot.get_user(uid)
            if user is None:
                try:
                    user = await self.bot.fetch_user(uid)
                except discord.HTTPException:
                    continue

            embed = discord.Embed(
                title="🔔 Watchlist Price Match Found!",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="Item", value=f"**{item_info['item_name']}** (x{item_info['quantity']})", inline=False)
            embed.add_field(name="Listed Price", value=f"**{self._format_currency(item_info['cost'])}**", inline=True)
            embed.add_field(name="Your Target", value=f"<= `{self._format_currency(max_price)}`", inline=True)
            embed.add_field(
                name="Shop Location",
                value=f"`{shop_data.get('shop_name', 'N/A')}` by **{shop_data.get('owner', 'N/A')}** ({shop_data.get('map', 'N/A')})",
                inline=False,
            )
            try:
                await user.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

    # =========================================================================
    # 3. REAL-TIME WHALE BUYOUT & FIRE SALE ANOMALY ALERTS
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
        if amount >= 1_000_000_000:
            return f"{amount / 1_000_000_000:.2f}B"
        if amount >= 1_000_000:
            return f"{amount / 1_000_000:.2f}M"
        if amount >= 1_000:
            return f"{amount / 1_000:.1f}K"
        return f"{amount:,.0f}"

    async def _broadcast_market_embed(self, embed: discord.Embed, cross_chat_summary: str):
        """Send market intelligence to /setup_announcement channels and Cross-Chat network."""
        cursor = server_configs_col.find(
            {"channel_id": {"$exists": True, "$ne": None}},
            {"channel_id": 1},
        )
        sent_channels: set[int] = set()
        async for cfg in cursor:
            cid = cfg.get("channel_id")
            if not cid or int(cid) in sent_channels:
                continue
            channel = self.bot.get_channel(int(cid))
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(embed=embed)
                    sent_channels.add(int(cid))
                except (discord.Forbidden, discord.HTTPException):
                    pass

        cross_cog = self.bot.get_cog("CrossChatCog")
        if cross_cog and hasattr(cross_cog, "broadcast_system_message"):
            await cross_cog.broadcast_system_message(cross_chat_summary)

    async def check_market_anomalies(self, shop_data: dict[str, Any]):
        """
        Detect market anomalies while preventing troll-shop false positives:
        - 'open' shops trigger FIRE SALE alerts if priced <= 70% of 7-day median.
        - 'sold' events trigger WHALE BUYOUT alerts if actually bought >= 135% of 7-day median.
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
                item_map[key] = {"display_name": raw_name, "price": price}
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
            if median_price <= 0:
                continue

            cur_price = item_map[key]["price"]
            ratio = cur_price / median_price
            pct_change = (ratio - 1.0) * 100

            if update_type == "sold" and ratio >= WHALE_SPIKE_RATIO:
                if not self._is_anomaly_on_cooldown(f"whale:{key}"):
                    alerts.append(("WHALE", item_map[key]["display_name"], cur_price, median_price, pct_change))
            elif update_type == "open" and ratio <= DUMP_DROP_RATIO:
                if not self._is_anomaly_on_cooldown(f"dump:{key}"):
                    alerts.append(("DUMP", item_map[key]["display_name"], cur_price, median_price, pct_change))

        if not alerts:
            return

        alerts.sort(key=lambda x: abs(x[4]), reverse=True)
        top_alerts = alerts[:3]

        embed = discord.Embed(
            title="🚨 Live Market Anomaly Alert",
            description=f"Shop: **{shop_data.get('shop_name', 'Unknown')}** | Owner: `{shop_data.get('owner', 'Unknown')}` ({shop_data.get('map', 'N/A')})",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        headlines = []

        for kind, name, cur_p, med_p, pct in top_alerts:
            if kind == "WHALE":
                tag = f"📈 **WHALE BUYOUT (+{pct:.0f}%)**"
                headlines.append(f"📈 **{name}** sold at **+{pct:.0f}%** (`{self._format_currency(cur_p)}`)")
            else:
                tag = f"📉 **FIRE SALE ({pct:.0f}%)**"
                headlines.append(f"📉 **{name}** listed at **{pct:.0f}%** (`{self._format_currency(cur_p)}`)")

            embed.add_field(
                name=f"{tag} — {name}",
                value=(
                    f"• Trigger Price: **{self._format_currency(cur_p)}**\n"
                    f"• 7-Day Median: `{self._format_currency(med_p)}`"
                ),
                inline=False,
            )

        embed.set_footer(text="MyKBot Market Intelligence • Open /menu -> Market Hub for 30d charts")
        await self._broadcast_market_embed(embed, "🚨 **[Market Alert]** " + " | ".join(headlines))

    # =========================================================================
    # 4. AUTOMATED NIGHTLY MARKET DIGEST & OWNER CONTROL PANEL
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
            f"• **{name.title()}**: **+{pct:.1f}%** (Floor: `{self._format_currency(floor)}`)"
            for name, pct, floor in top_gainers
        ) or "No significant price spikes today."

        losers_text = "\n".join(
            f"• **{name.title()}**: **{pct:.1f}%** (Floor: `{self._format_currency(floor)}`)"
            for name, pct, floor in top_losers
        ) or "No major price drops today."

        volume_text = "\n".join(
            f"• **{name.title()}**: `{count}` listings (Floor: `{self._format_currency(floor)}`)"
            for name, count, floor in top_volume
        ) or "Insufficient volume data."

        embed.add_field(name="📈 Top Price Gainers", value=gainers_text, inline=False)
        embed.add_field(name="📉 Best Bargains / Drops", value=losers_text, inline=False)
        embed.add_field(name="🔥 Most Active Volume", value=volume_text, inline=False)
        embed.set_footer(text="MyKBot Nightly Market Report • Open /menu -> Market Hub to set DM alerts")
        return embed

    @tasks.loop(time=DIGEST_TIME_UTC)
    async def daily_market_digest(self):
        """Publish the scheduled 24h market report."""
        embed = await self.build_daily_digest_embed()
        if embed is None:
            return
        cross_summary = (
            "📊 **[Nightly Market Digest]** 24h market report posted! "
            "Open `/menu` -> **Market Hub** for 30-day price charts."
        )
        await self._broadcast_market_embed(embed, cross_summary)

    @daily_market_digest.before_loop
    async def _before_daily_digest(self):
        await self.bot.wait_until_ready()

    async def open_market_live_control(self, interaction: discord.Interaction):
        """Owner-only control panel to inspect 24/7 Gateway status and test/force Market Digest."""
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


class _MarketDigestControlView(discord.ui.View):
    """Ephemeral Owner buttons to preview or force-broadcast the 24h Market Digest."""

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
            content="**Preview only (not broadcast to servers):**",
            embed=embed,
            ephemeral=True,
        )

    @discord.ui.button(label="Force Broadcast Digest", style=discord.ButtonStyle.danger, emoji="📢")
    async def broadcast_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embed = await self.cog.build_daily_digest_embed()
        if embed is None:
            await interaction.followup.send(
                "Cannot broadcast: insufficient `market_history` data in the last 48 hours.",
                ephemeral=True,
            )
            return
        cross_summary = (
            "📊 **[Nightly Market Digest]** 24h market report posted! "
            "Open `/menu` -> **Market Hub** for 30-day price charts."
        )
        await self.cog._broadcast_market_embed(embed, cross_summary)
        await interaction.followup.send(
            "✅ Market Digest broadcasted to all announcement channels and Cross-Chat.",
            ephemeral=True,
        )