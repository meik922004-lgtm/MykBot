import os
import json
import logging
import asyncio
import discord
from discord.ext import commands, tasks
from motor.motor_asyncio import AsyncIOMotorClient
import google.generativeai as genai

# Cấu hình logging chi tiết
logger = logging.getLogger("DMW_PatchBot")
logger.setLevel(logging.INFO)

# Biến môi trường cấu hình (Thay đổi trong Dashboard của Render)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SOURCE_CHANNEL_ID = int(os.getenv("SOURCE_CHANNEL_ID", "123456789012345678")) # ID channel #patch-notes của DMW

# Cấu hình Gemini
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

# Map định dạng hiển thị ngôn ngữ
LANG_MAP = {
    "en": "English 🇬🇧",
    "vi": "Tiếng Việt 🇻🇳",
    "de": "Deutsch 🇩🇪",
    "ms": "Melayu 🇲🇾",
    "id": "Bahasa Indonesia 🇮🇩"
}

def create_embed_chunks(text: str, lang: str, source_id: str, image_url: str = None):
    """
    Chia nhỏ text thành các Embed nếu độ dài vượt quá giới hạn thiết kế (3500 ký tự để an toàn)
    """
    chunks = []
    while len(text) > 3500:
        split_idx = text.rfind("\n", 0, 3500)
        if split_idx == -1:
            split_idx = 3500
        chunks.append(text[:split_idx])
        text = text[split_idx:].strip()
    if text:
        chunks.append(text)

    embeds = []
    for i, chunk in enumerate(chunks):
        embed = discord.Embed(
            title=f"📢 [DMW] Patch Notes Summary ({LANG_MAP.get(lang, lang.upper())})" if i == 0 else None,
            description=chunk,
            color=discord.Color.dark_green()
        )
        # Chỉ set ảnh và footer chứa Source ID ở embed cuối cùng
        if i == len(chunks) - 1:
            embed.set_footer(text=f"Source Patch ID: {source_id}")
            if image_url:
                embed.set_image(url=image_url)
        embeds.append(embed)
    return embeds


