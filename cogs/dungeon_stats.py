import discord
from discord.ext import commands
from discord import app_commands
from Database import db

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
        
        # Lưu IGN vào gốc document của user
        await db.players.update_one(
            {"user_id": interaction.user.id},
            {"$set": {"ign": ign_value}},
            upsert=True
        )
        
        # Gọi tiếp menu Wizard cấu hình Gear
        embed = discord.Embed(
            title="⚙️ Setup MyGear", 
            description=f"Your IGN has been set to: **{ign_value}**\nPlease select the following Role indicators below:", 
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed, view=MyGearWizard(interaction.user.id), ephemeral=True)

# ==========================================
# WIZARD: CẬP NHẬT GEAR (Đã tích hợp thêm Bracelet)
# ==========================================
class MyGearWizard(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.data = {"role": None, "gear": None, "vice": None, "deck": None, "bracelet": None}
        self.step = 0
        self.refresh_menu()

    def refresh_menu(self):
        self.clear_items()
        if self.step == 0:
            select = discord.ui.Select(placeholder="Select role", options=[discord.SelectOption(label=r) for r in ["AA", "SK", "TANK"]])
            async def role_callback(interaction: discord.Interaction):
                self.data["role"] = interaction.data["values"][0]
                self.step = 1
                await self.next_step(interaction)
            select.callback = role_callback
            self.add_item(select)
        elif self.step == 1:
            select = discord.ui.Select(placeholder="Select gear", options=[discord.SelectOption(label=g) for g in GEAR_OPTIONS])
            async def gear_callback(interaction: discord.Interaction):
                self.data["gear"] = interaction.data["values"][0]
                self.step = 2
                await self.next_step(interaction)
            select.callback = gear_callback
            self.add_item(select)
        elif self.step == 2:
            select = discord.ui.Select(placeholder="Select vice", options=[discord.SelectOption(label=v) for v in VICE_OPTIONS[self.data["role"]]])
            async def vice_callback(interaction: discord.Interaction):
                self.data["vice"] = interaction.data["values"][0]
                self.step = 3
                await self.next_step(interaction)
            select.callback = vice_callback
            self.add_item(select)
        elif self.step == 3:
            select = discord.ui.Select(placeholder="Select deck", options=[discord.SelectOption(label=d) for d in DECK_OPTIONS[self.data["role"]]])
            async def deck_callback(interaction: discord.Interaction):
                self.data["deck"] = interaction.data["values"][0]
                self.step = 4
                await self.next_step(interaction)
            select.callback = deck_callback
            self.add_item(select)
        elif self.step == 4:
            select = discord.ui.Select(placeholder="Select bracelet", options=[discord.SelectOption(label=b) for b in BRACELET_OPTIONS])
            async def bracelet_callback(interaction: discord.Interaction):
                self.data["bracelet"] = interaction.data["values"][0]
                self.step = 5
                await self.next_step(interaction)
            select.callback = bracelet_callback
            self.add_item(select)

    async def next_step(self, interaction: discord.Interaction):
        if self.step < 5:
            self.refresh_menu()
            embed = discord.Embed(title="⚙️ Setup MyGear", color=discord.Color.blue())
            embed.add_field(
                name="Current", 
                value=f"Role: {self.data['role'] or '...'}\n"
                      f"Gear: {self.data['gear'] or '...'}\n"
                      f"Vice: {self.data['vice'] or '...'}\n"
                      f"Deck: {self.data['deck'] or '...'}\n"
                      f"Bracelet: {self.data['bracelet'] or '...'}"
            )
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            role = self.data["role"]
            await db.players.update_one(
                {"user_id": self.user_id}, 
                {"$set": {f"my_stats.{role}": self.data}}, 
                upsert=True
            )
            await interaction.response.edit_message(content=f"✅ Saved config for **{role}**!", embed=None, view=None)

# ==========================================
# VIEW: DANH SÁCH DUNGEON
# ==========================================
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

# ==========================================
# COG CHÍNH
# ==========================================
class DungeonStats(commands.Cog):
    def __init__(self, bot): 
        self.bot = bot

    @staticmethod
    async def _perform_check(interaction: discord.Interaction, dg_name: str):
        await interaction.response.defer(ephemeral=True)
        player = await db.players.find_one({"user_id": interaction.user.id})
        
        cfg = await db.dungeon_configs.find_one({"dg_name": dg_name})
        if not cfg:
            return await interaction.followup.send(f"❌ Error: Cant find data of `{dg_name}` in DB.", ephemeral=True)

        if not player or "my_stats" not in player or not player["my_stats"]:
            return await interaction.followup.send("❌ Please use `/mygear` first!", ephemeral=True)

        req = cfg.get("reqs", {})
        has_any_passed = False 
        
        embed = discord.Embed(title=f"Check: {dg_name.upper()}")
        
        for role_name, stats in player["my_stats"].items():
            if not isinstance(stats, dict): 
                continue
                
            results = []
            is_role_ok = True
            
            for cat in ["gear", "vice", "deck", "bracelet"]:
                u_val = stats.get(cat)
                allowed = req.get(cat, [])
                
                if u_val in allowed:
                    results.append(f"✅ {cat.upper()}: {u_val}")
                else:
                    allowed_str = ', '.join(allowed) if allowed else 'None'
                    results.append(f"❌ {cat.upper()}: {u_val} (Req: {allowed_str})")
                    is_role_ok = False
            
            if is_role_ok:
                has_any_passed = True
                
            status_text = "✅ PASS" if is_role_ok else "❌ FAIL"
            embed.add_field(name=f"Role: {role_name} [{status_text}]", value="\n".join(results), inline=False)

        embed.color = discord.Color.green() if has_any_passed else discord.Color.red()
        
        if not embed.fields:
            return await interaction.followup.send("❌ Cant check your gear info, please re update!", ephemeral=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="mygear", description="Set your character profile")
    async def mygear(self, interaction: discord.Interaction):
        # 1. Kiểm tra xem người dùng đã có profile và đã có IGN chưa
        p = await db.players.find_one({"user_id": interaction.user.id})
        
        # 2. Phân nhánh xử lý:
        if not p or not p.get("ign") or p.get("ign") == "Not Set":
            # TRƯỜNG HỢP A: Chưa có IGN -> Bắt buộc phải nhập IGN trước
            # (Gửi Modal như bạn đã làm)
            await interaction.response.send_modal(MyGearIGNModal(self.bot))
        else:
            # TRƯỜNG HỢP B: Đã có IGN rồi -> Bỏ qua bước nhập tên, nhảy thẳng vào chọn Gear
            ign_value = p.get("ign")
            embed = discord.Embed(
                title="⚙️ Setup MyGear", 
                description=f"Current profile: **{ign_value}**\nPlease select role to setup gears:", 
                color=discord.Color.blue()
            )
            # Truyền thẳng view MyGearWizard
            await interaction.response.send_message(embed=embed, view=MyGearWizard(interaction.user.id), ephemeral=True)

    @app_commands.command(name="showmygear", description="Flex Gear")
    async def showmygear(self, interaction: discord.Interaction):
        p = await db.players.find_one({"user_id": interaction.user.id})
        
        if not p or "my_stats" not in p or not p["my_stats"]: 
            return await interaction.response.send_message("❌ Your gear information is empty!", ephemeral=True)
        
        # 1. Kiểm tra trực tiếp xem có IGN chưa, nếu chưa hiện rõ chữ cảnh báo
        ign_in_db = p.get('ign')
        if not ign_in_db or ign_in_db == "Not Set":
            player_ign = f"⚠️ {interaction.user.name} (Missing IGN)"
        else:
            player_ign = ign_in_db
            
        embed = discord.Embed(title=f"🛡️ {player_ign}'s Profile", color=discord.Color.gold())
        
        for role_name, stats in p["my_stats"].items():
            if isinstance(stats, dict):
                value_str = f"Gear: {stats.get('gear', 'N/A')}\nVice: {stats.get('vice', 'N/A')}\nDeck: {stats.get('deck', 'N/A')}\nBracelet: {stats.get('bracelet', 'N/A')}"
                embed.add_field(name=f"Role: {role_name}", value=value_str, inline=False)
        
        await interaction.response.send_message(embed=embed)
        

    @app_commands.command(name="dglist", description="Check gear requirement of dg")
    async def dglist(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        dungeons = await db.dungeon_configs.find({}).to_list(length=25)
        if not dungeons: 
            return await interaction.response.send_message("❌ Empty.", ephemeral=True)
        await interaction.followup.send("📍 Please select dungeon", view=DungeonListView(dungeons))

        
async def setup(bot):
    print("DEBUG: Đang load Cog DungeonStats...") 
    await bot.add_cog(DungeonStats(bot))
    print("DEBUG: Đã load thành công!")