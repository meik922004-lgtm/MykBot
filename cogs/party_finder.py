import discord
import re
import uuid
import asyncio
from discord import app_commands, ui
from discord.ext import commands
from datetime import datetime, timezone
from pymongo import MongoClient
import os
import time

# --- CONFIG ---
MONGO_URI = os.getenv("MONGO_URI", "YOUR_MONGO_URI_HERE")
client = MongoClient(MONGO_URI)
db = client["database0"]
players_col = db["players"]
parties_col = db["parties"]
dungeon_configs = db["dungeon_configs"] 

# Cooldown for joining parties
join_cooldowns = {}

# --- HELPER FUNCTIONS ---
def get_dungeon_config(dungeon_name):
    return dungeon_configs.find_one({"dg_name": {"$regex": re.escape(dungeon_name), "$options": "i"}})

def get_ping_role(dungeon_name):
    config = get_dungeon_config(dungeon_name)
    return f"<@&{config['ping_role']}>" if config and "ping_role" in config else ""

def get_mapped_role_keys(role_input: str):
    role = role_input.strip().upper()
    if role in ["DPS", "UFM"]:
        return ["AA", "SK"]
    elif role == "TANK":
        return ["TANK"]
    return [role]

def get_gear_from_db(user_id: int, role_input: str):
    player = players_col.find_one({"user_id": {"$in": [user_id, str(user_id)]}})
    if not player or "my_stats" not in player: return "❌ Profile not found. Please use /mygear first."
    
    mapped_keys = get_mapped_role_keys(role_input)
    found_stats = []
    for key in mapped_keys:
        stats = player["my_stats"].get(key)
        if stats:
            found_stats.append(f"[{key}] Gear: {stats.get('gear', 'N/A')} | Deck: {stats.get('deck', 'N/A')} | Vice: {stats.get('vice', 'N/A')}")
            
    if not found_stats: 
        return f"❌ Role '{role_input}' (DB Key: {', '.join(mapped_keys)}) not set up."
    return "\n".join(found_stats)

def is_player_qualified(user_id, role_input, dungeon_name):
    config = get_dungeon_config(dungeon_name)
    if not config or "reqs" not in config: return True 
    
    player = players_col.find_one({"user_id": {"$in": [user_id, str(user_id)]}})
    if not player or "my_stats" not in player: return False
    
    mapped_keys = get_mapped_role_keys(role_input)
    reqs = config.get("reqs", {})
    
    for key in mapped_keys:
        stats = player["my_stats"].get(key)
        if not stats: continue
        
        passed = True
        if "gear" in reqs and stats.get("gear") not in reqs["gear"]: passed = False
        if "vice" in reqs and stats.get("vice") not in reqs["vice"]: passed = False
        if "deck" in reqs and stats.get("deck") not in reqs["deck"]: passed = False
        
        if passed: return True
    return False

