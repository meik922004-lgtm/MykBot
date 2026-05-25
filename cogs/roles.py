import discord
from discord.ext import commands
import json
import os

# ==========================
# CONSTANTS & CONFIGURATION
# ==========================
TOURIST_ROLE_NAME = "Tourist"
STAGE_ROLES = ["Newbie stage", "Mid game stage", "Endgame stage"]
MEMBER_ROLE_NAME = "Member"
CONFIG_FILE = "roles_config.json"

# Load dynamic combat roles from JSON
def load_combat_roles():
    if not os.path.exists(CONFIG_FILE):
        default_data = {"combat_roles": ["DPS", "TANK"]}
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_data, f)
        return default_data["combat_roles"]
    
    with open(CONFIG_FILE, "r") as f:
        data = json.load(f)
        return data.get("combat_roles", [])

# Save updated combat roles to JSON
def save_combat_roles(roles_list):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"combat_roles": roles_list}, f)

# ==========================
# SELECT: DYNAMIC COMBAT ROLES
# ==========================
class DynamicCombatSelect(discord.ui.Select):
    def __init__(self):
        combat_roles = load_combat_roles()
        options = [
            discord.SelectOption(label=role, description=f"Select to get the {role} role", emoji="⚔️") 
            for role in combat_roles
        ]
        
        # Fallback if admin removes all roles
        if not options:
            options = [discord.SelectOption(label="None", description="No roles have been set up yet")]

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

        await interaction.followup.send("✅ **Updated your Combat roles!**", ephemeral=True)


# ==========================
# VIEW: MAIN ROLE SELECTION PANEL
# ==========================
class ServerRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        # Add Dynamic Dropdown to View
        self.add_item(DynamicCombatSelect())

    # 1. DROPDOWN FOR TOURIST ROLE
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
            await interaction.followup.send("❌ **Cannot find the requested role(s) in this server.**", ephemeral=True)
            return

        if "get" in select.values:
            if role not in interaction.user.roles:
                await interaction.user.add_roles(role)
        elif "remove" in select.values or len(select.values) == 0:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)

        await interaction.followup.send("✅ **Your Tourist role preference has been updated!**", ephemeral=True)

    # 2. DROPDOWN FOR STAGE ROLE
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

        await interaction.followup.send("✅ **Updated your Progression Stage role!**", ephemeral=True)


# ==========================
# COG: ROLE MANAGEMENT
# ==========================
class Roles(commands.Cog, name="Management and Roles"):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(ServerRolesView())

    @commands.command(name="setup_role_panel")
    @commands.has_permissions(administrator=True)
    async def setup_role_panel(self, ctx):
        """Deploy the Role selection panel"""
        embed = discord.Embed(
            title="🔔 SERVER ROLES MENU 🔔",
            description=(
                f"Please select your server roles using the dropdown menus below!\n\n"
                f"--- \n\n"
                f"**📢 Tours & Raids Alerts**\n"
                f"Turn on/off notification of Raid tours.\n\n"
                f"**🌱 Game Progression Stage**\n"
                f"Choose your progression (Only 1).\n\n"
                f"**🗡️ Combat Roles**\n"
                f"Pick your playstyle (Can choose multiple)."
            ),
            color=discord.Color.purple()
        )
        embed.set_footer(text=f"MyK Bot • {ctx.guild.name} Automation")
        await ctx.send(embed=embed, view=ServerRolesView())

    # ==========================
    # ADMIN COMMANDS: ADD/REMOVE DYNAMIC ROLES
    # ==========================
    @commands.command(name="add_role")
    @commands.has_permissions(administrator=True)
    async def add_role(self, ctx, *, role_name: str):
        """Add new combat role to menu (Example: !add_role UFM)"""
        combat_roles = load_combat_roles()
        if role_name in combat_roles:
            await ctx.send(f"⚠️ Role **{role_name}** is already in the list.")
            return
            
        combat_roles.append(role_name)
        save_combat_roles(combat_roles)
        await ctx.send(f"✅ Successfully added role **{role_name}** to the system.\n👉 **Notice:** Please use command `!setup_role_panel` to create a new updated menu!")

    @commands.command(name="remove_role")
    @commands.has_permissions(administrator=True)
    async def remove_role(self, ctx, *, role_name: str):
        """Remove role from menu (Example: !remove_role TANK)"""
        combat_roles = load_combat_roles()
        if role_name not in combat_roles:
            await ctx.send(f"⚠️ Role **{role_name}** does not exist in the system.")
            return
            
        combat_roles.remove(role_name)
        save_combat_roles(combat_roles)
        await ctx.send(f"🗑️ Removed **{role_name}** from the system.\n👉 **Notice:** Please use command `!setup_role_panel` to create a new updated menu!")

    @commands.command(name="give_member_all")
    @commands.has_permissions(administrator=True)
    async def give_member_all(self, ctx):
        """Give Member role to all people"""
        role = discord.utils.get(ctx.guild.roles, name=MEMBER_ROLE_NAME)
        if not role:
            await ctx.send(f"❌ Role **{MEMBER_ROLE_NAME}** does not exist in this server.")
            return

        await ctx.send("⏳ Giving role to all members...")
        count = 0
        for member in ctx.guild.members:
            if not member.bot and role not in member.roles:
                try:
                    await member.add_roles(role)
                    count += 1
                except (discord.Forbidden, discord.HTTPException):
                    pass 
        
        await ctx.send(f"✅ Done! Assigned **{MEMBER_ROLE_NAME}** to **{count}** members.")

async def setup(bot):
    await bot.add_cog(Roles(bot))