import discord
from discord.ext import commands
import google.generativeai as genai
import aiohttp
import os
from Database import db # Sử dụng chung DB từ file Database.py

# --- CẤU HÌNH ---
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    ai_model = genai.GenerativeModel('gemini-1.5-flash')

class PatchSummary(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Collection riêng biệt chỉ lưu server ĐÃ SETUP
        self.collection = db["patch_channels_active"]

    async def cog_load(self):
        """Tự động tạo collection mới nếu chưa có"""
        try:
            if "patch_channels_active" not in await db.list_collection_names():
                await db.create_collection("patch_channels_active")
                print("✅ [Database] Created collection: 'patch_channels_active'")
        except Exception as e:
            print(f"⚠️ Error creating collection: {e}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def set_announce(self, ctx, channel: discord.TextChannel):
        """Chỉ những server dùng lệnh này mới được thêm vào collection active"""
        await self.collection.update_one(
            {"_id": str(ctx.guild.id)},
            {"$set": {"announce_channel": channel.id}},
            upsert=True
        )
        await ctx.send(f"✅ Đã kích hoạt Patch Summary cho kênh: {channel.mention}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def set_summary(self, ctx, channel: discord.TextChannel):
        await self.collection.update_one(
            {"_id": str(ctx.guild.id)},
            {"$set": {"summary_channel": channel.id}},
            upsert=True
        )
        await ctx.send(f"✅ Kênh tóm tắt đã được thiết lập: {channel.mention}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user or not message.guild or message.content.startswith('!'):
            return

        # LOGIC QUAN TRỌNG: Chỉ truy vấn trong collection "patch_channels_active"
        config = await self.collection.find_one({"_id": str(message.guild.id)})
        
        # Nếu server chưa từng setup (không có trong collection này), bot bỏ qua ngay lập tức
        if not config:
            return

        announce_id = config.get("announce_channel")
        summary_id = config.get("summary_channel")

        # Kiểm tra đúng kênh announce đã set
        if message.channel.id == announce_id and summary_id:
            summary_channel = self.bot.get_channel(summary_id)
            if not summary_channel: return

            # Thu thập nội dung (Text + Embeds)
            patch_text = message.content or ""
            if message.embeds:
                for embed in message.embeds:
                    if embed.title: patch_text += f"\n{embed.title}"
                    if embed.description: patch_text += f"\n{embed.description}"
                    for field in embed.fields: patch_text += f"\n{field.name}: {field.value}"

            if not patch_text.strip() and not message.attachments: return

            processing_msg = await summary_channel.send("🔄 Đang xử lý Patch Note...")

            try:
                # Xử lý ảnh như cũ...
                image_parts = []
                if message.attachments:
                    async with aiohttp.ClientSession() as session:
                        for attachment in message.attachments:
                            if attachment.filename.lower().endswith(('png', 'jpg', 'jpeg', 'webp')):
                                async with session.get(attachment.url) as resp:
                                    if resp.status == 200:
                                        image_bytes = await resp.read()
                                        image_parts.append({"mime_type": attachment.content_type or "image/png", "data": image_bytes})

                prompt = "Summarize these patch notes professionally in English using Markdown."
                ai_payload = [prompt, f"Patch Note Content:\n{patch_text}"]
                if image_parts: ai_payload.extend(image_parts)

                response = ai_model.generate_content(ai_payload)
                
                # Gửi kết quả (không cần view nếu bồ chưa dùng dịch thuật)
                await summary_channel.send(embed=discord.Embed(title="📢 PATCH SUMMARY", description=response.text[:4000], color=discord.Color.gold()))
                await processing_msg.delete()

            except Exception as e:
                print(f"Error: {e}")
                await processing_msg.edit(content="❌ Lỗi khi phân tích.")

async def setup(bot):
    await bot.add_cog(PatchSummary(bot))