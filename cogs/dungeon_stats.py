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
        self.refresh_menu()

    def refresh_menu(self):
        self.clear_items()
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
        elif self.step == 2:
            select = discord.ui.Select(placeholder="Chọn Vice", options=[discord.SelectOption(label=v) for v in VICE_OPTIONS[self.data["role"]]])
            async def vice_callback(interaction: discord.Interaction):
                self.data["vice"] = interaction.data["values"][0]
                self.step = 3
                await self.next_step(interaction)
            select.callback = vice_callback
            self.add_item(select)
        elif self.step == 3:
            select = discord.ui.Select(placeholder="Chọn Deck", options=[discord.SelectOption(label=d) for d in DECK_OPTIONS[self.data["role"]]])
            async def deck_callback(interaction: discord.Interaction):
                self.data["deck"] = interaction.data["values"][0]
                self.step = 4
                await self.next_step(interaction)
            select.callback = deck_callback
            self.add_item(select)

    async def next_step(self, interaction: discord.Interaction):
        if self.step < 4:
            self.refresh_menu()
            embed = discord.Embed(title="⚙️ Setup MyGear", color=discord.Color.blue())
            embed.add_field(name="Current", value=f"Role: {self.data['role'] or '...'}\nGear: {self.data['gear'] or '...'}\nVice: {self.data['vice'] or '...'}\nDeck: {self.data['deck'] or '...'}")
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
    @staticmethod
    async def _perform_check(interaction: discord.Interaction, dg_name: str):
        await interaction.response.defer(ephemeral=True)
        player = await db.players.find_one({"user_id": interaction.user.id})
        
        # Lấy thông tin Dungeon từ DB
        cfg = await db.dungeon_configs.find_one({"dg_name": dg_name})
        if not cfg:
            return await interaction.followup.send(f"❌ Error: Cant check infomation of`{dg_name}` in DB.", ephemeral=True)

        # Kiểm tra xem người dùng đã setup gear chưa
        if not player or "my_stats" not in player or not player["my_stats"]:
            return await interaction.followup.send("❌ Please use `/mygear` first!", ephemeral=True)

        req = cfg.get("reqs", {})
        has_any_passed = False # Biến cờ để theo dõi xem có role nào pass không
        
        embed = discord.Embed(title=f"Check: {dg_name.upper()}")
        
        # Duyệt qua toàn bộ các role mà user đã lưu
        for role_name, stats in player["my_stats"].items():
            if not isinstance(stats, dict): 
                continue
                
            results = []
            is_role_ok = True
            
            # Kiểm tra từng hạng mục của role này với yêu cầu của Dungeon
            for cat in ["gear", "vice", "deck"]:
                u_val = stats.get(cat)
                allowed = req.get(cat, [])
                
                if u_val in allowed:
                    results.append(f"✅ {cat.upper()}: {u_val}")
                else:
                    allowed_str = ', '.join(allowed) if allowed else 'None'
                    results.append(f"❌ {cat.upper()}: {u_val} (Req: {allowed_str})")
                    is_role_ok = False
            
            # Nếu role này đạt đủ mọi chỉ tiêu, đánh dấu là user đã pass
            if is_role_ok:
                has_any_passed = True
                
            status_text = "✅ PASS" if is_role_ok else "❌ FAIL"
            embed.add_field(name=f"Role: {role_name} [{status_text}]", value="\n".join(results), inline=False)

        # Đổi màu embed dựa trên việc có ít nhất 1 role pass hay không
        embed.color = discord.Color.green() if has_any_passed else discord.Color.red()
        
        if not embed.fields:
            return await interaction.followup.send("❌ Error: cant check your gear's infomation", ephemeral=True)

        await interaction.followup.send(embed=embed, ephemeral=True)
    @app_commands.command(name="mygear", description="Update your profile")
    async def mygear(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=discord.Embed(title="⚙️ Setup MyGear", description="Chọn role để bắt đầu:", color=discord.Color.blue()), view=MyGearWizard(interaction.user.id), ephemeral=True)

    @app_commands.command(name="showmygear", description="Flex Gear")
    async def showmygear(self, interaction: discord.Interaction):
        p = await db.players.find_one({"user_id": interaction.user.id})
        
        if not p or "my_stats" not in p or not p["my_stats"]: 
            return await interaction.response.send_message("❌ Your gear information is empty!", ephemeral=True)
        
        embed = discord.Embed(title=f"🛡️ {interaction.user.name}'s Profile", color=discord.Color.gold())
        
        for role_name, stats in p["my_stats"].items():
            if isinstance(stats, dict):
                value_str = f"Gear: {stats.get('gear', 'N/A')}\nVice: {stats.get('vice', 'N/A')}\nDeck: {stats.get('deck', 'N/A')}"
                embed.add_field(name=f"Role: {role_name}", value=value_str, inline=False)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="dglist", description="List of Dungeons")
    async def dglist(self, interaction: discord.Interaction):
        dungeons = await db.dungeon_configs.find({}).to_list(length=25)
        if not dungeons: 
            return await interaction.response.send_message("❌ Empty.", ephemeral=True)
        await interaction.response.send_message("📍 Please select dungeon", view=DungeonListView(dungeons), ephemeral=True)

async def setup(bot): 
    await bot.add_cog(DungeonStats(bot))