import discord
from discord.ext import commands
from discord import app_commands
import json
import io
import os
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
from database import shop_subscriptions_col, user_slots_col, bot_logs_col, players_col, market_history_col

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
        
        await self.cog.process_chart_render(interaction, item_name, days)


# ==========================================
# CENTRALIZED VIEW HUB
# ==========================================

class CentralHubView(discord.ui.View):
    def __init__(self, cog, user_id, alerts_enabled):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.alerts_enabled = alerts_enabled

        # Button 1: Toggle Alerts
        self.toggle_btn = discord.ui.Button(
            label="🔔 Alerts: ON" if alerts_enabled else "🔕 Alerts: OFF",
            style=discord.ButtonStyle.success if alerts_enabled else discord.ButtonStyle.danger,
            row=0
        )
        self.toggle_btn.callback = self.toggle_alerts
        self.add_item(self.toggle_btn)

        # Button 2: Watchlist
        self.watchlist_btn = discord.ui.Button(label="📋 My Watchlist", style=discord.ButtonStyle.primary, row=0)
        self.watchlist_btn.callback = self.my_list
        self.add_item(self.watchlist_btn)

        # Button 3: Chart
        self.chart_btn = discord.ui.Button(label="📈 Price Chart", style=discord.ButtonStyle.secondary, row=0)
        self.chart_btn.callback = self.price_chart
        self.add_item(self.chart_btn)

    async def toggle_alerts(self, interaction: discord.Interaction):
        self.alerts_enabled = not self.alerts_enabled
        
        # Cập nhật DB
        await user_slots_col.update_one(
            {"_id": self.user_id}, 
            {"$set": {"alerts_enabled": self.alerts_enabled}}, 
            upsert=True
        )

        # Cập nhật UI của nút bấm
        self.toggle_btn.label = "🔔 Alerts: ON" if self.alerts_enabled else "🔕 Alerts: OFF"
        self.toggle_btn.style = discord.ButtonStyle.success if self.alerts_enabled else discord.ButtonStyle.danger

        # Cập nhật lại Hub Message
        embed = interaction.message.embeds[0]
        status_text = '🟢 ON' if self.alerts_enabled else '🔴 OFF'
        embed.description = embed.description.replace('🟢 ON', status_text).replace('🔴 OFF', status_text)
        
        await interaction.response.edit_message(embed=embed, view=self)

    async def my_list(self, interaction: discord.Interaction):
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

    async def price_chart(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ChartModal(self.cog))

# ==========================================
# MAIN COG ENGINE
# ==========================================

class ShopTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Dictionary lưu thông tin message cảnh báo đã gửi để update trạng thái
        # Format: {"owner_itemname": [(user_id, message_id)]}
        self.active_alerts = {}

    async def cog_load(self):
        print("⏳ [Database]: Configuring automatic data cleanup...")
        try:
            await market_history_col.create_index("timestamp", expireAfterSeconds=2592000)
            print("✅ [Cơ sở dữ liệu]: TTL Index enabled! Data older than 30 days will be automatically deleted..")
        except Exception as e:
            print(f"❌ [Database]: Unable to set up TTL Index: {e}")
            
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
        return user_doc.get("max_slots", 10) if user_doc else 10

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

    async def process_chart_render(self, interaction: discord.Interaction, item_name: str, days: int):
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
    @app_commands.command(name="market_hub", description="Open the Market monitoring and management center..")
    async def market_hub(self, interaction: discord.Interaction):
        profile = await players_col.find_one({"user_id": interaction.user.id}, {"ign": 1})
        if not profile or not profile.get("ign") or profile.get("ign") == "Not Set":
            return await interaction.response.send_message("❌ Profile unlinked. Set via `/mygear` first.", ephemeral=True)

        # CẬP NHẬT: Đã đổi default slots thành 10
        user_doc = await user_slots_col.find_one({"_id": interaction.user.id})
        alerts_enabled = user_doc.get("alerts_enabled", True) if user_doc else True
        max_slots = user_doc.get("max_slots", 10) if user_doc else 10 
        tracked_items = await self.get_user_items(interaction.user.id)

        await interaction.response.defer(ephemeral=False)
        
        embed = discord.Embed(
            title="🎯 MyK Central Market Hub",
            description=(
                "Your personal market tracking dashboard. "
                "Manage your watchlist and adjust real-time price alerts..\n\n"
                f"**📦 Slot for track:** `{len(tracked_items)}/{max_slots}`\n"
                f"**🔔 Receive notifications:** `{'🟢 ON' if alerts_enabled else '🔴 OFF'}`"
            ),
            color=discord.Color.dark_theme()
        )
        embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        embed.set_footer(text="MyK • Automatic Supporter")
        
        view = CentralHubView(self, interaction.user.id, alerts_enabled)
        await interaction.followup.send(embed=embed, view=view)


    # ==========================================
    # BOT OWNER ONLY COMMANDS
    # ==========================================
    

    @app_commands.command(name="addslot", description="[Bot Owner Only] Grant or adjust the user's maximum number of tracking slots.")
    @app_commands.describe(user="Select the user whose slot needs editing.", slots="The maximum number of slots you wish to allocate (e.g., 10)")
    async def addslot(self, interaction: discord.Interaction, user: discord.User, slots: int):
        is_bot_owner = await self.bot.is_owner(interaction.user)
        
        if not is_bot_owner:
            return await interaction.response.send_message(
                "❌ This command is strictly secured and reserved exclusively for the **Bot Owner**.*!", 
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        
        try:
            await user_slots_col.update_one(
                {"_id": user.id},
                {"$set": {"max_slots": slots}},
                upsert=True
            )
            
            await self.log_action(interaction.user.id, "OWNER_GRANT_SLOT", f"Set slots for {user.id} ({user.name}) to {slots}")
            await interaction.followup.send(f"✅ Success! User limits have been reconfigured. {user.mention} thành **{slots}** slots.", ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Operation failed. Database error.: {e}", ephemeral=True)


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

                    # --- UPDATE TRẠNG THÁI NẾU ITEM ĐÃ BÁN ---
                    if shop_data.get("type") == "sold":
                        owner = shop_data.get("owner", "Unknown")
                        for itm in items_in_shop:
                            key = f"{owner}_{itm['item_name']}"
                            if key in self.active_alerts:
                                for user_id, dm_id in self.active_alerts[key]:
                                    try:
                                        user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                                        if not user.dm_channel:
                                            await user.create_dm()
                                            
                                        msg = await user.dm_channel.fetch_message(dm_id)
                                        if msg.embeds:
                                            em = msg.embeds[0]
                                            # Cập nhật Highlight trạng thái đã bán
                                            em.description = "## 🔴 **(SOLD OUT)**"
                                            em.color = discord.Color.red()
                                            await msg.edit(embed=em)
                                    except Exception:
                                        pass
                                # Xóa khỏi cache sau khi đã báo hết hàng
                                self.active_alerts.pop(key, None)
                        continue
                    
                    if shop_data.get("type") != "open":
                        continue

                    # --- GỬI THÔNG BÁO ITEM MỚI ---
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
                                    
                                    # Kiểm tra xem người dùng có tắt thông báo hay không
                                    user_doc = await user_slots_col.find_one({"_id": sub['user_id']})
                                    if user_doc and not user_doc.get("alerts_enabled", True):
                                        continue
                                        
                                    embed = discord.Embed(
                                        title="🎉 MyK Hunter Alert", 
                                        description="## 🟢 **AVAILABLE**", 
                                        color=discord.Color.green()
                                    )
                                    embed.add_field(name="📦 Item ", value=f"**{item['item_name'].title()}**", inline=True)
                                    embed.add_field(name="💰 Price", value=f"**{cost:,}** ea", inline=True)
                                    embed.add_field(name="⚖️ Stock", value=f"`{quantity:,}`" if isinstance(quantity, int) else f"`{quantity}`", inline=True)
                                    embed.add_field(name="🏪 Location", value=f"Map: `{map_name}`\nShop: `{shop_name}`\nOwner: `{owner}`", inline=False)
                                    embed.add_field(name="⌨️ Quick Copy Link", value=f"```/shop {shop_name}```", inline=False)
                                    
                                    try:
                                        user = self.bot.get_user(sub['user_id']) or await self.bot.fetch_user(sub['user_id'])
                                        sent_msg = await user.send(embed=embed)
                                        
                                        # Lưu tin nhắn vào Cache để update trạng thái sau này
                                        key = f"{owner}_{name_lower}"
                                        if key not in self.active_alerts:
                                            self.active_alerts[key] = []
                                        self.active_alerts[key].append((sub['user_id'], sent_msg.id))
                                        
                                    except Exception:
                                        pass

async def setup(bot):
    await bot.add_cog(ShopTracker(bot))