import asyncio
import logging
import os
import textwrap
from datetime import datetime, timezone
from bson.objectid import ObjectId
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from Database import patch_subscribers_col, patch_history_col
from utils.checks import is_admin_or_bot_owner

logger = logging.getLogger("DMW_Broadcaster")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
    logger.addHandler(handler)

DATA_CENTER_CHANNEL_ID = int(os.getenv("DATA_CENTER_CHANNEL_ID", "1517166085940445284"))
DEBOUNCE_SECONDS = 90  # Chờ 90 giây sau tin cuối cùng của GM để gom trọn bộ Patch Note

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

LANG_MAP = {
    "vn": ("Vietnamese", "🇻🇳 Tiếng Việt"),
    "de": ("German", "🇩🇪 Deutsch"),
    "ms": ("Malay", "🇲🇾 Bahasa Melayu"),
    "id": ("Indonesian", "🇮🇩 Bahasa Indonesia"),
}


def build_patch_embed(chunks: list[str], page: int, title: str = "📰 DMW Patch Summary") -> discord.Embed:
    safe_page = max(0, min(page, len(chunks) - 1))
    embed = discord.Embed(
        title=title,
        description=chunks[safe_page],
        color=discord.Color.blue(),
    )
    embed.set_footer(text=f"Page {safe_page + 1}/{len(chunks)} • Bấm nút bên dưới để dịch nhanh")
    return embed


class PatchView(discord.ui.View):
    """View bền vững dựa trên MongoDB patch_id — hoạt động ổn định ngay cả sau khi Render restart."""

    def __init__(self, patch_id: str, total_pages: int = 1, current_page: int = 0):
        super().__init__(timeout=None)
        if total_pages > 1:
            self.add_item(
                discord.ui.Button(
                    label="◀ Prev",
                    style=discord.ButtonStyle.grey,
                    custom_id=f"patch:nav:{patch_id}:{max(0, current_page - 1)}",
                    disabled=(current_page <= 0),
                    row=0,
                )
            )
            self.add_item(
                discord.ui.Button(
                    label="Next ▶",
                    style=discord.ButtonStyle.grey,
                    custom_id=f"patch:nav:{patch_id}:{min(total_pages - 1, current_page + 1)}",
                    disabled=(current_page >= total_pages - 1),
                    row=0,
                )
            )

        for code, (_, label) in LANG_MAP.items():
            self.add_item(
                discord.ui.Button(
                    label=label.split(" ")[0] + " " + code.upper(),
                    style=discord.ButtonStyle.primary,
                    custom_id=f"patch:trans:{patch_id}:{code}",
                    row=1,
                )
            )


