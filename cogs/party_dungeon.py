import discord
from discord.ext import commands, tasks
from bson.objectid import ObjectId
import asyncio
import re
from datetime import datetime, timedelta, timezone
from database import players_col, parties_col, db

GEAR_OPTIONS = ["Full fang gear", "1 piece of Spiral", "2 piece of Spiral", "Full Spiral set", "1 piece of corrupted", "2 piece of corrupted", "full set of corrupted", "Other"]
VICE_OPTIONS = {
    "AA": ["D.ark 4", "D,ark 5", "D.ark 6", "D.ark Uncontroll", "Void vice", "Other"],
    "SK": ["Royal Vice","Truevice", "Truevice(Advance)", "Void vice", "Other"],
    "TANK": ["D.ark 6", "D.ark Chrome", "Void vice", "Other"]
}
DECK_OPTIONS = {
    "AA": ["Divinus", "CrimsonPath/Corrupted Power", "Power of Darkness / Crimson Nexus", "Eclipsed Genesis", "Other"],
    "SK": ["Celesfracture", "Latent Power", "RoyalKnight X/ DemonLord X", "Legendary Core", "Other"],
    "TANK": ["Fortis Magna", "Crown", "Royal Crown", "Eternal Dominion", "Other"]
}
BRACELET_OPTIONS = ["Bracelet 5 stats", "Ygg Bracelet", "Pied Bracelet"]

def get_discord_timestamp(time_str: str, tz_offset: float = 7.0) -> str:
    try:
        user_tz = timezone(timedelta(hours=float(tz_offset)))
        now = datetime.now(user_tz)
        target_time = datetime.strptime(time_str.strip(), "%H:%M").time()
        dt = datetime.combine(now.date(), target_time, tzinfo=user_tz)
        if dt < now: dt += timedelta(days=1)
        return f"<t:{int(dt.timestamp())}:t> (<t:{int(dt.timestamp())}:R>)"
    except Exception:
        return time_str

async def get_player_profile(user_id: int) -> dict:
    return await players_col.find_one({"user_id": user_id})

def is_profile_complete(profile: dict) -> bool:
    if not profile or not profile.get('ign') or profile.get('ign') == "Not Set": return False
    if 'tz_offset' not in profile or not profile.get('my_stats'): return False
    return True

def create_party_embed(party: dict) -> discord.Embed:
    embed = discord.Embed(title=f"⚔️ Party: {party.get('dg_name', 'Unknown DG')}", color=discord.Color.blue())
    embed.add_field(name="👑 Leader", value=party.get('leader_ign', 'Unknown'), inline=True)
    embed.add_field(name="⏰ Start Time", value=party.get('start_time', 'N/A'), inline=True)
    embed.add_field(name="📋 Yêu cầu", value=party.get('requirements') or "Không", inline=False)
    
    members_text = ""
    for idx, member in enumerate(party.get('members', [])):
        clean_role = member.get('role', 'Unknown').split('(')[0].strip().upper()
        members_text += f"{idx+1}. <@{member.get('user_id')}> - **{member.get('ign', 'Unknown')}** (Role: {clean_role})\n"
        
    embed.add_field(name=f"👥 Thành viên ({len(party.get('members', []))}/4)", value=members_text or "Chưa có", inline=False)
    return embed

async def handle_cross_server_chat(bot, party, user_id=None, action="create", msg_override=None):
    try:
        dg_name = party.get('dg_name', 'Unknown DG')
        if msg_override:
            for m in party.get('members', []):
                u = bot.get_user(m['user_id']) or await bot.fetch_user(m['user_id'])
                if u: await u.send(msg_override)
            return

        if action == "create":
            leader = bot.get_user(party.get('leader_id', 0)) or await bot.fetch_user(party.get('leader_id', 0))
            if leader: await leader.send(f"✅ **Kênh Chat Nhóm Bắt Đầu!** Bạn đang trong Party đi **{dg_name}**.")

        elif action == "add" and user_id:
            member = bot.get_user(user_id) or await bot.fetch_user(user_id)
            if member: await member.send(f"👋 **Đã Vào Chat Nhóm!** Bạn đang tham gia Party đi **{dg_name}**.")
            new_ign = next((m.get('ign') for m in party.get('members', []) if m['user_id'] == user_id), "Thành viên mới")
            for m in party.get('members', []):
                if m['user_id'] != user_id:
                    o = bot.get_user(m['user_id']) or await bot.fetch_user(m['user_id'])
                    if o: await o.send(f"📥 **{new_ign}** đã tham gia kênh chat nhóm!")

        elif action == "remove" and user_id:
            left_ign = next((m.get('ign') for m in party.get('members', []) if m.get('user_id') == user_id), "Thành viên")
            for m in party.get('members', []):
                if m['user_id'] != user_id:
                    o = bot.get_user(m['user_id']) or await bot.fetch_user(m['user_id'])
                    if o: await o.send(f"🚪 **{left_ign}** đã rời kênh chat nhóm.")
    except Exception as e:
        print(f"Lỗi Relay Chat Party: {e}")

