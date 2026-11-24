import asyncio
import io
import json
import os
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")  # Bắt buộc cho server không có màn hình (Render)
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

import discord
from discord import app_commands
from discord.ext import commands
from Database import (
    shop_subscriptions_col,
    user_slots_col,
    bot_logs_col,
    players_col,
    market_history_col,
)
from utils.checks import is_bot_owner_slash

BRIDGE_CHANNEL_ID = int(os.getenv("SHOP_BRIDGE_CHANNEL_ID", "1515038293643759728"))
MAX_ACTIVE_ALERTS = 500


def _render_chart_sync(item_name: str, timestamps: list, prices: list) -> io.BytesIO:
    """Hàm đồng bộ thuần (thread-safe) chạy qua asyncio.to_thread để không block Event Loop."""
    fig = Figure(figsize=(10, 5), facecolor="#121212")
    ax = fig.add_subplot(111, facecolor="#1a1a1a")

    ax.plot(timestamps, prices, label="Spot Price", color="#3498db", marker="o", markersize=4, linewidth=1.6)

    if len(prices) > 3:
        rolling_avg = [(prices[i - 2] + prices[i - 1] + prices[i]) / 3.0 for i in range(2, len(prices))]
        ax.plot(timestamps[2:], rolling_avg, label="Trend (MA-3)", color="#f39c12", linestyle="--", linewidth=1.5)

    ax.set_title(f"Price Analytics: {item_name.title()}", fontsize=13, color="white", pad=12)
    ax.set_xlabel("Timeline (UTC)", color="#aaaaaa")
    ax.set_ylabel("Price", color="#aaaaaa")
    ax.tick_params(colors="#cccccc")
    for spine in ax.spines.values():
        spine.set_color("#444444")
    ax.grid(True, linestyle=":", alpha=0.4, color="#666666")
    ax.legend(loc="upper left", facecolor="#1e1e1e", edgecolor="#444444", labelcolor="white")
    fig.autofmt_xdate()

    buf = io.BytesIO()
    FigureCanvasAgg(fig).print_png(buf)
    buf.seek(0)
    fig.clear()
    return buf


