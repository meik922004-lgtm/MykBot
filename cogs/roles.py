import discord
from discord.ext import commands
import json
import os

# ==========================
# CẤU HÌNH ROLE CỐ ĐỊNH & JSON
# ==========================
TOURIST_ROLE_NAME = "Tourist"
STAGE_ROLES = ["Newbie stage", "Mid game stage", "Endgame stage"]
MEMBER_ROLE_NAME = "Member"
CONFIG_FILE = "roles_config.json"

# Hàm tải danh sách role từ JSON
def load_combat_roles():
    if not os.path.exists(CONFIG_FILE):
        default_data = {"combat_roles": ["DPS", "TANK"]}
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_data, f)
        return default_data["combat_roles"]
    
    with open(CONFIG_FILE, "r") as f:
        data = json.load(f)
        return data.get("combat_roles", [])

# Hàm lưu danh sách role mới vào JSON
def save_combat_roles(roles_list):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"combat_roles": roles_list}, f)

# ==========================
# TỪ ĐIỂN NGÔN NGỮ (DICTIONARY)
# ==========================
MESSAGES = {
    "role_not_found": {
        "en": "❌ **Cannot find the requested role(s) in this server.**",
        "de": "🇩🇪 Die angeforderte(n) Rolle(n) wurde(n) auf diesem Server nicht gefunden.",
        "vn": "🇻🇳 Không tìm thấy (các) role yêu cầu trong server.",
        "id": "🇮🇩 Tidak dapat menemukan role yang diminta di server ini.",
        "br": "🇧🇷 Não foi possível encontrar o(s) cargo(s) solicitado(s) neste servidor."
    },
    "tourist_updated": {
        "en": "✅ **Your Tourist role preference has been updated!**",
        "de": "🇩🇪 Deine Tourist-Rollenpräferenz wurde aktualisiert!",
        "vn": "🇻🇳 Đã cập nhật trạng thái role Tourist của bạn!",
        "id": "🇮🇩 Preferensi role Tourist Anda telah diperbarui!",
        "br": "🇧🇷 Sua preferência do cargo Tourist foi atualizada!"
    },
    "stage_updated": {
        "en": "✅ **Updated your Progression Stage role!**",
        "de": "🇩🇪 Deine Fortschritts-Rolle wurde aktualisiert!",
        "vn": "🇻🇳 Đã cập nhật role Giai đoạn của bạn!",
        "id": "🇮🇩 Role Tahap Perkembangan Anda berhasil diperbarui!",
        "br": "🇧🇷 Seu cargo de Estágio de Progresso foi atualizado!"
    },
    "combat_updated": {
        "en": "✅ **Updated your Combat roles!**",
        "de": "🇩🇪 Deine Kampf-Rollen wurden aktualisiert!",
        "vn": "🇻🇳 Đã cập nhật role Hệ chiến đấu của bạn!",
        "id": "🇮🇩 Role Tempur Anda berhasil diperbarui!",
        "br": "🇧🇷 Seus cargos de Combate foram atualizados!"
    }
}

