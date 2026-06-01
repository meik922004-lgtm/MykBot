import discord
from discord.ext import commands
from discord import app_commands
from Database import db, rpg_profiles_col

# ==========================================
# CẤU HÌNH DỮ LIỆU
# ==========================================
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

# ==========================================
# MODAL NHẬP IGN
# ==========================================
class MyGearIGNModal(discord.ui.Modal, title="Setup Profile - IGN"):
    ign = discord.ui.TextInput(label="In-Game Name (IGN)", placeholder="Enter your character name...", required=True, max_length=30)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ign_value = self.ign.value.strip()
        await db.players.update_one({"user_id": interaction.user.id}, {"$set": {"ign": ign_value}}, upsert=True)
        embed = discord.Embed(title="⚙️ Setup MyGear", description=f"Your IGN has been set to: **{ign_value}**\nPlease select the following Role indicators below:", color=discord.Color.blue())
        await interaction.followup.send(embed=embed, view=MyGearWizard(interaction.user.id, {}), ephemeral=True)

# ==========================================
# WIZARD: CẬP NHẬT GEAR
# ==========================================
class MyGearWizard(discord.ui.View):
    def __init__(self, user_id, player_data=None):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.player_data = player_data or {}
        self.data = {"tz_offset": 7.0, "role": None, "gear": None, "vice": None, "deck": None, "bracelet": None}
        
        if "tz_offset" in self.player_data:
            self.data["tz_offset"] = self.player_data["tz_offset"]
            self.step = 1
        else:
            self.step = 0
            
        self.refresh_menu()

    def refresh_menu(self):
        self.clear_items()
        if self.step == 0:
            options = [
                discord.SelectOption(label="UTC-8", description="UTC-8", value="-8"),
                discord.SelectOption(label="UTC-5", description="UTC-5", value="-5"),
                discord.SelectOption(label="UTC-3", description="UTC-3", value="-3"),
                discord.SelectOption(label="UTC+0", description="UTC+0", value="0"),
                discord.SelectOption(label="UTC+1", description="UTC+1", value="1"),
                discord.SelectOption(label="UTC+3", description="UTC+3", value="3"),
                discord.SelectOption(label="UTC+7", description="UTC+7", value="7"),
                discord.SelectOption(label="UTC+8", description="UTC+8", value="8"),
                discord.SelectOption(label="UTC+9", description="UTC+9", value="9"),
                discord.SelectOption(label="UTC+10", description="UTC+10", value="10")
            ]
            select = discord.ui.Select(placeholder="🌍 Select your Timezone", options=options)
            async def tz_callback(interaction: discord.Interaction):
                self.data["tz_offset"] = float(interaction.data["values"][0])
                self.step = 1
                await self.next_step(interaction)
            select.callback = tz_callback
            self.add_item(select)
            
        elif self.step == 1:
            select = discord.ui.Select(placeholder="Select role", options=[discord.SelectOption(label=r) for r in ["AA", "SK", "TANK"]])
            async def role_callback(interaction: discord.Interaction):
                self.data["role"] = interaction.data["values"][0]
                self.step = 2
                await self.next_step(interaction)
            select.callback = role_callback
            self.add_item(select)
            
        elif self.step == 2:
            select = discord.ui.Select(placeholder="Select gear", options=[discord.SelectOption(label=g) for g in GEAR_OPTIONS])
            async def gear_callback(interaction: discord.Interaction):
                self.data["gear"] = interaction.data["values"][0]
                self.step = 3
                await self.next_step(interaction)
            select.callback = gear_callback
            self.add_item(select)
            
        elif self.step == 3:
            select = discord.ui.Select(placeholder="Select vice", options=[discord.SelectOption(label=v) for v in VICE_OPTIONS[self.data["role"]]])
            async def vice_callback(interaction: discord.Interaction):
                self.data["vice"] = interaction.data["values"][0]
                self.step = 4
                await self.next_step(interaction)
            select.callback = vice_callback
            self.add_item(select)
            
        elif self.step == 4:
            select = discord.ui.Select(placeholder="Select deck", options=[discord.SelectOption(label=d) for d in DECK_OPTIONS[self.data["role"]]])
            async def deck_callback(interaction: discord.Interaction):
                self.data["deck"] = interaction.data["values"][0]
                self.step = 5
                await self.next_step(interaction)
            select.callback = deck_callback
            self.add_item(select)
            
        elif self.step == 5:
            select = discord.ui.Select(placeholder="Select bracelet", options=[discord.SelectOption(label=b) for b in BRACELET_OPTIONS])
            async def bracelet_callback(interaction: discord.Interaction):
                self.data["bracelet"] = interaction.data["values"][0]
                self.step = 6 
                await self.next_step(interaction)
            select.callback = bracelet_callback
            self.add_item(select)

    async def next_step(self, interaction: discord.Interaction):
        if self.step < 6:
            self.refresh_menu()
            embed = discord.Embed(title="⚙️ Setup MyGear", color=discord.Color.blue())
            tz = self.data["tz_offset"]
            tz_str = f"+{tz}" if tz > 0 else str(tz)
            embed.add_field(name="Current", value=f"🌍 Timezone: UTC{tz_str.replace('.0', '')}\nRole: {self.data.get('role') or '...'}\nGear: {self.data.get('gear') or '...'}\nVice: {self.data.get('vice') or '...'}\nDeck: {self.data.get('deck') or '...'}\nBracelet: {self.data.get('bracelet') or '...'}")
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            role = self.data["role"]
            stats_data = {k: v for k, v in self.data.items() if k != "tz_offset"}
            await db.players.update_one({"user_id": self.user_id}, {"$set": {"tz_offset": self.data["tz_offset"], f"my_stats.{role}": stats_data}}, upsert=True)
            await interaction.response.edit_message(content=f"✅ Saved config for **{role}** successfully!", embed=None, view=None)


