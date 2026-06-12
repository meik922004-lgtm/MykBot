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
    @app_commands.command(name="additem", description="Đăng ký nhận thông báo khi vật phẩm có giá nhỏ hơn hoặc bằng mức mong muốn")
    @app_commands.describe(
        item_name="Nhập chính xác tên vật phẩm cần theo dõi (Ví dụ: Bravery Energy)",
        max_price="Nhập mức giá tối đa (Hệ thống sẽ tìm các shop có giá NHỎ HƠN HOẶC BẰNG mức này)"
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
        await interaction.followup.send(f"✅ Đã ghi nhận vào Database! Bot sẽ ping khi có **{item_name}** với giá <= **{max_price:,}**.")

    # ==========================================
    # SLASH COMMAND: /removeitem
    # ==========================================
    @app_commands.command(name="removeitem", description="Hủy theo dõi một vật phẩm cụ thể")
    @app_commands.describe(item_name="Nhập tên vật phẩm muốn hủy canh giá")
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
            await interaction.followup.send(f"❌ Đã hủy theo dõi vật phẩm: **{item_name}**.")
        else:
            await interaction.followup.send("Bạn chưa đăng ký theo dõi vật phẩm này.")

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
                    alerts = []
                    
                    for item in shop_data.get("items", []):
                        name_lower = item["item_name"].lower()
                        cost = item["cost"]
                        
                        item_doc = self.collection.find_one({"_id": name_lower})
                        
                        if item_doc:
                            for sub in item_doc.get("subscribers", []):
                                if cost <= sub["max_price"]:
                                    alerts.append(
                                        f"🔔 <@{sub['user_id']}>! Phát hiện **{item['item_name']}** giá tốt: **{cost:,}** ea!\n"
                                        f"📍 Shop: *{shop_name}* (Chủ: {owner}) - Vị trí: **{map_name}**"
                                    )
                    
                    if alerts:
                        alert_channel = self.bot.get_channel(PUBLIC_ALERT_CHANNEL_ID)
                        if alert_channel:
                            await alert_channel.send("\n\n".join(alerts))

async def setup(bot):
    await bot.add_cog(ShopTracker(bot))