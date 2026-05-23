import discord
from discord.ext import commands

# ==========================
# CẤU HÌNH TÊN ROLE
# ==========================
TOURIST_ROLE_NAME = "Tourist"
STAGE_ROLES = ["Newbie stage", "Mid game stage", "Endgame stage"]
COMBAT_ROLES = ["DPS", "TANK"]
MEMBER_ROLE_NAME = "Member"

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
# VIEW: BẢNG CHỌN ROLE CHÍNH
# ==========================
class ServerRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    # ==========================
    # 1. DROPDOWN CHO TOURIST ROLE
    # ==========================
    @discord.ui.select(
        placeholder="🔔 Notifications / Alerts (Tourist)...",
        min_values=0,
        max_values=1,
        options=[
            discord.SelectOption(label="Get Tourist Role", value="get", description="Receive alerts 5 minutes before events", emoji="📢"),
            discord.SelectOption(label="Remove Tourist Role", value="remove", description="Stop receiving active mentions", emoji="🔕")
        ],
        custom_id="tourist_role_select",
        row=0
    )
    async def tourist_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.defer(ephemeral=True)
        
        role = discord.utils.get(interaction.guild.roles, name=TOURIST_ROLE_NAME)
        if not role:
            await interaction.followup.send(MESSAGES["role_not_found"]["en"], view=TranslationView("role_not_found"), ephemeral=True)
            return

        # Xử lý dựa trên giá trị người dùng chọn
        if "get" in select.values:
            if role not in interaction.user.roles:
                await interaction.user.add_roles(role)
        elif "remove" in select.values or len(select.values) == 0:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)

        await interaction.followup.send(MESSAGES["tourist_updated"]["en"], view=TranslationView("tourist_updated"), ephemeral=True)

    # ==========================
    # 2. DROPDOWN CHO STAGE ROLE
    # ==========================
    @discord.ui.select(
        placeholder="🌱 Game Progression Stages...",
        min_values=0,
        max_values=1,
        options=[
            discord.SelectOption(label="Newbie stage", description="Just starting your journey", emoji="🌱"),
            discord.SelectOption(label="Mid game stage", description="Building up your strength", emoji="⚔️"),
            discord.SelectOption(label="Endgame stage", description="Conquering late game content", emoji="👑")
        ],
        custom_id="stage_role_select",
        row=1
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
    # 3. DROPDOWN CHO COMBAT ROLE (DPS/TANK)
    # ==========================
    @discord.ui.select(
        placeholder="🗡️ Combat Styles / Roles...",
        min_values=0,
        max_values=2, # Cho phép chọn cả 2
        options=[
            discord.SelectOption(label="DPS", description="High damage output focus", emoji="🗡️"),
            discord.SelectOption(label="TANK", description="Frontline crowd control & defense", emoji="🛡️")
        ],
        custom_id="combat_role_select",
        row=2
    )
    async def combat_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.defer(ephemeral=True)
        
        roles_to_add = []
        roles_to_remove = []

        for name in COMBAT_ROLES:
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

        await interaction.followup.send(MESSAGES["combat_updated"]["en"], view=TranslationView("combat_updated"), ephemeral=True)


class Roles(commands.Cog, name="Management and Roles"):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(ServerRolesView())

    @commands.command(name="setup_role_panel")
    @commands.has_permissions(administrator=True)
    async def setup_role_panel(self, ctx):
        """Triển khai bảng chọn Role dạng Dropdown hoàn toàn"""
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

    @commands.command(name="give_member_all")
    @commands.has_permissions(administrator=True)
    async def give_member_all(self, ctx):
        """Cấp role Member cho toàn bộ người dùng trong server (chỉ Admin)"""
        role = discord.utils.get(ctx.guild.roles, name=MEMBER_ROLE_NAME)
        if not role:
            await ctx.send(f"❌ Không tìm thấy role **{MEMBER_ROLE_NAME}** trong server.")
            return

        await ctx.send("⏳ Giving role for all member...")
        
        count = 0
        for member in ctx.guild.members:
            if not member.bot and role not in member.roles:
                try:
                    await member.add_roles(role)
                    count += 1
                except discord.Forbidden:
                    pass 
                except discord.HTTPException:
                    pass 
        
        await ctx.send(f"✅ Done! Already give **{MEMBER_ROLE_NAME}** for **{count}** members.")


async def setup(bot):
    await bot.add_cog(Roles(bot))