# --- MODALS ---
class CreatePartyModal(ui.Modal, title="Create New Party"):
    dg_name = ui.TextInput(label="Dungeon Name", placeholder="e.g: PDG, MDG")
    leader_ign = ui.TextInput(label="Leader IGN")
    leader_role = ui.TextInput(label="Your Role")
    recruitment = ui.TextInput(label="Role Needed")
    start_in = ui.TextInput(label="Start In", placeholder="e.g: 5mins, now")

    async def on_submit(self, interaction: discord.Interaction):
        if not is_player_qualified(interaction.user.id, self.leader_role.value, self.dg_name.value):
            return await interaction.response.send_message("❌ Your gear does not meet the requirements for this dungeon!", ephemeral=True)

        existing_party = parties_col.find_one({"members.id": interaction.user.id})
        if existing_party:
            return await interaction.response.send_message(f"❌ You are already in party **{existing_party['dg_name']}**! Please leave or disband it first.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        pid = str(uuid.uuid4())[:6].upper()
        now = datetime.now(timezone.utc)
        
        embed = discord.Embed(title=f"⚔️ [PARTY RECRUITMENT] {self.dg_name.value}", color=discord.Color.blue())
        embed.add_field(name="Leader", value=self.leader_ign.value, inline=True)
        embed.add_field(name="Looking for", value=self.recruitment.value, inline=True)
        embed.add_field(name="Starts", value=self.start_in.value, inline=True)
        
        class OpenLobbyView(ui.View):
            def __init__(self): super().__init__(timeout=None)
            @ui.button(label="Open Lobby UI", style=discord.ButtonStyle.success)
            async def open_lobby(self, i: discord.Interaction, btn: ui.Button):
                await i.response.send_message(embed=build_lobby_embed(), view=LobbyView(), ephemeral=True)

        broadcasts = []
        for guild in interaction.client.guilds:
            board = discord.utils.get(guild.text_channels, name="party-board")
            if board:
                try:
                    role_mention = get_ping_role(self.dg_name.value) if guild == interaction.guild else ""
                    msg = await board.send(content=f"{role_mention}", embed=embed, view=OpenLobbyView())
                    broadcasts.append({"channel_id": board.id, "message_id": msg.id})
                except discord.Forbidden:
                    pass

        party_data = {
            "id": pid, "dg_name": self.dg_name.value, "leader_ign": self.leader_ign.value,
            "leader_role": self.leader_role.value, "recruitment": self.recruitment.value, 
            "start_in": self.start_in.value, "host_id": interaction.user.id, "created_at": now,
            "members": [{"id": interaction.user.id, "ign": self.leader_ign.value, "role": self.leader_role.value}],
            "filter_enabled": True,
            "broadcasts": broadcasts
        }
        parties_col.insert_one(party_data)
        
        await interaction.followup.send(f"✅ Party **{self.dg_name.value}** created successfully!", ephemeral=True)

class RequestJoinModal(ui.Modal, title="Join Party Request"):
    ign = ui.TextInput(label="Your IGN")
    role = ui.TextInput(label="Your Role")
    
    def __init__(self, party):
        super().__init__()
        self.party = party

    async def on_submit(self, interaction: discord.Interaction):
        existing_party = parties_col.find_one({"members.id": interaction.user.id})
        if existing_party:
            return await interaction.response.send_message("❌ You are already in another party!", ephemeral=True)

        latest_party = parties_col.find_one({"id": self.party["id"]})
        if not latest_party:
            return await interaction.response.send_message("❌ This party no longer exists!", ephemeral=True)

        if len(latest_party["members"]) >= 4:
            return await interaction.response.send_message("❌ This party is full!", ephemeral=True)
            
        if latest_party.get("filter_enabled") and not is_player_qualified(interaction.user.id, self.role.value, latest_party["dg_name"]):
            return await interaction.response.send_message("❌ Your gear does not meet the requirements (Auto-Rejected)!", ephemeral=True)

        host = interaction.client.get_user(latest_party["host_id"])
        if host:
            gear_info = get_gear_from_db(interaction.user.id, self.role.value)
            embed = discord.Embed(title=f"🔔 Join Request: {latest_party['dg_name']}", color=discord.Color.gold())
            embed.add_field(name="User", value=f"{interaction.user.mention} (IGN: {self.ign.value})", inline=False)
            embed.add_field(name="Role", value=self.role.value, inline=False)
            embed.add_field(name="Gear Profile (DB)", value=gear_info, inline=False)
            
            await host.send(embed=embed, view=DecisionView(latest_party["id"], interaction.user, self.ign.value, self.role.value))
            await interaction.response.send_message("✅ Request sent to the Leader!", ephemeral=True)

class SearchModal(ui.Modal, title="Search Party"):
    keyword = ui.TextInput(label="Dungeon Keyword")
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.search_query = self.keyword.value.lower()
        self.parent_view.page = 0
        await self.parent_view.update_lobby(interaction)

# --- VIEWS ---
class DecisionView(ui.View):
    def __init__(self, pid, user, ign, role):
        super().__init__(timeout=None)
        self.pid = pid; self.user = user; self.ign = ign; self.role = role

    @ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, i: discord.Interaction, b: ui.Button):
        in_other_party = parties_col.find_one({"members.id": self.user.id})
        if in_other_party:
            return await i.response.edit_message(content="❌ This user has already joined another party.", embed=None, view=None)

        party = parties_col.find_one({"id": self.pid})
        if party and len(party["members"]) < 4:
            parties_col.update_one({"id": self.pid}, {"$push": {"members": {"id": self.user.id, "ign": self.ign, "role": self.role}}})
            await i.response.edit_message(content="✅ Member accepted.", embed=None, view=None)
            try: await self.user.send(f"🎉 Your join request for **{party['dg_name']}** was accepted!")
            except: pass
        else:
            await i.response.edit_message(content="❌ Party is full or no longer exists.", embed=None, view=None)

    @ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject(self, i: discord.Interaction, b: ui.Button):
        await i.response.edit_message(content="❌ Member rejected.", embed=None, view=None)
        try: await self.user.send("💔 Your join request has been rejected.")
        except: pass