# ==========================
# VIEW: NÚT BẤM DỊCH THUẬT
# ==========================
class TranslationView(discord.ui.View):
    def __init__(self, msg_key: str):
        super().__init__(timeout=None)
        self.msg_key = msg_key

    async def update_message(self, interaction: discord.Interaction, lang: str):
        content = MESSAGES[self.msg_key][lang]
        await interaction.response.edit_message(content=content, view=self)

    @discord.ui.button(emoji="🇬🇧", style=discord.ButtonStyle.secondary)
    async def btn_en(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_message(interaction, "en")

    @discord.ui.button(emoji="🇩🇪", style=discord.ButtonStyle.secondary)
    async def btn_de(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_message(interaction, "de")

    @discord.ui.button(emoji="🇻🇳", style=discord.ButtonStyle.secondary)
    async def btn_vn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_message(interaction, "vn")

    @discord.ui.button(emoji="🇮🇩", style=discord.ButtonStyle.secondary)
    async def btn_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_message(interaction, "id")

    @discord.ui.button(emoji="🇧🇷", style=discord.ButtonStyle.secondary)
    async def btn_br(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_message(interaction, "br")


# ==========================
# SELECT: COMBAT ROLES ĐỘNG (DYNAMIC)
# ==========================
class DynamicCombatSelect(discord.ui.Select):
    def __init__(self):
        combat_roles = load_combat_roles()
        options = [
            discord.SelectOption(label=role, description=f"Chọn để lấy role {role}", emoji="⚔️") 
            for role in combat_roles
        ]
        
        # Đảm bảo bot không lỗi nếu admin xóa hết role
        if not options:
            options = [discord.SelectOption(label="None", description="Chưa có role nào được set up")]

        super().__init__(
            placeholder="🗡️ Combat Styles / Roles...",
            min_values=0,
            max_values=len(options) if combat_roles else 1,
            options=options,
            custom_id="combat_role_select",
            row=2
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        combat_roles = load_combat_roles()
        
        roles_to_add = []
        roles_to_remove = []

        for name in combat_roles:
            role = discord.utils.get(interaction.guild.roles, name=name)
            if role:
                if name in self.values:
                    roles_to_add.append(role)
                elif role in interaction.user.roles:
                    roles_to_remove.append(role)

        if roles_to_remove:
            await interaction.user.remove_roles(*roles_to_remove)
        if roles_to_add:
            await interaction.user.add_roles(*roles_to_add)

        await interaction.followup.send(MESSAGES["combat_updated"]["en"], view=TranslationView("combat_updated"), ephemeral=True)


# ==========================
# VIEW: BẢNG CHỌN ROLE CHÍNH
# ==========================
class ServerRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        # Thêm Dropdown Động vào View
        self.add_item(DynamicCombatSelect())

    # 1. DROPDOWN CHO TOURIST ROLE
    @discord.ui.select(
        placeholder="🔔 Notifications / Alerts (Tourist)...",
        min_values=0, max_values=1,
        options=[
            discord.SelectOption(label="Get Tourist Role", value="get", description="Receive alerts 5 minutes before events", emoji="📢"),
            discord.SelectOption(label="Remove Tourist Role", value="remove", description="Stop receiving active mentions", emoji="🔕")
        ],
        custom_id="tourist_role_select", row=0
    )
    async def tourist_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.defer(ephemeral=True)
        role = discord.utils.get(interaction.guild.roles, name=TOURIST_ROLE_NAME)
        if not role:
            await interaction.followup.send(MESSAGES["role_not_found"]["en"], view=TranslationView("role_not_found"), ephemeral=True)
            return

        if "get" in select.values:
            if role not in interaction.user.roles:
                await interaction.user.add_roles(role)
        elif "remove" in select.values or len(select.values) == 0:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)

        await interaction.followup.send(MESSAGES["tourist_updated"]["en"], view=TranslationView("tourist_updated"), ephemeral=True)

    # 2. DROPDOWN CHO STAGE ROLE
    @discord.ui.select(
        placeholder="🌱 Game Progression Stages...",
        min_values=0, max_values=1,
        options=[
            discord.SelectOption(label="Newbie stage", description="Just starting your journey", emoji="🌱"),
            discord.SelectOption(label="Mid game stage", description="Building up your strength", emoji="⚔️"),
            discord.SelectOption(label="Endgame stage", description="Conquering late game content", emoji="👑")
        ],
        custom_id="stage_role_select", row=1
    )
    async def stage_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.defer(ephemeral=True)
        roles_to_add = []
        roles_to_remove = []

        for name in STAGE_ROLES:
            role = discord.utils.get(interaction.guild.roles, name=name)
            if role:
                if name in select.values:
                    roles_to_add.append(role)
                elif role in interaction.user.roles:
                    roles_to_remove.append(role)

        if roles_to_remove:
            await interaction.user.remove_roles(*roles_to_remove)
        if roles_to_add:
            await interaction.user.add_roles(*roles_to_add)

        await interaction.followup.send(MESSAGES["stage_updated"]["en"], view=TranslationView("stage_updated"), ephemeral=True)


# ==========================
# COG: QUẢN LÝ
# ==========================
class Roles(commands.Cog, name="Management and Roles"):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(ServerRolesView())

    @commands.command(name="setup_role_panel")
    @commands.has_permissions(administrator=True)
    async def setup_role_panel(self, ctx):
        """Triển khai bảng chọn Role dạng Dropdown"""
        embed = discord.Embed(
            title="🔔 SERVER ROLES MENU 🔔",
            description=(
                f"Please select your server roles using the dropdown menus below! "
                f"You can translate notifications by clicking the flags afterwards.\n\n"
                f"--- \n\n"
                f"**📢 Tours & Raids Alerts**\n"
                f"Turn on/off notification of Raid tour .\n\n"
                f"**🌱 Game Progression Stage**\n"
                f"Choose your progression (Only 1).\n\n"
                f"**🗡️ Combat Roles**\n"
                f"Pick your playstyle (Can choose all)."
            ),
            color=discord.Color.purple()
        )
        embed.set_footer(text=f"MyK Bot • {ctx.guild.name} Automation")
        await ctx.send(embed=embed, view=ServerRolesView())

    # ==========================
    # LỆNH ADMIN: THÊM / XÓA ROLE ĐỘNG
    # ==========================
    @commands.command(name="add_role")
    @commands.has_permissions(administrator=True)
    async def add_role(self, ctx, *, role_name: str):
        """Add new combat role to menu (Example: !add_role UFM)"""
        combat_roles = load_combat_roles()
        if role_name in combat_roles:
            await ctx.send(f"⚠️ Role **{role_name}** Already in list.")
            return
            
        combat_roles.append(role_name)
        save_combat_roles(combat_roles)
        await ctx.send(f"✅ Sucessful added role **{role_name}** to system.\n👉 **Notice:** Please use command `!setup_role_panel` To creat new menu!")

    @commands.command(name="remove_role")
    @commands.has_permissions(administrator=True)
    async def remove_role(self, ctx, *, role_name: str):
        """Remove role from meru (Example: !remove_role TANK)"""
        combat_roles = load_combat_roles()
        if role_name not in combat_roles:
            await ctx.send(f"⚠️ Role **{role_name}** is not exist in system.")
            return
            
        combat_roles.remove(role_name)
        save_combat_roles(combat_roles)
        await ctx.send(f"🗑️ Removed **{role_name}** from system.\n👉 **Notice:** Please use command `!setup_role_panel` To creat new menu!")

    @commands.command(name="give_member_all")
    @commands.has_permissions(administrator=True)
    async def give_member_all(self, ctx):
        """Give Role Member to all people"""
        role = discord.utils.get(ctx.guild.roles, name=MEMBER_ROLE_NAME)
        if not role:
            await ctx.send(f"❌Role **{MEMBER_ROLE_NAME}** is not existed.")
            return

        await ctx.send("⏳ Giving role for all members...")
        count = 0
        for member in ctx.guild.members:
            if not member.bot and role not in member.roles:
                try:
                    await member.add_roles(role)
                    count += 1
                except (discord.Forbidden, discord.HTTPException):
                    pass 
        
        await ctx.send(f"✅ Done! Already give **{MEMBER_ROLE_NAME}** for **{count}** members.")

async def setup(bot):
    await bot.add_cog(Roles(bot))