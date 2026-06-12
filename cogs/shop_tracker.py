import discord
from discord.ext import commands
from discord import app_commands  # Thư viện bắt buộc để dùng Slash Command
import json
from pymongo import MongoClient 
import os

class ShopTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # SẠCH 100%: Chỉ gọi từ Render, không để lộ một ký tự mật khẩu nào trong code
        mongo_uri = os.getenv("MONGO_URI")
        
        self.cluster = MongoClient(mongo_uri)
        self.db = self.cluster["database0"]
        self.collection = self.db["shop_subscriptions"]
        
        # Bộ nhớ đệm (Cache) trên RAM
        self.subs_cache = {}
        
        # ⚠️ BẢN VÁ LỖI 1: Bắt buộc phải có đoạn này để bot nạp lại data khi bị reset
        try:
            for doc in self.collection.find():
                self.subs_cache[doc["_id"]] = doc.get("subscribers", [])
            print(f"💾 [Cache] Successfully loaded {len(self.subs_cache)} items into RAM!")
        except Exception as e:
            print(f"❌ [Cache] Error loading data: {e}")

    # ==========================================
    # SLASH COMMAND: /additem
    # ==========================================
    @app_commands.command(name="additem", description="Sign up to receive notifications when the item's price is less than or equal to your desired price.")
    @app_commands.describe(
        item_name="Enter the exact item name you want to track (e.g., Bravery Energy).",
        max_price="Enter the maximum price range (MyK will find shops with prices LESS THAN OR EQUAL to this range)."
    )
    async def additem(self, interaction: discord.Interaction, item_name: str, max_price: int):
        await interaction.response.defer(ephemeral=True) 
        
        item_key = item_name.lower().strip()
        user_id = interaction.user.id 

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
            new_doc = {
                "_id": item_key,
                "subscribers": subscribers
            }
            self.collection.insert_one(new_doc)

        # Cập nhật RAM ngay lập tức
        self.subs_cache[item_key] = subscribers

        await interaction.followup.send(f"✅ Added **{item_name}** to your wishlist, MyK will ping you with price <= **{max_price:,}**.")

    # ==========================================
    # SLASH COMMAND: /removeitem
    # ==========================================
    @app_commands.command(name="removeitem", description="Cancel track item")
    @app_commands.describe(item_name="Write the name you want to cancel tracker")
    async def removeitem(self, interaction: discord.Interaction, item_name: str):
        await interaction.response.defer(ephemeral=True)
        
        item_key = item_name.lower().strip()
        user_id = interaction.user.id

        item_doc = self.collection.find_one({"_id": item_key})
        
        if item_doc:
            subscribers = item_doc.get("subscribers", [])
            new_subscribers = [sub for sub in subscribers if sub["user_id"] != user_id]
            
            if not new_subscribers:
                self.collection.delete_one({"_id": item_key})
                self.subs_cache.pop(item_key, None)
            else:
                self.collection.update_one(
                    {"_id": item_key}, 
                    {"$set": {"subscribers": new_subscribers}}
                )
                self.subs_cache[item_key] = new_subscribers
                
            await interaction.followup.send(f"❌ Removed item from track list: **{item_name}**.")
        else:
            await interaction.followup.send("You didn't register to track this item.")

    # ==========================================
    # LISTENER: LẮNG NGHE WEBHOOK
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message):
        BRIDGE_CHANNEL_ID = 1515038293643759728  
        PUBLIC_ALERT_CHANNEL_ID = 1515038293643759727 

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
                                        description="MyK found a cheap item for you.",
                                        color=discord.Color.green() 
                                    )
                                    
                                    embed.add_field(name="📦 Item", value=f"**{item['item_name']}**", inline=True)
                                    embed.add_field(name="💰 Price (ea)", value=f"**{cost:,}**", inline=True)
                                    
                                    qty_str = f"**{quantity:,}**" if isinstance(quantity, int) else f"**{quantity}**"
                                    # Đã đồng bộ tiếng Anh chữ Số lượng
                                    embed.add_field(name="⚖️ Quantity", value=qty_str, inline=True)
                                    
                                    embed.add_field(name="🏪 Shop", value=f"`{shop_name}`", inline=True)
                                    embed.add_field(name="👤 Owner", value=f"`{owner}`", inline=True)
                                    embed.add_field(name="📍 Map", value=f"**{map_name}**", inline=True)
                                    
                                    embed.set_footer(text="MyK-Market Tracker • Auto update")
                                    
                                    alerts.append({
                                        "ping": f"🔔 <@{sub['user_id']}>",
                                        "embed": embed
                                    })
                    
                    if alerts:
                        alert_channel = self.bot.get_channel(PUBLIC_ALERT_CHANNEL_ID)
                        if alert_channel:
                            for alert in alerts:
                                # ⚠️ BẢN VÁ LỖI 2: Phải có allowed_mentions thì điện thoại người dùng mới rung
                                await alert_channel.send(
                                    content=alert["ping"], 
                                    embed=alert["embed"],
                                    allowed_mentions=discord.AllowedMentions(users=True)
                                )

async def setup(bot):
    await bot.add_cog(ShopTracker(bot))