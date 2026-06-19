import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import logging
import motor.motor_asyncio
import os
import textwrap

# Thiết lập Logger cho Debugging (Yêu cầu 5)
logger = logging.getLogger('DMW_Broadcaster')
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
if not logger.handlers:
    logger.addHandler(handler)

# --- CONFIGURATION ---
# Bạn có thể đưa các biến này vào file .env
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
DATA_CENTER_CHANNEL_ID = 1517166085940445284  # THAY BẰNG ID KÊNH MYK DATA CENTER CỦA BẠN
# Sử dụng model free phổ biến và mạnh mẽ trên OpenRouter năm 2026
AI_MODEL = "meta-llama/llama-3.3-70b-instruct:free" 
# ---------------------

class PaginationAndTranslationView(discord.ui.View):
    """View quản lý phân trang và các nút dịch thuật (Yêu cầu 2 & 8)"""
    def __init__(self, cog, chunks, original_text):
        super().__init__(timeout=None)
        self.cog = cog
        self.chunks = chunks
        self.original_text = original_text # Giữ lại text gốc để dịch toàn bộ
        self.current_page = 0

        # Nếu chỉ có 1 trang, vô hiệu hóa nút chuyển trang
        if len(self.chunks) <= 1:
            self.prev_button.disabled = True
            self.next_button.disabled = True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.grey, custom_id="prev_page")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_message(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.grey, custom_id="next_page")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.chunks) - 1:
            self.current_page += 1
            await self.update_message(interaction)

    async def update_message(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📰 DMW Data Center Update", 
            description=self.chunks[self.current_page], 
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{len(self.chunks)}")
        await interaction.response.edit_message(embed=embed, view=self)

    # --- CÁC NÚT DỊCH THUẬT (EPHEMERAL) ---
    async def handle_translation(self, interaction: discord.Interaction, target_lang: str):
        # Bắt buộc defer vì gọi AI có thể mất hơn 3 giây
        await interaction.response.defer(ephemeral=True)
        logger.debug(f"[Translation] User {interaction.user} requested translation to {target_lang}")
        
        system_prompt = (
            f"You are a gaming translator. Translate the following text to {target_lang}. "
            "CRITICAL RULE: DO NOT translate game-specific terms like Digimon names, "
            "Dungeon names, NPC names, or item names. Keep them strictly in English."
        )
        
        translated_text = await self.cog.call_openrouter(system_prompt, self.original_text)
        
        if not translated_text:
            await interaction.followup.send("Failed to translate data. Please try again later.", ephemeral=True)
            return

        # Phân trang cho bản dịch nếu quá dài
        trans_chunks = textwrap.wrap(translated_text, 4000, replace_whitespace=False)
        for i, chunk in enumerate(trans_chunks):
            embed = discord.Embed(title=f"DMW Update ({target_lang})", description=chunk, color=discord.Color.green())
            if i == 0:
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                # Gửi thêm các phần tiếp theo nếu văn bản quá dài
                await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="🇻🇳 VN", style=discord.ButtonStyle.primary, custom_id="trans_vn")
    async def translate_vn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_translation(interaction, "Vietnamese")

    @discord.ui.button(label="🇩🇪 DE", style=discord.ButtonStyle.primary, custom_id="trans_de")
    async def translate_de(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_translation(interaction, "German")

    @discord.ui.button(label="🇲🇾 MS", style=discord.ButtonStyle.primary, custom_id="trans_ms")
    async def translate_ms(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_translation(interaction, "Malay")

    @discord.ui.button(label="🇮🇩 ID", style=discord.ButtonStyle.primary, custom_id="trans_id")
    async def translate_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_translation(interaction, "Indonesian")


class DMWBroadcaster(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Khởi tạo kết nối MongoDB
        self.db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
        self.db = self.db_client.dmw_database # Tên Database
        self.collection = self.db.news_channels # Tên Collection lưu ID
        logger.info("[Init] DMW Broadcaster Cog loaded and MongoDB connected.")

    async def call_openrouter(self, system_prompt: str, user_text: str) -> str:
        """Gọi API OpenRouter (Yêu cầu 2)"""
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://github.com/meik922004-lgtm/MykBot", # Thay bằng link của bạn
            "X-Title": "DMW Discord Bot",
            "Content-Type": "application/json"
        }
        payload = {
            "model": AI_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ]
        }
        
        logger.debug(f"[OpenRouter] Sending request to OpenRouter using {AI_MODEL}...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.debug("[OpenRouter] Request successful.")
                        return data['choices'][0]['message']['content']
                    else:
                        error_data = await resp.text()
                        logger.error(f"[OpenRouter] Request failed with status {resp.status}: {error_data}")
                        return None
        except Exception as e:
            logger.error(f"[OpenRouter] Exception occurred: {e}")
            return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Lắng nghe tin nhắn từ Data Center (Yêu cầu 1)"""
        if message.author.bot and message.author == self.bot.user:
            return # Bỏ qua tin nhắn do chính bot này gửi

        if message.channel.id == DATA_CENTER_CHANNEL_ID:
            logger.info(f"[Data Center] Detected new message in source channel. ID: {message.id}")
            
            # Lấy nội dung tin nhắn (bao gồm cả embed nếu có)
            content = message.content
            if message.embeds:
                for embed in message.embeds:
                    if embed.description:
                        content += f"\n{embed.description}"

            if not content.strip():
                logger.debug("[Data Center] Message is empty, skipping.")
                return

            system_prompt = (
                "You are an AI assistant for a Digimon Masters server. "
                "Summarize the following game updates/news. Output ONLY in English. "
                "CRITICAL: Keep all specific terms like Digimon names, Dungeon names, "
                "and item names exactly as they are in English. Be concise and format nicely with bullet points."
            )

            summary = await self.call_openrouter(system_prompt, content)
            
            if summary:
                await self.broadcast_summary(summary)
            else:
                logger.error("[Process] Failed to generate summary from AI.")

    async def broadcast_summary(self, summary: str):
        """Gửi thông báo tới các server đã đăng ký (Yêu cầu 3 & 4)"""
        logger.info("[Broadcast] Starting broadcast to registered channels.")
        
        # Cắt nội dung thành các phần nhỏ 4000 ký tự (Yêu cầu 8)
        chunks = textwrap.wrap(summary, 4000, replace_whitespace=False)
        
        cursor = self.collection.find({})
        async for document in cursor:
            guild_id = document.get("guild_id")
            channel_id = document.get("channel_id")
            
            channel = self.bot.get_channel(channel_id)
            
            if channel is None:
                try:
                    # Thử fetch nếu channel không nằm trong cache
                    channel = await self.bot.fetch_channel(channel_id)
                except (discord.NotFound, discord.Forbidden):
                    # Kênh bị xóa hoặc bot bị mất quyền
                    logger.warning(f"[Broadcast] Lost access or channel deleted for Guild {guild_id}. Removing from DB.")
                    await self.collection.delete_one({"guild_id": guild_id})
                    continue
                except Exception as e:
                    logger.error(f"[Broadcast] Error fetching channel {channel_id}: {e}")
                    continue

            try:
                view = PaginationAndTranslationView(self, chunks, summary)
                embed = discord.Embed(
                    title="📰 DMW Data Center Update", 
                    description=chunks[0], 
                    color=discord.Color.blue()
                )
                if len(chunks) > 1:
                    embed.set_footer(text=f"Page 1/{len(chunks)}")
                    
                await channel.send(embed=embed, view=view)
                logger.debug(f"[Broadcast] Successfully sent to Guild {guild_id}, Channel {channel.name}.")
                
            except discord.Forbidden:
                # Bot không có quyền chat -> Xóa khỏi DB (Yêu cầu 4)
                logger.warning(f"[Broadcast] Missing permissions to send in Guild {guild_id}. Removing from DB.")
                await self.collection.delete_one({"guild_id": guild_id})
            except Exception as e:
                logger.error(f"[Broadcast] Failed to send message to {channel_id}: {e}")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """Tự động xóa DB khi bot bị kick khỏi server (Yêu cầu 4)"""
        logger.info(f"[Event] Bot was removed from Guild: {guild.name} ({guild.id}). Cleaning up DB.")
        await self.collection.delete_one({"guild_id": guild.id})

    # --- SLASH COMMANDS (Yêu cầu 6 & 7) ---
    @app_commands.command(name="setup_news", description="Register the current channel to receive DMW news broadcasts.")
    @app_commands.default_permissions(administrator=True) # Chỉ Admin mới thấy/sài được
    async def setup_news(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        channel_id = interaction.channel.id

        logger.info(f"[Command] Setup requested by {interaction.user} for Guild {guild_id} in Channel {channel_id}")

        # Upsert: Lưu ID guild và channel, tạo collection mới nếu chưa có
        await self.collection.update_one(
            {"guild_id": guild_id},
            {"$set": {"guild_id": guild_id, "channel_id": channel_id}},
            upsert=True
        )

        embed = discord.Embed(
            title="✅ Setup Complete",
            description=f"This channel (`{interaction.channel.name}`) has been successfully registered to receive DMW news broadcasts.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(DMWBroadcaster(bot))