class DungeonListView(discord.ui.View):
    def __init__(self, dungeons):
        super().__init__(timeout=60)
        for dg in dungeons:
            dg_name = dg.get("dg_name")
            button = discord.ui.Button(label=dg_name.upper(), style=discord.ButtonStyle.primary, custom_id=f"btn_check_{dg_name}")
            button.callback = self.create_callback(dg_name)
            self.add_item(button)

    def create_callback(self, dg_name):
        async def callback(interaction: discord.Interaction):
            await DungeonStats._perform_check(interaction, dg_name)
        return callback


class DungeonStats(commands.Cog):
    def __init__(self, bot): 
        self.bot = bot

    @staticmethod
    async def _perform_check(interaction: discord.Interaction, dg_name: str):
        await interaction.response.defer(ephemeral=True)
        player = await db.players.find_one({"user_id": interaction.user.id})
        cfg = await db.dungeon_configs.find_one({"dg_name": dg_name})
        
        if not cfg: return await interaction.followup.send(f"❌ Error: Can't find data for `{dg_name}` in the database.", ephemeral=True)
        if not player or "my_stats" not in player or not player["my_stats"]: return await interaction.followup.send("❌ Please setup your profile using `/mygear` first!", ephemeral=True)

        req = cfg.get("reqs", {})
        has_any_passed = False 
        embed = discord.Embed(title=f"Check: {dg_name.upper()}")
        
        for role_name, stats in player["my_stats"].items():
            if not isinstance(stats, dict): continue
            results = []
            is_role_ok = True
            
            for cat in ["gear", "vice", "deck", "bracelet"]:
                u_val = stats.get(cat)
                allowed = req.get(cat, [])
                if u_val in allowed:
                    results.append(f"✅ {cat.upper()}: {u_val}")
                else:
                    results.append(f"❌ {cat.upper()}: {u_val} (Req: {', '.join(allowed) if allowed else 'None'})")
                    is_role_ok = False
            
            if is_role_ok: has_any_passed = True
            embed.add_field(name=f"Role: {role_name} [{'✅ PASS' if is_role_ok else '❌ FAIL'}]", value="\n".join(results), inline=False)

        embed.color = discord.Color.green() if has_any_passed else discord.Color.red()
        if not embed.fields: return await interaction.followup.send("❌ Could not check your gear info, please update it!", ephemeral=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="mygear", description="Set up your character profile")
    async def mygear(self, interaction: discord.Interaction):
        p = await db.players.find_one({"user_id": interaction.user.id})
        if not p or not p.get("ign") or p.get("ign") == "Not Set":
            await interaction.response.send_modal(MyGearIGNModal(self.bot))
        else:
            embed = discord.Embed(title="⚙️ Setup MyGear", description=f"Current profile: **{p.get('ign')}**\nPlease select a role to setup your gears:", color=discord.Color.blue())
            await interaction.response.send_message(embed=embed, view=MyGearWizard(interaction.user.id, p), ephemeral=True)

    @app_commands.command(name="set_timezone", description="🌍 Set your local timezone")
    async def set_timezone(self, interaction: discord.Interaction):
        options = [discord.SelectOption(label=f"UTC{'+' if i>0 else ''}{i}", value=str(i)) for i in [-8, -5, -3, 0, 1, 2, 3, 7, 8, 9, 10]]
        select = discord.ui.Select(placeholder="🌍 Select your region / timezone...", options=options)
        
        async def tz_callback(inter: discord.Interaction):
            offset = float(select.values[0])
            await db.players.update_one({"user_id": inter.user.id}, {"$set": {"tz_offset": offset}}, upsert=True)
            await inter.response.edit_message(content=f"✅ Timezone UTC{'+' if offset>0 else ''}{str(offset).replace('.0', '')} has been saved successfully.", view=None, embed=None)
            
        select.callback = tz_callback
        view = discord.ui.View()
        view.add_item(select)
        embed = discord.Embed(title="🌍 Configure your timezone", description="Choose your location so the bot can synchronize Party times accurately for you.", color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="showmygear", description="Flex your current gear profile")
    async def showmygear(self, interaction: discord.Interaction):
        p = await db.players.find_one({"user_id": interaction.user.id})
        if not p or "my_stats" not in p or not p["my_stats"]: return await interaction.response.send_message("❌ Your gear information is empty!", ephemeral=True)
        
        rpg_p = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        is_premium = rpg_p.get("premium_ui", False) if rpg_p else False
        
        ign_in_db = p.get('ign', 'Not Set')
        player_ign = f"⚠️ {interaction.user.name} (Missing IGN)" if ign_in_db == "Not Set" else ign_in_db
            
        embed = discord.Embed(title=f"{'🌟' if is_premium else '🛡️'} {player_ign}'s Profile", color=discord.Color.gold() if is_premium else discord.Color.blue())
        for role_name, stats in p["my_stats"].items():
            if isinstance(stats, dict):
                embed.add_field(name=f"Role: {role_name}", value=f"Gear: {stats.get('gear', 'N/A')}\nVice: {stats.get('vice', 'N/A')}\nDeck: {stats.get('deck', 'N/A')}\nBracelet: {stats.get('bracelet', 'N/A')}", inline=False)
        await interaction.response.send_message(embed=embed)
        
    @app_commands.command(name="dglist", description="Check gear requirements for dungeons")
    async def dglist(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        dungeons = await db.dungeon_configs.find({}).to_list(length=25)
        if not dungeons: return await interaction.response.send_message("❌ Database is empty.", ephemeral=True)
        await interaction.followup.send("📍 Please select a dungeon to check:", view=DungeonListView(dungeons))

async def setup(bot):
    await bot.add_cog(DungeonStats(bot))