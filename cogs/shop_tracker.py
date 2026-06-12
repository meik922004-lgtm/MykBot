import discord
from discord.ext import commands
import json
import os

class ShopTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "shop_subscriptions.json"
        self.subscriptions = self.load_subscriptions()

    def load_subscriptions(self):
        """Đọc dữ liệu người dùng đã đăng ký mua đồ"""
        if os.path.exists(self.db_path):
            with open(self.db_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_subscriptions(self):
        """Lưu dữ liệu đăng ký xuống file"""
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self.subscriptions, f, ensure_ascii=False, indent=4)

    @commands.command(name="additem")
    async def canh_do(self, ctx, item_name: str, max_price: int):
        """Lệnh cho user: !canh_do \"Bravery Energy\" 1200"""
        item_key = item_name.lower().strip()
        user_id = ctx.author.id

        if item_key not in self.subscriptions:
            self.subscriptions[item_key] = []

        # Kiểm tra xem user này đã đăng ký item này chưa, nếu có thì cập nhật giá
        existing = next((sub for sub in self.subscriptions[item_key] if sub["user_id"] == user_id), None)
        if existing:
            existing["max_price"] = max_price
        else:
            self.subscriptions[item_key].append({"user_id": user_id, "max_price": max_price})

        self.save_subscriptions()
        await ctx.send(f"✅ Đã ghi nhận! Bot sẽ ping khi có **{item_name}** với giá <= **{max_price:,}**.")

    @commands.command(name="removeitem")
    async def huy_canh(self, ctx, item_name: str):
        """Lệnh hủy theo dõi: !huy_canh \"Bravery Energy\""""
        item_key = item_name.lower().strip()
        user_id = ctx.author.id

        if item_key in self.subscriptions:
            self.subscriptions[item_key] = [sub for sub in self.subscriptions[item_key] if sub["user_id"] != user_id]
            if not self.subscriptions[item_key]:
                del self.subscriptions[item_key]
            self.save_subscriptions()
            await ctx.send(f"❌ Đã hủy theo dõi vật phẩm: **{item_name}**.")
        else:
            await ctx.send("Bạn chưa đăng ký theo dõi vật phẩm này.")

    @commands.Cog.listener()
    async def on_message(self, message):
        # Đổi ID_KENH_WEBHOOK thành ID kênh ẩn mà bạn tạo để nhận file JSON
        BRIDGE_CHANNEL_ID = 1515038293643759728  
        # Đổi ID_KENH_PING thành ID kênh chung nơi bot sẽ tag người dùng
        PUBLIC_ALERT_CHANNEL_ID = 1515038293643759727 

        # Kiểm tra nếu tin nhắn đến từ kênh Webhook và có đính kèm file
        if message.channel.id == BRIDGE_CHANNEL_ID and message.attachments:
            for attachment in message.attachments:
                if attachment.filename == "shop_data.json":
                    # Tải và đọc nội dung file JSON
                    file_bytes = await attachment.read()
                    try:
                        shop_data = json.loads(file_bytes.decode('utf-8'))
                    except Exception:
                        continue # Bỏ qua nếu lỗi định dạng file
                    
                    shop_name = shop_data.get("shop_name", "Không rõ")
                    owner = shop_data.get("owner", "Không rõ")
                    map_name = shop_data.get("map", "Không rõ")
                    
                    alerts = []
                    
                    # Quét qua từng item trong shop vừa nhận được
                    for item in shop_data.get("items", []):
                        name_lower = item["item_name"].lower()
                        cost = item["cost"]
                        
                        if name_lower in self.subscriptions:
                            for sub in self.subscriptions[name_lower]:
                                if cost <= sub["max_price"]:
                                    alerts.append(
                                        f"🔔 <@{sub['user_id']}>!  **{item['item_name']}** price: **{cost:,}** ea!\n"
                                        f"📍 Shop: *{shop_name}* (Seller {owner}) - Map: **{map_name}**"
                                    )
                    
                    # Gửi toàn bộ thông báo ra kênh công khai
                    if alerts:
                        alert_channel = self.bot.get_channel(PUBLIC_ALERT_CHANNEL_ID)
                        if alert_channel:
                            await alert_channel.send("\n\n".join(alerts))

async def setup(bot):
    await bot.add_cog(ShopTracker(bot))