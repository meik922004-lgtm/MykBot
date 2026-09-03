import discord
from discord.ext import commands
from discord import app_commands
import json
import os

# ==========================================
# OWNER ID CONFIGURATION
OWNER_IDS = [1283689737567211581]  # Replace with your Discord ID
# ==========================================

CONFIG_PATH = "roles_config.json"

def load_config():
    if not os.path.exists(CONFIG_PATH):
        default_config = {
            "stage": ["Endgame stage", "Newbie stage", "Midgame stage"],
            "general": ["Member", "Tourist", "PIED", "Mugen", "MDG", "PDG", "APO", "PILLAR AB", "RBH"],
            "combat": ["DPS SK/AA", "UFM", "TANK"]
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=4, ensure_ascii=False)
        return default_config
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

# CUSTOM FILTER: EITHER ADMIN OR OWNER
def is_admin_or_owner():
    def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id in OWNER_IDS:
            return True
        if interaction.guild and interaction.user.guild_permissions.administrator:
            return True
        return False
    return app_commands.check(predicate)

# ==========================================
# SELECT CLASSES FOR ADDING / REMOVING ROLES
# ==========================================

class AddRoleSelect(discord.ui.Select):
    def __init__(self, category_name, options_list, is_stage=False):
        options = [discord.SelectOption(label=name, value=name) for name in options_list[:25]]
        max_vals = 1 if is_stage else len(options)
        super().__init__(
            placeholder=f"Select {category_name} Roles (Add)...", 
            min_values=1, 
            max_values=max_vals, 
            options=options
        )
        self.category_name = category_name
        self.is_stage = is_stage

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        config = load_config()

        if self.is_stage:
            selected_name = self.values[0]
            target_role = discord.utils.get(guild.roles, name=selected_name)
            
            if not target_role:
                return await interaction.followup.send(f"❌ Role **{selected_name}** does not exist on the server!", ephemeral=True)
            if target_role in member.roles:
                return await interaction.followup.send(f"⚠️ You already own the role **{selected_name}**!", ephemeral=True)
            
            stage_roles_names = config.get("stage", [])
            roles_to_remove = [discord.utils.get(guild.roles, name=n) for n in stage_roles_names if n != selected_name and discord.utils.get(guild.roles, name=n) in member.roles]
            roles_to_remove = [r for r in roles_to_remove if r]
            
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove)
            
            await member.add_roles(target_role)
            return await interaction.followup.send(f"✅ Your Stage Role has been updated to: **{selected_name}**", ephemeral=True)
        
        else:
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
                msg_parts.append(f"➕ Added: {', '.join([f'**{r.name}**' for r in roles_to_add])}")
            if already_have:
                msg_parts.append(f"⚠️ Already owned (skipped): {', '.join(already_have)}")
            if not_found:
                msg_parts.append(f"❌ Does not exist on the server: {', '.join(not_found)}")
                
            await interaction.followup.send("\n".join(msg_parts), ephemeral=True)


class RemoveRoleSelect(discord.ui.Select):
    def __init__(self, category_name, options_list):
        options = [discord.SelectOption(label=name, value=name) for name in options_list[:25]]
        super().__init__(
            placeholder=f"Select {category_name} Roles (Remove)...", 
            min_values=1, 
            max_values=len(options), 
            options=options
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
        
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)
        
        msg_parts = []
        if roles_to_remove:
            msg_parts.append(f"➖ Removed: {', '.join([f'**{r.name}**' for r in roles_to_remove])}")
        if dont_have:
            msg_parts.append(f"⚠️ Not owned (cannot be removed): {', '.join(dont_have)}")
        if not_found:
            msg_parts.append(f"❌ Does not exist on the server: {', '.join(not_found)}")
        
        await interaction.followup.send("\n".join(msg_parts) if msg_parts else "⚠️ No changes made.", ephemeral=True)

# ==========================================
# SETTING CLASSES FOR ADMINS
# ==========================================

class SettingModal(discord.ui.Modal):
    def __init__(self, action: str):
        super().__init__(title="Add Role to Menu" if action == "add" else "Remove Role from Menu")
        self.action = action
        
        self.category = discord.ui.TextInput(
            label="Category (stage / general / combat)",
            placeholder="Enter: stage, general, or combat",
            required=True,
            max_length=10
        )
        self.role_name = discord.ui.TextInput(
            label="Role Name",
            placeholder="Enter exact role name",
            required=True
        )
        self.add_item(self.category)
        self.add_item(self.role_name)

    async def on_submit(self, interaction: discord.Interaction):
        cat_val = self.category.value.strip().lower()
        role_val = self.role_name.value.strip()
        
        if cat_val not in ["stage", "general", "combat"]:
            return await interaction.response.send_message("❌ Invalid category! Please enter stage, general, or combat.", ephemeral=True)
        
        config = load_config()
        if self.action == "add":
            if role_val in config[cat_val]:
                return await interaction.response.send_message(f"⚠️ Role **{role_val}** is already in the system.", ephemeral=True)
            config[cat_val].append(role_val)
            save_config(config)
            await interaction.response.send_message(f"✅ Added **{role_val}** to the `{cat_val}` category!", ephemeral=True)
        else:
            if role_val not in config[cat_val]:
                return await interaction.response.send_message(f"⚠️ Role **{role_val}** does not exist in this category.", ephemeral=True)
            config[cat_val].remove(role_val)
            save_config(config)
            await interaction.response.send_message(f"✅ Removed **{role_val}** from the `{cat_val}` category!", ephemeral=True)

class SettingMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Add Role to Config", style=discord.ButtonStyle.success)
    async def btn_add_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SettingModal(action="add"))

    @discord.ui.button(label="Remove Role from Config", style=discord.ButtonStyle.danger)
    async def btn_remove_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SettingModal(action="remove"))

# ==========================================
# MAIN PERMANENT MENU VIEW CLASS
# ==========================================

class MainRolesMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Add Role", style=discord.ButtonStyle.success, custom_id="main_menu:add_role")
    async def btn_add_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = load_config()
        view = discord.ui.View(timeout=300)
        
        if config.get("stage"): view.add_item(AddRoleSelect("Stage", config["stage"], is_stage=True))
        if config.get("general"): view.add_item(AddRoleSelect("General", config["general"]))
        if config.get("combat"): view.add_item(AddRoleSelect("Combat", config["combat"]))
        
        embed = discord.Embed(
            title="➕ ADD ROLE", 
            description="Please select the roles you want to get through the menu below.\n*(The system will notify you if the role does not exist or you already own it)*.", 
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Remove Role", style=discord.ButtonStyle.danger, custom_id="main_menu:remove_role")
    async def btn_remove_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = load_config()
        member = interaction.user
        view = discord.ui.View(timeout=300)
        
        def get_owned_roles(category_list):
            return [name for name in category_list if discord.utils.get(interaction.guild.roles, name=name) in member.roles]

        owned_stage = get_owned_roles(config.get("stage", []))
        owned_general = get_owned_roles(config.get("general", []))
        owned_combat = get_owned_roles(config.get("combat", []))

        has_roles = False
        if owned_stage:
            view.add_item(RemoveRoleSelect("Stage", owned_stage))
            has_roles = True
        if owned_general:
            view.add_item(RemoveRoleSelect("General", owned_general))
            has_roles = True
        if owned_combat:
            view.add_item(RemoveRoleSelect("Combat", owned_combat))
            has_roles = True

        if not has_roles:
            return await interaction.response.send_message("⚠️ You currently do not have any roles in the automatic system to remove!", ephemeral=True)

        embed = discord.Embed(
            title="➖ REMOVE ROLE", 
            description="The system only shows the roles you currently own.\nYou can select **multiple roles at once** to remove.", 
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Setting", style=discord.ButtonStyle.secondary, custom_id="main_menu:setting")
    async def btn_setting(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_owner = interaction.user.id in OWNER_IDS
        is_admin = interaction.guild and interaction.user.guild_permissions.administrator
        
        if not (is_owner or is_admin):
            return await interaction.response.send_message("❌ Access denied! Only Administrators or Bot Owners can use this button.", ephemeral=True)
        
        embed = discord.Embed(
            title="⚙️ ROLE MENU MANAGEMENT", 
            description="Choose to add or remove roles from the database (roles_config.json):", 
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=SettingMenuView(), ephemeral=True)

# ==========================================
# COG AND COMMAND INITIALIZATION
# ==========================================

class RolesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        load_config()

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            error_msg = "❌ You do not have permission to use this command! (Administrator or Bot Owner privileges required)."
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)
        else:
            print(f"Error in RolesCog: {error}")

    @app_commands.command(name="roles_menu", description="Send the menu to automatically assign roles.")
    @is_admin_or_owner()
    async def send_roles_menu(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎭 AUTOMATIC ROLES RECOGNITION SYSTEM",
            description="**Automatic Roles System**\n\n"
                        "Please use the buttons below to interact:\n"
                        "🟢 **Add Role:** Select to receive new roles.\n"
                        "🔴 **Remove Role:** Remove roles you no longer want to own.\n"
                        "⚙️ **Setting:** *(Staff only)*",
            color=discord.Color.from_rgb(46, 204, 113)
        )
        await interaction.response.send_message(embed=embed, view=MainRolesMenuView())

async def setup(bot):
    bot.add_view(MainRolesMenuView()) 
    await bot.add_cog(RolesCog(bot))