import discord
from discord import app_commands
from discord.ext import commands
from Database import db
from utils.checks import check_is_owner, is_admin_or_bot_owner

roles_config_col = db["roles_config"]

DEFAULT_ROLES_CONFIG = {
    "stage": ["Endgame stage", "Newbie stage", "Midgame stage"],
    "general": ["Member", "Tourist", "PIED", "Mugen", "MDG", "PDG", "APO", "PILLAR AB", "RBH"],
    "combat": ["DPS SK/AA", "UFM", "TANK"],
}


async def get_guild_roles_config(guild_id: int) -> dict:
    doc = await roles_config_col.find_one({"guild_id": guild_id})
    if not doc:
        doc = {"guild_id": guild_id, **{k: list(v) for k, v in DEFAULT_ROLES_CONFIG.items()}}
        await roles_config_col.insert_one(doc)
    return doc


class AddRoleSelect(discord.ui.Select):
    def __init__(self, category_name: str, options_list: list[str], is_stage: bool = False):
        options = [discord.SelectOption(label=name, value=name) for name in options_list[:25]]
        max_vals = 1 if is_stage else len(options)
        super().__init__(
            placeholder=f"Chọn {category_name} Roles (Nhận)...",
            min_values=1,
            max_values=max_vals,
            options=options,
        )
        self.is_stage = is_stage

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user

        try:
            if self.is_stage:
                selected_name = self.values[0]
                target_role = discord.utils.get(guild.roles, name=selected_name)
                if not target_role:
                    return await interaction.followup.send(f"❌ Role **{selected_name}** chưa được tạo trên server!", ephemeral=True)
                if target_role in member.roles:
                    return await interaction.followup.send(f"⚠️ Bạn đã có role **{selected_name}** rồi!", ephemeral=True)

                config = await get_guild_roles_config(guild.id)
                stage_names = config.get("stage", [])
                roles_to_remove = [
                    r for n in stage_names
                    if n != selected_name and (r := discord.utils.get(guild.roles, name=n)) in member.roles
                ]
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove)
                await member.add_roles(target_role)
                return await interaction.followup.send(f"✅ Đã cập nhật Stage Role thành: **{selected_name}**", ephemeral=True)

            roles_to_add, already_have, not_found = [], [], []
            for role_name in self.values:
                role = discord.utils.get(guild.roles, name=role_name)
                if not role:
                    not_found.append(role_name)
                elif role in member.roles:
                    already_have.append(role_name)
                else:
                    roles_to_add.append(role)

            if roles_to_add:
                await member.add_roles(*roles_to_add)

            msg_parts = []
            if roles_to_add:
                msg_parts.append(f"➕ Đã thêm: {', '.join(f'**{r.name}**' for r in roles_to_add)}")
            if already_have:
                msg_parts.append(f"⚠️ Đã có sẵn: {', '.join(already_have)}")
            if not_found:
                msg_parts.append(f"❌ Không tồn tại trên server: {', '.join(not_found)}")

            await interaction.followup.send("\n".join(msg_parts) or "⚠️ Không có thay đổi.", ephemeral=True)

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Bot không đủ quyền cấp role này (hãy kéo role của Bot lên cao hơn trong Server Settings).",
                ephemeral=True,
            )


class RemoveRoleSelect(discord.ui.Select):
    def __init__(self, category_name: str, options_list: list[str]):
        options = [discord.SelectOption(label=name, value=name) for name in options_list[:25]]
        super().__init__(
            placeholder=f"Chọn {category_name} Roles (Gỡ bỏ)...",
            min_values=1,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user

        roles_to_remove, dont_have, not_found = [], [], []
        for role_name in self.values:
            role = discord.utils.get(guild.roles, name=role_name)
            if not role:
                not_found.append(role_name)
            elif role not in member.roles:
                dont_have.append(role_name)
            else:
                roles_to_remove.append(role)

        try:
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove)
        except discord.Forbidden:
            return await interaction.followup.send(
                "❌ Bot không đủ quyền gỡ role này (hãy kiểm tra thứ tự role của Bot).",
                ephemeral=True,
            )

        msg_parts = []
        if roles_to_remove:
            msg_parts.append(f"➖ Đã gỡ: {', '.join(f'**{r.name}**' for r in roles_to_remove)}")
        if dont_have:
            msg_parts.append(f"⚠️ Bạn không có: {', '.join(dont_have)}")
        if not_found:
            msg_parts.append(f"❌ Không tồn tại trên server: {', '.join(not_found)}")

        await interaction.followup.send("\n".join(msg_parts) or "⚠️ Không có thay đổi.", ephemeral=True)


