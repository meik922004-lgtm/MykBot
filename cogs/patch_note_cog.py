import os
import json
import logging
import asyncio
import discord
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
import google.generativeai as genai
from groq import Groq
# Cấu hình logging
logger = logging.getLogger("DMW_PatchBot")
logger.setLevel(logging.INFO)

# Biến môi trường
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SOURCE_CHANNEL_ID = int(os.getenv("SOURCE_CHANNEL_ID", "1517166085940445284")) # ID channel #patch-notes nguồn

# Cấu hình Gemini
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-2.0-flash-lite")

LANG_MAP = {
    "en": "English 🇬🇧",
    "vi": "Tiếng Việt 🇻🇳",
    "de": "Deutsch 🇩🇪",
    "ms": "Melayu 🇲🇾",
    "id": "Bahasa Indonesia 🇮🇩"
}

def create_embed_chunks(text: str, lang: str, source_id: str, image_url: str = None):
    """Chia nhỏ nội dung thành các cụm Embed để tránh giới hạn ký tự từ Discord"""
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
        if i == len(chunks) - 1:
            embed.set_footer(text=f"Source Patch ID: {source_id}")
            if image_url:
                embed.set_image(url=image_url)
        embeds.append(embed)
    return embeds


class PatchView(discord.ui.View):
    """Persistent View giữ các nút dịch hoạt động vĩnh viễn sau khi restart"""
    def __init__(self):
        super().__init__(timeout=None)

    async def _switch_language(self, interaction: discord.Interaction, lang: str):
        await interaction.response.defer(ephemeral=True)
        if not interaction.message.embeds:
            return await interaction.followup.send("Không tìm thấy dữ liệu cấu trúc embed.", ephemeral=True)
            
        footer_text = interaction.message.embeds[0].footer.text
        try:
            source_msg_id = footer_text.split(":")[-1].strip()
        except Exception:
            return await interaction.followup.send("Không thể phân tích mã nguồn bản vá.", ephemeral=True)

        cog = interaction.client.get_cog("PatchNotesCog")
        if not cog:
            return await interaction.followup.send("Hệ thống lõi đang bận, vui lòng thử lại sau.", ephemeral=True)

        doc = await cog.db.patch_history.find_one({"_id": source_msg_id})
        if not doc or "translations" not in doc or lang not in doc["translations"]:
            return await interaction.followup.send("Không tìm thấy bản dịch sẵn cho ngôn ngữ này trong DB.", ephemeral=True)

        content = doc["translations"][lang]
        image_url = doc.get("image_url")

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
        self.mongo_client = AsyncIOMotorClient(MONGO_URI)
        self.db = self.mongo_client["database0"] # Khớp chính xác database0
        
        # Hệ thống hàng đợi gom patch an toàn (Tránh task.cancel)
        self.msg_buffer = []
        self.last_arrival_time = 0
        self.bg_loop_task = None

    async def cog_load(self):
        self.bot.add_view(PatchView())
        # Khởi chạy vòng lặp giám sát bộ đệm chạy ngầm độc lập
        self.bg_loop_task = asyncio.create_task(self.buffer_monitor_loop())
        logger.info("PatchNotesCog loaded and background loop monitor started.")

    async def cog_unload(self):
        if self.bg_loop_task:
            self.bg_loop_task.cancel()

    async def buffer_monitor_loop(self):
        """Vòng lặp chạy ngầm kiểm tra bộ đệm mỗi giây (Trailing Debounce cực kỳ ổn định)"""
        print("[DEBUG] Vòng lặp monitor chạy ngầm đã kích hoạt thành công!", flush=True)
        while True:
            try:
                await asyncio.sleep(1)
                current_time = asyncio.get_event_loop().time()
                
                # Nếu có tin nhắn trong bộ đệm VÀ đã qua 10 giây kể từ tin nhắn cuối cùng được gửi
                if self.msg_buffer and (current_time - self.last_arrival_time >= 10.0):
                    working_batch = self.msg_buffer.copy()
                    self.msg_buffer.clear()
                    
                    print(f"[DEBUG] Hết 10 giây chờ (Debounce). Bắt đầu xử lý gom cụm {len(working_batch)} tin nhắn...", flush=True)
                    await self.process_patch_batch(working_batch)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[ERROR] Lỗi trong vòng lặp chạy ngầm: {e}", flush=True)

    async def call_gemini_with_retry(self, content: str, retries=3, delay=5) -> dict:
        prompt = f"""
        You are an expert game analyzer. Analyze the game patch note provided below.
        1. Extract and summarize all key changes neatly in structured markdown (e.g., dungeons, stats, rewards, bug fixes).
        2. Translate this exact summary content into 5 target languages: English, Vietnamese, German, Malay, and Indonesian.
        
        Strictly return the response ONLY as a valid JSON object matching this structural format:
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
                response = await gemini_model.generate_content_async(
                    prompt,
                    generation_config={"response_mime_type": "application/json"}
                )
                text = response.text.strip()
                
                # Giải cứu dữ liệu nếu Gemini tự ý bọc block ```json
                if text.startswith("```"):
                    if text.startswith("```json"):
                        text = text[7:]
                    else:
                        text = text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                        
                data = json.loads(text.strip())
                if all(k in data for k in ["en", "vi", "de", "ms", "id"]):
                    return data
                raise ValueError("Missing language keys in Gemini response.")
            except Exception as e:
                logger.warning(f"[Attempt {attempt}/{retries}] Gemini API Error: {e}")
                if attempt < retries:
                    await asyncio.sleep(delay)
                else:
                    raise e

    async def process_patch_batch(self, working_batch):
        """Gom nội dung toàn bộ tin nhắn trong hàng đợi và đẩy lên xử lý"""
        combined_content = "\n\n".join([m.content for m in working_batch if m.content])
        if not combined_content.strip():
            print("[DEBUG] Cụm tin nhắn trống rỗng. Hủy xử lý.", flush=True)
            return

        image_url = None
        for m in working_batch:
            if m.attachments:
                image_url = m.attachments[0].url
                break

        source_id = str(working_batch[0].id)

        try:
            exists = await self.db.patch_history.find_one({"_id": source_id})
            if exists:
                print(f"[DEBUG] Patch ID {source_id} đã từng được xử lý trước đó. Bỏ qua.", flush=True)
                return

            print("[DEBUG] Đang tiến hành gửi dữ liệu sang API Gemini để tóm tắt và dịch thuật...", flush=True)
            translations = await self.call_gemini_with_retry(combined_content)
            print("[DEBUG] Đã nhận phản hồi dịch thuật từ Gemini thành công!", flush=True)

            patch_data = {
                "_id": source_id,
                "created_at": working_batch[0].created_at.isoformat(),
                "image_url": image_url,
                "translations": translations
            }
            await self.db.patch_history.insert_one(patch_data)
            print(f"[DEBUG] Đã lưu dữ liệu bản vá {source_id} vào bảng patch_history.", flush=True)

            # Broadcast diện rộng đến các server khách
            await self.execute_broadcast(source_id, translations, image_url)
        except Exception as e:
            print(f"[CRITICAL ERROR] Lỗi nghiêm trọng tại process_patch_batch: {e}", flush=True)

    async def execute_broadcast(self, source_id: str, translations: dict, image_url: str):
        print("[DEBUG] Bắt đầu tìm kiếm các kênh đăng ký nhận thông báo trong MongoDB...", flush=True)
        embeds = create_embed_chunks(translations["vi"], "vi", source_id, image_url)
        
        cursor = self.db.patch_channels_active.find({})
        channels_to_notify = await cursor.to_list(length=1000)
        
        print(f"[DEBUG] Tìm thấy tất cả {len(channels_to_notify)} kênh đang hoạt động trong DB.", flush=True)
        
        for doc in channels_to_notify:
            channel_id_str = doc.get("channel_id")
            if not channel_id_str:
                continue

            channel_id = int(channel_id_str)
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                if channel:
                    await channel.send(embeds=embeds, view=PatchView())
                    print(f"[DEBUG] -> Đã gửi thành công tới kênh nhận: {channel_id}", flush=True)
                else:
                    raise discord.errors.NotFound()
            except (discord.errors.Forbidden, discord.errors.NotFound):
                print(f"[DEBUG] -> Kênh {channel_id} không còn tồn tại hoặc Bot bị mất quyền xem kênh. Đang xóa khỏi DB.", flush=True)
                await self.db.patch_channels_active.delete_one({"channel_id": channel_id_str})
            except Exception as e:
                print(f"[ERROR] Lỗi khi gửi broadcast tới kênh {channel_id}: {e}", flush=True)
            
            await asyncio.sleep(0.2)

    @commands.Cog.listener()
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Lắng nghe toàn bộ tin nhắn tại kênh nguồn để đưa vào bộ đệm gom bài"""
        # IN LOG CHẮC CHẮN LÊN RENDER ĐỂ KIỂM TRA BOT CÓ NGHE THẤY KÊNH KHÔNG
        print(f"[DEBUG] Nhận tin nhắn tại kênh ID: {message.channel.id} | Kênh nguồn cần tìm: {SOURCE_CHANNEL_ID}", flush=True)
        
        if message.channel.id != SOURCE_CHANNEL_ID:
            return
        if message.author.bot:
            print(f"[DEBUG] Tin nhắn bị bỏ qua vì tác giả là BOT hoặc WEBHOOK (ID: {message.author.id})", flush=True)
            return

        # Thêm tin nhắn vào hàng đợi và cập nhật thời gian tin nhắn cuối cùng xuất hiện
        self.msg_buffer.append(message)
        self.last_arrival_time = asyncio.get_event_loop().time()
        print(f"[DEBUG] Đã thêm tin nhắn {message.id} vào bộ đệm. Kích thước hiện tại: {len(self.msg_buffer)}", flush=True)

    # --- HỆ THỐNG SLASH COMMANDS ĐƯỢC GIỮ NGUYÊN HOÀN TOÀN ---

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