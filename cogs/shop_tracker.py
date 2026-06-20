import discord
from discord.ext import commands
from discord import app_commands
import json
from pymongo import MongoClient 
import os

# ==========================================
# UI CLASSES (MODAL & VIEW) FOR /MYLIST
# ==========================================
class ItemModal(discord.ui.Modal):
    def __init__(self, cog, action: str, item_name: str = None):
        title = "Add New Item" if action == "add" else f"Edit Price: {item_name}"
        super().__init__(title=title[:45])  # Discord modal title limit is 45 chars
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
        
        # Reuse add/edit logic from the cog
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
        super().__init__(timeout=180) # 3 minutes timeout
        self.cog = cog
        self.user_id = user_id

        # Check current item count
        items = self.cog.get_user_items(user_id)
        current_slots = len(items)
        max_slots = self.cog.get_max_slots(user_id)

        # Add Button: Disabled if slots are full
        add_btn = discord.ui.Button(
            label="➕ Add Item", 
            style=discord.ButtonStyle.success, 
            disabled=(current_slots >= max_slots)
        )
        async def add_callback(interaction):
            await interaction.response.send_modal(ItemModal(self.cog, "add"))
        add_btn.callback = add_callback
        self.add_item(add_btn)

        # Edit/Delete Dropdowns: Disabled if there are no items
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
        self.cluster = MongoClient(mongo_uri)
        self.db = self.cluster["database0"]
        self.collection = self.db["shop_subscriptions"]
        self.users_coll = self.db["user_slots"] # Collection for user limits
        
        self.subs_cache = {}
        
        try:
            for doc in self.collection.find():
                self.subs_cache[doc["_id"]] = doc.get("subscribers", [])
            print(f"💾 [Cache] Successfully loaded {len(self.subs_cache)} items into RAM!")
        except Exception as e:
            print(f"❌ [Cache] Error loading data: {e}")

    # ===== HELPER METHODS FOR DATA FETCHING =====
    def get_user_items(self, user_id):
        items = []
        for item_key, subscribers in self.subs_cache.items():
            for sub in subscribers:
                if sub["user_id"] == user_id:
                    items.append({"name": item_key, "max_price": sub["max_price"]})
        return items

    def get_max_slots(self, user_id):
        user_doc = self.users_coll.find_one({"_id": user_id})
        if user_doc:
            return user_doc.get("max_slots", 2)
        return 2 # Default is 2 slots

    # ===== CORE LOGIC (Shared for Commands & UI) =====
    async def process_add_or_edit(self, user_id, item_name, max_price, is_edit=False):
        item_key = item_name.lower().strip()
        user_items = self.get_user_items(user_id)
        
        # 1. Anti-duplicate mechanism (when adding)
        if not is_edit:
            if any(i["name"] == item_key for i in user_items):
                return False, "You are already tracking this item! Use the 'Edit Price' option if you want to change it."
            
            # 2. Slot limit check
            max_slots = self.get_max_slots(user_id)
            if len(user_items) >= max_slots:
                return False, f"You have reached your slot limit ({len(user_items)}/{max_slots}). Please ask the Bot Owner for an expansion!"

        item_doc = self.collection.find_one({"_id": item_key})
        subscribers = []

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
                
            self.collection.update_one(
                {"_id": item_key}, 
                {"$set": {"subscribers": subscribers}}
            )
        else:
            subscribers = [{"user_id": user_id, "max_price": max_price}]
            new_doc = {"_id": item_key, "subscribers": subscribers}
            self.collection.insert_one(new_doc)

        self.subs_cache[item_key] = subscribers
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
                self.subs_cache.pop(item_key, None)
            else:
                self.collection.update_one({"_id": item_key}, {"$set": {"subscribers": new_subscribers}})
                self.subs_cache[item_key] = new_subscribers
            return True, f"Unsubscribed from: **{item_name}**."
        return False, "This item is not registered in the system."

    # ==========================================
    # SLASH COMMAND: /additem (Manual version)
    # ==========================================
    @app_commands.command(name="additem", description="Sign up to receive notifications when an item's price is good.")
    async def additem(self, interaction: discord.Interaction, item_name: str, max_price: int):
        await interaction.response.defer(ephemeral=True) 
        success, msg = await self.process_add_or_edit(interaction.user.id, item_name, max_price, is_edit=False)
        await interaction.followup.send(msg)

    # ==========================================
    # SLASH COMMAND: /removeitem (Manual version)
    # ==========================================
    @app_commands.command(name="removeitem", description="Cancel item tracking.")
    async def removeitem(self, interaction: discord.Interaction, item_name: str):
        await interaction.response.defer(ephemeral=True)
        success, msg = self.process_remove(interaction.user.id, item_name)
        await interaction.followup.send(msg)

    # ==========================================
    # SLASH COMMAND: /mylist (MAIN UI COMMAND)
    # ==========================================
    @app_commands.command(name="mylist", description="View and manage your tracked items list.")
    async def mylist(self, interaction: discord.Interaction):
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

    # ==========================================
    # SLASH COMMAND: /addslot (BOT OWNER ONLY)
    # ==========================================
    @app_commands.command(name="addslot", description="[Owner] Change the slot limit for a user.")
    async def addslot(self, interaction: discord.Interaction, user: discord.Member, slots: int):
        # ⚠️ Check if the user executing the command is the Bot Owner
        is_owner = await self.bot.is_owner(interaction.user)
        if not is_owner:
            await interaction.response.send_message("❌ Only the Bot Owner can use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        self.users_coll.update_one(
            {"_id": user.id},
            {"$set": {"max_slots": slots}},
            upsert=True
        )
        await interaction.followup.send(f"✅ Granted **{slots} max slots** to **{user.display_name}**.")

    # ==========================================
    # WEBHOOK LISTENER & DM ALERTS
    # ==========================================
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
                    
                    shop_name = shop_data.get("shop_name", "Unknown")
                    owner = shop_data.get("owner", "Unknown")
                    map_name = shop_data.get("map", "Unknown")
                    
                    alerts = []
                    
                    for item in shop_data.get("items", []):
                        name_lower = item["item_name"].lower()
                        cost = item["cost"]
                        quantity = item.get("quantity", "Unknown") 
                        
                        subscribers = self.subs_cache.get(name_lower)
                        
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
                                    embed.set_footer(text="MyK-Market Tracker • Auto update")
                                    
                                    alerts.append({
                                        "user_id": sub['user_id'],
                                        "embed": embed
                                    })
                    
                    # Send DM to each user
                    for alert in alerts:
                        try:
                            user = await self.bot.fetch_user(alert["user_id"])
                            # Send directly to user's Direct Messages
                            await user.send(embed=alert["embed"])
                        except discord.Forbidden:
                            # Skip if the user has their DMs closed
                            print(f"⚠️ Cannot send DM to user {alert['user_id']} (DMs closed).")
                        except Exception as e:
                            print(f"❌ Error sending DM: {e}")

async def setup(bot):
    await bot.add_cog(ShopTracker(bot))