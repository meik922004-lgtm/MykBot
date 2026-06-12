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

    # ==========================================
    # SLASH COMMAND: /additem
    # ==========================================
    @app_commands.command(name="additem", description="Sign up to receive notifications when the item's price is less than or equal to your desired price.")
    @app_commands.describe(
        item_name="Enter the exact item name you want to track (e.g., Bravery Energy).",
        max_price="Enter the maximum price range (MyK will find shops with prices LESS THAN OR EQUAL to this range)."
    )
    async def additem(self, interaction: discord.Interaction, item_name: str, max_price: int):
        # Slash Command sử dụng interaction thay vì ctx
        await interaction.response.defer(ephemeral=True) # Tạo trạng thái "Bot đang suy nghĩ..." để tránh bị timeout
        
        item_key = item_name.lower().strip()
        user_id = interaction.user.id # Lấy ID người dùng từ interaction

        # Tìm xem vật phẩm này đã có ai đăng ký chưa
        item_doc = self.collection.find_one({"_id": item_key})

        if item_doc:
            subscribers = item_doc.get("subscribers", [])
            user_exists = False
            
            for sub in subscribers:
                if sub["user_id"] == user_id:
                    sub["max_price"] = max_price # Cập nhật giá mới
                    user_exists = True
                    break
            
            if not user_exists:
                subscribers.append({"user_id": user_id, "max_price": max_price})
                
            self.collection.update_one(
                {"_id": item_key}, 
                {"$set": {"subscribers": subscribers}}
            )
        else:
            new_doc = {
                "_id": item_key,
                "subscribers": [{"user_id": user_id, "max_price": max_price}]
            }
            self.collection.insert_one(new_doc)

        # Phản hồi lại cho người dùng biết
        await interaction.followup.send(f"✅ Added **{item_name}**to your wishlist, MyK will ping you with price <= **{max_price:,}**.")

    # ==========================================
    # SLASH COMMAND: /removeitem
    # ==========================================
    @app_commands.command(name="removeitem", description="Cancel track item")
    @app_commands.describe(item_name="write the name you want to cancel tracker")
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
            else:
                self.collection.update_one(
                    {"_id": item_key}, 
                    {"$set": {"subscribers": new_subscribers}}
                )
            await interaction.followup.send(f"❌ Removed item from track list: **{item_name}**.")
        else:
            await interaction.followup.send("You didnt regist to track this item.")

    # ==========================================
    # LISTENER: LẮNG NGHE WEBHOOK (Giữ nguyên)
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
                    
                    shop_name = shop_data.get("shop_name", "Không rõ")
                    owner = shop_data.get("owner", "Không rõ")
                    map_name = shop_data.get("map", "Không rõ")
                    
                    # Khởi tạo list chứa các thông báo Embed
                    alerts = []
                    
                    for item in shop_data.get("items", []):
                        name_lower = item["item_name"].lower()
                        cost = item["cost"]
                        # Lấy thêm số lượng từ JSON, nếu không có thì mặc định là "Không rõ"
                        quantity = item.get("quantity", "Không rõ") 
                        
                        subscribers = self.subs_cache.get(name_lower)
                        
                        if subscribers:
                            for sub in subscribers:
                                if cost <= sub["max_price"]:
                                    # 🎨 TẠO GIAO DIỆN EMBED ĐẸP MẮT
                                    embed = discord.Embed(
                                        title="🎉 MyK tracker",
                                        description="MyK found cheap item for you.",
                                        color=discord.Color.green() # Viền màu xanh lá
                                    )
                                    
                                    # Hàng 1: Thông tin Item (Chia 3 cột)
                                    embed.add_field(name="📦 Item", value=f"**{item['item_name']}**", inline=True)
                                    embed.add_field(name="💰 Price (ea)", value=f"**{cost:,}**", inline=True)
                                    
                                    # Format số lượng có dấu phẩy nếu là số, giữ nguyên nếu là chữ
                                    qty_str = f"**{quantity:,}**" if isinstance(quantity, int) else f"**{quantity}**"
                                    embed.add_field(name="⚖️ Số lượng", value=qty_str, inline=True)
                                    
                                    # Hàng 2: Thông tin Shop (Chia 3 cột)
                                    embed.add_field(name="🏪 Shop", value=f"`{shop_name}`", inline=True)
                                    embed.add_field(name="👤 Owner", value=f"`{owner}`", inline=True)
                                    embed.add_field(name="📍 Map", value=f"**{map_name}**", inline=True)
                                    
                                    # Thêm footer cho chuyên nghiệp
                                    embed.set_footer(text="MyK-Market Tracker • Auto update")
                                    
                                    # Lưu lại nội dung ping (để Discord hiện thông báo đỏ cho user) và Embed
                                    alerts.append({
                                        "ping": f"🔔 <@{sub['user_id']}>",
                                        "embed": embed
                                    })
                    
                    # Gửi từng cảnh báo ra kênh public
                    if alerts:
                        alert_channel = self.bot.get_channel(PUBLIC_ALERT_CHANNEL_ID)
                        if alert_channel:
                            for alert in alerts:
                                await alert_channel.send(content=alert["ping"], embed=alert["embed"])

async def setup(bot):
    await bot.add_cog(ShopTracker(bot))