class PatchView(discord.ui.View):
    """
    Persistent View: Nút bấm tương tác không bị mất khi bot bị restart.
    Trạng thái được đọc trực tiếp từ DB dựa trên Footer ID của Embed.
    """
    def __init__(self):
        super().__init__(timeout=None)

    async def _switch_language(self, interaction: discord.Interaction, lang: str):
        await interaction.response.defer(ephemeral=True)
        
        # Đọc Source ID từ Footer của Embed hiện tại
        if not interaction.message.embeds:
            return await interaction.followup.send("Không tìm thấy dữ liệu cấu trúc embed.", ephemeral=True)
            
        footer_text = interaction.message.embeds[0].footer.text
        try:
            source_msg_id = footer_text.split(":")[-1].strip()
        except Exception:
            return await interaction.followup.send("Không thể phân tích mã nguồn bản vá.", ephemeral=True)

        # Lấy dữ liệu dịch sẵn từ MongoDB
        cog = interaction.client.get_cog("PatchNotesCog")
        if not cog:
            return await interaction.followup.send("Hệ thống lõi đang bận, vui lòng thử lại sau.", ephemeral=True)

        doc = await cog.db.patch_history.find_one({"_id": source_msg_id})
        if not doc or "translations" not in doc or lang not in doc["translations"]:
            return await interaction.followup.send("Không tìm thấy bản dịch sẵn cho ngôn ngữ này trong DB.", ephemeral=True)

        content = doc["translations"][lang]
        image_url = doc.get("image_url")

        # Cập nhật giao diện tin nhắn mới
        new_embeds = create_embed_chunks(content, lang, source_msg_id, image_url)
        await interaction.message.edit(embeds=new_embeds)
        await interaction.followup.send(f"Đã chuyển sang: {LANG_MAP[lang]}", ephemeral=True)

    @discord.ui.button(label="English", style=discord.ButtonStyle.secondary, custom_id="persistent_patch:en")
    async def btn_en(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_language(interaction, "en")

    @discord.ui.button(label="Tiếng Việt", style=discord.ButtonStyle.primary, custom_id="persistent_patch:vi")
    async def btn_vi(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_language(interaction, "vi")

    @discord.ui.button(label="Deutsch", style=discord.ButtonStyle.secondary, custom_id="persistent_patch:de")
    async def btn_de(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_language(interaction, "de")

    @discord.ui.button(label="Melayu", style=discord.ButtonStyle.secondary, custom_id="persistent_patch:ms")
    async def btn_ms(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_language(interaction, "ms")

    @discord.ui.button(label="Indonesia", style=discord.ButtonStyle.secondary, custom_id="persistent_patch:id")
    async def btn_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_language(interaction, "id")


class PatchNotesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Khởi tạo kết nối MongoDB
        self.mongo_client = AsyncIOMotorClient(MONGO_URI)
        self.db = self.mongo_client["database0"]
        
    async def cog_load(self):
        # Đăng ký View chạy ngầm vĩnh viễn khi tải Cog
        self.bot.add_view(PatchView())
        # Khởi động tác vụ quét bù dữ liệu phòng trường hợp Render restart làm lỡ tin nhắn
        self.history_recovery_task.start()
        logger.info("PatchNotesCog loaded successfully.")

    async def cog_unload(self):
        self.history_recovery_task.cancel()

    @tasks.loop(count=1)
    async def history_recovery_task(self):
        """
        Hàng đợi khôi phục sau khi Render restart:
        Quét lại 10 tin nhắn gần nhất từ Server nguồn để tránh bị mất patch note trong lúc bot offline.
        """
        await self.bot.wait_until_ready()
        logger.info("Starting startup history recovery check...")
        channel = self.bot.get_channel(SOURCE_CHANNEL_ID)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(SOURCE_CHANNEL_ID)
            except Exception as e:
                logger.error(f"Cannot access source channel {SOURCE_CHANNEL_ID}: {e}")
                return

        async for message in channel.history(limit=10, oldest_first=False):
            # Kiểm tra chống gửi trùng
            exists = await self.db.patch_history.find_one({"_id": str(message.id)})
            if not exists and self.is_patch_note(message):
                logger.info(f"Recovery queue found missing patch: {message.id}. Processing...")
                await self.process_and_broadcast_patch(message)

    def is_patch_note(self, message: discord.Message) -> bool:
        """Bộ lọc điều kiện kiểm tra tin nhắn có phải patch note hợp lệ hay không"""
        if message.author.bot:
            return False
        # Bạn có thể thêm logic kiểm tra nội dung (ví dụ: có chứa cụm từ 'patch' hoặc 'update')
        content_lower = message.content.lower()
        return "patch" in content_lower or "update" in content_lower

    async def call_gemini_with_retry(self, content: str, retries=3, delay=5) -> dict:
        """
        Gọi Gemini API kèm cơ chế Retry nếu dính lỗi tạm thời (Rate limit, Network...)
        Yêu cầu trả về JSON schema cố định để tiết kiệm tài nguyên.
        """
        prompt = f"""
        You are an expert game analyzer for digimon master online. Analyze the game patch note provided below.
        1. Extract and summarize all key changes neatly in structured markdown (e.g., dungeons, stats, rewards, bug fixes, new event).
        2. Translate this exact summary content into 5 target languages: English, Vietnamese, German, Malay, and Indonesian.
        
        Strictly return the response ONLY as a minified JSON object matching this exact structural format without any markdown code block wrappers:
        {{
          "en": "Markdown summary in English",
          "vi": "Markdown summary in Vietnamese",
          "de": "Markdown summary in German",
          "ms": "Markdown summary in Malay",
          "id": "Markdown summary in Indonesian"
        }}
        
        Patch content to parse:
        {content}
        """

        for attempt in range(1, retries + 1):
            try:
                # Sử dụng mode JSON của Gemini 1.5 để đảm bảo đầu ra chuẩn
                response = await gemini_model.generate_content_async(
                    prompt,
                    generation_config={"response_mime_type": "application/json"}
                )
                data = json.loads(response.text)
                # Kiểm tra đủ các key ngôn ngữ yêu cầu
                if all(k in data for k in ["en", "vi", "de", "ms", "id"]):
                    return data
                raise ValueError("Missing language keys in Gemini response.")
            except Exception as e:
                logger.warning(f"[Attempt {attempt}/{retries}] Gemini API Error: {e}")
                if attempt < retries:
                    await asyncio.sleep(delay)
                else:
                    raise e

    async def process_and_broadcast_patch(self, message: discord.Message):
        """Gom dữ liệu, dịch thuật thông qua Gemini, lưu DB và tiến hành Broadcast"""
        try:
            # 1. Trích xuất ảnh đính kèm (nếu có)
            image_url = message.attachments[0].url if message.attachments else None

            # 2. Gọi Gemini xử lý đa ngôn ngữ (1 call duy nhất)
            translations = await self.call_gemini_with_retry(message.content)

            # 3. Lưu trữ vào MongoDB (Bộ nhớ Cache & chống trùng lập)
            patch_data = {
                "_id": str(message.id),
                "author_id": str(message.author.id),
                "created_at": message.created_at.isoformat(),
                "image_url": image_url,
                "translations": translations
            }
            await self.db.patch_history.insert_one(patch_data)
            logger.info(f"Successfully saved patch {message.id} to MongoDB patch_history.")

            # 4. Phát sóng an toàn (Safe Broadcast) đến hàng trăm server
            await self.execute_broadcast(str(message.id), translations, image_url)

        except Exception as e:
            logger.error(f"Critical failed to process patch note {message.id}: {e}")

    async def execute_broadcast(self, source_id: str, translations: dict, image_url: str):
        """Hệ thống phát sóng diện rộng, tự tối ưu hóa tốc độ và tự dọn dẹp data rác"""
        # Mặc định lấy Tiếng Việt làm ngôn ngữ hiển thị ban đầu khi gửi đến các Server khách
        embeds = create_embed_chunks(translations["vi"], "vi", source_id, image_url)
        
        cursor = self.db.patch_channels_active.find({})
        channels_to_notify = await cursor.to_list(length=1000)
        
        logger.info(f"Starting broadcast for patch {source_id} to {len(channels_to_notify)} registered channels.")

        for doc in channels_to_notify:
            channel_id_str = doc.get("channel_id")
            if not channel_id_str:
                continue

            channel_id = int(channel_id_str)
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                if channel:
                    view = PatchView()
                    await channel.send(embeds=embeds, view=view)
                else:
                    raise discord.errors.NotFound()
            
            except (discord.errors.Forbidden, discord.errors.NotFound):
                # Tự động xử lý dọn dẹp khi kênh bị xóa hoặc bot bị kick khỏi Server khách
                await self.db.patch_channels_active.delete_one({"channel_id": channel_id_str})
                logger.info(f"Cleaned up inactive/unauthorized channel registration: {channel_id_str}")
            
            except Exception as e:
                logger.error(f"Failed to send broadcast to channel {channel_id}: {e}")
            
            # Giãn cách 200ms giữa mỗi Server để chống bị dính Rate Limit diện rộng của Discord API
            await asyncio.sleep(0.2)
            
        logger.info(f"Broadcast sequence finished for patch {source_id}.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Lắng nghe sự kiện tin nhắn thời gian thực tại Server nguồn"""
        if message.channel.id != SOURCE_CHANNEL_ID:
            return

        if self.is_patch_note(message):
            # Chống trùng lặp tuyệt đối bằng cơ chế DB Unique Check trước khi xử lý sâu
            exists = await self.db.patch_history.find_one({"_id": str(message.id)})
            if exists:
                return

            logger.info(f"New patch detected in real-time: {message.id}. Analyzing...")
            await self.process_and_broadcast_patch(message)

    # --- HỆ THỐNG LỆNH ĐĂNG KÝ KÊNH (HYBRID COMMANDS) ---

    @commands.hybrid_command(name="register_patch", description="Đăng ký nhận thông báo Patch Notes tự động từ DMW.")
    @commands.has_permissions(manage_channels=True)
    async def register_patch(self, ctx: commands.Context):
        await ctx.defer(ephemeral=True)
        channel_id_str = str(ctx.channel.id)
        guild_id_str = str(ctx.guild.id) if ctx.guild else "DM"

        exists = await self.db.patch_channels_active.find_one({"channel_id": channel_id_str})
        if exists:
            return await ctx.send("Kênh này đã được đăng ký nhận Patch Notes từ trước rồi!", ephemeral=True)

        await self.db.patch_channels_active.insert_one({
            "channel_id": channel_id_str,
            "guild_id": guild_id_str
        })
        await ctx.send("✅ Đăng ký thành công! Kênh này sẽ nhận được các bản dịch tóm tắt Patch Notes mới nhất.", ephemeral=True)

    @commands.hybrid_command(name="unregister_patch", description="Hủy đăng ký nhận thông báo Patch Notes tự động.")
    @commands.has_permissions(manage_channels=True)
    async def unregister_patch(self, ctx: commands.Context):
        await ctx.defer(ephemeral=True)
        channel_id_str = str(ctx.channel.id)

        result = await self.db.patch_channels_active.delete_one({"channel_id": channel_id_str})
        if result.deleted_count > 0:
            await ctx.send("❌ Đã hủy đăng ký nhận thông báo Patch Notes thành công cho kênh này.", ephemeral=True)
        else:
            await ctx.send("Kênh này hiện tại chưa đăng ký dịch vụ nào.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PatchNotesCog(bot))