class KickMemberSelect(ui.Select):
    def __init__(self, party):
        options = [discord.SelectOption(label=mem['ign'], value=str(mem['id'])) for mem in party["members"] if mem['id'] != party["host_id"]]
        if not options:
            options = [discord.SelectOption(label="No members to kick", value="none")]
        super().__init__(placeholder="Select member to kick...", options=options)
        self.party = party

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message("❌ No members available to kick.", ephemeral=True)
            
        try:
            member_id = int(self.values[0])
            parties_col.update_one({"id": self.party["id"]}, {"$pull": {"members": {"id": member_id}}})
            await interaction.response.edit_message(content="✅ Kick successful.", view=None)
            try:
                user = await interaction.client.fetch_user(member_id)
                await user.send(f"⚠️ You were kicked from party: **{self.party['dg_name']}**")
            except: pass
        except Exception:
            await interaction.response.send_message("❌ System error during kick.", ephemeral=True)

class ManagePartyView(ui.View):
    def __init__(self, party, is_leader):
        super().__init__(timeout=None)
        self.party = party
        self.is_leader = is_leader

        for child in self.children:
            if getattr(child, "label", None) in ["Toggle AutoFill Filter", "Kick Member", "Disband Party"]:
                if not self.is_leader: self.remove_item(child) 
            elif getattr(child, "label", None) == "Leave Party":
                if self.is_leader: self.remove_item(child) 
    @ui.button(label="Ready Check", style=discord.ButtonStyle.primary, row=2)
    async def ready_check_btn(self, i: discord.Interaction, b: ui.Button):
        # Kiểm tra nếu người bấm là Leader
        if i.user.id != self.party["host_id"]:
            return await i.response.send_message("❌ Only the Leader can initiate a Ready Check.", ephemeral=True)
        
        view = ReadyCheckView(self.party)
        embed = discord.Embed(
            title=f"🔔 Ready Check: {self.party['dg_name']}",
            description="All members, please respond to the Ready Check!",
            color=discord.Color.gold()
        )
        
        # Gửi thông báo cho tất cả thành viên trong nhóm
        await i.response.send_message("✅ Ready Check initiated!", ephemeral=True)
        for member in self.party["members"]:
            await i.client.get_user(member["id"]).send(...)
        
        # Đợi 60 giây để thu thập kết quả
        await asyncio.sleep(60)
        
        # Tổng hợp kết quả
        results = "\n".join([f"{uid}: {status}" for uid, status in view.ready_members.items()])
        result_embed = discord.Embed(title="📊 Ready Check Results", description=results or "No one responded.", color=discord.Color.blue())
        # Thay vì dùng msg.edit, hãy dùng i.message.edit
        await i.message.edit(embed=result_embed, view=None)

    @ui.button(label="View Members", style=discord.ButtonStyle.primary)
    async def view_members(self, i: discord.Interaction, b: ui.Button):
        await i.response.defer(ephemeral=True)
        try:
            current_party = parties_col.find_one({"id": self.party["id"]})
            if not current_party:
                return await i.followup.send("❌ Party no longer exists.", ephemeral=True)

            embed = discord.Embed(title=f"👥 Party Members: {current_party['dg_name']}", color=discord.Color.blue())
            for idx, mem in enumerate(current_party["members"]):
                gear = get_gear_from_db(mem["id"], mem["role"])
                is_host = "👑 (Leader)" if mem["id"] == current_party["host_id"] else ""
                embed.add_field(name=f"[{idx+1}] {mem['ign']} {is_host}", value=f"Role: {mem['role']}\n{gear}", inline=False)
            await i.followup.send(embed=embed, ephemeral=True)
        except Exception:
            await i.followup.send("❌ Error retrieving data.", ephemeral=True)

    @ui.button(label="Toggle Filter", style=discord.ButtonStyle.secondary)
    async def toggle_filter(self, i: discord.Interaction, b: ui.Button):
        try:
            new_val = not self.party.get("filter_enabled", True)
            parties_col.update_one({"id": self.party["id"]}, {"$set": {"filter_enabled": new_val}})
            self.party["filter_enabled"] = new_val 
            status = 'ON 🟢' if new_val else 'OFF 🔴'
            await i.response.send_message(f"✅ Filter status: **{status}**", ephemeral=True)
        except Exception:
            await i.response.send_message("❌ Database error.", ephemeral=True)

    @ui.button(label="Kick Member", style=discord.ButtonStyle.danger)
    async def kick_member_btn(self, i: discord.Interaction, b: ui.Button):
        try:
            current_party = parties_col.find_one({"id": self.party["id"]})
            if not current_party or len(current_party["members"]) <= 1: 
                return await i.response.send_message("❌ No members to kick.", ephemeral=True)
            
            view = ui.View()
            view.add_item(KickMemberSelect(current_party))
            await i.response.send_message("Select member to kick:", view=view, ephemeral=True)
        except Exception:
            await i.response.send_message("❌ Database error.", ephemeral=True)

    @ui.button(label="Disband Party", style=discord.ButtonStyle.danger)
    async def disband_party(self, i: discord.Interaction, b: ui.Button):
        await i.response.defer(ephemeral=True)
        try:
            current_party = parties_col.find_one({"id": self.party["id"]})
            if not current_party:
                return await i.followup.send("❌ Party not found or already disbanded.", ephemeral=True)
            
            if "broadcasts" in current_party:
                for b_info in current_party["broadcasts"]:
                    try:
                        ch = i.client.get_channel(b_info["channel_id"]) or await i.client.fetch_channel(b_info["channel_id"])
                        msg = await ch.fetch_message(b_info["message_id"])
                        
                        disband_embed = discord.Embed(
                            title=f"❌ [PARTY DISBANDED] {current_party['dg_name']}", 
                            color=discord.Color.red(),
                            description=f"🚫 This party has been disbanded by the Leader **{current_party['leader_ign']}**."
                        )
                        disband_embed.set_footer(text="Status: Recruitment closed")
                        await msg.edit(content="", embed=disband_embed, view=None)
                    except Exception:
                        pass 
            
            parties_col.delete_one({"id": self.party["id"]})
            await i.edit_original_response(content="💥 Party disbanded.", view=None, embed=None)
        except Exception:
            await i.followup.send("❌ Error disbanding the party.", ephemeral=True)

    @ui.button(label="Leave Party", style=discord.ButtonStyle.danger)
    async def leave_party(self, i: discord.Interaction, b: ui.Button):
        await i.response.defer(ephemeral=True)
        try:
            parties_col.update_one({"id": self.party["id"]}, {"$pull": {"members": {"id": i.user.id}}})
            try:
                host_user = await i.client.fetch_user(self.party["host_id"])
                await host_user.send(f"⚠️ Member **{i.user.display_name}** left your party **{self.party['dg_name']}**!")
            except: pass
            
            await i.edit_original_response(content="👋 You left the party.", view=None, embed=None)
        except Exception:
            await i.followup.send("❌ Database error.", ephemeral=True)

