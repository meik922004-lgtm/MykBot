import discord
from discord.ext import commands
import json

# Nếu bạn dùng thư viện async (như motor), hãy đổi pymongo thành motor.motor_asyncio
from pymongo import MongoClient 

class ShopTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # KẾT NỐI MONGODB
        # Mẹo: Hãy copy chuỗi kết nối này từ file Database.py hiện tại của bạn
        mongo_uri = "mongodb+srv://meik922004_db_user:LrXxnoloY8TaezNI@database0.gjbsfwh.mongodb.net/?appName=database0"
        self.cluster = MongoClient(mongo_uri)
        
        # Trỏ vào database0 giống như trong ảnh của bạn
        self.db = self.cluster["database0"]
        
        # Khởi tạo collection mới cho tính năng này
        self.collection = self.db["shop_subscriptions"]

    @commands.command(name="additem")
    async def canh_do(self, ctx, item_name: str, max_price: int):
        """Lệnh cho user: !canh_do "Bravery Energy" 1200"""
        item_key = item_name.lower().strip()
        user_id = ctx.author.id

        # Tìm xem vật phẩm này đã có ai đăng ký chưa
        item_doc = self.collection.find_one({"_id": item_key})

        if item_doc:
            # Nếu đã có, kiểm tra xem user này có trong danh sách chưa
            subscribers = item_doc.get("subscribers", [])
            user_exists = False
            
            for sub in subscribers:
                if sub["user_id"] == user_id:
                    sub["max_price"] = max_price # Cập nhật giá mới
                    user_exists = True
                    break
            
            if not user_exists:
                subscribers.append({"user_id": user_id, "max_price": max_price})
                
            # Lưu lại vào MongoDB
            self.collection.update_one(
                {"_id": item_key}, 
                {"$set": {"subscribers": subscribers}}
            )
        else:
            # Tạo mới document trong DB nếu vật phẩm chưa ai canh
            new_doc = {
                "_id": item_key,
                "subscribers": [{"user_id": user_id, "max_price": max_price}]
            }
            self.collection.insert_one(new_doc)

        await ctx.send(f"✅ Đã ghi nhận vào Database! Bot sẽ ping khi có **{item_name}** với giá <= **{max_price:,}**.")

    @commands.command(name="removeitem")
    async def huy_canh(self, ctx, item_name: str):
        """Lệnh hủy theo dõi: !huy_canh "Bravery Energy" """
        item_key = item_name.lower().strip()
        user_id = ctx.author.id

        item_doc = self.collection.find_one({"_id": item_key})
        
        if item_doc:
            subscribers = item_doc.get("subscribers", [])
            # Lọc bỏ user hiện tại ra khỏi danh sách
            new_subscribers = [sub for sub in subscribers if sub["user_id"] != user_id]
            
            if not new_subscribers:
                # Nếu không còn ai theo dõi item này, xóa luôn khỏi Database cho nhẹ
                self.collection.delete_one({"_id": item_key})
            else:
                self.collection.update_one(
                    {"_id": item_key}, 
                    {"$set": {"subscribers": new_subscribers}}
                )
            await ctx.send(f"❌ Đã hủy theo dõi vật phẩm: **{item_name}**.")
        else:
            await ctx.send("Bạn chưa đăng ký theo dõi vật phẩm này.")

    @commands.Cog.listener()
    async def on_message(self, message):
        BRIDGE_CHANNEL_ID = 1515038293643759728  # ID kênh ẩn nhận JSON
        PUBLIC_ALERT_CHANNEL_ID = 1515038293643759727 # ID kênh thông báo public

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
                        
                        # Truy vấn trực tiếp từ MongoDB thay vì file local
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