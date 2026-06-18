import os
import json
import logging
import asyncio
import discord
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from openai import AsyncOpenAI  # Sử dụng thư viện AsyncOpenAI chuẩn để kết nối OpenRouter

# Cấu hình logging
logger = logging.getLogger("DMW_PatchBot")
logger.setLevel(logging.INFO)

# Biến môi trường
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
SOURCE_CHANNEL_ID = int(os.getenv("SOURCE_CHANNEL_ID", "1517166085940445284")) # ID channel #patch-notes nguồn

# Khởi tạo OpenRouter Client (Bất đồng bộ)
openrouter_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY
)

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
        self.db = self.mongo_client["database0"]
        
        self.msg_buffer = []
        self.last_arrival_time = 0
        self.bg_loop_task = None

    async def cog_load(self):
        self.bot.add_view(PatchView())
        self.bg_loop_task = asyncio.create_task(self.buffer_monitor_loop())
        logger.info("PatchNotesCog loaded and background loop monitor started.")

    async def cog_unload(self):
        if self.bg_loop_task:
            self.bg_loop_task.cancel()

    async def buffer_monitor_loop(self):
        while True:
            try:
                await asyncio.sleep(1)
                current_time = asyncio.get_event_loop().time()
                
                if self.msg_buffer and (current_time - self.last_arrival_time >= 5.0):
                    working_batch = self.msg_buffer.copy()
                    self.msg_buffer.clear()
                    
                    logger.info(f"Debounce finished. Processing a combined batch of {len(working_batch)} messages.")
                    await self.process_patch_batch(working_batch)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in background buffer monitor loop: {e}")

    async def call_openrouter_with_retry(self, content: str, retries=2, delay=3) -> dict:
        """Gọi OpenRouter API với cơ chế tự động chuyển đổi model vàLOG DEBUG siêu chi tiết"""
        free_models = [
            "google/gemini-2.0-flash-lite-preview-02-05:free", # Model mới nhất của Google, siêu nhanh & free
            "google/gemini-flash-1.5-8b",                      # Bản 1.5 8B của Google (thường được hỗ trợ free)
            "qwen/qwen-2.5-7b-instruct",                       # Qwen 2.5 bản 7B
            "meta-llama/llama-3.2-3b-instruct"                 # Llama 3.2 3B bản gọn nhẹ
         ] # Dự phòng 3: Của Microsoft, xử lý JSON cực kỳ chuẩn
        
        
        logger.info(f"[DEBUG] Khởi chạy dịch thuật. Tổng độ dài ký tự Patch Note gốc: {len(content)}")

        
        prompt = f"""
        You are an expert digmon master online game analyzer. Analyze the game patch note provided below.
        1. Extract and summarize all key changes neatly in structured markdown (e.g., dungeons, stats, rewards, bug fixes, new events).
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

        for idx, model_name in enumerate(free_models, 1):
            logger.info(f"[DEBUG] [Model {idx}/{len(free_models)}] Đang chọn cấu hình: {model_name}")
            for attempt in range(1, retries + 1):
                try:
                    logger.info(f"[DEBUG] Đang gửi request đến OpenRouter | Model: {model_name} | Lần thử: {attempt}/{retries}")
                    
                    response = await openrouter_client.chat.completions.create(
                        model=model_name, 
                        messages=[
                            {"role": "system", "content": "You are a professional game patch notes translator. You must output strictly valid JSON."},
                            {"role": "user", "content": prompt}
                        ],
                        response_format={"type": "json_object"}, 
                        temperature=0.2
                    )
                    
                    logger.info(f"[DEBUG] Đã nhận phản hồi từ OpenRouter thành công cho model: {model_name}")
                    
                    if not response.choices:
                        logger.warning("[DEBUG] Cảnh báo: Thuộc tính choices trả về bị trống!")
                        raise ValueError("OpenRouter choices list is empty.")
                        
                    text = response.choices[0].message.content
                    if not text:
                        logger.warning("[DEBUG] Cảnh báo: Thuộc tính content bên trong tin nhắn bị trống!")
                        raise ValueError("OpenRouter returned message content is None.")
                        
                    text = text.strip()
                    # In ra 250 ký tự đầu tiên của AI trả về để check xem có phải JSON không
                    logger.info(f"[DEBUG] Đoạn văn bản thô (Raw Text) AI phản hồi (250 ký tự đầu): {text[:250]}...")
                    
                    # Khử cấu trúc markdown block ```json ... ``` nếu AI lỡ tay bọc ngoài JSON
                    if text.startswith("```"):
                        logger.info("[DEBUG] Phát hiện văn bản bị bọc bởi markdown code block (```). Đang tiến hành bóc tách...")
                        if text.startswith("```json"):
                            text = text[7:]
                        else:
                            text = text[3:]
                        if text.endswith("```"):
                            text = text[:-3]
                        text = text.strip()
                        logger.info(f"[DEBUG] Văn bản sau khi bóc tách code block: {text[:250]}...")
                        
                    logger.info("[DEBUG] Tiến hành ép chuỗi ký tự sang định dạng JSON dict (json.loads)...")
                    data = json.loads(text)
                    
                    # Kiểm tra tính toàn vẹn của các key ngôn ngữ
                    required_keys = ["en", "vi", "de", "ms", "id"]
                    missing_keys = [k for k in required_keys if k not in data]
                    
                    if not missing_keys:
                        logger.info(f"✅ [DEBUG] Thành công tuyệt đối! Model {model_name} đã trả về cấu trúc JSON hợp lệ.")
                        return data
                    else:
                        logger.error(f"[DEBUG] Chuỗi JSON bị thiếu các trường ngôn ngữ bắt buộc: {missing_keys}")
                        raise ValueError(f"Missing keys: {missing_keys}")
                        
                except Exception as e:
                    logger.warning(f"⚠️ [DEBUG] Lỗi xảy ra tại Model {model_name} (Lần thử {attempt}/{retries}): {repr(e)}")
                    if attempt < retries:
                        logger.info(f"[DEBUG] Chờ {delay} giây trước khi thử lại lượt tiếp theo...")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"❌ [DEBUG] Model {model_name} đã hết số lần thử. Tự động nhảy sang model dự phòng tiếp theo...")
                        break 
                        
        raise RuntimeError("🚨 Cực kỳ nghiêm trọng: Toàn bộ các model miễn phí của OpenRouter đều đang bị sập hoặc quá tải cùng lúc.")

    async def process_patch_batch(self, working_batch):
        logger.info(f"[DEBUG] Bắt đầu gom xử lý batch gồm {len(working_batch)} tin nhắn.")
        combined_content = "\n\n".join([m.content for m in working_batch if m.content])
        if not combined_content.strip():
            logger.warning("[DEBUG] Nội dung batch trống rỗng. Huỷ bỏ tiến trình xử lý.")
            return

        image_url = None
        for m in working_batch:
            if m.attachments:
                image_url = m.attachments[0].url
                logger.info(f"[DEBUG] Tìm thấy ảnh đính kèm trong tin nhắn: {image_url}")
                break

        source_id = str(working_batch[0].id)
        logger.info(f"[DEBUG] ID gốc của tin nhắn đầu tiên làm mốc khóa: {source_id}")

        try:
            exists = await self.db.patch_history.find_one({"_id": source_id})
            if exists:
                logger.info(f"[DEBUG] Bản vá ID {source_id} này đã được xử lý từ trước trong DB. Bỏ qua.")
                return

            logger.info("[DEBUG] Kích hoạt hàm dịch thuật call_openrouter_with_retry...")
            translations = await self.call_openrouter_with_retry(combined_content)
            logger.info("[DEBUG] Nhận kết quả dịch hoàn tất thành công. Đang lưu vào MongoDB...")

            patch_data = {
                "_id": source_id,
                "created_at": working_batch[0].created_at.isoformat(),
                "image_url": image_url,
                "translations": translations
            }
            await self.db.patch_history.insert_one(patch_data)
            logger.info(f"Successfully processed and saved patch batch {source_id}.")

            logger.info("[DEBUG] Tiến hành phát sóng (Broadcast) dữ liệu đến các channel đăng ký...")
            await self.execute_broadcast(source_id, translations, image_url)
        except Exception as e:
            logger.error(f"Critical failed to process batch {source_id}: {e}", exc_info=True)

    async def execute_broadcast(self, source_id: str, translations: dict, image_url: str):
        embeds = create_embed_chunks(translations["vi"], "vi", source_id, image_url)
        
        cursor = self.db.patch_channels_active.find({})
        channels_to_notify = await cursor.to_list(length=1000)
        logger.info(f"[DEBUG] Tìm thấy tổng cộng {len(channels_to_notify)} kênh trong hệ thống cần gửi thông báo.")
        
        for doc in channels_to_notify:
            channel_id_str = doc.get("channel_id")
            if not channel_id_str:
                continue

            channel_id = int(channel_id_str)
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                if channel:
                    await channel.send(embeds=embeds, view=PatchView())
                    logger.info(f"[DEBUG] Đã gửi thông báo thành công đến kênh: {channel_id}")
                else:
                    raise discord.errors.NotFound()
            except (discord.errors.Forbidden, discord.errors.NotFound):
                logger.warning(f"[DEBUG] Không có quyền hoặc không tìm thấy kênh {channel_id}. Đang tự động xóa kênh này khỏi danh sách DB.")
                await self.db.patch_channels_active.delete_one({"channel_id": channel_id_str})
            except Exception as e:
                logger.error(f"Broadcast failure on channel {channel_id}: {e}")
            
            await asyncio.sleep(0.2)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.channel.id != SOURCE_CHANNEL_ID:
            return
        if message.author.bot:
            return

        self.msg_buffer.append(message)
        self.last_arrival_time = asyncio.get_event_loop().time()
        logger.info(f"[DEBUG] Nhận tin nhắn mới ID: {message.id}. Đã đưa vào bộ đệm (Buffer Size: {len(self.msg_buffer)})")

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