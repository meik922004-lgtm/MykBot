import discord
from discord.ext import commands
from discord import app_commands
import json
import io
import os
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
from Database import shop_subscriptions_col, user_slots_col, bot_logs_col, players_col, market_history_col

# ==========================================
# UI COMPONENTS (AUTOCOMPLETE & MODALS)
# ==========================================

class ItemModal(discord.ui.Modal):
    def __init__(self, cog, action: str, item_name: str = None):
        super().__init__(title="Track New Item" if action == "add" else f"Edit: {item_name}")
        self.cog = cog
        self.action = action
        self.target_item = item_name

        if self.action == "add":
            self.item_name_input = discord.ui.TextInput(label="Item Name", placeholder="Enter exact name...", required=True)
            self.add_item(self.item_name_input)

        self.price_input = discord.ui.TextInput(label="Max Alert Price", placeholder="e.g. 5000000", required=True)
        self.add_item(self.price_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            max_price = int(self.price_input.value.strip().replace(',', ''))
        except ValueError:
            return await interaction.response.send_message("❌ Price must be a valid number!", ephemeral=True)

        item_name = self.target_item if self.action == "edit" else self.item_name_input.value.strip()
        success, message = await self.cog.process_add_or_edit(interaction.user.id, item_name, max_price, is_edit=(self.action=="edit"))
        await interaction.response.send_message(f"{'✅' if success else '⚠️'} {message}", ephemeral=True)


class ItemSelect(discord.ui.Select):
    def __init__(self, items, action: str, cog):
        self.action = action
        self.cog = cog
        options = [
            discord.SelectOption(label=i["name"].title(), description=f"Alert: {i['max_price']:,} ea", value=i["name"])
            for i in items[:25]
        ]
        super().__init__(placeholder=f"Select item to {action}...", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        if self.action == "edit":
            await interaction.response.send_modal(ItemModal(self.cog, "edit", selected))
        elif self.action == "delete":
            success, message = await self.cog.process_remove(interaction.user.id, selected)
            await interaction.response.send_message(f"✅ {message}", ephemeral=True)


class HubDurationSelect(discord.ui.Select):
    """Dropdown phân tích thị trường được nhúng trực tiếp vào Menu chính"""
    def __init__(self, cog, row: int):
        self.cog = cog
        options = [
            discord.SelectOption(label="Analyze: Last 24 Hours", value="1"),
            discord.SelectOption(label="Analyze: Last 7 Days", value="7"),
            discord.SelectOption(label="Analyze: Last 14 Days", value="14"),
            discord.SelectOption(label="Analyze: Last 30 Days", value="30"),
        ]
        super().__init__(placeholder="📊 Select Timeframe Window to Analyze Market...", options=options, row=row)

    async def callback(self, interaction: discord.Interaction):
        days = int(self.values[0])
        await interaction.response.defer(ephemeral=True)
        embed = await self.cog.generate_market_analysis_embed(days)
        await interaction.followup.send(embed=embed, ephemeral=True)


class ChartModal(discord.ui.Modal):
    """Modal yêu cầu nhập thông tin vẽ chart khi nhấn nút"""
    def __init__(self, cog):
        super().__init__(title="Render Price Chart")
        self.cog = cog
        self.item_name_input = discord.ui.TextInput(label="Item Name", placeholder="Enter exact item name...", required=True)
        self.days_input = discord.ui.TextInput(label="Days to Look Back", placeholder="e.g. 7", default="7", required=False)
        self.add_item(self.item_name_input)
        self.add_item(self.days_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        item_name = self.item_name_input.value.strip()
        try:
            days = int(self.days_input.value.strip()) if self.days_input.value.strip() else 7
        except ValueError:
            return await interaction.followup.send("❌ Days must be a valid number!", ephemeral=True)
        
        # Gọi luồng xử lý vẽ đồ thị từ Cog Engine
        await self.cog.process_chart_render(interaction, item_name, days)

# ==========================================
# CENTRALIZED VIEW HUB
# ==========================================

class CentralHubView(discord.ui.View):
    def __init__(self, cog, user_id):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        
        # Nhúng trực tiếp Dropdown Phân tích vào dòng 0
        self.add_item(HubDurationSelect(self.cog, row=0))

    @discord.ui.button(label="📋 My Watchlist", style=discord.ButtonStyle.primary, row=1)
    async def my_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        items = await self.cog.get_user_items(self.user_id)
        max_slots = await self.cog.get_max_slots(self.user_id)
        
        embed = discord.Embed(title="📋 Watchlist Management", description=f"Capacity: `{len(items)}/{max_slots}` slots", color=discord.Color.blue())
        view = discord.ui.View()
        
        add_btn = discord.ui.Button(label="➕ Add Item", style=discord.ButtonStyle.success, disabled=(len(items) >= max_slots))
        add_btn.callback = lambda i: i.response.send_modal(ItemModal(self.cog, "add"))
        view.add_item(add_btn)
        
        if items:
            view.add_item(ItemSelect(items, "edit", self.cog))
            view.add_item(ItemSelect(items, "delete", self.cog))
            
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="💰 Profitable Flips", style=discord.ButtonStyle.success, row=1)
    async def profitable_flips(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embed = await self.cog.calculate_flip_opportunities()
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="📈 Price Chart", style=discord.ButtonStyle.secondary, row=1)
    async def price_chart(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Mở Modal nhập tên item cần vẽ đồ thị
        await interaction.response.send_modal(ChartModal(self.cog))

# ==========================================
# MAIN COG ENGINE
# ==========================================

class ShopTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        print("⏳ [Cơ sở dữ liệu]: Đang thiết lập cấu hình tự động dọn dẹp dữ liệu...")
        try:
            await market_history_col.create_index("timestamp", expireAfterSeconds=2592000)
            print("✅ [Cơ sở dữ liệu]: Đã bật TTL Index! Dữ liệu cũ quá 30 ngày sẽ tự động bị tiêu hủy.")
        except Exception as e:
            print(f"❌ [Cơ sở dữ liệu]: Không thể thiết lập TTL Index: {e}")
            
    async def log_action(self, user_id: int, action: str, details: str):
        await bot_logs_col.insert_one({
            "user_id": str(user_id), "action": action, "details": details, "timestamp": datetime.utcnow()
        })

    async def get_user_items(self, user_id):
        cursor = shop_subscriptions_col.find({"subscribers.user_id": user_id})
        items = []
        async for doc in cursor:
            for sub in doc.get("subscribers", []):
                if sub["user_id"] == user_id:
                    items.append({"name": doc["_id"], "max_price": sub["max_price"]})
                    break
        return items

    async def get_max_slots(self, user_id):
        user_doc = await user_slots_col.find_one({"_id": user_id})
        return user_doc.get("max_slots", 0) if user_doc else 3

    async def process_add_or_edit(self, user_id, item_name, max_price, is_edit=False):
        item_key = item_name.lower().strip()
        user_items = await self.get_user_items(user_id)
        
        if not is_edit:
            if any(i["name"] == item_key for i in user_items):
                return False, "You are already tracking this item!"
            max_slots = await self.get_max_slots(user_id)
            if len(user_items) >= max_slots:
                return False, f"Reached slot limit ({len(user_items)}/{max_slots})."

        item_doc = await shop_subscriptions_col.find_one({"_id": item_key})
        if item_doc:
            subscribers = item_doc.get("subscribers", [])
            exists = False
            for sub in subscribers:
                if sub["user_id"] == user_id:
                    sub["max_price"] = max_price
                    exists = True
                    break
            if not exists:
                subscribers.append({"user_id": user_id, "max_price": max_price})
            await shop_subscriptions_col.update_one({"_id": item_key}, {"$set": {"subscribers": subscribers}})
        else:
            await shop_subscriptions_col.insert_one({"_id": item_key, "subscribers": [{"user_id": user_id, "max_price": max_price}]})
            
        await self.log_action(user_id, "ADD/EDIT", f"{item_key} -> {max_price}")
        return True, f"Tracking **{item_name}** at price ≤ **{max_price:,}**"

    async def process_remove(self, user_id, item_name):
        item_key = item_name.lower().strip()
        item_doc = await shop_subscriptions_col.find_one({"_id": item_key})
        if item_doc:
            subs = [s for s in item_doc["subscribers"] if s["user_id"] != user_id]
            if not subs:
                await shop_subscriptions_col.delete_one({"_id": item_key})
            else:
                await shop_subscriptions_col.update_one({"_id": item_key}, {"$set": {"subscribers": subs}})
            return True, f"Removed **{item_name}**."
        return False, "Item not found."

    # --- MARKET INTELLIGENCE ENGINE (AGGREGATION) ---
    async def generate_market_analysis_embed(self, days: int):
        time_boundary = datetime.utcnow() - timedelta(days=days)
        pipeline = [
            {"$match": {"timestamp": {"$gte": time_boundary}, "type": "sold"}},
            {"$unwind": "$items"},
            {"$group": {
                "_id": "$items.item_name",
                "total_sold": {"$sum": "$items.quantity"},
                "min_price": {"$min": "$items.cost"},
                "max_price": {"$max": "$items.cost"},
                "avg_price": {"$avg": "$items.cost"}
            }},
            {"$sort": {"total_sold": -1}},
            {"$limit": 10}
        ]
        
        embed = discord.Embed(title=f"🔥 Top 10 Best Sellers ({days} Days Window)", color=discord.Color.gold())
        async for doc in market_history_col.aggregate(pipeline):
            metrics = (
                f"• Vol Sold: `{doc['total_sold']:,}` units\n"
                f"• Min-Max: `{doc['min_price']:,}` - `{doc['max_price']:,}`\n"
                f"• Avg Price: **{int(doc['avg_price']):,}** ea"
            )
            embed.add_field(name=f"📦 {doc['_id'].title()}", value=metrics, inline=False)
        return embed

    async def calculate_flip_opportunities(self):
        time_boundary = datetime.utcnow() - timedelta(days=7)
        sold_stats = {}
        pipeline_sold = [
            {"$match": {"timestamp": {"$gte": time_boundary}, "type": "sold"}},
            {"$unwind": "$items"},
            {"$group": {"_id": "$items.item_name", "avg_sold": {"$avg": "$items.cost"}, "vol": {"$sum": "$items.quantity"}}}
        ]
        async for doc in market_history_col.aggregate(pipeline_sold):
            if doc["vol"] > 5:
                sold_stats[doc["_id"]] = doc["avg_sold"]

        pipeline_open = [
            {"$match": {"timestamp": {"$gte": datetime.utcnow() - timedelta(hours=12)}, "type": "open"}},
            {"$unwind": "$items"},
            {"$sort": {"items.cost": 1}}
        ]
        
        embed = discord.Embed(title="💰 Algorithmic Resell Signals (Flipping)", description="Suggested purchase targets with high margin yield", color=discord.Color.green())
        count = 0
        
        async for doc in market_history_col.aggregate(pipeline_open):
            item_name = doc["items"]["item_name"]
            current_cost = doc["items"]["cost"]
            
            if item_name in sold_stats:
                avg_market_value = sold_stats[item_name]
                if current_cost < (avg_market_value * 0.75):
                    profit_per_item = int(avg_market_value - current_cost)
                    details = (
                        f"🏪 Shop: `{doc['shop_name']}` | Owner: `{doc['owner']}`\n"
                        f"📍 Map: **{doc['map']}**\n"
                        f"📉 Current Listing: **{current_cost:,}** ea\n"
                        f"📈 Historical Avg Value: `{int(avg_market_value):,}` ea\n"
                        f"🔥 **Estimated Margin Profit: +{profit_per_item:,}** per unit"
                    )
                    embed.add_field(name=f"💎 Deal Target: {item_name.title()}", value=details, inline=False)
                    count += 1
                    if count >= 5: break
                    
        if count == 0:
            embed.description = "No anomalies detected. Market prices are currently balanced stabily."
        return embed

    async def process_chart_render(self, interaction: discord.Interaction, item_name: str, days: int):
        """Hàm xử lý logic vẽ đồ thị Matplotlib"""
        time_boundary = datetime.utcnow() - timedelta(days=days)
        cursor = market_history_col.find({
            "timestamp": {"$gte": time_boundary},
            "items.item_name": item_name.lower().strip()
        }).sort("timestamp", 1)
        
        timestamps = []
        prices = []
        
        async for doc in cursor:
            for item in doc["items"]:
                if item["item_name"].lower().strip() == item_name.lower().strip():
                    timestamps.append(doc["timestamp"])
                    prices.append(item["cost"])
                    
        if not prices:
            return await interaction.followup.send(f"❌ No trend history recorded for **{item_name}** in the requested window.", ephemeral=True)

        plt.figure(figsize=(10, 5))
        plt.style.use('dark_background')
        
        plt.plot(timestamps, prices, label='Spot Price Exchange', color='#1f77b4', marker='o', markersize=4, linewidth=1.5)
        
        if len(prices) > 3:
            rolling_avg = np.convolve(prices, np.ones(3)/3, mode='valid')
            plt.plot(timestamps[2:], rolling_avg, label='Smooth Trend (MA-3)', color='#ff7f0e', linestyle='--')

        plt.title(f"Fluctuation Price Analytics: {item_name.title()}", fontsize=14, color='white', pad=15)
        plt.xlabel("Timeline UTC", color='gray')
        plt.ylabel("Price (Tera/M)", color='gray')
        plt.grid(True, linestyle=':', alpha=0.6)
        plt.legend(loc='upper left')
        plt.gcf().autofmt_xdate()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=150)
        buf.seek(0)
        plt.close()

        file = discord.File(buf, filename="market_trend.png")
        await interaction.followup.send(file=file, ephemeral=True)

    # --- SINGLE CENTRAL HUB SLASH COMMAND ---
    @app_commands.command(name="market_hub", description="Open the central executive Market Analysis Dashboard.")
    async def market_hub(self, interaction: discord.Interaction):
        profile = await players_col.find_one({"user_id": interaction.user.id}, {"ign": 1})
        if not profile or not profile.get("ign") or profile.get("ign") == "Not Set":
            return await interaction.response.send_message("❌ Profile unlinked. Set via `/mygear` first.", ephemeral=True)

        await interaction.response.defer(ephemeral=False)
        
        embed = discord.Embed(
            title="📊 MyK Advanced Market Intelligence Hub",
            description="Welcome to the center trading control panel. Access deep market data analytics via buttons/dropdown below.",
            color=discord.Color.dark_theme()
        )
        embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        embed.set_footer(text="MyK • automatic supporter")
        
        # Gọi giao diện Hub tổng hợp mới
        view = CentralHubView(self, interaction.user.id)
        await interaction.followup.send(embed=embed, view=view)

    # ==========================================
    # BOT OWNER ONLY COMMAND
    # ==========================================

    @app_commands.command(name="addslot", description="[Bot Owner Only] Cấp hoặc điều chỉnh số lượng slot theo dõi tối đa của người dùng.")
    @app_commands.describe(user="Chọn người dùng cần chỉnh sửa slot", slots="Tổng số lượng slot tối đa muốn cấp (Ví dụ: 10)")
    async def addslot(self, interaction: discord.Interaction, user: discord.User, slots: int):
        """Lệnh ẩn chỉ có Bot Owner (Nhà phát triển) mới có quyền thực thi"""
        # Kiểm tra xem người dùng bấm lệnh có phải là Owner của Bot không
        is_bot_owner = await self.bot.is_owner(interaction.user)
        
        if not is_bot_owner:
            return await interaction.response.send_message(
                "❌ Lệnh này được bảo mật nghiêm ngặt và chỉ dành riêng cho **Bot Owner**!", 
                ephemeral=True
            )

        # Nếu đúng là Bot Owner, tiến hành xử lý dữ liệu
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Cập nhật số lượng slot vào MongoDB (Sử dụng ID dạng số của user làm mốc định danh gốc)
            await user_slots_col.update_one(
                {"_id": user.id},
                {"$set": {"max_slots": slots}},
                upsert=True  # Nếu user chưa từng có dữ liệu slot, tự động tạo bản ghi mới
            )
            
            # Ghi log hệ thống để theo dõi
            await self.log_action(
                interaction.user.id, 
                "OWNER_GRANT_SLOT", 
                f"Set slots for {user.id} ({user.name}) to {slots}"
            )
            
            await interaction.followup.send(
                f"✅ Thành công! Đã cấu hình lại giới hạn của người dùng {user.mention} thành **{slots}** slots.", 
                ephemeral=True
            )
            
        except Exception as e:
            await interaction.followup.send(
                f"❌ Thao tác thất bại. Lỗi cơ sở dữ liệu: {e}", 
                ephemeral=True
            )
    # --- STREAM FEED LISTENER ---
    @commands.Cog.listener()
    async def on_message(self, message):
        BRIDGE_CHANNEL_ID = 1515038293643759728  

        if message.channel.id == BRIDGE_CHANNEL_ID and message.attachments:
            for attachment in message.attachments:
                if attachment.filename == "shop_data.json":
                    file_bytes = await attachment.read()
                    try:
                        shop_data = json.loads(file_bytes.decode('utf-8'))
                    except Exception:
                        continue
                    
                    items_in_shop = shop_data.get("items", [])
                    if not items_in_shop: continue
                    
                    shop_data["timestamp"] = datetime.utcnow()
                    for itm in shop_data["items"]:
                        itm["item_name"] = itm["item_name"].lower().strip()
                    await market_history_col.insert_one(shop_data)

                    if shop_data.get("type") != "open":
                        continue

                    item_names = [item["item_name"] for item in items_in_shop]
                    relevant_docs = await shop_subscriptions_col.find({"_id": {"$in": item_names}}).to_list(length=None)
                    active_subs = {doc["_id"]: doc.get("subscribers", []) for doc in relevant_docs}
                    
                    shop_name = shop_data.get("shop_name", "Unknown")
                    owner = shop_data.get("owner", "Unknown")
                    map_name = shop_data.get("map", "Unknown")
                    
                    for item in items_in_shop:
                        name_lower = item["item_name"]
                        cost = item["cost"]
                        quantity = item.get("quantity", "Unknown")
                        
                        subscribers = active_subs.get(name_lower)
                        if subscribers:
                            for sub in subscribers:
                                if cost <= sub["max_price"]:
                                    embed = discord.Embed(title="🎉 MyK Hunter Alert", description="MyK found a cheap item for you!", color=discord.Color.green())
                                    embed.add_field(name="📦 Item ", value=f"**{item['item_name'].title()}**", inline=True)
                                    embed.add_field(name="💰 Price", value=f"**{cost:,}** ea", inline=True)
                                    embed.add_field(name="⚖️ Stock", value=f"`{quantity:,}`" if isinstance(quantity, int) else f"`{quantity}`", inline=True)
                                    embed.add_field(name="🏪 Location", value=f"Map: `{map_name}`\nShop: `{shop_name}`\nOwner: `{owner}`", inline=False)
                                    embed.add_field(name="⌨️ Quick Copy Link", value=f"```/shop {shop_name}```", inline=False)
                                    
                                    try:
                                        user = self.bot.get_user(sub['user_id']) or await self.bot.fetch_user(sub['user_id'])
                                        await user.send(embed=embed)
                                    except Exception:
                                        pass

async def setup(bot):
    await bot.add_cog(ShopTracker(bot))