class DMWBroadcaster(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None
        self._message_buffer: list[str] = []
        self._debounce_task: asyncio.Task | None = None

    async def cog_unload(self):
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45))
        return self._session

    async def call_ai(self, system_prompt: str, user_text: str) -> str | None:
        """Gọi AI theo thứ tự ưu tiên: Groq -> Gemini REST -> OpenRouter."""
        session = await self._get_session()

        # 1. Ưu tiên Groq (Rất nhanh, miễn phí ổn định)
        if GROQ_API_KEY:
            try:
                async with session.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_text},
                        ],
                        "temperature": 0.3,
                    },
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"]
                    logger.warning(f"[Groq] HTTP {resp.status}: {await resp.text()}")
            except Exception as e:
                logger.error(f"[Groq] Exception: {e}")

        # 2. Dự phòng Google Gemini API (qua REST để không block event loop)
        if GEMINI_API_KEY:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
                payload = {
                    "system_instruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"parts": [{"text": user_text}]}],
                }
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["candidates"][0]["content"]["parts"][0]["text"]
                    logger.warning(f"[Gemini] HTTP {resp.status}: {await resp.text()}")
            except Exception as e:
                logger.error(f"[Gemini] Exception: {e}")

        # 3. Dự phòng cuối cùng: OpenRouter
        if OPENROUTER_API_KEY:
            try:
                async with session.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "HTTP-Referer": "https://github.com/meik922004-lgtm/MykBot",
                        "X-Title": "MyKBot DMW Patch Summary",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": OPENROUTER_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_text},
                        ],
                    },
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"]
                    logger.error(f"[OpenRouter] HTTP {resp.status}: {await resp.text()}")
            except Exception as e:
                logger.error(f"[OpenRouter] Exception: {e}")

        return None

    # ==========================================
    # DEBOUNCE BUFFER GOM TIN NHẮN PATCH NOTE
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return
        if message.channel.id != DATA_CENTER_CHANNEL_ID:
            return

        parts = []
        if message.content.strip():
            parts.append(message.content.strip())
        for emb in message.embeds:
            if emb.title:
                parts.append(f"**{emb.title}**")
            if emb.description:
                parts.append(emb.description)
            for field in emb.fields:
                parts.append(f"{field.name}: {field.value}")

        combined = "\n".join(parts).strip()
        if not combined:
            return

        self._message_buffer.append(combined)
        logger.info(f"[PatchBuffer] Đã gom {len(self._message_buffer)} tin nhắn. Đợi {DEBOUNCE_SECONDS}s...")

        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = asyncio.create_task(self._flush_buffer_after_delay())

    async def _flush_buffer_after_delay(self):
        try:
            await asyncio.sleep(DEBOUNCE_SECONDS)
            if not self._message_buffer:
                return

            full_text = "\n\n---\n\n".join(self._message_buffer)
            self._message_buffer.clear()

            system_prompt = (
                "You are an AI assistant for a Digimon Masters World (DMW) community. "
                "Summarize the following game patch notes/updates clearly in English using concise bullet points. "
                "Group by sections (e.g., Events, Cash Shop, Fixes, Balance). "
                "CRITICAL: Keep all Digimon names, Dungeon names, NPC names, and Item names strictly in English."
            )
            summary = await self.call_ai(system_prompt, full_text)
            if not summary:
                logger.error("[PatchSummary] Không thể tạo bản tóm tắt từ AI.")
                return

            chunks = textwrap.wrap(summary, 3900, replace_whitespace=False)
            doc = {
                "summary": summary,
                "chunks": chunks,
                "translations": {},
                "created_at": datetime.now(timezone.utc),
            }
            res = await patch_history_col.insert_one(doc)
            await self.broadcast_summary(str(res.inserted_id), chunks)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[PatchSummary] Lỗi xử lý buffer: {e}")

    async def broadcast_summary(self, patch_id: str, chunks: list[str]):
        embed = build_patch_embed(chunks, 0)
        view = PatchView(patch_id, len(chunks), 0)

        async for doc in patch_subscribers_col.find({}):
            guild_id = doc.get("guild_id")
            channel_id = doc.get("channel_id")
            if not channel_id:
                continue

            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                await channel.send(embed=embed, view=view)
                await asyncio.sleep(0.3)
            except (discord.NotFound, discord.Forbidden):
                logger.warning(f"[PatchBroadcast] Mất quyền hoặc xóa kênh tại Guild {guild_id}. Đã gỡ khỏi DB.")
                await patch_subscribers_col.delete_one({"guild_id": guild_id})
            except Exception as e:
                logger.error(f"[PatchBroadcast] Lỗi gửi tới kênh {channel_id}: {e}")

    # ==========================================
    # XỬ LÝ NÚT CHUYỂN TRANG & DỊCH THUẬT (PERSISTENT)
    # ==========================================
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if not interaction.data:
            return
        custom_id = interaction.data.get("custom_id", "")
        if not custom_id.startswith("patch:"):
            return

        parts = custom_id.split(":")
        if len(parts) != 4:
            return

        _, action, patch_id, arg = parts
        if not ObjectId.is_valid(patch_id):
            return await interaction.response.send_message("❌ Bản tin này không còn hợp lệ.", ephemeral=True)

        doc = await patch_history_col.find_one({"_id": ObjectId(patch_id)})
        if not doc:
            return await interaction.response.send_message("❌ Không tìm thấy dữ liệu bản tin trong Database.", ephemeral=True)

        chunks = doc.get("chunks") or textwrap.wrap(doc.get("summary", ""), 3900, replace_whitespace=False)

        if action == "nav":
            page = int(arg)
            embed = build_patch_embed(chunks, page)
            view = PatchView(patch_id, len(chunks), page)
            return await interaction.response.edit_message(embed=embed, view=view)

        if action == "trans":
            if arg not in LANG_MAP:
                return
            target_lang, display_name = LANG_MAP[arg]
            await interaction.response.defer(ephemeral=True)

            # Kiểm tra cache bản dịch trên MongoDB trước khi gọi AI
            cached_trans = doc.get("translations", {}).get(arg)
            if not cached_trans:
                system_prompt = (
                    f"You are a gaming translator. Translate the following DMW patch summary into {target_lang}. "
                    "CRITICAL RULE: Keep all Digimon names, Dungeon names, NPC names, and item names strictly in English."
                )
                cached_trans = await self.call_ai(system_prompt, doc.get("summary", ""))
                if not cached_trans:
                    return await interaction.followup.send("❌ Dịch thất bại, vui lòng thử lại sau.", ephemeral=True)
                await patch_history_col.update_one(
                    {"_id": ObjectId(patch_id)},
                    {"$set": {f"translations.{arg}": cached_trans}},
                )

            trans_chunks = textwrap.wrap(cached_trans, 3900, replace_whitespace=False)
            for idx, chunk in enumerate(trans_chunks):
                emb = discord.Embed(
                    title=f"📰 DMW Patch Summary ({display_name})" + (f" [{idx + 1}/{len(trans_chunks)}]" if len(trans_chunks) > 1 else ""),
                    description=chunk,
                    color=discord.Color.green(),
                )
                await interaction.followup.send(embed=emb, ephemeral=True)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        await patch_subscribers_col.delete_one({"guild_id": guild.id})

    # ==========================================
    # HELPER CHO /menu & SLASH COMMANDS
    # ==========================================
    async def open_latest_patch(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        latest = await patch_history_col.find_one(sort=[("created_at", -1)])
        if not latest:
            return await interaction.followup.send("📭 Chưa có bản tóm tắt Patch Note nào được lưu.", ephemeral=True)

        chunks = latest.get("chunks") or textwrap.wrap(latest.get("summary", ""), 3900, replace_whitespace=False)
        embed = build_patch_embed(chunks, 0, title="📰 DMW Patch Summary (Mới nhất)")
        view = PatchView(str(latest["_id"]), len(chunks), 0)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="setup_news", description="Đăng ký kênh hiện tại nhận tóm tắt Patch Note DMW tự động")
    @is_admin_or_bot_owner()
    async def setup_news(self, interaction: discord.Interaction):
        await patch_subscribers_col.update_one(
            {"guild_id": interaction.guild_id},
            {"$set": {"guild_id": interaction.guild_id, "channel_id": interaction.channel_id}},
            upsert=True,
        )
        embed = discord.Embed(
            title="✅ Setup Patch Summary Thành Công",
            description=f"Kênh {interaction.channel.mention} đã được đăng ký nhận bản tóm tắt Patch Note tự động.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="patch_latest", description="Xem bản tóm tắt Patch Note DMW mới nhất")
    async def patch_latest(self, interaction: discord.Interaction):
        await self.open_latest_patch(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(DMWBroadcaster(bot))