class SettingModal(discord.ui.Modal):
    def __init__(self, action: str):
        super().__init__(title="Thêm Role vào Menu" if action == "add" else "Xóa Role khỏi Menu")
        self.action = action
        self.category = discord.ui.TextInput(
            label="Danh mục (stage / general / combat)",
            placeholder="Nhập: stage, general hoặc combat",
            required=True,
            max_length=10,
        )
        self.role_name = discord.ui.TextInput(
            label="Tên Role",
            placeholder="Nhập chính xác tên Role trên server",
            required=True,
        )
        self.add_item(self.category)
        self.add_item(self.role_name)

    async def on_submit(self, interaction: discord.Interaction):
        cat_val = self.category.value.strip().lower()
        role_val = self.role_name.value.strip()

        if cat_val not in ("stage", "general", "combat"):
            return await interaction.response.send_message(
                "❌ Danh mục không hợp lệ! Chỉ chấp nhận `stage`, `general` hoặc `combat`.",
                ephemeral=True,
            )

        config = await get_guild_roles_config(interaction.guild_id)
        current_list = config.get(cat_val, [])

        if self.action == "add":
            if role_val in current_list:
                return await interaction.response.send_message(f"⚠️ Role **{role_val}** đã có trong `{cat_val}`.", ephemeral=True)
            await roles_config_col.update_one(
                {"guild_id": interaction.guild_id},
                {"$addToSet": {cat_val: role_val}},
                upsert=True,
            )
            await interaction.response.send_message(f"✅ Đã thêm **{role_val}** vào danh mục `{cat_val}`!", ephemeral=True)
        else:
            if role_val not in current_list:
                return await interaction.response.send_message(f"⚠️ Role **{role_val}** không có trong `{cat_val}`.", ephemeral=True)
            await roles_config_col.update_one(
                {"guild_id": interaction.guild_id},
                {"$pull": {cat_val: role_val}},
            )
            await interaction.response.send_message(f"✅ Đã xóa **{role_val}** khỏi danh mục `{cat_val}`!", ephemeral=True)


class SettingMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Thêm Role vào Menu", style=discord.ButtonStyle.success)
    async def btn_add_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SettingModal(action="add"))

    @discord.ui.button(label="Xóa Role khỏi Menu", style=discord.ButtonStyle.danger)
    async def btn_remove_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SettingModal(action="remove"))


class MainRolesMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Add Role", emoji="🟢", style=discord.ButtonStyle.success, custom_id="main_menu:add_role")
    async def btn_add_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await get_guild_roles_config(interaction.guild_id)
        view = discord.ui.View(timeout=300)

        if config.get("stage"):
            view.add_item(AddRoleSelect("Stage", config["stage"], is_stage=True))
        if config.get("general"):
            view.add_item(AddRoleSelect("General", config["general"]))
        if config.get("combat"):
            view.add_item(AddRoleSelect("Combat", config["combat"]))

        embed = discord.Embed(
            title="➕ NHẬN ROLE TỰ ĐỘNG",
            description="Chọn các role bạn muốn nhận ở danh sách bên dưới.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Remove Role", emoji="🔴", style=discord.ButtonStyle.danger, custom_id="main_menu:remove_role")
    async def btn_remove_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await get_guild_roles_config(interaction.guild_id)
        member = interaction.user
        view = discord.ui.View(timeout=300)

        def get_owned(cat_list):
            return [name for name in cat_list if discord.utils.get(interaction.guild.roles, name=name) in member.roles]

        owned_stage = get_owned(config.get("stage", []))
        owned_general = get_owned(config.get("general", []))
        owned_combat = get_owned(config.get("combat", []))

        if owned_stage:
            view.add_item(RemoveRoleSelect("Stage", owned_stage))
        if owned_general:
            view.add_item(RemoveRoleSelect("General", owned_general))
        if owned_combat:
            view.add_item(RemoveRoleSelect("Combat", owned_combat))

        if not view.children:
            return await interaction.response.send_message("⚠️ Bạn hiện không sở hữu role nào trong hệ thống tự động!", ephemeral=True)

        embed = discord.Embed(
            title="➖ GỠ ROLE TỰ ĐỘNG",
            description="Chỉ hiển thị các role bạn đang sở hữu. Bạn có thể chọn gỡ nhiều role cùng lúc.",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Setting", emoji="⚙️", style=discord.ButtonStyle.secondary, custom_id="main_menu:setting")
    async def btn_setting(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_owner = await check_is_owner(interaction.client, interaction.user)
        is_admin = interaction.guild and interaction.user.guild_permissions.administrator
        if not (is_owner or is_admin):
            return await interaction.response.send_message("⛔ Chỉ **Administrator** hoặc **Bot Owner** mới được dùng nút này.", ephemeral=True)

        embed = discord.Embed(
            title="⚙️ QUẢN LÝ MENU ROLE",
            description="Thêm hoặc xóa role khỏi danh sách tự động (lưu trực tiếp trên MongoDB theo từng server):",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, view=SettingMenuView(), ephemeral=True)


class RolesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def build_roles_panel(self) -> tuple[discord.Embed, discord.ui.View]:
        embed = discord.Embed(
            title="🎭 HỆ THỐNG NHẬN ROLE TỰ ĐỘNG",
            description=(
                "Sử dụng các nút bên dưới để tự quản lý Role của bạn:\n"
                "🟢 **Add Role:** Chọn nhận thêm role mới.\n"
                "🔴 **Remove Role:** Gỡ bỏ các role không còn dùng.\n"
                "⚙️ **Setting:** *(Chỉ dành cho Admin / Bot Owner)*"
            ),
            color=discord.Color.from_rgb(46, 204, 113),
        )
        return embed, MainRolesMenuView()

    @app_commands.command(name="roles_menu", description="Gửi bảng chọn Role tự động vào kênh hiện tại")
    @is_admin_or_bot_owner()
    async def send_roles_menu(self, interaction: discord.Interaction):
        embed, view = self.build_roles_panel()
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    bot.add_view(MainRolesMenuView())
    await bot.add_cog(RolesCog(bot))