class LobbySelectParty(ui.Select):
    def __init__(self, parties_on_page):
        options = [discord.SelectOption(label=f"Join: {p['dg_name']}", description=f"Leader: {p['leader_ign']} | Role: {p['recruitment']}", value=p["id"]) for p in parties_on_page]
        super().__init__(placeholder="⬇️ Select a party to join...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        now = time.time()
        if user_id in join_cooldowns and now - join_cooldowns[user_id] < 10:
            return await interaction.response.send_message(f"⏳ Cooldown active! Please wait {int(10 - (now - join_cooldowns[user_id]))}s.", ephemeral=True)
        
        existing_party = parties_col.find_one({"members.id": user_id})
        if existing_party:
            return await interaction.response.send_message(f"❌ You are already in party **{existing_party['dg_name']}**! Please leave the current one first.", ephemeral=True)

        party = parties_col.find_one({"id": self.values[0]})
        if not party: return await interaction.response.send_message("❌ Party does not exist.", ephemeral=True)
        
        join_cooldowns[user_id] = now
        await interaction.response.send_modal(RequestJoinModal(party))

class ReadyCheckView(ui.View):
    def __init__(self, party):
        super().__init__(timeout=60) # Tự hủy sau 60 giây
        self.party = party
        self.ready_members = {}

    @ui.button(label="✅ Ready", style=discord.ButtonStyle.success)
    async def ready(self, i: discord.Interaction, b: ui.Button):
        self.ready_members[i.user.id] = "Ready"
        await i.response.send_message("✅ You marked yourself as Ready!", ephemeral=True)

    @ui.button(label="❌ Not Ready", style=discord.ButtonStyle.danger)
    async def not_ready(self, i: discord.Interaction, b: ui.Button):
        self.ready_members[i.user.id] = "Not Ready"
        await i.response.send_message("❌ You marked yourself as Not Ready!", ephemeral=True)

class LobbyView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.page = 0
        self.search_query = ""
        self.update_components()

    def get_filtered_parties(self):
        parties = list(parties_col.find().sort("created_at", -1))
        if self.search_query:
            parties = [p for p in parties if self.search_query in p["dg_name"].lower()]
        return parties

    def update_components(self):
        self.clear_items()
        parties = self.get_filtered_parties()
        max_pages = max(1, (len(parties) - 1) // 6 + 1)
        self.page = min(self.page, max_pages - 1)
        
        parties_on_page = parties[self.page * 6 : self.page * 6 + 6]
        if parties_on_page: self.add_item(LobbySelectParty(parties_on_page))

        async def create_callback(i: discord.Interaction): await i.response.send_modal(CreatePartyModal())
        async def search_callback(i: discord.Interaction): await i.response.send_modal(SearchModal(self))
        
        btn_create = ui.Button(label="Create", style=discord.ButtonStyle.primary, row=1)
        btn_create.callback = create_callback
        
        btn_search = ui.Button(label="Search", style=discord.ButtonStyle.secondary, row=1)
        btn_search.callback = search_callback
        
        btn_refresh = ui.Button(label="Refresh", style=discord.ButtonStyle.secondary, row=1)
        btn_refresh.callback = self.update_lobby
        
        btn_manage = ui.Button(label="Manage My Party", style=discord.ButtonStyle.success, row=1)
        btn_manage.callback = self.manage_party_callback
        
        self.add_item(btn_create); self.add_item(btn_search); self.add_item(btn_refresh); self.add_item(btn_manage)

        if len(parties) > 6:
            btn_prev = ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary, disabled=(self.page == 0), row=2)
            btn_prev.callback = self.prev_page
            
            btn_next = ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, disabled=(self.page == max_pages - 1), row=2)
            btn_next.callback = self.next_page
            
            self.add_item(btn_prev); self.add_item(btn_next)

    async def update_lobby(self, interaction: discord.Interaction):
        self.update_components()
        await interaction.response.edit_message(embed=build_lobby_embed(self.page, self.search_query), view=self)

    async def prev_page(self, interaction: discord.Interaction): self.page -= 1; await self.update_lobby(interaction)
    async def next_page(self, interaction: discord.Interaction): self.page += 1; await self.update_lobby(interaction)

    async def manage_party_callback(self, interaction: discord.Interaction):
        user_party = parties_col.find_one({"members.id": interaction.user.id})
        if user_party:
            return await interaction.response.send_message(f"⚙️ Managing: {user_party['dg_name']}", view=ManagePartyView(user_party, user_party["host_id"] == interaction.user.id), ephemeral=True)
        await interaction.response.send_message("❌ You are not in any party.", ephemeral=True)

