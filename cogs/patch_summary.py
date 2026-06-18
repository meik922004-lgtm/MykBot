import discord
from discord.ext import commands
import google.generativeai as genai
import motor.motor_asyncio  # Thư viện MongoDB Async
import aiohttp
import os

# --- BẢO MẬT: Cấu hình API từ Environment Variables ---
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI") # Link kết nối MongoDB của bạn

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    ai_model = genai.GenerativeModel('gemini-1.5-flash')
else:
    print("❌ CẢNH BÁO: Chưa cấu hình GEMINI_API_KEY!")

# --- GIAO DIỆN NÚT BẤM DỊCH NGÔN NGỮ ---
class TranslationView(discord.ui.View):
    def __init__(self, original_summary: str):
        super().__init__(timeout=None)
        self.original_summary = original_summary

    async def handle_translation(self, interaction: discord.Interaction, target_lang: str):
        await interaction.response.defer(ephemeral=True)
        try:
            prompt = f"Translate the following gaming patch note summary into {target_lang}. Keep the exact same Markdown formatting, layout, and emojis:\n\n{self.original_summary}"
            response = ai_model.generate_content(prompt)
            
            embed = discord.Embed(
                title=f"🌍 Patch Note Translation ({target_lang})",
                description=response.text[:4000],
                color=discord.Color.blue()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Translation failed: {e}", ephemeral=True)

    @discord.ui.button(label="Tiếng Việt", style=discord.ButtonStyle.primary, custom_id="btn_vi")
    async def trans_vi(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_translation(interaction, "Vietnamese")

    @discord.ui.button(label="Deutsch (Đức)", style=discord.ButtonStyle.primary, custom_id="btn_de")
    async def trans_de(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_translation(interaction, "German")

    @discord.ui.button(label="Malaysia", style=discord.ButtonStyle.primary, custom_id="btn_ms")
    async def trans_ms(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_translation(interaction, "Malaysian")

    @discord.ui.button(label="Indonesia", style=discord.ButtonStyle.primary, custom_id="btn_id")
    async def trans_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_translation(interaction, "Indonesian")


# --- CLASS COG CHÍNH ---
class PatchSummary(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # Kết nối tới MongoDB Atlas
        if MONGO_URI:
            self.db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
            # Theo ảnh của bạn, tên database là 'database0'
            self.db = self.db_client["database0"] 
            self.collection = self.db["server_configs"]
        else:
            print("❌ CẢNH BÁO: Chưa cấu hình MONGO_URI trong Environment Variables!")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def set_announce(self, ctx, channel: discord.TextChannel):
        """Lệnh lưu kênh hóng patch note vào MongoDB"""
        guild_id = str(ctx.guild.id)
        
        # Sử dụng $set và upsert=True để tạo mới hoặc chỉ cập nhật trường này, không ảnh hưởng trường khác
        await self.collection.update_one(
            {"_id": guild_id},
            {"$set": {"announce_channel": channel.id}},
            upsert=True
        )
        await ctx.send(f"✅ Set announcement channel to: {channel.mention}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def set_summary(self, ctx, channel: discord.TextChannel):
        """Lệnh lưu kênh trả kết quả tóm tắt vào MongoDB"""
        guild_id = str(ctx.guild.id)
        
        await self.collection.update_one(
            {"_id": guild_id},
            {"$set": {"summary_channel": channel.id}},
            upsert=True
        )
        await ctx.send(f"✅ Set summary channel to: {channel.mention}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        guild_id = str(message.guild.id)
        
        # Truy vấn cấu hình của Server hiện tại từ MongoDB
        config = await self.collection.find_one({"_id": guild_id})
        if not config:
            return

        announce_id = config.get("announce_channel")
        summary_id = config.get("summary_channel")

        # Kiểm tra xem có đúng kênh lắng nghe không
        if message.channel.id == announce_id and summary_id:
            summary_channel = self.bot.get_channel(summary_id)
            if not summary_channel:
                return

            patch_text = message.content
            if not patch_text and not message.attachments:
                return

            processing_msg = await summary_channel.send("🔄 Analyzing new Patch Note, please wait...")

            try:
                image_parts = []
                if message.attachments:
                    async with aiohttp.ClientSession() as session:
                        for attachment in message.attachments:
                            if attachment.filename.lower().endswith(('png', 'jpg', 'jpeg', 'webp')):
                                async with session.get(attachment.url) as resp:
                                    if resp.status == 200:
                                        image_bytes = await resp.read()
                                        image_parts.append({
                                            "mime_type": attachment.content_type,
                                            "data": image_bytes
                                        })

                prompt = """
                You are an expert gaming assistant. Analyze this Patch Note text and any attached images (which may contain character/Digimon stats).
                1. Summarize the main events, rewards, and core updates into clear English bullet points.
                2. If there are character/Digimon stats in the image, extract and list the key stats clearly.
                3. Keep the summary highly professional, well-structured, and easy to read using Markdown.
                """

                ai_payload = [prompt, f"Patch Note Content:\n{patch_text}"]
                if image_parts:
                    ai_payload.extend(image_parts)

                response = ai_model.generate_content(ai_payload)
                summary_en = response.text

                embed = discord.Embed(
                    title="📢 NEW PATCH NOTE SUMMARY",
                    description=summary_en[:4000],
                    color=discord.Color.gold(),
                    url=message.jump_url
                )
                embed.set_footer(text="Click buttons below to translate this summary.")

                view = TranslationView(original_summary=summary_en)
                
                await processing_msg.delete()
                await summary_channel.send(embed=embed, view=view)

            except Exception as e:
                print(f"Error in PatchSummary Cog: {e}")
                await processing_msg.edit(content="❌ An error occurred while generating the summary.")

async def setup(bot):
    await bot.add_cog(PatchSummary(bot))