class MyGearIGNModal(discord.ui.Modal, title="Setup Profile - IGN"):
    ign = discord.ui.TextInput(label="In-Game Name (IGN)", placeholder="Nhập tên nhân vật...", required=True, max_length=30)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ign_value = self.ign.value.strip()
        await db.players.update_one({"user_id": interaction.user.id}, {"$set": {"ign": ign_value}}, upsert=True)
        embed = discord.Embed(title="⚙️ Setup MyGear", description=f"IGN của bạn đã được cập nhật thành: **{ign_value}**\nVui lòng chọn các thông số thiết lập:", color=discord.Color.blue())
        await interaction.followup.send(embed=embed, view=MyGearWizard(interaction.user.id, {}), ephemeral=True)

class MyGearWizard(discord.ui.View):
    def __init__(self, user_id, player_data=None):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.player_data = player_data or {}
        self.data = {"tz_offset": 7.0, "role": None, "gear": None, "vice": None, "deck": None, "bracelet": None}
        self.step = 1 if "tz_offset" in self.player_data else 0
        self.refresh_menu()

    def refresh_menu(self):
        self.clear_items()
        if self.step == 0:
            options = [discord.SelectOption(label=f"UTC{'+' if i>0 else ''}{i}", value=str(i)) for i in [-8, -5, -3, 0, 1, 2, 3, 4, 7, 8, 9, 10]]
            select = discord.ui.Select(placeholder="🌍 Chọn Múi Giờ", options=options)
            async def tz_cb(inter: discord.Interaction):
                self.data["tz_offset"] = float(inter.data["values"][0])
                self.step = 1
                await self.next_step(inter)
            select.callback = tz_cb
            self.add_item(select)
        elif self.step == 1:
            select = discord.ui.Select(placeholder="Chọn Role", options=[discord.SelectOption(label=r) for r in ["AA", "SK", "TANK"]])
            async def role_cb(inter: discord.Interaction):
                self.data["role"] = inter.data["values"][0]
                self.step = 2
                await self.next_step(inter)
            select.callback = role_cb
            self.add_item(select)
        elif self.step == 2:
            select = discord.ui.Select(placeholder="Chọn Gear", options=[discord.SelectOption(label=g) for g in GEAR_OPTIONS])
            async def gear_cb(inter: discord.Interaction):
                self.data["gear"] = inter.data["values"][0]
                self.step = 3
                await self.next_step(inter)
            select.callback = gear_cb
            self.add_item(select)
        elif self.step == 3:
            select = discord.ui.Select(placeholder="Chọn Vice", options=[discord.SelectOption(label=v) for v in VICE_OPTIONS[self.data["role"]]])
            async def vice_cb(inter: discord.Interaction):
                self.data["vice"] = inter.data["values"][0]
                self.step = 4
                await self.next_step(inter)
            select.callback = vice_cb
            self.add_item(select)
        elif self.step == 4:
            select = discord.ui.Select(placeholder="Chọn Deck", options=[discord.SelectOption(label=d) for d in DECK_OPTIONS[self.data["role"]]])
            async def deck_cb(inter: discord.Interaction):
                self.data["deck"] = inter.data["values"][0]
                self.step = 5
                await self.next_step(inter)
            select.callback = deck_cb
            self.add_item(select)
        elif self.step == 5:
            select = discord.ui.Select(placeholder="Chọn Bracelet", options=[discord.SelectOption(label=b) for b in BRACELET_OPTIONS])
            async def bracelet_cb(inter: discord.Interaction):
                self.data["bracelet"] = inter.data["values"][0]
                self.step = 6
                await self.next_step(inter)
            select.callback = bracelet_cb
            self.add_item(select)

    async def next_step(self, interaction: discord.Interaction):
        if self.step < 6:
            self.refresh_menu()
            embed = discord.Embed(title="⚙️ Setup MyGear", color=discord.Color.blue())
            embed.add_field(name="Hiện tại", value=f"🌍 Timezone: UTC{self.data['tz_offset']}\nRole: {self.data.get('role') or '...'}\nGear: {self.data.get('gear') or '...'}\nVice: {self.data.get('vice') or '...'}\nDeck: {self.data.get('deck') or '...'}\nBracelet: {self.data.get('bracelet') or '...'}")
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            role = self.data["role"]
            stats_data = {k: v for k, v in self.data.items() if k != "tz_offset"}
            await db.players.update_one({"user_id": self.user_id}, {"$set": {"tz_offset": self.data["tz_offset"], f"my_stats.{role}": stats_data}}, upsert=True)
            await interaction.response.edit_message(content=f"✅ Cấu hình thành công cho **{role}**!", embed=None, view=None)

