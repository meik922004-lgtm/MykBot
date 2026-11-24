import asyncio
import re
from datetime import datetime, timedelta, timezone
from bson.objectid import ObjectId
import discord
from discord import app_commands
from discord.ext import commands, tasks
from Database import players_col, parties_col, news_channel_col as server_configs_col
from utils.checks import is_admin_or_bot_owner


# ==========================================
# HELPER FUNCTIONS
# ==========================================
def get_discord_timestamp(time_str: str, tz_offset: float = 7.0) -> str:
    """Convert an HH:MM string in the user's timezone into dynamic Discord timestamps."""
    try:
        user_tz = timezone(timedelta(hours=float(tz_offset)))
        now = datetime.now(user_tz)
        target_time = datetime.strptime(time_str.strip(), "%H:%M").time()
        dt = datetime.combine(now.date(), target_time, tzinfo=user_tz)
        if dt < now:
            dt += timedelta(days=1)
        unix_ts = int(dt.timestamp())
        return f"<t:{unix_ts}:t> (<t:{unix_ts}:R>)"
    except Exception:
        return time_str


async def get_player_profile(user_id: int) -> dict | None:
    return await players_col.find_one({"user_id": user_id})


def is_profile_complete(profile: dict | None) -> bool:
    """Verify that the player has registered both an IGN and a Timezone."""
    if not profile or not profile.get("ign") or profile.get("ign") == "Not Set":
        return False
    if "tz_offset" not in profile and "timezone" not in profile:
        return False
    return True


def create_party_embed(party: dict) -> discord.Embed:
    """Build the standardized Party status embed used in DMs and Server Boards."""
    embed = discord.Embed(
        title=f"⚔️ Party: {party.get('dg_name', 'Unknown Dungeon')}",
        color=discord.Color.blue(),
    )
    embed.add_field(name="👑 Leader", value=party.get("leader_ign", "Unknown"), inline=True)
    embed.add_field(name="⏰ Start Time", value=party.get("start_time", "N/A"), inline=True)
    embed.add_field(name="📋 Requirements", value=party.get("requirements") or "None", inline=False)

    members = party.get("members", [])
    members_lines = []
    for idx, member in enumerate(members, start=1):
        clean_role = member.get("role", "Member").split("(")[0].strip().upper()
        members_lines.append(f"{idx}. <@{member.get('user_id')}> - **{member.get('ign', 'Unknown')}** (`{clean_role}`)")

    embed.add_field(
        name=f"👥 Members ({len(members)}/4)",
        value="\n".join(members_lines) or "Empty",
        inline=False,
    )
    return embed


