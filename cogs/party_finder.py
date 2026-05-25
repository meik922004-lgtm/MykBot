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
from discord.ext import commands

# --- CONFIG ---
MONGO_URI = os.getenv("MONGO_URI", "YOUR_MONGO_URI_HERE")
client = MongoClient(MONGO_URI)
db = client["database0"]
players_col = db["players"]
dungeon_configs = db["dungeon_configs"] 

# Temporary storage for Parties and Cooldowns
active_parties = {}
join_cooldowns = {}

# --- HELPER FUNCTIONS ---
def get_dungeon_config(dungeon_name):
    return dungeon_configs.find_one({"dg_name": {"$regex": re.escape(dungeon_name), "$options": "i"}})

def get_ping_role(dungeon_name):
    config = get_dungeon_config(dungeon_name)
    return f"<@&{config['ping_role']}>" if config and "ping_role" in config else ""

def get_mapped_role_keys(role_input: str):
    """
    Maps user-input role to DB keys. Case-insensitive.
    """
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
        
        if passed:
            return True
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

        pid = str(uuid.uuid4())[:6].upper()
        now = datetime.now(timezone.utc)
        
        active_parties[pid] = {
            "id": pid, "dg_name": self.dg_name.value, "leader_ign": self.leader_ign.value,
            "leader_role": self.leader_role.value, "recruitment": self.recruitment.value, 
            "start_in": self.start_in.value, "host_id": interaction.user.id, "created_at": now,
            "members": [{"id": interaction.user.id, "ign": self.leader_ign.value, "role": self.leader_role.value}],
            "filter_enabled": True
        }
        
        await interaction.response.send_message(f"✅ Party **{self.dg_name.value}** created successfully!", ephemeral=True)
        
        party_board = discord.utils.get(interaction.guild.text_channels, name="party-board")
        if party_board:
            role_mention = get_ping_role(self.dg_name.value)
            embed = discord.Embed(title=f"⚔️ [PARTY RECRUITMENT] {self.dg_name.value}", color=discord.Color.blue())
            embed.add_field(name="Leader", value=self.leader_ign.value, inline=True)
            embed.add_field(name="Looking for", value=self.recruitment.value, inline=True)
            embed.add_field(name="Starts", value=self.start_in.value, inline=True)
            
            class OpenLobbyView(ui.View):
                def __init__(self): super().__init__(timeout=None)
                @ui.button(label="Open Lobby UI", style=discord.ButtonStyle.success)
                async def open_lobby(self, i: discord.Interaction, btn: ui.Button):
                    await i.response.send_message(embed=build_lobby_embed(), view=LobbyView(), ephemeral=True)

            await party_board.send(content=f"{role_mention}", embed=embed, view=OpenLobbyView())

class RequestJoinModal(ui.Modal, title="Join Party Request"):
    ign = ui.TextInput(label="Your IGN")
    role = ui.TextInput(label="Your Role")
    
    def __init__(self, party):
        super().__init__()
        self.party = party

    async def on_submit(self, interaction: discord.Interaction):
        if len(self.party["members"]) >= 4:
            return await interaction.response.send_message("❌ This party is full!", ephemeral=True)
            
        if self.party.get("filter_enabled") and not is_player_qualified(interaction.user.id, self.role.value, self.party["dg_name"]):
            return await interaction.response.send_message("❌ Your gear does not meet the requirements (Auto-Rejected)!", ephemeral=True)

        host = interaction.client.get_user(self.party["host_id"])
        if host:
            gear_info = get_gear_from_db(interaction.user.id, self.role.value)
            embed = discord.Embed(title=f"🔔 Join Request: {self.party['dg_name']}", color=discord.Color.gold())
            embed.add_field(name="User", value=f"{interaction.user.mention} (IGN: {self.ign.value})", inline=False)
            embed.add_field(name="Role", value=self.role.value, inline=False)
            embed.add_field(name="Gear Profile (DB)", value=gear_info, inline=False)
            
            await host.send(embed=embed, view=DecisionView(self.party["id"], interaction.user, self.ign.value, self.role.value))
            await interaction.response.send_message("✅ Request sent to Leader!", ephemeral=True)

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
        party = active_parties.get(self.pid)
        if party and len(party["members"]) < 4:
            party["members"].append({"id": self.user.id, "ign": self.ign, "role": self.role})
            await i.response.edit_message(content="✅ You have accepted this member.", embed=None, view=None)
            try: await self.user.send(f"🎉 Your join request for **{party['dg_name']}** was accepted!")
            except: pass
        else:
            await i.response.edit_message(content="❌ Party is full or no longer exists.", embed=None, view=None)

    @ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject(self, i: discord.Interaction, b: ui.Button):
        await i.response.edit_message(content="❌ You have rejected this member.", embed=None, view=None)
        try: await self.user.send("💔 Your join request has been rejected.")
        except: pass

