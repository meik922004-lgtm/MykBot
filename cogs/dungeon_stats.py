import discord
from discord.ext import commands
from discord import app_commands
from Database import db

# ==========================================
# CẤU HÌNH DỮ LIỆU
# ==========================================
GEAR_OPTIONS = ["Full fang gear", "1 piece of Spiral", "2 piece of Spiral", "Full Spiral set", "1 piece of corrupted", "2 piece of corrupted", "full set of corrupted"]
VICE_OPTIONS = {
    "AA": ["D.ark 4", "D,ark 5", "D.ark 6", "D.ark Uncontroll", "Void vice"], 
    "SK": ["Royal Vice","Truevice", "Truevice(Advance)", "Void vice"], 
    "TANK": ["D.ark 6", "D.ark Chrome", "Void vice"]
}
DECK_OPTIONS = {
    "AA": ["Divinus", "CrimsonPath/Corrupted Power", "Power of Darkness / Crimson Nexus", "Eclipsed Genesis"], 
    "SK": ["Celesfracture", "Latent Power", "RoyalKnight X/ DemonLord X", "Legendary Core"], 
    "TANK": ["Fortis Magna", "Crown", "Royal Crown", "Eternal Dominion"]
}

# ==========================================
# WIZARD: CẬP NHẬT GEAR
# ==========================================
class MyGearWizard(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.data = {"role": None, "gear": None, "vice": None, "deck": None}
        self.step = 0
        
        # Gọi hàm tạo menu
        self.refresh_menu()

    def refresh_menu(self):
        self.clear_items()
        print(f"DEBUG: Đang tạo menu ở bước {self.step}") # Kiểm tra trong console
        
        if self.step == 0:
            select = discord.ui.Select(placeholder="Chọn Role", options=[discord.SelectOption(label=r) for r in ["AA", "SK", "TANK"]])
            async def role_callback(interaction: discord.Interaction):
                self.data["role"] = interaction.data["values"][0]
                self.step = 1
                await self.next_step(interaction)
            select.callback = role_callback
            self.add_item(select)
            
        elif self.step == 1:
            select = discord.ui.Select(placeholder="Chọn Gear", options=[discord.SelectOption(label=g) for g in GEAR_OPTIONS])
            async def gear_callback(interaction: discord.Interaction):
                self.data["gear"] = interaction.data["values"][0]
                self.step = 2
                await self.next_step(interaction)
            select.callback = gear_callback
            self.add_item(select)
        
        # (Tiếp tục với các step khác...)
        # Lưu ý: Đảm bảo bạn đã thêm các step 2, 3 tương tự như trên

    async def next_step(self, interaction: discord.Interaction):
        if self.step < 4:
            self.refresh_menu()
            embed = discord.Embed(title="⚙️ Setup MyGear", color=discord.Color.blue())
            embed.add_field(name="Current", value=f"Role: {self.data['role'] or '...'}\nGear: {self.data['gear'] or '...'}\nVice: {self.data['vice'] or '...'}\nDeck: {self.data['deck'] or '...'}")
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await db.players.update_one({"user_id": self.user_id}, {"$set": {"my_stats": self.data}}, upsert=True)
            await interaction.response.edit_message(content="✅ Saved config!", embed=None, view=None)

# ==========================================
# VIEW: DANH SÁCH DUNGEON VỚI NÚT BẤM
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
        cfg = await db.dungeon_configs.find_one({"dg_name": dg_name.lower()})
        
        if not player or "my_stats" not in player:
            return await interaction.followup.send("❌ Please use `/mygear` to setup profile first!", ephemeral=True)
        if not cfg or "reqs" not in cfg:
            return await interaction.followup.send("❌ Dungeon standard is empty.", ephemeral=True)

        s = player["my_stats"]
        req = cfg["reqs"]
        results = []
        is_ok = True

        for cat in ["gear", "vice", "deck"]:
            u_val = s.get(cat)
            allowed = req.get(cat, [])
            if u_val in allowed:
                results.append(f"✅ {cat.upper()}: {u_val}")
            else:
                # Xử lý trường hợp allowed rỗng để bot không ném lỗi
                results.append(f"❌ {cat.upper()}: {u_val} (Requirement: {', '.join(allowed) if allowed else 'None'})")
                is_ok = False

        embed = discord.Embed(title=f"Check: {dg_name.upper()}", color=discord.Color.green() if is_ok else discord.Color.red())
        embed.description = "\n".join(results)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="mygear", description="Update your profile")
    async def mygear(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚙️ Setup MyGear", 
            description="Please choose your role before setup MyGear:", 
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=MyGearWizard(interaction.user.id), ephemeral=True)

    @app_commands.command(name="showmygear", description="Flex Gear")
    async def showmygear(self, interaction: discord.Interaction):
        p = await db.players.find_one({"user_id": interaction.user.id})
        if not p or "my_stats" not in p: 
            return await interaction.response.send_message("❌ Chưa setup!", ephemeral=True)
        
        s = p["my_stats"]
        embed = discord.Embed(title=f"🛡️ {interaction.user.name}", color=discord.Color.gold())
        for k, v in s.items(): 
            embed.add_field(name=k.upper(), value=v)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="dglist", description="List of Dungeons")
    async def dglist(self, interaction: discord.Interaction):
        cursor = db.dungeon_configs.find({})
        dungeons = await cursor.to_list(length=25)
        
        if not dungeons: 
            return await interaction.response.send_message("❌ Dungeons List is empty.", ephemeral=True)
        
        await interaction.response.send_message("📍 Select dungeon to check:", view=DungeonListView(dungeons), ephemeral=True)

async def setup(bot): 
    await bot.add_cog(DungeonStats(bot))