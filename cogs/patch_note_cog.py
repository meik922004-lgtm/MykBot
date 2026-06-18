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
                
                if self.msg_buffer and (current_time - self.last_arrival_time >= 10.0):
                    working_batch = self.msg_buffer.copy()
                    self.msg_buffer.clear()
                    
                    logger.info(f"Debounce finished. Processing a combined batch of {len(working_batch)} messages.")
                    await self.process_patch_batch(working_batch)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in background buffer monitor loop: {e}")

    async def call_openrouter_with_retry(self, content: str, retries=3, delay=5) -> dict:
        """Gọi OpenRouter API để dịch và tóm tắt với cơ chế xử lý JSON cứng"""
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
                # Sử dụng Llama 3.3 70B Bản Miễn Phí của OpenRouter
                response = await openrouter_client.chat.completions.create(
                    model="meta-llama/llama-3.3-70b-instruct:free", 
                    messages=[
                        {"role": "system", "content": "You are a professional game patch notes translator. You must output strictly valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"}, # Khóa định dạng đầu ra luôn là JSON
                    temperature=0.2
                )
                text = response.choices[0].message.content.strip()
                
                # Khử markdown block bọc ngoài chuỗi JSON nếu có
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
                raise ValueError("Missing language keys in OpenRouter response.")
            except Exception as e:
                logger.warning(f"[Attempt {attempt}/{retries}] OpenRouter API Error: {e}")
                if attempt < retries:
                    await asyncio.sleep(delay)
                else:
                    raise e

    async def process_patch_batch(self, working_batch):
        combined_content = "\n\n".join([m.content for m in working_batch if m.content])
        if not combined_content.strip():
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
                logger.info(f"Patch ID {source_id} already processed. Skipping.")
                return

            # Đổi hàm gọi sang OpenRouter API mới
            translations = await self.call_openrouter_with_retry(combined_content)

            patch_data = {
                "_id": source_id,
                "created_at": working_batch[0].created_at.isoformat(),
                "image_url": image_url,
                "translations": translations
            }
            await self.db.patch_history.insert_one(patch_data)
            logger.info(f"Successfully processed and saved patch batch {source_id}.")

            await self.execute_broadcast(source_id, translations, image_url)
        except Exception as e:
            logger.error(f"Critical failed to process batch {source_id}: {e}")

    async def execute_broadcast(self, source_id: str, translations: dict, image_url: str):
        embeds = create_embed_chunks(translations["vi"], "vi", source_id, image_url)
        
        cursor = self.db.patch_channels_active.find({})
        channels_to_notify = await cursor.to_list(length=1000)
        
        for doc in channels_to_notify:
            channel_id_str = doc.get("channel_id")
            if not channel_id_str:
                continue

            channel_id = int(channel_id_str)
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                if channel:
                    await channel.send(embeds=embeds, view=PatchView())
                else:
                    raise discord.errors.NotFound()
            except (discord.errors.Forbidden, discord.errors.NotFound):
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
        logger.info(f"Message {message.id} buffered. Current buffer size: {len(self.msg_buffer)}")

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