# ==========================================
# MODALS & SELECTS
# ==========================================
class ItemModal(discord.ui.Modal):
    def __init__(self, cog, action: str, item_name: str | None = None):
        super().__init__(title="Track New Item" if action == "add" else f"Edit: {item_name[:35]}")
        self.cog = cog
        self.action = action
        self.target_item = item_name

        if self.action == "add":
            self.item_name_input = discord.ui.TextInput(
                label="Item Name",
                placeholder="Nhập chính xác tên item...",
                required=True,
                max_length=100,
            )
            self.add_item(self.item_name_input)

        self.price_input = discord.ui.TextInput(
            label="Max Alert Price",
            placeholder="VD: 5000000",
            required=True,
            max_length=20,
        )
        self.add_item(self.price_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            max_price = int(self.price_input.value.strip().replace(",", "").replace(".", ""))
            if max_price <= 0:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("❌ Giá phải là một số nguyên dương hợp lệ!", ephemeral=True)

        item_name = self.target_item if self.action == "edit" else self.item_name_input.value.strip()
        success, message = await self.cog.process_add_or_edit(
            interaction.user.id, item_name, max_price, is_edit=(self.action == "edit")
        )
        await interaction.response.send_message(f"{'✅' if success else '⚠️'} {message}", ephemeral=True)


class ItemSelect(discord.ui.Select):
    def __init__(self, items: list[dict], action: str, cog):
        self.action = action
        self.cog = cog
        options = [
            discord.SelectOption(
                label=i["name"].title()[:100],
                description=f"Alert ≤ {i['max_price']:,}",
                value=i["name"],
            )
            for i in items[:25]
        ]
        super().__init__(placeholder=f"Chọn item để {'sửa giá' if action == 'edit' else 'xóa'}...", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        if self.action == "edit":
            await interaction.response.send_modal(ItemModal(self.cog, "edit", selected))
        elif self.action == "delete":
            success, message = await self.cog.process_remove(interaction.user.id, selected)
            await interaction.response.send_message(f"{'✅' if success else '⚠️'} {message}", ephemeral=True)


class ChartModal(discord.ui.Modal, title="📈 Xem Biểu Đồ Giá"):
    item_name_input = discord.ui.TextInput(label="Item Name", placeholder="Nhập chính xác tên item...", required=True)
    days_input = discord.ui.TextInput(label="Số ngày (1 - 30)", placeholder="VD: 7", default="7", required=False)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        item_name = self.item_name_input.value.strip()
        try:
            days = int(self.days_input.value.strip()) if self.days_input.value.strip() else 7
            days = max(1, min(30, days))
        except ValueError:
            return await interaction.followup.send("❌ Số ngày không hợp lệ (hãy nhập từ 1 đến 30)!", ephemeral=True)

        await self.cog.process_chart_render(interaction, item_name, days)


# ==========================================
# CENTRALIZED MARKET HUB VIEW
# ==========================================
class CentralHubView(discord.ui.View):
    def __init__(self, cog, user_id: int, alerts_enabled: bool):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.alerts_enabled = alerts_enabled

        self.toggle_btn = discord.ui.Button(
            label="🔔 Alerts: ON" if alerts_enabled else "🔕 Alerts: OFF",
            style=discord.ButtonStyle.success if alerts_enabled else discord.ButtonStyle.danger,
            row=0,
        )
        self.toggle_btn.callback = self.toggle_alerts
        self.add_item(self.toggle_btn)

        self.watchlist_btn = discord.ui.Button(label="📋 My Watchlist", style=discord.ButtonStyle.primary, row=0)
        self.watchlist_btn.callback = self.my_list
        self.add_item(self.watchlist_btn)

        self.chart_btn = discord.ui.Button(label="📈 Price Chart", style=discord.ButtonStyle.secondary, row=0)
        self.chart_btn.callback = self.price_chart
        self.add_item(self.chart_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "⛔ Bảng Market Hub này không phải của bạn! Hãy gõ `/menu` hoặc `/market_hub` để mở bảng riêng.",
                ephemeral=True,
            )
            return False
        return True

    async def toggle_alerts(self, interaction: discord.Interaction):
        self.alerts_enabled = not self.alerts_enabled
        await user_slots_col.update_one(
            {"_id": self.user_id},
            {"$set": {"alerts_enabled": self.alerts_enabled}},
            upsert=True,
        )

        self.toggle_btn.label = "🔔 Alerts: ON" if self.alerts_enabled else "🔕 Alerts: OFF"
        self.toggle_btn.style = discord.ButtonStyle.success if self.alerts_enabled else discord.ButtonStyle.danger

        embed = interaction.message.embeds[0]
        status_text = "🟢 ON" if self.alerts_enabled else "🔴 OFF"
        embed.description = embed.description.replace("🟢 ON", status_text).replace("🔴 OFF", status_text)
        await interaction.response.edit_message(embed=embed, view=self)

    async def my_list(self, interaction: discord.Interaction):
        items = await self.cog.get_user_items(self.user_id)
        max_slots = await self.cog.get_max_slots(self.user_id)

        embed = discord.Embed(
            title="📋 Quản Lý Watchlist",
            description=f"Đã dùng: `{len(items)}/{max_slots}` slots",
            color=discord.Color.blue(),
        )
        if items:
            lines = [f"• **{i['name'].title()}** — `≤ {i['max_price']:,}`" for i in items[:25]]
            embed.add_field(name="Danh sách đang theo dõi", value="\n".join(lines), inline=False)

        view = discord.ui.View(timeout=180)
        add_btn = discord.ui.Button(
            label="➕ Add Item",
            style=discord.ButtonStyle.success,
            disabled=(len(items) >= max_slots),
        )
        add_btn.callback = lambda i: i.response.send_modal(ItemModal(self.cog, "add"))
        view.add_item(add_btn)

        if items:
            view.add_item(ItemSelect(items, "edit", self.cog))
            view.add_item(ItemSelect(items, "delete", self.cog))

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def price_chart(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ChartModal(self.cog))


# ==========================================
# MAIN COG
# ==========================================
class ShopTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Giới hạn kích thước bằng OrderedDict chống rò rỉ RAM trên Render
        self.active_alerts: OrderedDict[str, list[tuple[int, int]]] = OrderedDict()

    async def log_action(self, user_id: int, action: str, details: str):
        await bot_logs_col.insert_one({
            "user_id": str(user_id),
            "action": action,
            "details": details,
            "created_at": datetime.now(timezone.utc),  # Khớp TTL Index 7 ngày trong Database.py
        })

    async def get_user_items(self, user_id: int) -> list[dict]:
        cursor = shop_subscriptions_col.find({"subscribers.user_id": user_id})
        items = []
        async for doc in cursor:
            for sub in doc.get("subscribers", []):
                if sub["user_id"] == user_id:
                    items.append({"name": doc["_id"], "max_price": sub["max_price"]})
                    break
        return items

    async def get_max_slots(self, user_id: int) -> int:
        user_doc = await user_slots_col.find_one({"_id": user_id}, {"max_slots": 1})
        return user_doc.get("max_slots", 10) if user_doc else 10

    async def process_add_or_edit(self, user_id: int, item_name: str, max_price: int, is_edit: bool = False) -> tuple[bool, str]:
        item_key = item_name.lower().strip()
        if not item_key:
            return False, "Tên item không được để trống."

        if not is_edit:
            user_items = await self.get_user_items(user_id)
            if any(i["name"] == item_key for i in user_items):
                return False, "Bạn đang theo dõi item này rồi!"
            max_slots = await self.get_max_slots(user_id)
            if len(user_items) >= max_slots:
                return False, f"Đã đạt giới hạn slot ({len(user_items)}/{max_slots})."

        # Atomic update chống race condition: thử cập nhật giá nếu user đã có trong mảng
        res = await shop_subscriptions_col.update_one(
            {"_id": item_key, "subscribers.user_id": user_id},
            {"$set": {"subscribers.$.max_price": max_price}},
        )
        if res.matched_count == 0:
            await shop_subscriptions_col.update_one(
                {"_id": item_key},
                {"$push": {"subscribers": {"user_id": user_id, "max_price": max_price}}},
                upsert=True,
            )

        await self.log_action(user_id, "ADD/EDIT", f"{item_key} -> {max_price}")
        return True, f"Đang theo dõi **{item_name}** với giá ≤ **{max_price:,}**"

    async def process_remove(self, user_id: int, item_name: str) -> tuple[bool, str]:
        item_key = item_name.lower().strip()
        res = await shop_subscriptions_col.update_one(
            {"_id": item_key},
            {"$pull": {"subscribers": {"user_id": user_id}}},
        )
        if res.modified_count > 0:
            # Xóa document rỗng nếu không còn ai theo dõi
            await shop_subscriptions_col.delete_one({"_id": item_key, "subscribers": {"$size": 0}})
            await self.log_action(user_id, "REMOVE", item_key)
            return True, f"Đã xóa **{item_name}** khỏi Watchlist."
        return False, "Không tìm thấy item trong danh sách của bạn."

    async def process_chart_render(self, interaction: discord.Interaction, item_name: str, days: int):
        item_key = item_name.lower().strip()
        time_boundary = datetime.now(timezone.utc) - timedelta(days=days)

        cursor = market_history_col.find(
            {"timestamp": {"$gte": time_boundary}, "items.item_name": item_key},
            {"timestamp": 1, "items": 1},
        ).sort("timestamp", 1)

        timestamps, prices = [], []
        async for doc in cursor:
            for item in doc.get("items", []):
                if item.get("item_name", "").lower().strip() == item_key:
                    timestamps.append(doc["timestamp"])
                    prices.append(item["cost"])

        if not prices:
            return await interaction.followup.send(
                f"❌ Không có dữ liệu lịch sử giá cho **{item_name}** trong {days} ngày qua.",
                ephemeral=True,
            )

        # Vẽ biểu đồ ở luồng nền để không làm lag/treo Bot
        buf = await asyncio.to_thread(_render_chart_sync, item_name, timestamps, prices)
        await interaction.followup.send(file=discord.File(buf, filename="market_trend.png"), ephemeral=True)

    # --- HELPER CHO CẢ /market_hub VÀ /menu ---
    async def open_market_hub(self, interaction: discord.Interaction, ephemeral: bool = True):
        profile = await players_col.find_one({"user_id": interaction.user.id}, {"ign": 1})
        if not profile or not profile.get("ign") or profile.get("ign") == "Not Set":
            msg = "❌ Bạn chưa liên kết hồ sơ! Hãy dùng `/mygear` trước."
            if interaction.response.is_done():
                return await interaction.followup.send(msg, ephemeral=True)
            return await interaction.response.send_message(msg, ephemeral=True)

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=ephemeral)

        user_doc = await user_slots_col.find_one({"_id": interaction.user.id})
        alerts_enabled = user_doc.get("alerts_enabled", True) if user_doc else True
        max_slots = user_doc.get("max_slots", 10) if user_doc else 10
        tracked_items = await self.get_user_items(interaction.user.id)

        embed = discord.Embed(
            title="🎯 MyK Central Market Hub",
            description=(
                "Bảng điều khiển theo dõi giá chợ cá nhân.\n\n"
                f"**📦 Slots đang dùng:** `{len(tracked_items)}/{max_slots}`\n"
                f"**🔔 Thông báo DM:** `{'🟢 ON' if alerts_enabled else '🔴 OFF'}`"
            ),
            color=discord.Color.gold(),
        )
        if self.bot.user and self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text="MyKBot • Real-time Market Tracker")

        view = CentralHubView(self, interaction.user.id, alerts_enabled)
        await interaction.followup.send(embed=embed, view=view, ephemeral=ephemeral)

    @app_commands.command(name="market_hub", description="Mở trung tâm quản lý Watchlist & Biểu đồ giá chợ")
    async def market_hub(self, interaction: discord.Interaction):
        await self.open_market_hub(interaction, ephemeral=True)

    @app_commands.command(name="addslot", description="[Bot Owner] Cấp hoặc chỉnh sửa số slot theo dõi chợ cho user")
    @app_commands.describe(user="Chọn người dùng", slots="Số slot tối đa (VD: 10)")
    @is_bot_owner_slash()
    async def addslot(self, interaction: discord.Interaction, user: discord.User, slots: int):
        if slots < 0:
            return await interaction.response.send_message("❌ Số slot phải lớn hơn hoặc bằng 0.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await user_slots_col.update_one({"_id": user.id}, {"$set": {"max_slots": slots}}, upsert=True)
        await self.log_action(interaction.user.id, "OWNER_GRANT_SLOT", f"Set slots for {user.id} to {slots}")
        await interaction.followup.send(f"✅ Đã cập nhật giới hạn cho {user.mention} thành **{slots}** slots.", ephemeral=True)

    # --- STREAM FEED LISTENER ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.channel.id != BRIDGE_CHANNEL_ID or not message.attachments:
            return

        for attachment in message.attachments:
            if attachment.filename != "shop_data.json":
                continue

            try:
                file_bytes = await attachment.read()
                shop_data = json.loads(file_bytes.decode("utf-8"))
            except Exception:
                continue

            items_in_shop = shop_data.get("items", [])
            if not items_in_shop:
                continue

            shop_data["timestamp"] = datetime.now(timezone.utc)
            for itm in items_in_shop:
                itm["item_name"] = itm["item_name"].lower().strip()
            await market_history_col.insert_one(shop_data)

            # 1. CẬP NHẬT TRẠNG THÁI ĐÃ BÁN (SOLD OUT)
            if shop_data.get("type") == "sold":
                owner = shop_data.get("owner", "Unknown")
                for itm in items_in_shop:
                    key = f"{owner}_{itm['item_name']}"
                    targets = self.active_alerts.pop(key, None)
                    if not targets:
                        continue
                    for user_id, dm_id in targets:
                        try:
                            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                            dm_channel = user.dm_channel or await user.create_dm()
                            msg = await dm_channel.fetch_message(dm_id)
                            if msg.embeds:
                                em = msg.embeds[0]
                                em.description = "## 🔴 **(SOLD OUT)**"
                                em.color = discord.Color.red()
                                await msg.edit(embed=em)
                        except Exception:
                            pass
                continue

            if shop_data.get("type") != "open":
                continue

            # 2. GỬI CẢNH BÁO ITEM MỚI (ĐÃ TỐI ƯU BATCH QUERY)
            item_names = list({item["item_name"] for item in items_in_shop})
            relevant_docs = await shop_subscriptions_col.find({"_id": {"$in": item_names}}).to_list(length=None)
            active_subs = {doc["_id"]: doc.get("subscribers", []) for doc in relevant_docs}

            # Gom toàn bộ user_id liên quan để kiểm tra alerts_enabled trong 1 query duy nhất
            all_sub_ids = list({sub["user_id"] for subs in active_subs.values() for sub in subs})
            if not all_sub_ids:
                continue

            disabled_docs = await user_slots_col.find(
                {"_id": {"$in": all_sub_ids}, "alerts_enabled": False},
                {"_id": 1},
            ).to_list(length=None)
            disabled_users = {doc["_id"] for doc in disabled_docs}

            shop_name = shop_data.get("shop_name", "Unknown")
            owner = shop_data.get("owner", "Unknown")
            map_name = shop_data.get("map", "Unknown")

            for item in items_in_shop:
                name_lower = item["item_name"]
                cost = item["cost"]
                quantity = item.get("quantity", "Unknown")
                subscribers = active_subs.get(name_lower, [])

                for sub in subscribers:
                    uid = sub["user_id"]
                    if uid in disabled_users or cost > sub["max_price"]:
                        continue

                    embed = discord.Embed(
                        title="🎉 MyK Hunter Alert",
                        description="## 🟢 **AVAILABLE**",
                        color=discord.Color.green(),
                    )
                    embed.add_field(name="📦 Item", value=f"**{name_lower.title()}**", inline=True)
                    embed.add_field(name="💰 Price", value=f"**{cost:,}** ea", inline=True)
                    embed.add_field(name="⚖️ Stock", value=f"`{quantity:,}`" if isinstance(quantity, int) else f"`{quantity}`", inline=True)
                    embed.add_field(name="🏪 Location", value=f"Map: `{map_name}`\nShop: `{shop_name}`\nOwner: `{owner}`", inline=False)
                    embed.add_field(name="⌨️ Quick Copy", value=f"```/shop {shop_name}```", inline=False)

                    try:
                        user = self.bot.get_user(uid) or await self.bot.fetch_user(uid)
                        sent_msg = await user.send(embed=embed)

                        key = f"{owner}_{name_lower}"
                        self.active_alerts.setdefault(key, []).append((uid, sent_msg.id))
                        self.active_alerts.move_to_end(key)
                        while len(self.active_alerts) > MAX_ACTIVE_ALERTS:
                            self.active_alerts.popitem(last=False)
                    except Exception:
                        pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ShopTracker(bot))