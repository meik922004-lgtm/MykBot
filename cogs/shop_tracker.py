import discord
from discord.ext import commands
from discord import app_commands
import json
from pymongo import MongoClient 
import os
from datetime import datetime

# ==========================================
# UI CLASSES (MODAL & VIEW) FOR /MYLIST
# ==========================================
class ItemModal(discord.ui.Modal):
    def __init__(self, cog, action: str, item_name: str = None):
        title = "Add New Item" if action == "add" else f"Edit Price: {item_name}"
        super().__init__(title=title[:45])  
        self.cog = cog
        self.action = action
        self.target_item = item_name

        if self.action == "add":
            self.item_name_input = discord.ui.TextInput(
                label="Exact Item Name",
                placeholder="e.g., Bravery Energy",
                required=True,
                max_length=100
            )
            self.add_item(self.item_name_input)

        self.price_input = discord.ui.TextInput(
            label="Max Price (Numbers only)",
            placeholder="e.g., 1000000",
            required=True,
            min_length=1,
            max_length=15
        )
        self.add_item(self.price_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            max_price = int(self.price_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Price must be a valid number!", ephemeral=True)
            return

        item_name = self.target_item if self.action == "edit" else self.item_name_input.value
        
        success, message = await self.cog.process_add_or_edit(
            interaction.user.id, 
            item_name, 
            max_price, 
            is_edit=(self.action=="edit")
        )
        
        if success:
            await interaction.response.send_message(f"✅ {message}", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ {message}", ephemeral=True)

class ActionSelect(discord.ui.Select):
    def __init__(self, items, action: str, cog):
        self.action = action
        self.cog = cog
        options = [
            discord.SelectOption(
                label=i["name"].title(), 
                description=f"Tracked price: {i['max_price']:,} ea", 
                value=i["name"]
            ) for i in items
        ]
        placeholder = "Which item to edit?" if action == "edit" else "Which item to remove?"
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_item = self.values[0]
        if self.action == "edit":
            await interaction.response.send_modal(ItemModal(self.cog, "edit", selected_item))
        elif self.action == "delete":
            success, message = self.cog.process_remove(interaction.user.id, selected_item)
            await interaction.response.send_message(f"✅ {message}", ephemeral=True)

class MyListView(discord.ui.View):
    def __init__(self, cog, user_id):
        super().__init__(timeout=180) 
        self.cog = cog
        self.user_id = user_id

        items = self.cog.get_user_items(user_id)
        current_slots = len(items)
        max_slots = self.cog.get_max_slots(user_id)

        add_btn = discord.ui.Button(
            label="➕ Add Item", 
            style=discord.ButtonStyle.success, 
            disabled=(current_slots >= max_slots)
        )
        async def add_callback(interaction):
            await interaction.response.send_modal(ItemModal(self.cog, "add"))
        add_btn.callback = add_callback
        self.add_item(add_btn)

        if items:
            self.add_item(ActionSelect(items, "edit", self.cog))
            self.add_item(ActionSelect(items, "delete", self.cog))

# ==========================================
# MAIN CLASS: SHOP TRACKER COG
# ==========================================
class ShopTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        mongo_uri = os.getenv("MONGO_URI")
        self.cluster = MongoClient(mongo_uri, maxPoolSize=10)
        self.db = self.cluster["database0"]
        self.collection = self.db["shop_subscriptions"]
        self.users_coll = self.db["user_slots"] 
        self.logs_coll = self.db["bot_logs"] 
        self.players_coll = self.db["players"]

    def log_action(self, user_id: int, action: str, details: str):
        log_entry = {
            "user_id": str(user_id),
            "action": action,
            "details": details,
            "timestamp": datetime.utcnow()
        }
        self.logs_coll.insert_one(log_entry)

    def get_user_items(self, user_id):
        cursor = self.collection.find({"subscribers.user_id": user_id})
        items = []
        for doc in cursor:
            for sub in doc.get("subscribers", []):
                if sub["user_id"] == user_id:
                    items.append({"name": doc["_id"], "max_price": sub["max_price"]})
                    break
        return items

    def get_max_slots(self, user_id):
        user_doc = self.users_coll.find_one({"_id": user_id})
        return user_doc.get("max_slots", 0) if user_doc else 0 

    async def process_add_or_edit(self, user_id, item_name, max_price, is_edit=False):
        item_key = item_name.lower().strip()
        user_items = self.get_user_items(user_id)
        
        if not is_edit:
            if any(i["name"] == item_key for i in user_items):
                return False, "You are already tracking this item! Use the 'Edit Price' option if you want to change it."
            
            max_slots = self.get_max_slots(user_id)
            if max_slots == 0:
                return False, "🚫 Access Denied! You don't have any slots. Please contact the Bot Owner to get access."
                
            if len(user_items) >= max_slots:
                return False, f"⚠️ You have reached your slot limit ({len(user_items)}/{max_slots}). Please ask the Bot Owner for an expansion!"

        item_doc = self.collection.find_one({"_id": item_key})
        
        if item_doc:
            subscribers = item_doc.get("subscribers", [])
            user_exists = False
            for sub in subscribers:
                if sub["user_id"] == user_id:
                    sub["max_price"] = max_price
                    user_exists = True
                    break
            if not user_exists:
                subscribers.append({"user_id": user_id, "max_price": max_price})
            self.collection.update_one({"_id": item_key}, {"$set": {"subscribers": subscribers}})
        else:
            self.collection.insert_one({
                "_id": item_key, 
                "subscribers": [{"user_id": user_id, "max_price": max_price}]
            })
        
        log_msg = f"Registered/Changed item '{item_key}' price to ≤ {max_price:,}"
        self.log_action(user_id, "ADD/EDIT ITEM", log_msg)

        action_text = "Updated new price for" if is_edit else "Added"
        return True, f"{action_text} **{item_name}** with max price <= **{max_price:,}**."

    def process_remove(self, user_id, item_name):
        item_key = item_name.lower().strip()
        item_doc = self.collection.find_one({"_id": item_key})
        
        if item_doc:
            subscribers = item_doc.get("subscribers", [])
            new_subscribers = [sub for sub in subscribers if sub["user_id"] != user_id]
            
            if len(new_subscribers) == len(subscribers):
                return False, "You are not tracking this item."

            if not new_subscribers:
                self.collection.delete_one({"_id": item_key})
            else:
                self.collection.update_one({"_id": item_key}, {"$set": {"subscribers": new_subscribers}})
            
            self.log_action(user_id, "REMOVE ITEM", f"Deleted '{item_key}' from the tracking list")
            return True, f"Unsubscribed from: **{item_name}**."
        return False, "This item is not registered in the system."

    async def has_profile(self, interaction: discord.Interaction) -> bool:
        profile = self.players_coll.find_one({"user_id": interaction.user.id}, {"ign": 1})
        if not profile or not profile.get("ign") or profile.get("ign") == "Not Set":
            await interaction.response.send_message("❌ **Access Denied!** You must set up your profile via `/mygear` first.", ephemeral=True)
            return False
        return True

    @app_commands.command(name="additem", description="Sign up to receive notifications when an item's price is good.")
    async def additem(self, interaction: discord.Interaction, item_name: str, max_price: int):
        if not await self.has_profile(interaction): return
        await interaction.response.defer(ephemeral=True) 
        success, msg = await self.process_add_or_edit(interaction.user.id, item_name, max_price, is_edit=False)
        await interaction.followup.send(msg)

    @app_commands.command(name="removeitem", description="Cancel item tracking.")
    async def removeitem(self, interaction: discord.Interaction, item_name: str):
        if not await self.has_profile(interaction): return
        await interaction.response.defer(ephemeral=True)
        success, msg = self.process_remove(interaction.user.id, item_name)
        await interaction.followup.send(msg)

    @app_commands.command(name="mylist", description="View and manage your tracked items list.")
    async def mylist(self, interaction: discord.Interaction):
        if not await self.has_profile(interaction): return
        user_id = interaction.user.id
        items = self.get_user_items(user_id)
        max_slots = self.get_max_slots(user_id)
        current_slots = len(items)

        embed = discord.Embed(
            title="📋 Your Tracked List", 
            description=f"**Capacity:** `{current_slots}/{max_slots} slots`",
            color=discord.Color.blue()
        )

        if items:
            for item in items:
                embed.add_field(
                    name=f"📦 {item['name'].title()}", 
                    value=f"Alert when price ≤ **{item['max_price']:,}**", 
                    inline=False
                )
        else:
            embed.add_field(name="Empty", value="You are not tracking any items.", inline=False)

        view = MyListView(self, user_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="addslot", description="[Owner] Change the slot limit for a user.")
    async def addslot(self, interaction: discord.Interaction, user: discord.Member, slots: int):
        is_owner = await self.bot.is_owner(interaction.user)
        if not is_owner:
            await interaction.response.send_message("❌ Only the Bot Owner can use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        self.users_coll.update_one({"_id": user.id}, {"$set": {"max_slots": slots}}, upsert=True)
        await interaction.followup.send(f"✅ Granted **{slots} max slots** to **{user.display_name}**.")

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
                    if not items_in_shop:
                        continue
                        
                    item_names = [item["item_name"].lower() for item in items_in_shop]
                    relevant_docs = list(self.collection.find({"_id": {"$in": item_names}}))
                    active_subs = {doc["_id"]: doc.get("subscribers", []) for doc in relevant_docs}
                    
                    shop_name = shop_data.get("shop_name", "Unknown")
                    owner = shop_data.get("owner", "Unknown")
                    map_name = shop_data.get("map", "Unknown")
                    
                    alerts = []
                    for item in items_in_shop:
                        name_lower = item["item_name"].lower()
                        cost = item["cost"]
                        quantity = item.get("quantity", "Unknown") 
                        
                        subscribers = active_subs.get(name_lower)
                        if subscribers:
                            for sub in subscribers:
                                if cost <= sub["max_price"]:
                                    embed = discord.Embed(
                                        title="🎉 MyK Tracker",
                                        description="MyK found a cheap item for you!",
                                        color=discord.Color.green() 
                                    )
                                    embed.add_field(name="📦 Item", value=f"**{item['item_name']}**", inline=True)
                                    embed.add_field(name="💰 Price (ea)", value=f"**{cost:,}**", inline=True)
                                    qty_str = f"**{quantity:,}**" if isinstance(quantity, int) else f"**{quantity}**"
                                    embed.add_field(name="⚖️ Quantity", value=qty_str, inline=True)
                                    embed.add_field(name="🏪 Shop", value=f"`{shop_name}`", inline=True)
                                    embed.add_field(name="👤 Owner", value=f"`{owner}`", inline=True)
                                    embed.add_field(name="📍 Map", value=f"**{map_name}**", inline=True)
                                    
                                    # --- ĐOẠN THÊM VÀO: LỆNH COPY NHANH CHO USER ---
                                    embed.add_field(
                                        name="⌨️ Quick Copy Command", 
                                        value=f"```/shop {shop_name}```", 
                                        inline=False
                                    )
                                    
                                    embed.set_footer(text="MyK-Market Tracker • Auto update")
                                    alerts.append({"user_id": sub['user_id'], "embed": embed})
                    
                    for alert in alerts:
                        try:
                            user = self.bot.get_user(alert["user_id"]) or await self.bot.fetch_user(alert["user_id"])
                            await user.send(embed=alert["embed"])
                        except Exception:
                            pass

async def setup(bot):
    await bot.add_cog(ShopTracker(bot))