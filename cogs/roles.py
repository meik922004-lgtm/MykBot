import discord
from discord.ext import commands
from discord import app_commands
import json
import os

CONFIG_PATH = "roles_config.json"

def load_config():
    """Tải cấu hình roles từ file JSON, nếu chưa có sẽ tạo mặc định"""
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
    """Lưu cấu hình roles vào file JSON"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

        
class StageSelect(discord.ui.Select):
    def __init__(self, options_list):
        options = [discord.SelectOption(label=name, value=name) for name in options_list]
        super().__init__(
            placeholder="=Select stage role (Only 1)...", 
            min_values=1, 
            max_values=1, 
            options=options, 
            custom_id="roles_select:stage"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        selected_name = self.values[0]
        
        config = load_config()
        stage_roles_names = config.get("stage", [])
        
        roles_to_remove = []
        role_to_add = None
        
        # Tìm các role trong server để xử lý loại trừ (chỉ giữ lại 1 stage duy nhất)
        for name in stage_roles_names:
            role = discord.utils.get(guild.roles, name=name)
            if role:
                if name == selected_name:
                    role_to_add = role
                elif role in member.roles:
                    roles_to_remove.append(role)
        
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)
        if role_to_add and role_to_add not in member.roles:
            await member.add_roles(role_to_add)
            
        await interaction.followup.send(f"✅ Stage Role has been updated to: **{selected_name}**", ephemeral=True)


class GeneralSelect(discord.ui.Select):
    def __init__(self, options_list):
        options = [discord.SelectOption(label=name, value=name) for name in options_list]
        max_vals = min(len(options), 25) if options else 1
        super().__init__(
            placeholder="Select General Roles (You can select multiple roles)...", 
            min_values=0, 
            max_values=max_vals, 
            options=options, 
            custom_id="roles_select:general"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        selected_names = self.values
        
        config = load_config()
        general_roles_names = config.get("general", [])
        
        roles_to_add = []
        roles_to_remove = []
        
        # Đồng bộ hóa các role được chọn và bỏ chọn
        for name in general_roles_names:
            role = discord.utils.get(guild.roles, name=name)
            if role:
                if name in selected_names:
                    if role not in member.roles:
                        roles_to_add.append(role)
                else:
                    if role in member.roles:
                        roles_to_remove.append(role)
        
        if roles_to_add:
            await member.add_roles(*roles_to_add)
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)
            
        await interaction.followup.send("✅ Your General Roles list has been updated!", ephemeral=True)


class CombatSelect(discord.ui.Select):
    def __init__(self, options_list):
        options = [discord.SelectOption(label=name, value=name) for name in options_list]
        max_vals = min(len(options), 25) if options else 1
        super().__init__(
            placeholder="Select Combat Roles (You can select multiple roles)...", 
            min_values=0, 
            max_values=max_vals, 
            options=options, 
            custom_id="roles_select:combat"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        selected_names = self.values
        
        config = load_config()
        combat_roles_names = config.get("combat", [])
        
        roles_to_add = []
        roles_to_remove = []
        
        # Đồng bộ hóa các role được chọn và bỏ chọn
        for name in combat_roles_names:
            role = discord.utils.get(guild.roles, name=name)
            if role:
                if name in selected_names:
                    if role not in member.roles:
                        roles_to_add.append(role)
                else:
                    if role in member.roles:
                        roles_to_remove.append(role)
        
        if roles_to_add:
            await member.add_roles(*roles_to_add)
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)
            
        await interaction.followup.send("✅ Your Combat Roles list has been updated!", ephemeral=True)


class RolesMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        config = load_config()
        
        if config.get("stage"):
            self.add_item(StageSelect(config["stage"]))
        if config.get("general"):
            self.add_item(GeneralSelect(config["general"]))
        if config.get("combat"):
            self.add_item(CombatSelect(config["combat"]))


class RolesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        load_config()

    @app_commands.command(name="roles_menu", description="Send the menu to automatically assign roles to the channel.")
    @app_commands.default_permissions(administrator=True)
    async def send_roles_menu(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎭 AUTOMATIC ROLES RECOGNITION SYSTEM",
            description="Please interact with the dropdown menus below to receive your corresponding role.:\n\n"
                        "1️⃣ **Stage Role**: Choose one of three difficulty levels (Endgame / Midgame / Newbie).\n"
                        "2️⃣ **General Roles**: General roles, multiple roles can be selected at the same time..\n"
                        "3️⃣ **Combat Roles**: Combat roles, multiple roles can be selected simultaneously.",
            color=discord.Color.from_rgb(46, 204, 113)
        )
        embed.set_footer(text="The system automatically syncs roles based on your selection..")
        view = RolesMenuView()
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="addrole", description="Add a server role to the configuration menu.")
    @app_commands.describe(category="Categories to add roles to", role="Roles need to be added.")
    @app_commands.choices(category=[
        app_commands.Choice(name="Stage Role", value="stage"),
        app_commands.Choice(name="General Roles", value="general"),
        app_commands.Choice(name="Combat Roles", value="combat")
    ])
    @app_commands.default_permissions(administrator=True)
    async def add_role_to_menu(self, interaction: discord.Interaction, category: app_commands.Choice[str], role: discord.Role):
        cat_value = category.value
        config = load_config()
        
        if role.name in config[cat_value]:
            await interaction.response.send_message(f"⚠️ Role **{role.name}**already available in the catalog `{cat_value}`.", ephemeral=True)
            return

        config[cat_value].append(role.name)
        save_config(config)
        await interaction.response.send_message(f"✅Role **{role.name}** has been successfully added to the menu.`{cat_value}`!\n💡 Hãy sử dụng lại lệnh `/roles_menu` để cập nhật hiển thị.", ephemeral=True)

    @app_commands.command(name="removerole", description="Remove a role from the configuration menu.")
    @app_commands.describe(category="Category containing roles to be deleted", role_name="Name of the role to be deleted (write exactly in uppercase/lowercase).)")
    @app_commands.choices(category=[
        app_commands.Choice(name="Stage Role", value="stage"),
        app_commands.Choice(name="General Roles", value="general"),
        app_commands.Choice(name="Combat Roles", value="combat")
    ])
    @app_commands.default_permissions(administrator=True)
    async def remove_role_from_menu(self, interaction: discord.Interaction, category: app_commands.Choice[str], role_name: str):
        cat_value = category.value
        config = load_config()
        
        if role_name not in config[cat_value]:
            await interaction.response.send_message(f"⚠️ No role named **{role_name}** was found in the catalog. `{cat_value}`.", ephemeral=True)
            return

        config[cat_value].remove(role_name)
        save_config(config)
        await interaction.response.send_message(f"✅ Role **{role_name}** has been successfully removed from the `{cat_value}` menu!\n💡 Please use the `/roles_menu` command again to update the display..", ephemeral=True)

async def setup(bot):
    await bot.add_cog(RolesCog(bot))
