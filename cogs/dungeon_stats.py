import discord
from discord.ext import commands
from Database import db

class RoleStatsModal(discord.ui.Modal):
    def __init__(self, role, dg_name):
        super().__init__(title=f"Please type your stats {role}")
        self.role = role
        self.dg_name = dg_name
        
        if role == "DPS":
            self.at = discord.ui.TextInput(label="AT", placeholder="Attack")
            self.ht = discord.ui.TextInput(label="HT", placeholder="Hit")
            self.hp = discord.ui.TextInput(label="HP", placeholder="HP")
            for item in [self.at, self.ht, self.hp]: self.add_item(item)
        else: # TANK
            self.hp = discord.ui.TextInput(label="HP", placeholder="HP")
            self.de = discord.ui.TextInput(label="DE", placeholder="Defense")
            self.bl = discord.ui.TextInput(label="BL (%)", placeholder="Block")
            for item in [self.hp, self.de, self.bl]: self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            data = {child.label.split(' ')[0].lower(): int(child.value) for child in self.children}
            data["role"] = self.role
            await db.players.update_one({"user_id": interaction.user.id}, {"$set": {"my_stats": data}}, upsert=True)
            await interaction.response.send_message(f"✅ Stats saved! {self.role}!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please type valid number!", ephemeral=True)

class RoleSelectView(discord.ui.View):
    def __init__(self, dg_name):
        super().__init__()
        self.dg_name = dg_name

    @discord.ui.button(label="DPS", style=discord.ButtonStyle.danger)
    async def dps(self, inter, btn): 
        await inter.response.send_modal(RoleStatsModal("DPS", self.dg_name))

    @discord.ui.button(label="TANK", style=discord.ButtonStyle.primary)
    async def tank(self, inter, btn): 
        await inter.response.send_modal(RoleStatsModal("TANK", self.dg_name))


class RaidMenuView(discord.ui.View):
    def __init__(self, dg_name):
        super().__init__(timeout=None)
        self.dg_name = dg_name

    @discord.ui.button(label="Update stats", style=discord.ButtonStyle.primary, custom_id="btn_update")
    async def update_stats(self, inter, btn):
        await inter.response.send_message("Pick your role:", view=RoleSelectView(self.dg_name), ephemeral=True)

    @discord.ui.button(label="Check", style=discord.ButtonStyle.success, custom_id="btn_check")
    async def check_stats(self, inter, btn):
        await inter.response.defer(ephemeral=True)
        player = await db.players.find_one({"user_id": inter.user.id})
        cfg = await db.dungeon_configs.find_one({"dg_name": self.dg_name.lower()})
        
        if not cfg or "min_stats" not in cfg:
            await inter.followup.send(f"❌ Server dind'st set up the standard requirement`{self.dg_name.upper()}`!", ephemeral=True)
            return

        if not player or "my_stats" not in player:
            await inter.followup.send("❌ You didn't update your stats!", ephemeral=True)
            return

        u = player["my_stats"]
        role_key = u.get("role", "").lower()
        
        if role_key not in cfg["min_stats"]:
            await inter.followup.send(f"❌ Your stat not reached the requirement for dungeon! `{role_key.upper()}`.", ephemeral=True)
            return

        req = cfg["min_stats"][role_key]
        results = []
        is_ready = True
        
        for k, v in req.items():
            player_stat = u.get(k, 0)
            if player_stat < v:
                results.append(f"❌ {k.upper()}: {player_stat} < {v}")
                is_ready = False
            else:
                results.append(f"✅ {k.upper()}: {player_stat}")
                
        embed = discord.Embed(
            title=f"Result {u['role']} - {self.dg_name.upper()}", 
            color=discord.Color.green() if is_ready else discord.Color.red()
        )
        embed.description = "\n".join(results)
        await inter.followup.send(embed=embed, ephemeral=True)

class DungeonStats(commands.Cog):
    def __init__(self, bot): 
        self.bot = bot
        # Cần quản lý persistent custom_ids nếu muốn menu giữ vĩnh viễn,
        # tạm thời view này được gọi ra từ command !raid nên timeout=None là đủ.

    
    @commands.command(name="dglist")
    async def dglist(self, ctx):
        await ctx.typing()
        
        # Truy vấn toàn bộ dữ liệu từ collection 'dungeon_configs'
        cursor = db.dungeon_configs.find({})
        dungeons_list = await cursor.to_list(length=100)
        
        count = len(dungeons_list)
        
        if count == 0:
            await ctx.send("❌ There is no dungeons configured in data base.")
            return

        # Lấy danh sách tên các Dungeon
        names = [d.get("dg_name", "Unknown") for d in dungeons_list]
        
        embed = discord.Embed(
            title="📜 List of dungeon can check currently:", 
            color=discord.Color.green()
        )
        
        embed.add_field(name="📊 Total:", value=f"have **{count}** dungeon is supporting.", inline=False)
        embed.add_field(name="📍 List of dungeons", value="\n".join([f"• {name}" for name in names]), inline=False)
        
        embed.set_footer(text="use !raid name-dg to check the stats")
        await ctx.send(embed=embed)
    
    @commands.command(name="raid")
    async def raid(self, ctx, dg_name: str):
        await ctx.send(f"🎮 **Menu Raid: {dg_name.upper()}**", view=RaidMenuView(dg_name))

    @commands.command(name="setstd")
    @commands.has_permissions(administrator=True)
    async def setstd(self, ctx, dg_name: str):
        default_cfg = {
            "dg_name": dg_name.lower(),
            "min_stats": {
                "dps": {"at": 50000, "ht": 20000, "hp": 50000},
                "tank": {"hp": 150000, "de": 40000, "bl": 150}
            }
        }
        await db.dungeon_configs.update_one({"dg_name": dg_name.lower()}, {"$set": default_cfg}, upsert=True)
        await ctx.send(f"✅ Đã tạo khung chuẩn cho {dg_name.upper()}. Hãy vào DB (MongoDB Atlas) chỉnh thông số chi tiết!")


async def setup(bot): 
    await bot.add_cog(DungeonStats(bot))