# 1. Thêm Class này vào phía trên class ManagePartyView
class KickMemberSelect(ui.Select):
    def __init__(self, party, is_leader):
        options = [
            discord.SelectOption(label=mem['ign'], value=str(mem['id']))
            for mem in party["members"] if mem['id'] != party["host_id"]
        ]
        super().__init__(placeholder="Select a member to kick...", options=options)
        self.party = party

    async def callback(self, interaction: discord.Interaction):
        global parties_col
        member_id = int(self.values[0])
        
        # Xóa khỏi DB
        parties_col.update_one({"id": self.party["id"]}, {"$pull": {"members": {"id": member_id}}})
        
        # Gửi thông báo DM cho người bị kick
        try:
            user = await interaction.client.fetch_user(member_id)
            await user.send(f"⚠️ You have been kicked from the party: **{self.party['dg_name']}**")
        except: pass
        
        await interaction.response.send_message(f"✅ Member kicked successfully.", ephemeral=True)

# 2. Thay thế Class ManagePartyView cũ bằng Class này
class ManagePartyView(ui.View):
    def __init__(self, party, is_leader):
        super().__init__(timeout=None)
        self.party = party
        self.is_leader = is_leader

    @ui.button(label="View Members", style=discord.ButtonStyle.primary)
    async def view_members(self, i: discord.Interaction, b: ui.Button):
        embed = discord.Embed(title=f"👥 Party Members: {self.party['dg_name']}", color=discord.Color.blue())
        for idx, mem in enumerate(self.party["members"]):
            gear = get_gear_from_db(mem["id"], mem["role"])
            is_host = "👑 (Leader)" if mem["id"] == self.party["host_id"] else ""
            embed.add_field(name=f"[{idx+1}] {mem['ign']} {is_host}", value=f"Role: {mem['role']}\n{gear}", inline=False)
        await i.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Toggle AutoFill Filter", style=discord.ButtonStyle.secondary)
    async def toggle_filter(self, i: discord.Interaction, b: ui.Button):
        global parties_col
        if not self.is_leader: return await i.response.send_message("❌ Only the Leader can manage this.", ephemeral=True)
        new_val = not self.party.get("filter_enabled", True)
        parties_col.update_one({"id": self.party["id"]}, {"$set": {"filter_enabled": new_val}})
        status = 'ON 🟢' if new_val else 'OFF 🔴'
        await i.response.send_message(f"✅ Filter status: **{status}**", ephemeral=True)

    @ui.button(label="Kick Member", style=discord.ButtonStyle.danger)
    async def kick_member_btn(self, i: discord.Interaction, b: ui.Button):
        if not self.is_leader: return await i.response.send_message("❌ Only the Leader can kick.", ephemeral=True)
        if len(self.party["members"]) <= 1: return await i.response.send_message("❌ No members to kick.", ephemeral=True)
        
        view = ui.View()
        view.add_item(KickMemberSelect(self.party, self.is_leader))
        await i.response.send_message("Select a member to kick:", view=view, ephemeral=True)

    @ui.button(label="Leave Party", style=discord.ButtonStyle.danger)
    async def leave_party(self, i: discord.Interaction, b: ui.Button):
        global parties_col
        if self.is_leader:
            parties_col.delete_one({"id": self.party["id"]})
            await i.response.send_message("💥 Party disbanded.", ephemeral=True)
        else:
            parties_col.update_one({"id": self.party["id"]}, {"$pull": {"members": {"id": i.user.id}}})
            await i.response.send_message("👋 You left the party.", ephemeral=True)
