import discord
from discord import app_commands
from discord.ext import commands
from Database import db

# ==========================================
# 1. MODAL: BẢNG NHẬP CHỈ SỐ
# ==========================================
class RoleStatsModal(discord.ui.Modal):
    def __init__(self, role, dg_name):
        super().__init__(title=f"Please type your stats: {role}")
        self.role = role
        self.dg_name = dg_name
        
        # Nhập liệu theo chuẩn chỉ số in-game
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
            # Cập nhật thông số vào database
            await db.players.update_one({"user_id": interaction.user.id}, {"$set": {"my_stats": data}}, upsert=True)
            await interaction.response.send_message(f"✅ Stats saved for {self.role}!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please type a valid number!", ephemeral=True)


# ==========================================
# 2. VIEW: CHỌN ROLE VÀ MENU CHECK
# ==========================================
class RoleSelectView(discord.ui.View):
    def __init__(self, dg_name):
        super().__init__()
        self.dg_name = dg_name

    @discord.ui.button(label="DPS", style=discord.ButtonStyle.danger)
    async def dps(self, inter: discord.Interaction, btn: discord.ui.Button): 
        await inter.response.send_modal(RoleStatsModal("DPS", self.dg_name))

    @discord.ui.button(label="TANK", style=discord.ButtonStyle.primary)
    async def tank(self, inter: discord.Interaction, btn: discord.ui.Button): 
        await inter.response.send_modal(RoleStatsModal("TANK", self.dg_name))


class RaidMenuView(discord.ui.View):
    def __init__(self, dg_name):
        super().__init__(timeout=None)
        self.dg_name = dg_name

    @discord.ui.button(label="Update stats", style=discord.ButtonStyle.primary, custom_id="btn_update")
    async def update_stats(self, inter: discord.Interaction, btn: discord.ui.Button):
        await inter.response.send_message("Pick your role:", view=RoleSelectView(self.dg_name), ephemeral=True)

    @discord.ui.button(label="Check", style=discord.ButtonStyle.success, custom_id="btn_check")
    async def check_stats(self, inter: discord.Interaction, btn: discord.ui.Button):
        await inter.response.defer(ephemeral=True)
        player = await db.players.find_one({"user_id": inter.user.id})
        cfg = await db.dungeon_configs.find_one({"dg_name": self.dg_name.lower()})
        
        if not cfg or "min_stats" not in cfg:
            await inter.followup.send(f"❌ Server didn't set up the standard requirement for `{self.dg_name.upper()}`!", ephemeral=True)
            return

        if not player or "my_stats" not in player:
            await inter.followup.send("❌ You didn't update your stats! Please click **Update stats** first.", ephemeral=True)
            return

        u = player["my_stats"]
        role_key = u.get("role", "").lower()
        
        if role_key not in cfg["min_stats"]:
            await inter.followup.send(f"❌ Your stat role (`{role_key.upper()}`) does not match the dungeon requirements!", ephemeral=True)
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
                # Đã sửa lại hiển thị dấu >= cho logic hơn
                results.append(f"✅ {k.upper()}: {player_stat} >= {v}")
                
        embed = discord.Embed(
            title=f"Result {u['role']} - {self.dg_name.upper()}", 
            color=discord.Color.green() if is_ready else discord.Color.red()
        )
        embed.description = "\n".join(results)
        await inter.followup.send(embed=embed, ephemeral=True)


# ==========================================
# 3. COG DUNGEON STATS
# ==========================================
class DungeonStats(commands.Cog):
    def __init__(self, bot): 
        self.bot = bot
    
    # 3.1 Lệnh xem danh sách hầm ngục có thể check
    @app_commands.command(name="dglist", description="Xem danh sách các hầm ngục đang được hỗ trợ kiểm tra stats")
    async def dglist(self, interaction: discord.Interaction):
        # Tránh lỗi timeout nếu database phản hồi chậm
        await interaction.response.defer() 
        
        cursor = db.dungeon_configs.find({})
        dungeons_list = await cursor.to_list(length=100)
        
        count = len(dungeons_list)
        
        if count == 0:
            await interaction.followup.send("❌ There are no dungeons configured in the database.")
            return

        names = [d.get("dg_name", "Unknown").title() for d in dungeons_list]
        
        embed = discord.Embed(
            title="📜 List of dungeons you can check currently:", 
            color=discord.Color.green()
        )
        embed.add_field(name="📊 Total:", value=f"Supporting **{count}** dungeons.", inline=False)
        embed.add_field(name="📍 List of dungeons", value="\n".join([f"• {name}" for name in names]), inline=False)
        embed.set_footer(text="Use /dgcheck <name> to check your stats")
        
        await interaction.followup.send(embed=embed)
    
    # 3.2 Lệnh mở Menu check (ĐÃ ĐỔI TÊN ĐỂ TRÁNH XUNG ĐỘT VỚI LỆNH TẠO PT)
    @app_commands.command(name="dgcheck", description="Mở menu cập nhật và kiểm tra thông số cá nhân cho hầm ngục")
    @app_commands.describe(dg_name="Tên dungeon (VD: kaiser, royal_base, holy_beast)")
    async def dgcheck(self, interaction: discord.Interaction, dg_name: str):
        # UI chỉ hiện một lần, không cần ephemeral ở gốc để mọi người cùng thấy menu
        await interaction.response.send_message(f"🎮 **Menu Stats Check: {dg_name.upper()}**", view=RaidMenuView(dg_name))

    # 3.3 Lệnh cài đặt khung chuẩn (Chỉ dành cho Admin)
    @app_commands.command(name="setstd", description="Thiết lập chỉ số yêu cầu tối thiểu cho một hầm ngục")
    @app_commands.describe(dg_name="Tên dungeon cần tạo khung thông số")
    @app_commands.default_permissions(administrator=True)
    async def setstd(self, interaction: discord.Interaction, dg_name: str):
        default_cfg = {
            "dg_name": dg_name.lower(),
            "min_stats": {
                "dps": {"at": 50000, "ht": 20000, "hp": 50000},
                "tank": {"hp": 150000, "de": 40000, "bl": 150}
            }
        }
        await db.dungeon_configs.update_one({"dg_name": dg_name.lower()}, {"$set": default_cfg}, upsert=True)
        
        # Ẩn tin nhắn này đi để tránh rác kênh chat
        await interaction.response.send_message(f"✅ Đã tạo khung chuẩn cho `{dg_name.upper()}`. Hãy truy cập MongoDB Atlas để chỉnh sửa thông số chi tiết!", ephemeral=True)


async def setup(bot): 
    await bot.add_cog(DungeonStats(bot))