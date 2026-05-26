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
            placeholder="Chọn Stage Role (Chỉ được chọn 1)...", 
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
            
        await interaction.followup.send(f"✅ Đã cập nhật Stage Role thành: **{selected_name}**", ephemeral=True)


class GeneralSelect(discord.ui.Select):
    def __init__(self, options_list):
        options = [discord.SelectOption(label=name, value=name) for name in options_list]
        max_vals = min(len(options), 25) if options else 1
        super().__init__(
            placeholder="Chọn General Roles (Có thể chọn nhiều)...", 
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
            
        await interaction.followup.send("✅ Đã cập nhật danh sách General Roles của bạn!", ephemeral=True)


class CombatSelect(discord.ui.Select):
    def __init__(self, options_list):
        options = [discord.SelectOption(label=name, value=name) for name in options_list]
        max_vals = min(len(options), 25) if options else 1
        super().__init__(
            placeholder="Chọn Combat Roles (Có thể chọn nhiều)...", 
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
            
        await interaction.followup.send("✅ Đã cập nhật danh sách Combat Roles của bạn!", ephemeral=True)


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

    @app_commands.command(name="roles_menu", description="Gửi menu nhận role tự động vào kênh")
    @app_commands.default_permissions(administrator=True)
    async def send_roles_menu(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎭 HỆ THỐNG TỰ NHẬN ROLES",
            description="Vui lòng tương tác với các Menu thả xuống dưới đây để nhận Role tương ứng:\n\n"
                        "1️⃣ **Stage Role**: Chọn 1 trong 3 mức độ chơi (Endgame / Midgame / Newbie).\n"
                        "2️⃣ **General Roles**: Các vai trò chung, có thể chọn cùng lúc nhiều role.\n"
                        "3️⃣ **Combat Roles**: Các vai trò chiến đấu, có thể chọn cùng lúc nhiều role.",
            color=discord.Color.from_rgb(46, 204, 113)
        )
        embed.set_footer(text="Hệ thống tự động sync role theo lựa chọn của bạn.")
        view = RolesMenuView()
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="addrole", description="Thêm một role từ server vào menu cấu hình")
    @app_commands.describe(category="Danh mục để thêm role vào", role="Role cần thêm")
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
            await interaction.response.send_message(f"⚠️ Role **{role.name}** đã có sẵn trong danh mục `{cat_value}`.", ephemeral=True)
            return

        config[cat_value].append(role.name)
        save_config(config)
        await interaction.response.send_message(f"✅ Đã thêm thành công role **{role.name}** vào menu `{cat_value}`!\n💡 Hãy sử dụng lại lệnh `/roles_menu` để cập nhật hiển thị.", ephemeral=True)

    @app_commands.command(name="removerole", description="Xóa một role ra khỏi menu cấu hình")
    @app_commands.describe(category="Danh mục chứa role cần xóa", role_name="Tên role cần xóa (ghi chính xác chữ hoa/thường)")
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
            await interaction.response.send_message(f"⚠️ Không tìm thấy role mang tên **{role_name}** trong danh mục `{cat_value}`.", ephemeral=True)
            return

        config[cat_value].remove(role_name)
        save_config(config)
        await interaction.response.send_message(f"✅ Đã xóa thành công role **{role_name}** khỏi menu `{cat_value}`!\n💡 Hãy sử dụng lại lệnh `/roles_menu` để cập nhật hiển thị.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(RolesCog(bot))