def build_lobby_embed(page=0, search_query=""):
    parties = list(parties_col.find().sort("created_at", -1))
    if search_query: 
        parties = [p for p in parties if search_query in p["dg_name"].lower()]
    
    embed = discord.Embed(
        title="🏰 PARTY LOBBY", 
        description=f"🔍 Filter: `{search_query}`" if search_query else "List of parties recruiting", 
        color=discord.Color.dark_theme()
    )
    embed.set_author(name=f"Active Parties: {len(parties)}")
    
    start_idx = page * 6
    end_idx = start_idx + 6
    parties_on_page = parties[start_idx:end_idx]

    if not parties_on_page:
        embed.add_field(name="🪹 Empty", value="There are no parties on this page.", inline=False)
    else:
        for p in parties_on_page:
            created_time = p["created_at"].replace(tzinfo=timezone.utc).timestamp()
            header = f"🎮 **{p['dg_name']}** (ID: `{p['id']}`)"
            body = (
                f"> **Leader:** {p['leader_ign']} | **Need:** {p['recruitment']}\n"
                f"> **Start in:** {p['start_in']} | **Members:** `{len(p['members'])}/4`\n"
                f"> 🕒 Created: <t:{int(created_time)}:R>\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            embed.add_field(name=header, value=body, inline=False) 
            
    return embed

class PartyFinder(commands.Cog):
    def __init__(self, bot): self.bot = bot
    @app_commands.command(name="party_lobby", description="Open the Party Lobby UI")
    async def party_lobby(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_lobby_embed(), view=LobbyView(), ephemeral=True)

async def setup(bot): await bot.add_cog(PartyFinder(bot))