def build_lobby_embed(parties: list[dict], page: int, items_per_page: int = 5) -> discord.Embed:
    """Build a paginated Party Lobby embed."""
    max_pages = max(1, (len(parties) - 1) // items_per_page + 1)
    embed = discord.Embed(
        title="🌐 Party Finder Lobby",
        description=f"Page {page + 1}/{max_pages}" if parties else "No active parties found right now.",
        color=discord.Color.purple(),
    )
    for p in parties[page * items_per_page : (page + 1) * items_per_page]:
        embed.add_field(
            name=f"🎮 {p.get('dg_name', 'Unknown')} | Start: {p.get('start_time', 'ASAP')}",
            value=(
                f"👤 Leader: **{p.get('leader_ign', 'Unknown')}**\n"
                f"👥 Members: `{len(p.get('members', []))}/4`\n"
                f"📝 Req: *{p.get('requirements') or 'None'}*"
            ),
            inline=False,
        )
    return embed


async def _do_single_edit(bot: commands.Bot, channel_id: int, message_id: int, embed: discord.Embed):
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        if channel:
            msg = await channel.fetch_message(message_id)
            await msg.edit(embed=embed)
    except Exception:
        pass


async def update_broadcast_messages(bot: commands.Bot, party_id: str):
    """Sync updated party status across all server party boards."""
    if not ObjectId.is_valid(party_id):
        return
    party = await parties_col.find_one({"_id": ObjectId(party_id)})
    if not party:
        return
    embed = create_party_embed(party)
    edit_tasks = [
        _do_single_edit(bot, msg_data["channel_id"], msg_data["message_id"], embed)
        for msg_data in party.get("broadcasts", [])
    ]
    if edit_tasks:
        await asyncio.gather(*edit_tasks, return_exceptions=True)


async def update_party_lobby_dms(bot: commands.Bot, party_id: str):
    """Sync the live party control panel inside every member's DM."""
    if not ObjectId.is_valid(party_id):
        return
    party = await parties_col.find_one({"_id": ObjectId(party_id)})
    if not party:
        return

    embed = create_party_embed(party)
    leader_id = party.get("leader_id")

    async def _edit_dm(member: dict):
        dm_msg_id = member.get("dm_message_id")
        if not dm_msg_id:
            return
        try:
            user = bot.get_user(member["user_id"]) or await bot.fetch_user(member["user_id"])
            dm_channel = user.dm_channel or await user.create_dm()
            msg = await dm_channel.fetch_message(dm_msg_id)
            view = PartyLobbyDMView(bot, str(party_id), user_id=member["user_id"], leader_id=leader_id)
            await msg.edit(embed=embed, view=view)
        except Exception:
            pass

    dm_tasks = [_edit_dm(m) for m in party.get("members", [])]
    if dm_tasks:
        await asyncio.gather(*dm_tasks, return_exceptions=True)


async def broadcast_to_all_servers(bot: commands.Bot, embed: discord.Embed, party_id_str: str, dg_name: str) -> list[dict]:
    """Post a party recruitment card to every server's configured party board channel."""
    broadcasts = []
    view = BroadcastView(party_id=party_id_str)

    guild_ids = [g.id for g in bot.guilds]
    configs_cursor = server_configs_col.find({"guild_id": {"$in": guild_ids}}, {"guild_id": 1, "party_channel_id": 1})
    config_map = {doc["guild_id"]: doc.get("party_channel_id") async for doc in configs_cursor}

    keywords = [k for k in re.findall(r"\b\w+\b", dg_name.lower()) if len(k) >= 3 and k not in ("dungeon", "dg")]

    for guild in bot.guilds:
        chan_id = config_map.get(guild.id)
        channel = guild.get_channel(chan_id) if chan_id else discord.utils.get(guild.text_channels, name="party-board")
        if not channel:
            continue
        try:
            content_ping = ""
            if keywords:
                matched_roles = [r.mention for r in guild.roles if any(k in r.name.lower() for k in keywords)]
                if matched_roles:
                    content_ping = " ".join(matched_roles)
            msg = await channel.send(content=content_ping, embed=embed, view=view)
            broadcasts.append({"channel_id": channel.id, "message_id": msg.id})
        except Exception:
            pass

    return broadcasts


# ==========================================
# VIEWS & MODALS
# ==========================================
class PartyLobbyDMView(discord.ui.View):
    """Interactive party management panel sent directly to each member's DM."""

    def __init__(self, bot: commands.Bot, party_id: str, user_id: int, leader_id: int):
        super().__init__(timeout=3600)
        self.bot = bot
        self.party_id = party_id
        self.user_id = user_id
        self.leader_id = leader_id

        is_leader = (user_id == leader_id)
        self.edit_party_info.disabled = not is_leader
        self.broadcast_party.disabled = not is_leader

        if is_leader:
            self.exit_party.label = "❌ Disband Party"
            self.exit_party.style = discord.ButtonStyle.danger
        else:
            self.exit_party.label = "🚪 Leave Party"
            self.exit_party.style = discord.ButtonStyle.secondary

    @discord.ui.button(label="✏️ Edit Party Info", style=discord.ButtonStyle.primary, row=0)
    async def edit_party_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        party_data = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        if not party_data:
            return await interaction.response.send_message("❌ This party no longer exists.", ephemeral=True)
        if interaction.user.id != party_data.get("leader_id"):
            return await interaction.response.send_message("❌ Only the Party Leader can edit party info.", ephemeral=True)
        await interaction.response.send_modal(EditPartyInfoModal(party_data, self.bot))

    @discord.ui.button(label="📢 Broadcast Party", style=discord.ButtonStyle.success, row=0)
    async def broadcast_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        party_data = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        if not party_data:
            return await interaction.followup.send("❌ This party no longer exists.", ephemeral=True)
        if interaction.user.id != party_data.get("leader_id"):
            return await interaction.followup.send("❌ Only the Party Leader can broadcast recruitment.", ephemeral=True)

        embed = create_party_embed(party_data)
        broadcast_records = await broadcast_to_all_servers(self.bot, embed, self.party_id, party_data.get("dg_name", ""))
        if broadcast_records:
            await parties_col.update_one({"_id": ObjectId(self.party_id)}, {"$set": {"broadcasts": broadcast_records}})
        await interaction.followup.send("📢 Party recruitment card has been broadcast to all servers!", ephemeral=True)

    @discord.ui.button(label="🚪 Leave / Disband", style=discord.ButtonStyle.danger, row=1)
    async def exit_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        party_data = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        if not party_data:
            return await interaction.followup.send("❌ This party no longer exists.", ephemeral=True)

        if party_data.get("leader_id") == interaction.user.id:
            await handle_cross_server_chat(
                self.bot,
                party_data,
                action="delete",
                msg_override=f"❌ The party for **{party_data.get('dg_name')}** has been disbanded by the Leader.",
            )
            await parties_col.delete_one({"_id": ObjectId(self.party_id)})
            await interaction.followup.send("💥 You have disbanded the party.", ephemeral=True)
        else:
            await parties_col.update_one(
                {"_id": ObjectId(self.party_id)},
                {"$pull": {"members": {"user_id": interaction.user.id}}},
            )
            await interaction.followup.send("✅ You have left the party.", ephemeral=True)
            await handle_cross_server_chat(self.bot, party_data, interaction.user.id, action="remove")
            await update_party_lobby_dms(self.bot, self.party_id)
            await update_broadcast_messages(self.bot, self.party_id)


class BroadcastView(discord.ui.View):
    """Persistent buttons attached to broadcast party cards in server channels."""

    def __init__(self, party_id: str | None = None):
        super().__init__(timeout=None)
        if party_id:
            self.add_item(discord.ui.Button(label="📩 Send Request", style=discord.ButtonStyle.success, custom_id=f"bcast_join_{party_id}"))
        self.add_item(discord.ui.Button(label="🌐 Open Lobby UI", style=discord.ButtonStyle.primary, custom_id="bcast_lobby"))


class RequestJoinView(discord.ui.View):
    """Accept/Reject buttons sent to the Party Leader via DM when a player applies."""

    def __init__(self, bot: commands.Bot, party_id: str, applicant_id: int, applicant_ign: str, applicant_role: str):
        super().__init__(timeout=3600)
        self.bot = bot
        self.party_id = party_id
        self.applicant_id = applicant_id
        self.applicant_ign = applicant_ign
        self.applicant_role = applicant_role

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        if await parties_col.find_one({"members.user_id": self.applicant_id}):
            for child in self.children:
                child.disabled = True
            return await interaction.edit_original_response(content="⚠️ This player has already joined another party.", view=self)

        new_member = {"user_id": self.applicant_id, "ign": self.applicant_ign, "role": self.applicant_role}
        res = await parties_col.update_one(
            {
                "_id": ObjectId(self.party_id),
                "members.user_id": {"$ne": self.applicant_id},
                "$expr": {"$lt": [{"$size": "$members"}, 4]},
            },
            {"$push": {"members": new_member}},
        )

        if res.modified_count == 0:
            for child in self.children:
                child.disabled = True
            return await interaction.edit_original_response(
                content="❌ Unable to accept (Party is already full 4/4 or no longer exists).",
                view=self,
            )

        updated_party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        try:
            applicant = self.bot.get_user(self.applicant_id) or await self.bot.fetch_user(self.applicant_id)
            dm_channel = applicant.dm_channel or await applicant.create_dm()
            embed = create_party_embed(updated_party)
            view = PartyLobbyDMView(self.bot, self.party_id, user_id=self.applicant_id, leader_id=updated_party.get("leader_id"))
            msg = await dm_channel.send(
                content=f"🎉 Leader **{updated_party.get('leader_ign')}** accepted your request to join the party!",
                embed=embed,
                view=view,
            )
            await parties_col.update_one(
                {"_id": ObjectId(self.party_id), "members.user_id": self.applicant_id},
                {"$set": {"members.$.dm_message_id": msg.id}},
            )
        except discord.Forbidden:
            pass

        await update_party_lobby_dms(self.bot, self.party_id)
        await update_broadcast_messages(self.bot, self.party_id)
        await handle_cross_server_chat(self.bot, updated_party, self.applicant_id, action="add")

        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(content="✅ Request accepted.", view=self)
        self.stop()

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(content="❌ Request rejected.", view=self)
        self.stop()

        try:
            applicant = self.bot.get_user(self.applicant_id) or await self.bot.fetch_user(self.applicant_id)
            if applicant and party:
                await applicant.send(f"💔 Your request to join **{party.get('dg_name')}** was declined.")
        except discord.Forbidden:
            pass


class LobbyPaginationView(discord.ui.View):
    """Paginated Party Lobby browser view."""

    def __init__(self, bot: commands.Bot, parties: list[dict], page: int = 0):
        super().__init__(timeout=300)
        self.bot = bot
        self.parties = parties
        self.page = page
        self.items_per_page = 5
        self.max_pages = max(1, (len(parties) - 1) // self.items_per_page + 1)

        current_parties = self.parties[self.page * self.items_per_page : (self.page + 1) * self.items_per_page]
        if current_parties:
            options = [
                discord.SelectOption(
                    label=f"{p.get('dg_name', 'Unknown')} (Ldr: {p.get('leader_ign', 'Unknown')})"[:100],
                    description=f"{len(p.get('members', []))}/4 - {p.get('start_time', 'N/A')}"[:100],
                    value=str(p["_id"]),
                )
                for p in current_parties
            ]
            self.select = discord.ui.Select(placeholder="Select a party to request to join...", options=options, row=0)
            self.select.callback = self.send_request_callback
            self.add_item(self.select)

    async def send_request_callback(self, interaction: discord.Interaction):
        profile = await get_player_profile(interaction.user.id)
        if not is_profile_complete(profile):
            return await interaction.response.send_message(
                "❌ Please set up your IGN and Timezone via `/menu` → **Profile & Timezone** first!",
                ephemeral=True,
            )
        if await parties_col.find_one({"members.user_id": interaction.user.id}):
            return await interaction.response.send_message("❌ You are already in an active party.", ephemeral=True)
        await interaction.response.send_modal(JoinPartyModal(self.bot, self.select.values[0]))

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_lobby(interaction, max(0, self.page - 1))

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.blurple, row=1)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_lobby(interaction, self.page)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_lobby(interaction, min(self.max_pages - 1, self.page + 1))

    @discord.ui.button(label="➕ Create Party", style=discord.ButtonStyle.success, row=2)
    async def create_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        profile = await get_player_profile(interaction.user.id)
        if not is_profile_complete(profile):
            return await interaction.response.send_message(
                "❌ Please set up your IGN and Timezone via `/menu` → **Profile & Timezone** first!",
                ephemeral=True,
            )
        if await parties_col.find_one({"members.user_id": interaction.user.id}):
            return await interaction.response.send_message("❌ You are already in an active party!", ephemeral=True)
        await interaction.response.send_modal(CreatePartyModal(self.bot, self, interaction))

    @discord.ui.button(label="⚙️ Manage My Party", style=discord.ButtonStyle.primary, row=2)
    async def manage_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        party = await parties_col.find_one({"members.user_id": interaction.user.id})
        if not party:
            return await interaction.followup.send("You are not currently in any party.", ephemeral=True)

        try:
            dm_channel = interaction.user.dm_channel or await interaction.user.create_dm()
            embed = create_party_embed(party)
            view = PartyLobbyDMView(self.bot, str(party["_id"]), user_id=interaction.user.id, leader_id=party.get("leader_id"))
            msg = await dm_channel.send(embed=embed, view=view)
            await parties_col.update_one(
                {"_id": party["_id"], "members.user_id": interaction.user.id},
                {"$set": {"members.$.dm_message_id": msg.id}},
            )
            await interaction.followup.send("✅ Sent the Party Management panel to your DMs!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Cannot send DMs. Please enable Direct Messages in your server privacy settings.", ephemeral=True)

    async def update_lobby(self, target: discord.Interaction, new_page: int):
        fresh_parties = await parties_col.find({}).to_list(length=100)
        view = LobbyPaginationView(self.bot, fresh_parties, new_page)
        embed = build_lobby_embed(fresh_parties, new_page, view.items_per_page)

        if not target.response.is_done():
            await target.response.edit_message(embed=embed, view=view)
        else:
            await target.edit_original_response(embed=embed, view=view)


class JoinPartyModal(discord.ui.Modal, title="Apply to Join Party"):
    """Modal asking the applicant what role they want to fill in the party."""

    role = discord.ui.TextInput(
        label="Your Role (e.g., DPS, TANK, UFM, Any)",
        placeholder="Enter the role you are applying for...",
        required=True,
        max_length=30,
    )

    def __init__(self, bot: commands.Bot, party_id: str):
        super().__init__()
        self.bot = bot
        self.party_id = party_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not ObjectId.is_valid(self.party_id):
            return await interaction.followup.send("❌ Invalid party ID.", ephemeral=True)

        party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        profile = await get_player_profile(interaction.user.id)
        if not party or not is_profile_complete(profile):
            return await interaction.followup.send("❌ Party not found or your profile is incomplete.", ephemeral=True)

        applicant_ign = profile.get("ign")
        role_entered = self.role.value.strip()
        raw_tz = profile.get("tz_offset", profile.get("timezone", 0))
        tz_val = float(raw_tz)
        tz_label = f"UTC{'+' if tz_val >= 0 else ''}{tz_val:g}"

        try:
            leader = self.bot.get_user(party.get("leader_id", 0)) or await self.bot.fetch_user(party.get("leader_id", 0))
            embed = discord.Embed(title="📩 New Party Join Request!", color=discord.Color.green())
            embed.add_field(name="Applicant (IGN)", value=f"**{applicant_ign}** (<@{interaction.user.id}>)", inline=True)
            embed.add_field(name="Role Requested", value=f"**{role_entered.upper()}**", inline=True)
            embed.add_field(name="Timezone", value=tz_label, inline=True)
            await leader.send(
                embed=embed,
                view=RequestJoinView(self.bot, self.party_id, interaction.user.id, applicant_ign, role_entered),
            )
            await interaction.followup.send("✅ Join request sent to the Party Leader!", ephemeral=True)
        except (discord.Forbidden, discord.NotFound):
            await interaction.followup.send("❌ Unable to DM the Party Leader.", ephemeral=True)


class CreatePartyModal(discord.ui.Modal, title="Create New Party"):
    """Modal for creating a new cross-server dungeon/raid party."""

    dg_name = discord.ui.TextInput(label="Dungeon / Raid Name", placeholder="e.g., FDGH, RBH, MDG...", required=True, max_length=60)
    role = discord.ui.TextInput(label="Your Role (e.g., DPS, TANK, UFM)", required=True, max_length=30)
    start_time = discord.ui.TextInput(label="Start Time (HH:MM in your timezone)", placeholder="e.g., 20:30", required=True, max_length=20)
    requirements = discord.ui.TextInput(label="Requirements (Optional)", style=discord.TextStyle.paragraph, required=False, max_length=300)

    def __init__(self, bot: commands.Bot, lobby_view: LobbyPaginationView, parent_interaction: discord.Interaction):
        super().__init__()
        self.bot = bot
        self.lobby_view = lobby_view
        self.parent_interaction = parent_interaction

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await get_player_profile(interaction.user.id)
        if not is_profile_complete(profile):
            return await interaction.followup.send(
                "⚠️ Please configure your IGN and Timezone via `/menu` → **Profile & Timezone** first.",
                ephemeral=True,
            )

        tz_offset = float(profile.get("tz_offset", profile.get("timezone", 7.0)))
        formatted_time = get_discord_timestamp(self.start_time.value.strip(), tz_offset)
        leader_ign = profile.get("ign")
        role_entered = self.role.value.strip()

        party_doc = {
            "leader_id": interaction.user.id,
            "leader_ign": leader_ign,
            "dg_name": self.dg_name.value.strip(),
            "start_time": formatted_time,
            "requirements": self.requirements.value.strip(),
            "members": [{"user_id": interaction.user.id, "ign": leader_ign, "role": role_entered, "dm_message_id": None}],
            "broadcasts": [],
        }

        result = await parties_col.insert_one(party_doc)
        party_id_str = str(result.inserted_id)
        party_doc["_id"] = result.inserted_id

        try:
            dm_channel = interaction.user.dm_channel or await interaction.user.create_dm()
            embed = create_party_embed(party_doc)
            view = PartyLobbyDMView(self.bot, party_id_str, user_id=interaction.user.id, leader_id=interaction.user.id)
            msg = await dm_channel.send(embed=embed, view=view)
            await parties_col.update_one(
                {"_id": result.inserted_id, "members.user_id": interaction.user.id},
                {"$set": {"members.$.dm_message_id": msg.id}},
            )
        except discord.Forbidden:
            pass

        await handle_cross_server_chat(self.bot, party_doc, action="create")

        embed = create_party_embed(party_doc)
        broadcast_records = await broadcast_to_all_servers(self.bot, embed, party_id_str, party_doc["dg_name"])
        if broadcast_records:
            await parties_col.update_one({"_id": result.inserted_id}, {"$set": {"broadcasts": broadcast_records}})

        await interaction.followup.send("✅ Party created! Check your DMs to manage your party.", ephemeral=True)
        await self.lobby_view.update_lobby(self.parent_interaction, self.lobby_view.page)


class EditPartyInfoModal(discord.ui.Modal, title="Edit Party Information"):
    """Modal allowing the Party Leader to edit dungeon name, start time, or requirements."""

    new_name = discord.ui.TextInput(label="Dungeon / Raid Name", required=True, max_length=60)
    new_time = discord.ui.TextInput(label="Start Time (HH:MM) - Leave blank to keep", required=False, max_length=20)
    new_req = discord.ui.TextInput(label="Requirements", style=discord.TextStyle.paragraph, required=False, max_length=300)

    def __init__(self, party: dict, bot: commands.Bot):
        super().__init__()
        self.party = party
        self.bot = bot
        self.new_name.default = party.get("dg_name", "")
        self.new_req.default = party.get("requirements", "")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        update_data = {"dg_name": self.new_name.value.strip(), "requirements": self.new_req.value.strip()}
        if self.new_time.value.strip():
            profile = await get_player_profile(interaction.user.id)
            tz = float(profile.get("tz_offset", profile.get("timezone", 7.0))) if profile else 7.0
            update_data["start_time"] = get_discord_timestamp(self.new_time.value.strip(), tz)

        await parties_col.update_one({"_id": self.party["_id"]}, {"$set": update_data})
        await asyncio.gather(
            update_broadcast_messages(self.bot, str(self.party["_id"])),
            update_party_lobby_dms(self.bot, str(self.party["_id"])),
            return_exceptions=True,
        )
        await interaction.followup.send("✅ Party information updated!", ephemeral=True)


# ==========================================
# CROSS-SERVER DM CHAT RELAY
# ==========================================
async def _safe_dm(bot: commands.Bot, user_id: int, content: str):
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        if user:
            await user.send(content)
    except Exception:
        pass


async def handle_cross_server_chat(bot: commands.Bot, party: dict, user_id: int | None = None, action: str = "create", msg_override: str | None = None):
    dg_name = party.get("dg_name", "Unknown Dungeon")
    members = party.get("members", [])

    if msg_override:
        await asyncio.gather(*[_safe_dm(bot, m["user_id"], msg_override) for m in members], return_exceptions=True)
        return

    if action == "create":
        await _safe_dm(bot, party.get("leader_id", 0), f"✅ **Party Chat Started!** Send messages directly here in DM to chat with your **{dg_name}** party.")
    elif action == "add" and user_id:
        new_ign = next((m.get("ign", "New member") for m in members if m["user_id"] == user_id), "New member")
        dm_tasks = [_safe_dm(bot, user_id, f"👋 **Party Chat Joined!** You are now in the party chat for **{dg_name}**.")]
        for m in members:
            if m["user_id"] != user_id:
                dm_tasks.append(_safe_dm(bot, m["user_id"], f"📥 **{new_ign}** has joined the party chat!"))
        await asyncio.gather(*dm_tasks, return_exceptions=True)
    elif action == "remove" and user_id:
        left_ign = next((m.get("ign", "A member") for m in members if m["user_id"] == user_id), "A member")
        dm_tasks = [
            _safe_dm(bot, m["user_id"], f"🚪 **{left_ign}** has left the party chat.")
            for m in members if m["user_id"] != user_id
        ]
        if dm_tasks:
            await asyncio.gather(*dm_tasks, return_exceptions=True)


# ==========================================
# COG
# ==========================================
class PartyFinderCog(commands.Cog):
    """Cross-server party finder, DM relay chat, and party board broadcaster."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auto_cleanup_parties.start()

    def cog_unload(self):
        self.auto_cleanup_parties.cancel()

    @tasks.loop(hours=1.0)
    async def auto_cleanup_parties(self):
        """Automatically disband parties older than 24 hours."""
        threshold_time = datetime.now(timezone.utc) - timedelta(days=1)
        threshold_id = ObjectId.from_datetime(threshold_time)
        expired_parties = await parties_col.find({"_id": {"$lt": threshold_id}}).to_list(length=None)
        if not expired_parties:
            return

        for party in expired_parties:
            await handle_cross_server_chat(
                self.bot,
                party,
                action="delete",
                msg_override=f"⏳ The party for **{party.get('dg_name')}** was automatically disbanded after 24 hours.",
            )
        deleted = await parties_col.delete_many({"_id": {"$lt": threshold_id}})
        print(f"[PartyFinder] Auto-cleaned {deleted.deleted_count} expired parties.", flush=True)

    @auto_cleanup_parties.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Relay Direct Messages among active party members."""
        if message.author.bot or message.guild is not None:
            return
        party = await parties_col.find_one({"members.user_id": message.author.id})
        if not party:
            return

        sender_ign = next(
            (m.get("ign", message.author.name) for m in party.get("members", []) if m["user_id"] == message.author.id),
            message.author.name,
        )
        chat_content = f"**[{party.get('dg_name', 'Party')}] {sender_ign}:** {message.content}"
        if message.attachments:
            chat_content += "\n" + "\n".join(att.url for att in message.attachments)

        send_tasks = [
            _safe_dm(self.bot, m["user_id"], chat_content)
            for m in party.get("members", [])
            if m["user_id"] != message.author.id
        ]
        if send_tasks:
            await asyncio.gather(*send_tasks, return_exceptions=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Handle persistent broadcast card buttons."""
        if not interaction.data:
            return
        custom_id = interaction.data.get("custom_id", "")

        if custom_id.startswith("bcast_join_"):
            party_id_str = custom_id.replace("bcast_join_", "")
            if not ObjectId.is_valid(party_id_str):
                return await interaction.response.send_message("❌ This party is no longer valid.", ephemeral=True)
            profile = await get_player_profile(interaction.user.id)
            if not is_profile_complete(profile):
                return await interaction.response.send_message(
                    "❌ Please set up your IGN and Timezone via `/menu` → **Profile & Timezone** first!",
                    ephemeral=True,
                )
            if await parties_col.find_one({"members.user_id": interaction.user.id}):
                return await interaction.response.send_message("❌ You are already in an active party!", ephemeral=True)
            await interaction.response.send_modal(JoinPartyModal(self.bot, party_id_str))

        elif custom_id == "bcast_lobby":
            await self.open_party_lobby(interaction)

    # --- HELPERS INVOKED BY /menu ---
    async def open_party_lobby(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        profile = await get_player_profile(interaction.user.id)
        if not is_profile_complete(profile):
            return await interaction.followup.send(
                "❌ Your profile is incomplete! Please set your IGN and Timezone via `/menu` → **Profile & Timezone** first.",
                ephemeral=True,
            )

        parties = await parties_col.find({}).to_list(length=100)
        view = LobbyPaginationView(self.bot, parties, page=0)
        embed = build_lobby_embed(parties, 0, view.items_per_page)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def open_my_party(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        party = await parties_col.find_one({"members.user_id": interaction.user.id})
        if not party:
            return await interaction.followup.send("❌ You are not currently in any active party.", ephemeral=True)

        try:
            dm_channel = interaction.user.dm_channel or await interaction.user.create_dm()
            embed = create_party_embed(party)
            view = PartyLobbyDMView(self.bot, str(party["_id"]), user_id=interaction.user.id, leader_id=party.get("leader_id"))
            msg = await dm_channel.send(embed=embed, view=view)
            await parties_col.update_one(
                {"_id": party["_id"], "members.user_id": interaction.user.id},
                {"$set": {"members.$.dm_message_id": msg.id}},
            )
            await interaction.followup.send("✅ Sent your active Party Management panel to your DMs!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Unable to send DMs. Please check your privacy settings.", ephemeral=True)

    # --- ADMIN / OWNER SETUP COMMAND ---
    @app_commands.command(
        name="setup_party_channel",
        description="[Admin/Owner] Set the channel for cross-server party recruitment cards",
    )
    @app_commands.describe(channel="Target text channel for the Party Board")
    @app_commands.default_permissions(administrator=True)
    @is_admin_or_bot_owner()
    async def setup_party_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        await server_configs_col.update_one(
            {"guild_id": interaction.guild_id},
            {"$set": {"party_channel_id": channel.id}},
            upsert=True,
        )
        await interaction.followup.send(f"✅ Party Board channel configured: {channel.mention}", ephemeral=True)


async def setup(bot: commands.Bot):
    bot.add_view(BroadcastView())
    await bot.add_cog(PartyFinderCog(bot))