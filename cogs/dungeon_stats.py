import discord
from discord.ext import commands
from discord import app_commands
from Database import db

# --- CẤU HÌNH OPTION (Giữ nguyên như đã thống nhất) ---
GEAR_OPTIONS = ["Full fang gear", "1 piece of Spiral", "2 piece of Spiral", "Full Spiral set"]
VICE_OPTIONS = {"AA": ["Under D.ark 6", "D.ark Uncontroll", "Void vice"], "SK": ["Royal Vice", "Truevice(Advance)", "Void vice"], "TANK": ["Under D.ark 6", "D.ark Chrome", "Void vice"]}
DECK_OPTIONS = {"AA": ["Divinus", "CrimsonPath/Corrupted Power", "Power of Darkness / Crimson Nexus", "Eclipsed Genesis"], "SK": ["Celesfracture", "Latent Power", "RoyalKnight X/ DemonLord X", "Legendary Core"], "TANK": ["Fortis Magna", "Crown", "Royal Crown", "Eternal Dominion"]}

# ==========================================
# WIZARD: CẬP NHẬT GEAR
# ==========================================
class MyGearWizard(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.data = {"role": None, "gear": None, "vice": None, "deck": None}
        self.step = 0

    async def update_ui(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⚙️ Setup MyGear", color=discord.Color.blue())
        embed.add_field(name="Current", value=f"Role: {self.data['role'] or '...'}\nGear: {self.data['gear'] or '...'}\nVice: {self.data['vice'] or '...'}\nDeck: {self.data['deck'] or '...'}")
        
        self.clear_items()
        if self.step == 0:
            select = discord.ui.Select(placeholder="Chọn Role", options=[discord.SelectOption(label=r) for r in ["AA", "SK", "TANK"]])
            select.callback = lambda i: self.next_step(i, "role", 1)
        elif self.step == 1:
            select = discord.ui.Select(placeholder="Chọn Gear", options=[discord.SelectOption(label=g) for g in GEAR_OPTIONS])
            select.callback = lambda i: self.next_step(i, "gear", 2)
        elif self.step == 2:
            select = discord.ui.Select(placeholder="Chọn Vice", options=[discord.SelectOption(label=v) for v in VICE_OPTIONS[self.data["role"]]])
            select.callback = lambda i: self.next_step(i, "vice", 3)
        elif self.step == 3:
            select = discord.ui.Select(placeholder="Chọn Deck", options=[discord.SelectOption(label=d) for d in DECK_OPTIONS[self.data["role"]]])
            select.callback = lambda i: self.next_step(i, "deck", 4)
        
        if self.step < 4:
            self.add_item(select)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await db.players.update_one({"user_id": self.user_id}, {"$set": {"my_stats": self.data}}, upsert=True)
            await interaction.response.edit_message(content="✅ Đã lưu cấu hình!", embed=None, view=None)

    async def next_step(self, inter, key, next_step):
        self.data[key] = inter.data["values"][0]
        self.step = next_step
        await self.update_ui(inter)

# ==========================================
# COG CHÍNH
# ==========================================
class DungeonStats(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="mygear", description="Cập nhật Gear của bạn")
    async def mygear(self, interaction: discord.Interaction):
        await interaction.response.send_message(view=MyGearWizard(interaction.user.id), ephemeral=True)

    @app_commands.command(name="showmygear", description="Khoe Gear")
    async def showmygear(self, interaction: discord.Interaction):
        p = await db.players.find_one({"user_id": interaction.user.id})
        if not p: return await interaction.response.send_message("❌ Chưa setup!", ephemeral=True)
        s = p["my_stats"]
        embed = discord.Embed(title=f"🛡️ {interaction.user.name}", color=discord.Color.gold())
        for k, v in s.items(): embed.add_field(name=k.upper(), value=v)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="dgcheck", description="Kiểm tra điều kiện dungeon")
    async def dgcheck(self, interaction: discord.Interaction, dg_name: str):
        # 1. Lấy dữ liệu
        player = await db.players.find_one({"user_id": interaction.user.id})
        cfg = await db.dungeon_configs.find_one({"dg_name": dg_name.lower()})
        
        if not player or "my_stats" not in player: return await interaction.response.send_message("❌ Dùng /mygear trước!", ephemeral=True)
        if not cfg or "reqs" not in cfg: return await interaction.response.send_message("❌ Dungeon chưa cấu hình yêu cầu (Admin cần set reqs trong DB).", ephemeral=True)

        # 2. Logic so sánh mới (Categorical Check)
        s = player["my_stats"]
        req = cfg["reqs"]
        results = []
        is_ok = True

        for category in ["gear", "vice", "deck"]:
            user_val = s.get(category)
            allowed = req.get(category, [])
            if user_val in allowed:
                results.append(f"✅ {category.upper()}: {user_val}")
            else:
                results.append(f"❌ {category.upper()}: {user_val} (Yêu cầu: {', '.join(allowed)})")
                is_ok = False

        embed = discord.Embed(title=f"Check: {dg_name.upper()}", color=discord.Color.green() if is_ok else discord.Color.red())
        embed.description = "\n".join(results)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="dglist", description="Danh sách dungeon và yêu cầu")
    async def dglist(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cursor = db.dungeon_configs.find({})
        dungeons = await cursor.to_list(length=100)
        
        embed = discord.Embed(title="📜 Danh sách Dungeon", color=discord.Color.blue())
        for d in dungeons:
            reqs = d.get("reqs", {})
            req_str = f"Gear: {len(reqs.get('gear', []))} options"
            embed.add_field(name=d["dg_name"].upper(), value=req_str, inline=True)
        await interaction.followup.send(embed=embed)

async def setup(bot): await bot.add_cog(DungeonStats(bot))