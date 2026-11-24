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
    """Retrieve or initialize the per-guild self-assignable roles configuration in MongoDB."""
    doc = await roles_config_col.find_one({"guild_id": guild_id})
    if not doc:
        doc = {"guild_id": guild_id, **{k: list(v) for k, v in DEFAULT_ROLES_CONFIG.items()}}
        await roles_config_col.insert_one(doc)
    return doc


class AddRoleSelect(discord.ui.Select):
    """Dropdown menu for adding self-assignable roles."""

    def __init__(self, category_name: str, options_list: list[str], is_stage: bool = False):
        options = [discord.SelectOption(label=name, value=name) for name in options_list[:25]]
        max_vals = 1 if is_stage else len(options)
        super().__init__(
            placeholder=f"Select {category_name} Roles (Add)...",
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
                    return await interaction.followup.send(f"❌ Role **{selected_name}** does not exist on this server.", ephemeral=True)
                if target_role in member.roles:
                    return await interaction.followup.send(f"⚠️ You already have the **{selected_name}** role.", ephemeral=True)

                config = await get_guild_roles_config(guild.id)
                stage_names = config.get("stage", [])
                roles_to_remove = [
                    r for n in stage_names
                    if n != selected_name and (r := discord.utils.get(guild.roles, name=n)) in member.roles
                ]
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove)
                await member.add_roles(target_role)
                return await interaction.followup.send(f"✅ Updated your Stage Role to **{selected_name}**.", ephemeral=True)

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
                msg_parts.append(f"➕ Added: {', '.join(f'**{r.name}**' for r in roles_to_add)}")
            if already_have:
                msg_parts.append(f"⚠️ Already owned: {', '.join(already_have)}")
            if not_found:
                msg_parts.append(f"❌ Not found on server: {', '.join(not_found)}")

            await interaction.followup.send("\n".join(msg_parts) or "⚠️ No changes made.", ephemeral=True)

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Missing permissions to assign this role. Please move the bot's role higher in Server Settings.",
                ephemeral=True,
            )


class RemoveRoleSelect(discord.ui.Select):
    """Dropdown menu for removing currently owned self-assignable roles."""

    def __init__(self, category_name: str, options_list: list[str]):
        options = [discord.SelectOption(label=name, value=name) for name in options_list[:25]]
        super().__init__(
            placeholder=f"Select {category_name} Roles (Remove)...",
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
                "❌ Missing permissions to remove this role. Check the bot's role hierarchy.",
                ephemeral=True,
            )

        msg_parts = []
        if roles_to_remove:
            msg_parts.append(f"➖ Removed: {', '.join(f'**{r.name}**' for r in roles_to_remove)}")
        if dont_have:
            msg_parts.append(f"⚠️ Not owned: {', '.join(dont_have)}")
        if not_found:
            msg_parts.append(f"❌ Not found on server: {', '.join(not_found)}")

        await interaction.followup.send("\n".join(msg_parts) or "⚠️ No changes made.", ephemeral=True)


class SettingModal(discord.ui.Modal):
    """Admin/Owner modal to add or remove a role name from a category."""

    def __init__(self, action: str):
        super().__init__(title="Add Role to Panel" if action == "add" else "Remove Role from Panel")
        self.action = action
        self.category = discord.ui.TextInput(
            label="Category (stage / general / combat)",
            placeholder="Enter: stage, general, or combat",
            required=True,
            max_length=10,
        )
        self.role_name = discord.ui.TextInput(
            label="Exact Role Name",
            placeholder="Enter exact role name on this server",
            required=True,
        )
        self.add_item(self.category)
        self.add_item(self.role_name)

    async def on_submit(self, interaction: discord.Interaction):
        cat_val = self.category.value.strip().lower()
        role_val = self.role_name.value.strip()

        if cat_val not in ("stage", "general", "combat"):
            return await interaction.response.send_message(
                "❌ Invalid category! Please enter `stage`, `general`, or `combat`.",
                ephemeral=True,
            )

        config = await get_guild_roles_config(interaction.guild_id)
        current_list = config.get(cat_val, [])

        if self.action == "add":
            if role_val in current_list:
                return await interaction.response.send_message(f"⚠️ **{role_val}** is already in `{cat_val}`.", ephemeral=True)
            await roles_config_col.update_one(
                {"guild_id": interaction.guild_id},
                {"$addToSet": {cat_val: role_val}},
                upsert=True,
            )
            await interaction.response.send_message(f"✅ Added **{role_val}** to `{cat_val}`.", ephemeral=True)
        else:
            if role_val not in current_list:
                return await interaction.response.send_message(f"⚠️ **{role_val}** is not in `{cat_val}`.", ephemeral=True)
            await roles_config_col.update_one(
                {"guild_id": interaction.guild_id},
                {"$pull": {cat_val: role_val}},
            )
            await interaction.response.send_message(f"✅ Removed **{role_val}** from `{cat_val}`.", ephemeral=True)


class SettingMenuView(discord.ui.View):
    """Admin/Owner controls for editing the role list."""

    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Add Role to Config", style=discord.ButtonStyle.success)
    async def btn_add_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SettingModal(action="add"))

    @discord.ui.button(label="Remove Role from Config", style=discord.ButtonStyle.danger)
    async def btn_remove_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SettingModal(action="remove"))


class MainRolesMenuView(discord.ui.View):
    """Persistent self-role panel view."""

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
            title="➕ Add Roles",
            description="Select the roles you want to claim from the dropdown menus below.",
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
            return await interaction.response.send_message("⚠️ You do not currently own any self-assignable roles.", ephemeral=True)

        embed = discord.Embed(
            title="➖ Remove Roles",
            description="Only roles you currently own are listed. You can remove multiple roles at once.",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Settings", emoji="⚙️", style=discord.ButtonStyle.secondary, custom_id="main_menu:setting")
    async def btn_setting(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_owner = await check_is_owner(interaction.client, interaction.user)
        is_admin = interaction.guild and interaction.user.guild_permissions.administrator
        if not (is_owner or is_admin):
            return await interaction.response.send_message(
                "⛔ Access denied. Only **Administrators** or **Bot Owners** can configure roles.",
                ephemeral=True,
            )

        embed = discord.Embed(
            title="⚙️ Role Panel Configuration",
            description="Add or remove role names stored in MongoDB for this server:",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, view=SettingMenuView(), ephemeral=True)


class RolesCog(commands.Cog):
    """Self-assignable role panel cog."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def build_roles_panel(self) -> tuple[discord.Embed, discord.ui.View]:
        embed = discord.Embed(
            title="🎭 Self-Assignable Roles",
            description=(
                "Use the buttons below to manage your roles:\n"
                "🟢 **Add Role:** Claim new roles.\n"
                "🔴 **Remove Role:** Remove roles you no longer need.\n"
                "⚙️ **Settings:** *(Administrators & Bot Owners only)*"
            ),
            color=discord.Color.from_rgb(46, 204, 113),
        )
        return embed, MainRolesMenuView()

    @app_commands.command(
        name="setup_roles_panel",
        description="[Admin/Owner] Post the permanent self-role selection panel in this channel",
    )
    @app_commands.default_permissions(administrator=True)
    @is_admin_or_bot_owner()
    async def setup_roles_panel(self, interaction: discord.Interaction):
        embed, view = self.build_roles_panel()
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    bot.add_view(MainRolesMenuView())
    await bot.add_cog(RolesCog(bot))