class LobbySelectParty(ui.Select):
    def __init__(self, parties_on_page):
        options = [discord.SelectOption(label=f"Join: {p['dg_name']}", description=f"Leader: {p['leader_ign']} | Role: {p['recruitment']}", value=p["id"]) for p in parties_on_page]
        super().__init__(placeholder="⬇️ Select a party to join...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        now = time.time()
        if user_id in join_cooldowns and now - join_cooldowns[user_id] < 10:
            return await interaction.response.send_message(f"⏳ Cooldown active! Please wait {int(10 - (now - join_cooldowns[user_id]))}s.", ephemeral=True)
        
        party = active_parties.get(self.values[0])
        if not party: return await interaction.response.send_message("❌ Party does not exist.", ephemeral=True)
        
        join_cooldowns[user_id] = now
        await interaction.response.send_modal(RequestJoinModal(party))

class LobbyView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.page = 0
        self.search_query = ""
        self.update_components()

    def get_filtered_parties(self):
        parties = sorted(active_parties.values(), key=lambda x: x["created_at"], reverse=True)
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

        btn_create = ui.Button(label="Create", style=discord.ButtonStyle.primary, row=1, callback=lambda i: i.response.send_modal(CreatePartyModal()))
        btn_search = ui.Button(label="Search", style=discord.ButtonStyle.secondary, row=1, callback=lambda i: i.response.send_modal(SearchModal(self)))
        btn_refresh = ui.Button(label="Refresh", style=discord.ButtonStyle.secondary, row=1, callback=self.update_lobby)
        btn_manage = ui.Button(label="Manage My Party", style=discord.ButtonStyle.success, row=1, callback=self.manage_party_callback)
        
        self.add_item(btn_create); self.add_item(btn_search); self.add_item(btn_refresh); self.add_item(btn_manage)

        if len(parties) > 6:
            btn_prev = ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary, disabled=(self.page == 0), row=2, callback=self.prev_page)
            btn_next = ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, disabled=(self.page == max_pages - 1), row=2, callback=self.next_page)
            self.add_item(btn_prev); self.add_item(btn_next)

    async def update_lobby(self, interaction: discord.Interaction):
        self.update_components()
        await interaction.response.edit_message(embed=build_lobby_embed(self.page, self.search_query), view=self)

    async def prev_page(self, interaction: discord.Interaction): self.page -= 1; await self.update_lobby(interaction)
    async def next_page(self, interaction: discord.Interaction): self.page += 1; await self.update_lobby(interaction)

    async def manage_party_callback(self, interaction: discord.Interaction):
        for p in active_parties.values():
            if any(m["id"] == interaction.user.id for m in p["members"]):
                return await interaction.response.send_message(f"⚙️ Managing: {p['dg_name']}", view=ManagePartyView(p, p["host_id"] == interaction.user.id), ephemeral=True)
        await interaction.response.send_message("❌ You are not in any party.", ephemeral=True)

def build_lobby_embed(page=0, search_query=""):
    parties = sorted(active_parties.values(), key=lambda x: x["created_at"], reverse=True)
    if search_query: parties = [p for p in parties if search_query in p["dg_name"].lower()]
    
    embed = discord.Embed(title="🏰 PARTY LOBBY", description=f"🔍 Filter: `{search_query}`" if search_query else "", color=discord.Color.dark_theme())
    embed.set_author(name=f"Active Parties: {len(parties)}")
    
    for i in range(6):
        if i + (page * 6) < len(parties):
            p = parties[i + (page * 6)]
            embed.add_field(name=f"🎮 {p['dg_name']} (ID: {p['id']})", value=f"Leader: {p['leader_ign']}\nNeed: {p['recruitment']}\nStarts: {p['start_in']}\nMembers: `[{len(p['members'])}/4]`\nCreated: <t:{int(p['created_at'].timestamp())}:R>", inline=True)
        else:
            embed.add_field(name="🪹 [Empty]", value="No party here.", inline=True)
    return embed

class PartyFinder(commands.Cog):
    def __init__(self, bot): self.bot = bot
    @app_commands.command(name="party_lobby", description="Open the Party Lobby UI")
    async def party_lobby(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_lobby_embed(), view=LobbyView(), ephemeral=True)

async def setup(bot): await bot.add_cog(PartyFinder(bot))