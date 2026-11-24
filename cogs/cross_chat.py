import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from Database import db
from utils.checks import is_admin_or_bot_owner

logger = logging.getLogger("MyKBot.CrossChat")

# Reuse original collection names in database0 for seamless backward compatibility
boss_channels_col = db["boss_channels"]
cross_messages_col = db["cross_chat_logs"]

WEBHOOK_NAME = "DMW Relay"
LOG_RETENTION_DAYS = 7


class CrossChatCog(commands.Cog):
    """Cross-server global chat with webhook relay and edit/delete synchronization."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # In-memory map: {guild_id: {"channel_id": int, "webhook_url": str}}
        self.channels_cache: dict[int, dict] = {}
        self.session: Optional[aiohttp.ClientSession] = None

    async def cog_load(self):
        """Initialize HTTP session, MongoDB indexes, and channel cache."""
        self.session = aiohttp.ClientSession()

        # Ensure fast lookups for edit/delete sync and auto-cleanup after 7 days
        await cross_messages_col.create_index("source_msg_id")
        await cross_messages_col.create_index(
            "created_at", expireAfterSeconds=LOG_RETENTION_DAYS * 86400
        )

        await self.refresh_channels()

    async def cog_unload(self):
        """Close the shared HTTP session cleanly when unloading the cog."""
        if self.session and not self.session.closed:
            await self.session.close()

    async def refresh_channels(self):
        """Load all configured cross-chat channels from MongoDB into memory."""
        new_cache: dict[int, dict] = {}
        async for doc in boss_channels_col.find({}):
            guild_id = doc.get("guild_id")
            channel_id = doc.get("channel_id")
            webhook_url = doc.get("webhook_url")
            if guild_id and channel_id and webhook_url:
                new_cache[int(guild_id)] = {
                    "channel_id": int(channel_id),
                    "webhook_url": webhook_url,
                }
        self.channels_cache = new_cache
        logger.info("[CrossChat] Loaded %d linked channel(s).", len(self.channels_cache))

    def _is_linked_channel(self, guild_id: int, channel_id: int) -> bool:
        cfg = self.channels_cache.get(guild_id)
        return bool(cfg and cfg["channel_id"] == channel_id)

    @staticmethod
    def _extract_content(message: discord.Message) -> str:
        """Combine text content and attachment URLs safely within Discord's 2000-char limit."""
        content = message.content or ""
        if message.attachments:
            att_urls = "\n".join(att.url for att in message.attachments)
            content = f"{content}\n{att_urls}" if content else att_urls
        return content[:2000]

    @app_commands.command(
        name="setup_cross_chat",
        description="Link or unlink a channel for Cross-Server Global Chat.",
    )
    @app_commands.describe(
        channel="Target text channel to link (leave empty to disable cross-chat on this server)."
    )
    @app_commands.default_permissions(administrator=True)
    @is_admin_or_bot_owner()
    async def setup_cross_chat(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            return await interaction.followup.send(
                "This command can only be used inside a server.", ephemeral=True
            )

        guild_id = interaction.guild.id

        # Disable cross-chat if no channel is provided
        if channel is None:
            await boss_channels_col.delete_one({"guild_id": guild_id})
            self.channels_cache.pop(guild_id, None)
            return await interaction.followup.send(
                "Cross-server chat has been **disabled** for this server.",
                ephemeral=True,
            )

        try:
            webhooks = await channel.webhooks()
            webhook = next(
                (w for w in webhooks if w.user == self.bot.user and w.token),
                None,
            ) or await channel.create_webhook(name=WEBHOOK_NAME)

            await boss_channels_col.update_one(
                {"guild_id": guild_id},
                {"$set": {"channel_id": channel.id, "webhook_url": webhook.url}},
                upsert=True,
            )
            self.channels_cache[guild_id] = {
                "channel_id": channel.id,
                "webhook_url": webhook.url,
            }
            await interaction.followup.send(
                f"Global chat linked to {channel.mention} "
                f"({len(self.channels_cache)} server(s) connected).",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "Error: Missing `Manage Webhooks` permission in that channel.",
                ephemeral=True,
            )
        except Exception as exc:
            logger.exception("[CrossChat] Setup failed for guild %s", guild_id)
            await interaction.followup.send(f"Setup failed: {exc}", ephemeral=True)

    async def _send_single_webhook(
        self,
        target_channel_id: int,
        webhook_url: str,
        content: str,
        username: str,
        avatar_url: Optional[str],
    ) -> Optional[dict]:
        """Send one relayed message and return tracking metadata for edit/delete sync."""
        try:
            webhook = discord.Webhook.from_url(webhook_url, session=self.session)
            sent_msg = await webhook.send(
                content=content,
                username=username,
                avatar_url=avatar_url,
                allowed_mentions=discord.AllowedMentions.none(),
                wait=True,
            )
            return {
                "webhook_url": webhook_url,
                "channel_id": target_channel_id,
                "message_id": sent_msg.id,
            }
        except Exception as exc:
            logger.warning(
                "[CrossChat] Relay failed to channel %s: %s", target_channel_id, exc
            )
            return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.webhook_id is not None or not message.guild:
            return
        if not self._is_linked_channel(message.guild.id, message.channel.id):
            return

        content = self._extract_content(message)
        if not content.strip():
            return

        targets = [
            cfg
            for gid, cfg in self.channels_cache.items()
            if gid != message.guild.id and cfg["channel_id"] != message.channel.id
        ]
        if not targets:
            return

        formatted_username = f"[{message.guild.name[:15]}] {message.author.display_name}"
        if len(formatted_username) > 80:
            formatted_username = formatted_username[:77] + "..."

        avatar_url = (
            message.author.display_avatar.url if message.author.display_avatar else None
        )

        results = await asyncio.gather(
            *(
                self._send_single_webhook(
                    target_channel_id=cfg["channel_id"],
                    webhook_url=cfg["webhook_url"],
                    content=content,
                    username=formatted_username,
                    avatar_url=avatar_url,
                )
                for cfg in targets
            ),
            return_exceptions=True,
        )

        sent_targets = [res for res in results if isinstance(res, dict)]
        if sent_targets:
            await cross_messages_col.insert_one(
                {
                    "source_msg_id": message.id,
                    "source_channel_id": message.channel.id,
                    "targets": sent_targets,
                    "created_at": datetime.now(timezone.utc),
                }
            )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.author.bot or not after.guild:
            return
        if not self._is_linked_channel(after.guild.id, after.channel.id):
            return

        new_content = self._extract_content(after)
        if not new_content.strip():
            return

        log = await cross_messages_col.find_one({"source_msg_id": before.id})
        if not log:
            return

        tasks = []
        for target in log.get("targets", []):
            webhook = discord.Webhook.from_url(target["webhook_url"], session=self.session)
            tasks.append(
                webhook.edit_message(
                    target["message_id"],
                    content=new_content,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not self._is_linked_channel(message.guild.id, message.channel.id):
            return

        log = await cross_messages_col.find_one({"source_msg_id": message.id})
        if not log:
            return

        tasks = []
        for target in log.get("targets", []):
            webhook = discord.Webhook.from_url(target["webhook_url"], session=self.session)
            tasks.append(webhook.delete_message(target["message_id"]))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        await cross_messages_col.delete_one({"_id": log["_id"]})

    async def broadcast_system_message(self, content: str):
        """Broadcast a system notice to all linked cross-chat channels."""
        if not content.strip() or not self.channels_cache:
            return
        tasks = [
            discord.Webhook.from_url(cfg["webhook_url"], session=self.session).send(
                content=content[:2000],
                username="SYSTEM",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            for cfg in self.channels_cache.values()
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CrossChatCog(bot))