class DungeonListView(discord.ui.View):
    def __init__(self, dungeons):
        super().__init__(timeout=60)
        for dg in dungeons:
            dg_name = dg.get("dg_name")
            btn = discord.ui.Button(label=dg_name.upper(), style=discord.ButtonStyle.primary)
            btn.callback = self.make_callback(dg_name)
            self.add_item(btn)

    def make_callback(self, dg_name):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            player = await db.players.find_one({"user_id": interaction.user.id})
            cfg = await db.dungeon_configs.find_one({"dg_name": dg_name})
            if not cfg or not player or "my_stats" not in player:
                return await interaction.followup.send("❌ Dữ liệu không khả dụng hoặc chưa thiết lập `/hub` -> `MyGear`.", ephemeral=True)
            req = cfg.get("reqs", {})
            embed = discord.Embed(title=f"Kiểm tra yêu cầu: {dg_name.upper()}")
            for r_name, stats in player["my_stats"].items():
                if isinstance(stats, dict):
                    res = [f"{'✅' if stats.get(c) in req.get(c, []) else '❌'} {c.upper()}: {stats.get(c)}" for c in ["gear", "vice", "deck", "bracelet"]]
                    embed.add_field(name=f"Role: {r_name}", value="\n".join(res), inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        return callback

class PartyLobbyDMView(discord.ui.View):
    def __init__(self, bot, party_id: str, user_id: int, leader_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.party_id = party_id
        is_leader = (user_id == leader_id)
        if not is_leader:
            self.exit_party.label = "🚪 Rời Party"
            self.exit_party.style = discord.ButtonStyle.secondary

    @discord.ui.button(label="🚪 Rời / Giải tán", style=discord.ButtonStyle.danger)
    async def exit_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        if not party: return await interaction.followup.send("❌ Party không tồn tại.", ephemeral=True)
        
        if party.get("leader_id") == interaction.user.id:
            await handle_cross_server_chat(self.bot, party, action="delete", msg_override=f"❌ Party **{party.get('dg_name')}** đã bị Trưởng nhóm giải tán.")
            await parties_col.delete_one({"_id": ObjectId(self.party_id)})
            await interaction.followup.send("💥 Đã giải tán đội thành công.", ephemeral=True)
        else:
            await parties_col.update_one({"_id": ObjectId(self.party_id)}, {"$pull": {"members": {"user_id": interaction.user.id}}})
            await interaction.followup.send("✅ Đã rời đội.", ephemeral=True)
            await handle_cross_server_chat(self.bot, party, interaction.user.id, action="remove")

class LobbyPaginationView(discord.ui.View):
    def __init__(self, bot, parties, page=0):
        super().__init__(timeout=None)
        self.bot = bot
        self.parties = parties
        self.page = page
        self.items_per_page = 5
        self.max_pages = max(1, (len(parties) - 1) // self.items_per_page + 1)
        
        curr = self.parties[self.page * self.items_per_page : (self.page + 1) * self.items_per_page]
        if curr:
            options = [discord.SelectOption(label=f"{p.get('dg_name')} (Ldr: {p.get('leader_ign')})", value=str(p['_id'])) for p in curr]
            select = discord.ui.Select(placeholder="Chọn Party muốn gia nhập...", options=options)
            select.callback = self.join_callback
            self.add_item(select)

    async def join_callback(self, interaction: discord.Interaction):
        p_id = interaction.data["values"][0]
        await interaction.response.send_modal(JoinPartyModal(self.bot, p_id))

    @discord.ui.button(label="➕ Tạo Party Mới", style=discord.ButtonStyle.success)
    async def create_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreatePartyModal(self.bot))

class JoinPartyModal(discord.ui.Modal, title='Chọn Role Gia Nhập Party'):
    role = discord.ui.TextInput(label='Role của bạn (Ví dụ: DPS, TANK)', required=True)

    def __init__(self, bot, party_id):
        super().__init__()
        self.bot = bot
        self.party_id = party_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        party = await parties_col.find_one({"_id": ObjectId(self.party_id)})
        profile = await get_player_profile(interaction.user.id)
        if not party or not is_profile_complete(profile):
            return await interaction.followup.send("❌ Cần hoàn tất Profile Gear trước!", ephemeral=True)

        leader = self.bot.get_user(party.get('leader_id', 0)) or await self.bot.fetch_user(party.get('leader_id', 0))
        if leader:
            embed = discord.Embed(title="📩 Yêu Cầu Gia Nhập Party Mới!", color=discord.Color.green())
            embed.add_field(name="Ứng viên", value=profile.get('ign'), inline=True)
            embed.add_field(name="Role", value=self.role.value.upper(), inline=True)
            await leader.send(embed=embed)
            await interaction.followup.send("✅ Đã gửi yêu cầu tới Trưởng nhóm!", ephemeral=True)

class CreatePartyModal(discord.ui.Modal, title='Tạo Party Dungeon Mới'):
    dg_name = discord.ui.TextInput(label='Tên Dungeon', placeholder='Ví dụ: PIED, MDG...', required=True)
    role = discord.ui.TextInput(label='Role của bạn', placeholder='DPS / TANK...', required=True)
    start_time = discord.ui.TextInput(label='Giờ dự kiến (HH:MM)', required=True)
    requirements = discord.ui.TextInput(label='Yêu cầu thêm', style=discord.TextStyle.paragraph, required=False)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await get_player_profile(interaction.user.id)
        if not is_profile_complete(profile):
            return await interaction.followup.send("⚠️ Vui lòng hoàn tất setup Profile Gear trước!", ephemeral=True)

        formatted_time = get_discord_timestamp(self.start_time.value.strip(), float(profile.get('tz_offset', 7.0)))
        party_doc = {
            "leader_id": interaction.user.id, "leader_ign": profile.get('ign'), "dg_name": self.dg_name.value,
            "start_time": formatted_time, "requirements": self.requirements.value,
            "members": [{"user_id": interaction.user.id, "ign": profile.get('ign'), "role": self.role.value.strip(), "dm_message_id": None}]
        }
        res = await parties_col.insert_one(party_doc)
        party_doc["_id"] = res.inserted_id

        try:
            dm = interaction.user.dm_channel or await interaction.user.create_dm()
            msg = await dm.send(embed=create_party_embed(party_doc), view=PartyLobbyDMView(self.bot, str(res.inserted_id), interaction.user.id, interaction.user.id))
            await parties_col.update_one({"_id": res.inserted_id, "members.user_id": interaction.user.id}, {"$set": {"members.$.dm_message_id": msg.id}})
        except discord.Forbidden: pass

        await handle_cross_server_chat(self.bot, party_doc, action="create")
        await interaction.followup.send("✅ Đã tạo Party thành công! Hãy kiểm tra DM của bạn.", ephemeral=True)

class PartyDungeonCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auto_cleanup_parties.start()

    def cog_unload(self):
        self.auto_cleanup_parties.cancel()

    @tasks.loop(hours=1.0)
    async def auto_cleanup_parties(self):
        threshold = datetime.now(timezone.utc) - timedelta(days=1)
        threshold_id = ObjectId.from_datetime(threshold)
        expired = await parties_col.find({"_id": {"$lt": threshold_id}}).to_list(length=None)
        for p in expired:
            try: await handle_cross_server_chat(self.bot, p, action="delete", msg_override=f"⏳ Party **{p.get('dg_name')}** đã tự động hủy do quá 24h.")
            except Exception: pass
        await parties_col.delete_many({"_id": {"$lt": threshold_id}})

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is not None: return
        party = await parties_col.find_one({"members.user_id": message.author.id})
        if not party: return

        sender_ign = next((m.get('ign', message.author.name) for m in party.get('members', []) if m['user_id'] == message.author.id), "Unknown")
        chat_content = f"**[{party.get('dg_name', 'Unknown')}] {sender_ign}**: {message.content}"
        if message.attachments:
            chat_content += "\n" + "\n".join([att.url for att in message.attachments])

        for m in party.get('members', []):
            if m['user_id'] != message.author.id:
                target = self.bot.get_user(m['user_id']) or await self.bot.fetch_user(m['user_id'])
                if target:
                    try: await target.send(content=chat_content)
                    except discord.Forbidden: pass

async def setup(bot):
    await bot.add_cog(PartyDungeonCog(bot))