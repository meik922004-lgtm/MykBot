import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import aiohttp
import random
import time
import uuid
from datetime import datetime
from bson import ObjectId
from cogs.party_finder import handle_cross_server_chat
from Database import rpg_profiles_col, world_boss_col, boss_channels_col, parties_col
import pymongo
from pymongo import UpdateOne

farm_logs_buffer = {}
cross_messages_col = rpg_profiles_col.database["cross_chat_logs"]
market_col = rpg_profiles_col.database["rpg_marketplace"]
OWNER_IDS = [1283689737567211581]

# ========================================================================
# GLOBAL CONSTANTS & POOLS
# ========================================================================

NEW_MEGA_POOL = [
    {"name": "ShineGreymon BM", "stage": "Mega", "atk": 1250, "hp": 15500, "base_price": 600},
    {"name": "MirageGaogamon BM", "stage": "Mega", "atk": 1200, "hp": 14800, "base_price": 600},
    {"name": "Rosemon BM", "stage": "Mega", "atk": 1150, "hp": 14200, "base_price": 600},
    {"name": "Ravemon BM", "stage": "Mega", "atk": 1180, "hp": 14000, "base_price": 600},
    {"name": "BlackWarGreymon", "stage": "Mega", "atk": 1300, "hp": 16500, "base_price": 600},
    {"name": "MetalSeadramon", "stage": "Mega", "atk": 1220, "hp": 15800, "base_price": 600},
    {"name": "Piedmon", "stage": "Mega", "atk": 1260, "hp": 15000, "base_price": 600},
    {"name": "Valkyrimon", "stage": "Mega", "atk": 1100, "hp": 13800, "base_price": 600},
    {"name": "Vikemon", "stage": "Mega", "atk": 1120, "hp": 16800, "base_price": 600},
    {"name": "GranKuwagamon", "stage": "Mega", "atk": 1190, "hp": 14500, "base_price": 600}
]

HIGH_TIER_GEARS = [
    {"name": "Omega Artifact Sword", "type": "weapon", "atk": 650, "rarity": "Mythic"},
    {"name": "Alpha Absolute Shield", "type": "armor", "def": 550, "hp": 1500, "rarity": "Mythic"},
    {"name": "Ultimate Omegamon Vice", "type": "vice", "atk": 400, "hp": 3000, "rarity": "Mythic"},
    {"name": "Crimson End Armor", "type": "armor", "def": 600, "hp": 3500, "rarity": "Mythic"},
    {"name": "Miracle Origin Ring", "type": "vice", "atk": 350, "def": 350, "rarity": "Mythic"}
]

# Cache cho hệ thống Auto Attack tối ưu hóa (Yêu cầu 7)
auto_attack_cache = {} 


# ========================================================================
# UI INTERFACE CLASSES (VIEWS, SELECTS & MODALS)
# ========================================================================
class GearInventorySelect(discord.ui.Select):
    def __init__(self, profile: dict, cog_instance):
        options = []
        self.cog = cog_instance
        
        inventory = profile.get("inventory", [])
        equipped = profile.get("equipped", {}) # Lấy dữ liệu đồ đang mặc
        
        # 1. Đưa các trang bị ĐANG MẶC vào đầu danh sách để dễ Gỡ (Unequip)
        for slot in ["weapon", "armor", "vice"]:
            item = equipped.get(slot)
            if item and item != "None":
                item_name = item if isinstance(item, str) else item.get("name", "Unknown")
                options.append(discord.SelectOption(
                    label=f"[Wearing] {item_name}",
                    description=f"Click to remove from slot {slot.upper()}",
                    value=f"unequip_{slot}", # Giá trị đặc biệt để nhận diện lệnh tháo
                    emoji="🔓"
                ))

        # 2. Gom nhóm và đưa các vật phẩm TRONG TÚI vào danh sách
        string_counts = {}
        dict_items = []
        
        for gear in inventory:
            if isinstance(gear, str):
                string_counts[gear] = string_counts.get(gear, 0) + 1
            elif isinstance(gear, dict):
                dict_items.append(gear)
        
        for gear_str, count in string_counts.items():
            if len(options) >= 25: break
            cleaned_name = cog_instance.clean_item_name(gear_str)
            gear_data = cog_instance.ITEMS.get(cleaned_name, {})
            
            stats = []
            if "atk" in gear_data: stats.append(f"ATK +{gear_data['atk']}")
            if "def" in gear_data: stats.append(f"DEF +{gear_data['def']}")
            if "hp" in gear_data: stats.append(f"HP +{gear_data['hp']}")
            stat_desc = " | ".join(stats) if stats else "Consumable"
            
            quantity_label = f" x{count}" if count > 1 else ""
            options.append(discord.SelectOption(
                label=f"{cleaned_name}{quantity_label}",
                description=f"Type: {gear_data.get('type', 'item').upper()} | {stat_desc}",
                value=gear_str 
            ))
            
        for gear_dict in dict_items:
            if len(options) >= 25: break
            stats = []
            if "atk" in gear_dict: stats.append(f"ATK +{gear_dict['atk']}")
            if "def" in gear_dict: stats.append(f"DEF +{gear_dict['def']}")
            if "hp" in gear_dict: stats.append(f"HP +{gear_dict['hp']}")
            stat_desc = " | ".join(stats) if stats else "No Stats"
            
            options.append(discord.SelectOption(
                label=f"{gear_dict.get('name', 'Unknown')} ({gear_dict.get('rarity', 'Common')})",
                description=f"Type: {gear_dict.get('type', 'N/A').upper()} | {stat_desc}",
                value=gear_dict.get("id", str(uuid.uuid4()))
            ))

        if not options:
            options = [discord.SelectOption(label="The warehouse is empty.", value="empty")]
            
        super().__init__(placeholder="🎒 Choose equipment to Wear, Use, or Remove..", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_value = self.values[0]
        if selected_value == "empty":
            return await interaction.response.send_message("❌ Your inventory is empty.!", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        if not profile:
            return await interaction.followup.send("❌ Character data not found.", ephemeral=True)
            
        inventory = profile.get("inventory", [])
        equipped = profile.get("equipped", {})

        # ==================================================
        # XỬ LÝ LỆNH: THÁO TRANG BỊ (UNEQUIP)
        # ==================================================
        if selected_value.startswith("unequip_"):
            slot = selected_value.replace("unequip_", "")
            item_to_remove = equipped.get(slot)
            
            if item_to_remove:
                inventory.append(item_to_remove) # Trả đồ về túi
                equipped[slot] = "None"          # Xóa khỏi slot đang mặc
                
                await rpg_profiles_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"inventory": inventory, "equipped": equipped}}
                )
                item_name = item_to_remove if isinstance(item_to_remove, str) else item_to_remove.get("name")
                return await interaction.followup.send(f"🔓 I have removed **{item_name}** from position **[{slot.upper()}]** and put it in the storage!", ephemeral=True)
            else:
                return await interaction.followup.send("❌ LError: This location is not equipped.", ephemeral=True)

        # ==================================================
        # XỬ LÝ LỆNH: DÙNG/MẶC TRANG BỊ
        # ==================================================
        target_item = None
        is_dict = False
        for item in inventory:
            if isinstance(item, str) and item == selected_value:
                target_item = item
                break
            elif isinstance(item, dict) and item.get("id") == selected_value:
                target_item = item
                is_dict = True
                break
                
        if target_item is None:
            return await interaction.followup.send("❌ This item is no longer in your inventory!", ephemeral=True)
            
        item_name = target_item if isinstance(target_item, str) else target_item.get("name", "Unknown")
        
        # Trường hợp 1: Dùng trái cây (Fruit)
        if "Fruit" in item_name:
            active_id = profile.get("active_digimon_id")
            digimon_list = profile.get("digimon_list", [])
            active_digi = next((d for d in digimon_list if d["id"] == active_id), None)
            
            if not active_digi:
                return await interaction.followup.send("❌ You need to activate a Digimon before using a Fruit.!", ephemeral=True)
                
            new_size = round(random.uniform(0.5, 1.25), 2)
            active_digi["size"] = new_size
            inventory.remove(target_item)
            
            await rpg_profiles_col.update_one(
                {"user_id": user_id},
                {"$set": {"inventory": inventory, "digimon_list": digimon_list}}
            )
            return await interaction.followup.send(f"🍎 **{item_name}** has been used on **{active_digi['name']}**!\n📏 New size: **{new_size * 100:.1f}%**", ephemeral=True)
            
        # Trường hợp 2: Mặc trang bị (Gear)
        cleaned_name = self.cog.clean_item_name(item_name)
        gear_base_data = self.cog.ITEMS.get(cleaned_name, {}) if not is_dict else target_item
        gear_type = gear_base_data.get("type")
        
        if gear_type in ["weapon", "armor", "vice"]:
            old_equipped = equipped.get(gear_type)
            
            # Đổi đồ: Nhét đồ cũ vào túi trước
            if old_equipped and old_equipped != "None":
                inventory.append(old_equipped)
                
            equipped[gear_type] = target_item
            inventory.remove(target_item)
            
            await rpg_profiles_col.update_one(
                {"user_id": user_id},
                {"$set": {"inventory": inventory, "equipped": equipped}}
            )
            return await interaction.followup.send(f"✅**{item_name}** has been placed in position**[{gear_type.upper()}]**!", ephemeral=True)
            
        await interaction.followup.send(f"📦Item **{item_name}** cannot be used directly here..", ephemeral=True)

class DigiBagSelect(discord.ui.Select):
    def __init__(self, digimon_list, active_id, cog_instance):
        self.cog = cog_instance
        options = []
        for d in digimon_list:
            is_active = "✅ " if d["id"] == active_id else ""
            options.append(discord.SelectOption(
                label=f"{is_active}{d['name']}",
                value=d["id"],
                description=f"Stage: {d['stage']} | Size: {d.get('size', 1)*100:.0f}%"
            ))
        
        if not options:
            options = [discord.SelectOption(label="Empty bag", value="none")]
            
        super().__init__(placeholder="🐾 Choose a Digimon to activate..", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none": return
        # Gọi hàm xử lý active Digimon trong cog của bạn
        await self.cog.handle_set_active_digimon(interaction, self.values[0])

class InventoryView(discord.ui.View):
    # Chỉ nhận 1 tham số select_menu là đủ
    def __init__(self, select_menu: discord.ui.Select, timeout=180):
        super().__init__(timeout=timeout)
        self.add_item(select_menu)

def generate_inventory_embed(profile: dict) -> discord.Embed:
    """Hàm tạo Embed hiển thị Block List túi đồ và đồ đang mặc"""
    embed = discord.Embed(title="🎒 Inventory", color=discord.Color.blue())
    
    # --- 1. Block: Đồ đang mặc ---
    equipped = profile.get("equipped", {})
    w_name = equipped.get("weapon")
    a_name = equipped.get("armor")
    v_name = equipped.get("vice")
    
    # Xử lý lấy tên nếu đồ là dạng Dict (đồ hiếm)
    w_display = w_name if isinstance(w_name, str) else w_name.get("name", "Empty") if w_name else "Empty"
    a_display = a_name if isinstance(a_name, str) else a_name.get("name", "Empty") if a_name else "Empty"
    v_display = v_name if isinstance(v_name, str) else v_name.get("name", "Empty") if v_name else "Empty"
    
    equipped_text = f"⚔️ **Weapon:** {w_display}\n🛡️ **Armor:** {a_display}\n📿 **Vice:** {v_display}"
    embed.add_field(name="👕 Equipment currently worn", value=equipped_text, inline=False)
    
    # --- 2. Block: Đồ trong túi ---
    inventory = profile.get("inventory", [])
    if not inventory:
        embed.add_field(name="📦Storage", value="*Your equipment storage is empty.*", inline=False)
    else:
        # Gom nhóm đồ thừa
        string_counts = {}
        dict_items = []
        for item in inventory:
            if isinstance(item, str):
                string_counts[item] = string_counts.get(item, 0) + 1
            else:
                dict_items.append(item)
                
        inv_text = ""
        # Render đồ thường (cộng dồn số lượng)
        for name, count in string_counts.items():
            qty = f" (x{count})" if count > 1 else ""
            inv_text += f"🔹 {name}{qty}\n"
            
        # Render đồ hiếm (Dictionary)
        for item in dict_items:
            rarity = item.get("rarity", "Rare")
            inv_text += f"🌟 {item.get('name', 'Unknown')} `[{rarity}]`\n"
            
        # Giới hạn text hiển thị để tránh lỗi quá dài của Discord Embed
        if len(inv_text) > 1024:
            inv_text = inv_text[:1000] + "\n... (And more)"
            
        embed.add_field(name="📦 In bag", value=inv_text, inline=False)
        
    embed.set_footer(text="Use the menu below to Equip, Remove, or Use items..")
    return embed

class ProfileView(discord.ui.View):
    def __init__(self, profile: dict, cog_instance):
        super().__init__(timeout=180)
        self.profile = profile
        self.cog = cog_instance

    @discord.ui.button(label="🥚 Hatch Digi (5 Cores)", style=discord.ButtonStyle.primary, row=0)
    async def hatch_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_hatch_action(interaction)

    @discord.ui.button(label="🏋️ Train ATK (500 Bits)", style=discord.ButtonStyle.secondary, row=0)
    async def train_atk_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_train_action(interaction, "atk")

    @discord.ui.button(label="🏋️ Train HP (500 Bits)", style=discord.ButtonStyle.secondary, row=0)
    async def train_hp_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_train_action(interaction, "hp")

    @discord.ui.button(label="🩹 Heal Partner", style=discord.ButtonStyle.success, row=1)
    async def heal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_heal(interaction)

    @discord.ui.button(label="🧬 Evolve", style=discord.ButtonStyle.danger, row=1)
    async def evolve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_evolve(interaction)
    @discord.ui.button(label="Digimon bag", style=discord.ButtonStyle.secondary, emoji="🐾")
    async def open_digi_bag(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile:
            return await interaction.followup.send("❌ Character data not found.", ephemeral=True)
        
        # Chỉ tạo Menu Digimon
        digi_menu = DigiBagSelect(
            profile.get("digimon_list", []), 
            profile.get("active_digimon_id"), 
            self.cog
        )
        
        embed = discord.Embed(
            title="🐾 Your Digimon Bag", 
            description="Manage your Digimon here.", 
            color=discord.Color.gold()
        )
        
        # Nạp menu Digimon vào view
        # Bạn có thể dùng chung class InventoryView nếu nó chỉ là cái khung
        view = InventoryView(digi_menu) 
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Equipment storage", style=discord.ButtonStyle.primary, emoji="🎒")
    async def open_inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Lệnh mở UI Kho đồ mới
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile:
            return await interaction.followup.send("❌No Data.", ephemeral=True)
            
        embed = generate_inventory_embed(profile)
        view = InventoryView(profile, self.cog)
        
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

class MarketBuySelect(discord.ui.Select):
    def __init__(self, listings: list, cog_instance):
        self.cog = cog_instance
        options = []
        
        for item in listings:
            # Xác định Tiền tố/Hậu tố hiển thị dựa trên tính chất sản phẩm
            is_digimon = item.get("listing_type") == "digimon"
            emoji = "🧬" if is_digimon else "🛒"
            rarity = item.get("item_data", {}).get("rarity", "Mega" if is_digimon else "Regular")
            
            options.append(
                discord.SelectOption(
                    label=f"{item['item_name']} ({rarity}) - {item['price']:.2f} orb",
                    description=f"Seller: {item['seller_name']} | ID: {item['listing_id']}",
                    value=item["listing_id"],
                    emoji=emoji,
                )
            )
            
        if not options:
            options = [discord.SelectOption(label="The market is currently empty.", value="empty")]
            
        super().__init__(
            placeholder="🛒 Choose an item/digimon from the list to buy...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "empty":
            return await interaction.response.send_message("❌ Currently, no items are available for sale.", ephemeral=True)
        # Gọi hàm xử lý giao dịch tập trung đã được điều hướng ở trên
        await self.cog.handle_market_buy(interaction, self.values[0])

class MarketShopView(discord.ui.View):
    def __init__(self, listings: list, cog_instance):
        super().__init__(timeout=180)
        # Tự động nạp menu lựa chọn mua hàng dựa theo dữ liệu thực tế
        self.add_item(MarketBuySelect(listings, cog_instance))

class CombatView(discord.ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=None)
        self.cog = cog_instance

    @discord.ui.button(label="Attack", style=discord.ButtonStyle.danger, emoji="⚔️", custom_id="boss_atk")
    async def attack_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_manual_attack(interaction)
        
    @discord.ui.button(label="Auto-Attack", style=discord.ButtonStyle.primary, emoji="🤖", custom_id="boss_auto_atk")
    async def auto_attack_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.toggle_auto_attack(interaction)
        
    @discord.ui.button(label="Protect (45s CD)", style=discord.ButtonStyle.secondary, emoji="🛡️", custom_id="boss_protect")
    async def protect_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_protect(interaction)

class FarmDungeonSelect(discord.ui.Select):
    def __init__(self, cog_instance):
        self.cog = cog_instance
        options = [
            discord.SelectOption(label="🌌 Enter Digital Dimension (All-in-One)", value="digital_dimension", emoji="🌌"),
            discord.SelectOption(label="🛑 Stop Auto-Farm", value="stop", emoji="⏹️")
        ]
        super().__init__(placeholder="⚙️ Toggle Auto-Farm status...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await self.cog.handle_toggle_auto_dungeon(interaction, self.values[0])

class FarmDigiMinerSelect(discord.ui.Select):
    def __init__(self, eligible_digimon: list):
        options = []
        for d in eligible_digimon[:25]:
            options.append(discord.SelectOption(
                label=d["name"],
                description=f"Stage: {d['stage']} | Assistant Support",
                value=d["id"]
            ))
        max_vals = min(6, len(options)) if options else 1
        super().__init__(
            placeholder="Select up to 6 Digimon to boost digibits...",
            min_values=1,
            max_values=max_vals,
            options=options if options else [discord.SelectOption(label="No valid Digimon", value="none")]
        )

    async def callback(self, interaction: discord.Interaction):
        if "none" in self.values:
            return await interaction.response.send_message("There are no valid Digimon to choose from.", ephemeral=True)
            
        stage_multipliers = {"rookie": 1, "champion": 2, "ultimate": 3, "mega": 4}
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile:
            return await interaction.response.send_message("Character data not found.", ephemeral=True)
            
        selected_digis = [d for d in profile.get("digimon_list", []) if d["id"] in self.values]
        total_efficiency = sum(stage_multipliers.get(d.get("stage", "rookie").lower(), 1) for d in selected_digis)
        
        await rpg_profiles_col.update_one(
            {"user_id": interaction.user.id},
            {"$set": {
                "mining_assistants": self.values,
                "mining_efficiency_bonus": total_efficiency
            }}
        )
        await interaction.response.send_message(
            f"⚡ Distributed {len(selected_digis)} Digimon to the operations! +{total_efficiency * 10}% extra DB from Auto-Farm.", 
            # Giờ đây bonus này sẽ nhân thêm vàng/DB trực tiếp trong loop
            ephemeral=True
        )

class FarmView(discord.ui.View):
    def __init__(self, cog_instance, profile: dict):
        super().__init__(timeout=300)
        self.cog = cog_instance
        self.add_item(FarmDungeonSelect(cog_instance))

        digimon_list = profile.get("digimon_list", [])
        if digimon_list:
            self.add_item(FarmDigiMinerSelect(digimon_list))

    @discord.ui.button(label="View Farm Logs", style=discord.ButtonStyle.secondary, emoji="📜")
    async def view_logs(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_view_logs(interaction)
# ========================================================================
#                            MAIN COG SYSTEM
# ========================================================================
class RPGSystemCog(commands.Cog):
    ITEMS = {
        "Rusty Sword": {"type": "weapon", "atk": 15}, "Rusty Armor": {"type": "armor", "hp": 150, "def": 10}, "Rusty Vice": {"type": "vice", "crit_rate": 5, "crit_dmg": 1.2},
        "Chrome Dagger": {"type": "weapon", "atk": 45}, "Chrome Cloak": {"type": "armor", "hp": 350, "def": 25}, "Chrome Vice": {"type": "vice", "crit_rate": 10, "crit_dmg": 1.5},
        "Divine Blade": {"type": "weapon", "atk": 120}, "Divine Aegis": {"type": "armor", "hp": 800, "def": 60}, "Divine Vice": {"type": "vice", "crit_rate": 20, "crit_dmg": 2.0}
    }

    # Chỉ còn 1 Dungeon duy nhất đại diện cho toàn bộ hệ thống Farm
    DUNGEONS = {
        "digital_dimension": {"name": "Digital Dimension", "description": "The ultimate dimensional zone for all farming activities."}
    }

    DIGIMON_DATA = {
        "rookie": {
            "Agumon": {"attr": "Vaccine", "atk": 60, "hp": 1200, "vip": False, "img": "https://digimon.net/cimages/digimon/agumon.jpg"},
            "Gabumon": {"attr": "Data", "atk": 55, "hp": 1300, "vip": False, "img": "https://digimon.net/cimages/digimon/gabumon.jpg"},
            "Guilmon": {"attr": "Virus", "atk": 65, "hp": 1100, "vip": False, "img": "https://digimon.net/cimages/digimon/guilmon.jpg"},
            "Lucemon": {"attr": "Virus", "atk": 90, "hp": 1000, "vip": False, "img": "https://digimon.net/cimages/digimon/lucemon.jpg"},
            "V-mon": {"attr": "Vaccine", "atk": 75, "hp": 1250, "vip": False, "img": "https://digimon.net/cimages/digimon/v-mon.jpg"},
            "Patamon": {"attr": "Data", "atk": 50, "hp": 1150, "vip": False, "img": "https://digimon.net/cimages/digimon/patamon.jpg"},
            "DemiDevimon": {"attr": "Virus", "atk": 65, "hp": 1050, "vip": False, "img": "https://digimon.net/cimages/digimon/pico_devimon.jpg"},
            "Palmon": {"attr": "Data", "atk": 60, "hp": 1250, "vip": False, "img": "https://digimon.net/cimages/digimon/palmon.jpg"},
            "Tentomon": {"attr": "Vaccine", "atk": 65, "hp": 1200, "vip": False, "img": "https://digimon.net/cimages/digimon/tentomon.jpg"},
            "Psychemon": {"attr": "Data", "atk": 70, "hp": 1100, "vip": False, "img": "https://digimon.net/cimages/digimon/psychemon.jpg"}
        },
        "champion": {
            "Greymon": {"attr": "Vaccine", "atk": 180, "hp": 3000, "img": "https://digimon.net/cimages/digimon/greymon.jpg"},
            "Garurumon": {"attr": "Data", "atk": 160, "hp": 3200, "img": "https://digimon.net/cimages/digimon/garurumon.jpg"},
            "Growlmon": {"attr": "Virus", "atk": 190, "hp": 2800, "img": "https://digimon.net/cimages/digimon/growlmon.jpg"},
            "ExVeemon": {"attr": "Vaccine", "atk": 210, "hp": 3100, "img": "https://digimon.net/cimages/digimon/exveemon.jpg"},
            "Lucemon FM": {"attr": "Virus", "atk": 250, "hp": 2500, "img": "https://digimon.net/cimages/digimon/lucemon_falldown_mode.jpg"},
            "Angemon": {"attr": "Vaccine", "atk": 200, "hp": 2900, "img": "https://digimon.net/cimages/digimon/angemon.jpg"},
            "Devimon": {"attr": "Virus", "atk": 220, "hp": 2600, "img": "https://digimon.net/cimages/digimon/devimon.jpg"},
            "Togemon": {"attr": "Data", "atk": 170, "hp": 3300, "img": "https://digimon.net/cimages/digimon/togemon.jpg"},
            "Kabuterimon": {"attr": "Vaccine", "atk": 195, "hp": 3100, "img": "https://digimon.net/cimages/digimon/kabuterimon.jpg"},
            "Gururumon": {"attr": "Vaccine", "atk": 190, "hp": 3000, "img": "https://digimon.net/cimages/digimon/gururumon.jpg"}
        },
        "ultimate": {
            "MetalGreymon": {"attr": "Vaccine", "atk": 450, "hp": 7500, "img": "https://digimon.net/cimages/digimon/metalgreymon.jpg"},
            "WereGarurumon": {"attr": "Data", "atk": 420, "hp": 8000, "img": "https://digimon.net/cimages/digimon/weregarurumon.jpg"},
            "WarGrowlmon": {"attr": "Virus", "atk": 480, "hp": 7000, "img": "https://digimon.net/cimages/digimon/megalo_growmon.jpg"},
            "Paildramon": {"attr": "Data", "atk": 460, "hp": 7200, "img": "https://digimon.net/cimages/digimon/paildramon.jpg"},
            "Lucemon SM": {"attr": "Virus", "atk": 600, "hp": 6500, "img": "https://digimon.net/cimages/digimon/lucemon_satan_mode.jpg"},
            "MagnaAngemon": {"attr": "Vaccine", "atk": 470, "hp": 7400, "img": "https://digimon.net/cimages/digimon/holyangemon.jpg"},
            "Myotismon": {"attr": "Virus", "atk": 500, "hp": 6800, "img": "https://digimon.net/cimages/digimon/vamdemon.jpg"},
            "Lillymon": {"attr": "Data", "atk": 410, "hp": 7800, "img": "https://digimon.net/cimages/digimon/lilimon.jpg"},
            "MegaKabuterimon": {"attr": "Vaccine", "atk": 460, "hp": 7600, "img": "https://digimon.net/cimages/digimon/atlurkabuterimon_red.jpg"},
            "Astamon": {"attr": "Virus", "atk": 480, "hp": 7200, "img": "https://digimon.net/cimages/digimon/astamon.jpg"}
        },
        "mega": {
            "WarGreymon": {"attr": "Vaccine", "atk": 1200, "hp": 20000, "img": "https://digimon.net/cimages/digimon/wargreymon.jpg", "skill": {"name": "Terra Force", "dmg_mult": 2.5, "chance": 0.2}},
            "MetalGarurumon": {"attr": "Data", "atk": 1100, "hp": 22000, "img": "https://digimon.net/cimages/digimon/metalgarurumon.jpg", "skill": {"name": "Metal Wolf Claw", "dmg_mult": 2.2, "chance": 0.25}},
            "Gallantmon": {"attr": "Virus", "atk": 1250, "hp": 19000, "img": "https://digimon.net/cimages/digimon/dukemon.jpg", "skill": {"name": "Lightning Joust", "dmg_mult": 2.8, "chance": 0.15}},
            "Imperialdramon": {"attr": "Vaccine", "atk": 1150, "hp": 21000, "img": "https://digimon.net/cimages/digimon/imperialdramon.jpg", "skill": {"name": "Positron Laser", "dmg_mult": 2.3, "chance": 0.2}},
            "Lucemon X": {"attr": "Virus", "atk": 1500, "hp": 15000, "img": "https://digimon.net/cimages/digimon/lucemon_x.jpg", "skill": {"name": "Seventh Cross", "dmg_mult": 3.2, "chance": 0.12}},
            "Seraphimon": {"attr": "Vaccine", "atk": 1300, "hp": 18000, "img": "https://digimon.net/cimages/digimon/seraphimon.jpg", "skill": {"name": "Seven Heavens", "dmg_mult": 3.0, "chance": 0.1}},
            "VenomMyotismon": {"attr": "Virus", "atk": 1350, "hp": 17500, "img": "https://digimon.net/cimages/digimon/venomvamdemon.jpg", "skill": {"name": "Venom Infusion", "dmg_mult": 2.6, "chance": 0.15}},
            "Rosemon": {"attr": "Data", "atk": 1050, "hp": 23000, "img": "https://digimon.net/cimages/digimon/rosemon.jpg", "skill": {"name": "Forbidden Temptation", "dmg_mult": 2.0, "chance": 0.3}},
            "HerculesKabuterimon": {"attr": "Vaccine", "atk": 1180, "hp": 22500, "img": "https://digimon.net/cimages/digimon/herakle_kabuterimon.jpg", "skill": {"name": "Giga Blaster", "dmg_mult": 2.4, "chance": 0.2}},
            "Mekurimon": {"attr": "Virus", "atk": 1400, "hp": 16000, "img": "https://digimon.net/cimages/digimon/mercurymon.jpg", "skill": {"name": "Spark", "dmg_mult": 2.9, "chance": 0.15}}
        }
    }

    EVOLUTION_LINE = {
        "Agumon": "Greymon", "Greymon": "MetalGreymon", "MetalGreymon": "WarGreymon",
        "Gabumon": "Garurumon", "Garurumon": "WereGarurumon", "WereGarurumon": "MetalGarurumon",
        "Guilmon": "Growlmon", "Growlmon": "WarGrowlmon", "WarGrowlmon": "Gallantmon",
        "V-mon": "ExVeemon", "ExVeemon": "Paildramon", "Paildramon": "Imperialdramon",
        "Lucemon": "Lucemon FM", "Lucemon FM": "Lucemon SM", "Lucemon SM": "Lucemon X",
        "Patamon": "Angemon", "Angemon": "MagnaAngemon", "MagnaAngemon": "Seraphimon",
        "DemiDevimon": "Devimon", "Devimon": "Myotismon", "Myotismon": "VenomMyotismon",
        "Palmon": "Togemon", "Togemon": "Lillymon", "Lillymon": "Rosemon",
        "Tentomon": "Kabuterimon", "Kabuterimon": "MegaKabuterimon", "MegaKabuterimon": "HerculesKabuterimon",
        "Psychemon": "Gururumon", "Gururumon": "Astamon", "Astamon": "Mekurimon"
    }
    
    HATCH_CORE_COST = 5

    def __init__(self, bot):
        self.bot = bot
        self.auto_attackers = set()
        self.auto_spawn_boss.start()
        self.farm_system_loop.start()
        self.live_boss_update_loop.start()
        self.bot.loop.create_task(self.initialize_market_mega_products())
        self.auto_attack_cache = {}
        self.HIGH_TIER_GEARS = [
    {"name": "Omega Artifact Sword", "type": "weapon", "atk": 650, "rarity": "Mythic"},
    {"name": "Alpha Absolute Shield", "type": "armor", "def": 550, "hp": 1500, "rarity": "Mythic"},
    {"name": "Ultimate Omegamon Vice", "type": "vice", "atk": 400, "hp": 3000, "rarity": "Mythic"},
    {"name": "Crimson End Armor", "type": "armor", "def": 600, "hp": 3500, "rarity": "Mythic"},
    {"name": "Miracle Origin Ring", "type": "vice", "atk": 350, "def": 350, "rarity": "Mythic"}]
        self.auto_spawn_boss.cancel()
        self.farm_system_loop.cancel()
        self.live_boss_update_loop.cancel()

    # ========================================================================
    #                       HELPER METHODS
    # ========================================================================

    #========================================
    #                 AUTO FARM
    #========================================
    @app_commands.command(name="farm", description="🌌 Auto farm resource")
    async def farm_command(self, interaction: discord.Interaction):
        # Defer trước để tránh lỗi quá hạn 3 giây của Discord khi truy vấn DB
        await interaction.response.defer(ephemeral=True)
        
        user_id = interaction.user.id
        # Đọc dữ liệu hồ sơ từ MongoDB
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        if not profile:
            return await interaction.followup.send(
                "❌ You don't have an RPG profile yet! Please create a character first..", 
                ephemeral=True
            )
            
        # Lấy thông tin trạng thái để hiển thị lên bảng điều khiển (Dashboard)
        efficiency_bonus = profile.get("mining_efficiency_bonus", 0)
        assistants = profile.get("mining_assistants", [])
        
        # Kiểm tra xem người chơi có đang bật Auto-Farm không (tùy thuộc vào cách bạn lưu biến này trong loop)
        is_farming = profile.get("is_farming", False) 
        status_text = "🟢Automated farming" if is_farming else "🔴 On pause"
        
        # Thiết kế giao diện Bảng Điều Khiển (Embed)
        embed = discord.Embed(
            title="⛏️ AUTO-FARM & OPERATIONS CENTER🌌",
            description="This is where the resource gathering and distribution of Digimon miners is managed..",
            color=discord.Color.dark_purple()
        )
        
        embed.add_field(name="🛰️ System status", value=f"**{status_text}**", inline=True)
        embed.add_field(name="⚡ Increased performance", value=f"**+{efficiency_bonus * 10}% DB**", inline=True)
        embed.add_field(name="👥 Number of assistants", value=f"**{len(assistants)}/6 Digimon**", inline=True)
        
        # Hiển thị danh sách tên các Digimon đang phụ trách đào mỏ
        if assistants:
            digimon_list = profile.get("digimon_list", [])
            assistant_names = [d["name"] for d in digimon_list if d["id"] in assistants]
            embed.add_field(name="🛠️ List of working assistants", value=f"• " + "\n• ".join(assistant_names), inline=False)
        else:
            embed.add_field(name="🛠️List of working assistants", value="*No Digimon have been working..*", inline=False)
            
        embed.set_footer(text="Use the menu and buttons below to control.")
        
        # Khởi tạo FarmView (Truyền self đóng vai trò cog_instance, và dữ liệu profile vừa đọc)
        view = FarmView(self, profile)
        
        # Gửi bảng điều khiển kèm UI lên cho người dùng
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    
    def roll_pve_loot(self) -> tuple[str, str]:
        """Tự động phân bổ loại trang bị rớt ra và trả về (Tên_Vật_Phẩm, Loại_Vật_Phẩm)"""
        is_high_tier = random.random() < 0.12 # 12% tỷ lệ ra đồ Rare trong nhóm đồ thường
        loot_type = random.choice(["weapon", "armor", "vice"])
        
        if loot_type == "weapon": 
            loot_base = "Chrome Dagger" if is_high_tier else "Rusty Sword"
        elif loot_type == "armor": 
            loot_base = "Divine Aegis" if is_high_tier else "Rusty Armor"
        else: 
            loot_base = "Chrome Vice" if is_high_tier else "Rusty Vice"
            
        return loot_base, loot_type

    def roll_auto_dungeon_high_tier_reward(self) -> dict:
        if random.random() <= 0.015:  # 1.5% tỷ lệ rơi đồ Mythic cực hiếm
            chosen_gear_template = random.choice(self.HIGH_TIER_GEARS)
            return {
                "id": str(uuid.uuid4()),
                "name": chosen_gear_template["name"],
                "type": chosen_gear_template["type"],
                "rarity": chosen_gear_template["rarity"],
                "atk": chosen_gear_template.get("atk", 0),
                "def": chosen_gear_template.get("def", 0),
                "hp": chosen_gear_template.get("hp", 0),
                "obtained_at": int(time.time())
            }
        return None
   
    async def handle_view_logs(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile:
            return await interaction.followup.send("❌ Character data not found.", ephemeral=True)
            
        logs = profile.get("farm_logs", [])
        
        embed = discord.Embed(title="📜 Farm Logs", color=discord.Color.dark_gray())
        
        if not logs:
            embed.description = "*Currently, there is no recorded data from the system crash..*"
        else:
            # 1. Đảo ngược danh sách để các dòng Log MỚI NHẤT hiển thị lên ĐẦU
            recent_logs = list(reversed(logs))
            
            # 2. Giới hạn chỉ lấy tối đa khoảng 15-20 dòng log gần nhất để giao diện gọn gàng
            recent_logs = recent_logs[:20] 
            
            # 3. Gộp log lại thành một chuỗi văn bản
            log_text = "\n".join(recent_logs)
            
            # 4. Phòng hờ: Nếu độ dài chuỗi vẫn quá dài, chủ động cắt chuỗi ở mức an toàn (ví dụ 3500 ký tự)
            if len(log_text) > 3500:
                log_text = log_text[:3500] + "\n... (Older log data has been compressed.)"
                
            embed.description = f"```markdown\n{log_text}\n```"
            
        embed.set_footer(text=f"Displays up to 20 most recent logs • Total number of stored logs: {len(logs)}")
        await interaction.followup.send(embed=embed, ephemeral=True)
    @tasks.loop(minutes=2)
    async def farm_system_loop(self):
        # Hệ thống chỉ chạy cho những ai đang ở trạng thái farm tại "digital_dimension"
        profiles = await rpg_profiles_col.find({"auto_dungeon": "digital_dimension"}).to_list(None)
        bulk_operations = []
        
        for profile in profiles:
            user_id = profile["user_id"]
            log_msgs = []
            updates = {"$inc": {}, "$push": {}}
            items_to_push = []
            
            is_vip = profile.get("is_vip", False)
            is_premium = profile.get("premium_ui", False)
            
            # --- Tải danh sách tên vật phẩm để kiểm tra trùng lặp (Anti-Dupe) ---
            inventory = profile.get("inventory", [])
            existing_item_names = set()
            for item in inventory:
                if isinstance(item, dict):
                    existing_item_names.add(item.get("name"))
                elif isinstance(item, str):
                    existing_item_names.add(item.replace(" (Unlocked)", ""))

            # --- 1. Xử lý phần thưởng Digibit (Mặc định +10) ---
            base_db = 60
            efficiency_bonus = profile.get("mining_efficiency_bonus", 0)
            assistant_bonus_db = int(base_db * (efficiency_bonus * 0.10)) # Thêm vàng từ Digimon trợ thủ
            
            total_db_gained = base_db + assistant_bonus_db
            bonus_db_from_dupes = 0
            new_gears_count = 0

            # --- 2. Điều chỉnh tỷ lệ rớt Hatch Cores mới ---
            # Người chơi thường có 40% ra 1 Core, VIP có 75% ra 1-2 Cores mỗi loop
            core_chance = 0.75 if is_vip else 0.40
            cores = random.randint(1, 2) if (random.random() < core_chance) else 0

            # --- 3. Điều chỉnh tỷ lệ rớt Trang bị Thường (All types) ---
            drop_chance = 0.04 if is_premium else 0.025 # Tỷ lệ rớt đồ tổng hợp được tối ưu lại
            if random.random() < drop_chance:
                loot_base_name, loot_type = self.roll_pve_loot()
                gear_obj = {
                    "id": str(uuid.uuid4()),
                    "name": loot_base_name,
                    "type": loot_type,
                    "rarity": "Common" if "Rusty" in loot_base_name else "Rare",
                    "obtained_at": int(time.time())
                }
                
                # Check trùng đồ thường
                if gear_obj["name"] in existing_item_names:
                    bonus_db_from_dupes += 15 # Trùng tự động đổi thành 15 DB
                else:
                    items_to_push.append(gear_obj)
                    existing_item_names.add(gear_obj["name"])
                    new_gears_count += 1

            # --- 4. Kiểm tra tỷ lệ rớt Trang bị Hiếm (Mythic) ---
            high_tier_gear = self.roll_auto_dungeon_high_tier_reward()
            if high_tier_gear:
                ht_name = high_tier_gear["name"]
                # Check trùng đồ Mythic
                if ht_name in existing_item_names:
                    bonus_db_from_dupes += 100 # Trùng tự động đổi thành 100 DB
                    log_msgs.append(f"🌟 Dupe: {ht_name} -> Salvaged for +100 DB")
                else:
                    items_to_push.append(high_tier_gear)
                    existing_item_names.add(ht_name)
                    new_gears_count += 1
                    log_msgs.append(f"🌟 MYTHIC DROP: Found {ht_name}!")

            # --- 5. Tổng hợp dữ liệu ghi nhận lên MongoDB ---
            total_db_gained += bonus_db_from_dupes
            updates["$inc"]["digibit"] = updates["$inc"].get("digibit", 0) + total_db_gained
            if cores > 0:
                updates["$inc"]["hatch_core"] = updates["$inc"].get("hatch_core", 0) + cores

            # Thiết lập định dạng Log gọn gàng, trực quan
            loot_str = ""
            if cores > 0: loot_str += f", {cores} Cores"
            if new_gears_count > 0: loot_str += f", {new_gears_count} New Gears"
            if bonus_db_from_dupes > 0: loot_str += f" (+{bonus_db_from_dupes} DB from Auto-Salvage)"
            
            log_msgs.append(f"🌌 Farm: +{total_db_gained} DB{loot_str}")

            if log_msgs:
                log_entry = f"[{datetime.utcnow().strftime('%H:%M')}] " + " | ".join(log_msgs)
                updates["$push"]["farm_logs"] = {"$each": [log_entry], "$slice": -10}
                
            if items_to_push:
                updates["$push"]["inventory"] = {"$each": items_to_push}
                
            if not updates["$inc"]: del updates["$inc"]
            if not updates["$push"]: del updates["$push"]
            
            if updates: 
                bulk_operations.append(UpdateOne({"user_id": user_id}, updates))

        if bulk_operations:
            await rpg_profiles_col.bulk_write(bulk_operations, ordered=False)
   
   #==============================================
   #                  WOLRD BOSS 
   #==============================================
    def generate_boss_embed(self, boss_data: dict) -> discord.Embed:
        max_hp = boss_data.get("max_hp", 1)
        current_hp = max(0, boss_data.get("current_hp", boss_data.get("hp", 0)))
        hp_percent = current_hp / max_hp
        hp_bar = "🟥" * int(hp_percent * 10) + "⬛" * (10 - int(hp_percent * 10))

        embed = discord.Embed(
            title=f"🚨 BOSS APPEARED: {boss_data['name']} 🚨", 
            description=f"**Attribute:** {boss_data.get('attr', 'Unknown')}\n\n**HP:** {current_hp:,} / {max_hp:,}\n{hp_bar} ({hp_percent * 100:.1f}%)",
            color=discord.Color.dark_red()
            )
        if boss_data.get("img"): embed.set_thumbnail(url=boss_data["img"])

        damage_log = boss_data.get("damage_log", {})
        if damage_log:
            sorted_log = sorted(damage_log.items(), key=lambda x: x[1], reverse=True)[:5] 
            lb_text = ""
            medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
            for idx, (uid_str, dmg) in enumerate(sorted_log):
                lb_text += f"{medals[idx]} <@{uid_str}>: **{dmg:,}** DMG\n"
            embed.add_field(name="🏆 DAMAGE LEADERBOARD", value=lb_text, inline=False)
        else:
            embed.add_field(name="🏆 DAMAGE LEADERBOARD", value="No attackers yet...", inline=False)

        embed.set_footer(text="Use /combat or buttons below to fight!")
        return embed    

    async def broadcast_initial_boss(self, boss_data: dict):
        # Đã xóa logic gửi thông báo Webhook tự động
        # Chỉ giữ lại lệnh kích hoạt vòng lặp cập nhật máu Boss (nếu vòng lặp đang ngủ)
        if not hasattr(self, 'live_boss_update_loop'):
            return
        if not self.live_boss_update_loop.is_running(): 
            self.live_boss_update_loop.start()

    @tasks.loop(seconds=20)
    async def live_boss_update_loop(self):
        bosses = await world_boss_col.find({"is_active": True}).to_list(None)
        if not bosses: return

        async with aiohttp.ClientSession() as session: # Dùng chung 1 session cho nhanh
            for boss in bosses:
                embed = self.generate_boss_embed(boss)
                active_messages = boss.get("active_messages", [])
                updated_messages = []

                for msg_info in active_messages:
                    try:
                        if msg_info.get("is_interaction"):
                            channel = self.bot.get_channel(msg_info["channel_id"])
                            if channel:
                                msg = channel.get_partial_message(msg_info["message_id"])
                                await msg.edit(embed=embed, view=CombatView(self))
                                updated_messages.append(msg_info)
                        else:
                            webhook_url = msg_info.get("webhook_url")
                            if webhook_url:
                                webhook = discord.Webhook.from_url(webhook_url, session=session)
                                await webhook.edit_message(msg_info["message_id"], embed=embed, view=CombatView(self))
                                updated_messages.append(msg_info)
                        
                        # Thêm dòng này: Nghỉ một chút trước khi sửa tin nhắn tiếp theo nếu có nhiều server
                        await asyncio.sleep(0.5) 
                        
                    except discord.NotFound: pass 
                    except discord.HTTPException as e:
                        if e.status == 429:
                            # Nếu xui rủi dính 429, giữ lại data để vòng sau cập nhật tiếp
                            print("Notice:The system is experiencing API congestion; this attempt will be automatically skipped..")
                        updated_messages.append(msg_info)

    @live_boss_update_loop.before_loop
    async def before_live_boss_update(self): await self.bot.wait_until_ready()  


    @app_commands.command(name="spawn_boss", description="[Admin] Force spawn a World Boss")
    async def spawn_boss(self, interaction: discord.Interaction, name: str, hp: int):
        if not interaction.user.guild_permissions.administrator: 
            return await interaction.response.send_message("❌ Admin privileges required.", ephemeral=True)
            
        # Tắt các boss cũ đang active
        await world_boss_col.update_many({"is_active": True, "party_id": {"$exists": False}}, {"$set": {"is_active": False}})
        
        new_boss = {
            "boss_id": str(uuid.uuid4()), "name": name, "max_hp": hp, "current_hp": hp, "hp": hp, 
            "attr": "Unknown", "img": "", "is_active": True, "damage_log": {}, "active_messages": [], "participants": []
        }
        result = await world_boss_col.insert_one(new_boss)
        new_boss["_id"] = result.inserted_id
        
        await interaction.response.send_message(f"⚔️ Spawned Boss **{name}**!", ephemeral=True)
        await self.broadcast_initial_boss(new_boss)

    @tasks.loop(minutes=1)
    async def auto_spawn_boss(self):
        config = await world_boss_col.find_one({"type": "spawn_config"})
        if not config or "next_spawn" not in config or int(time.time()) < config["next_spawn"]: return
        if await world_boss_col.find_one({"is_active": True, "party_id": {"$exists": False}}): return
        
        await world_boss_col.update_one({"type": "spawn_config"}, {"$unset": {"next_spawn": ""}})
        boss_roster = [
            {"name": "Devimon", "hp": 7_000, "attr": "Virus", "img": "https://digimon.net/cimages/digimon/devimon.jpg"}, 
            {"name": "WarGreymon", "hp": 7_000, "attr": "Vaccine", "img": "https://digimon.net/cimages/digimon/wargreymon.jpg"},
            {"name": "Apocalymon", "hp": 7_000, "attr": "Unknown", "img": "https://digimon.net/cimages/digimon/apocalymon.jpg"}
        ]
        chosen = random.choice(boss_roster)
        new_boss = {
            "boss_id": str(uuid.uuid4()), "name": chosen["name"], "max_hp": chosen["hp"], "current_hp": chosen["hp"], "hp": chosen["hp"], 
            "attr": chosen["attr"], "img": chosen["img"], "is_active": True, "damage_log": {}, "active_messages": [], "participants": []
        }
        
        result = await world_boss_col.insert_one(new_boss)
        new_boss["_id"] = result.inserted_id
        await self.broadcast_initial_boss(new_boss)

    @auto_spawn_boss.before_loop
    async def before_auto_spawn(self): 
        await self.bot.wait_until_ready()

    @app_commands.command(name="combat", description="Display Boss Combat Interface")
    async def combat_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        party = await parties_col.find_one({"members.user_id": interaction.user.id})
        boss = await world_boss_col.find_one({"is_active": True, "party_id": str(party["_id"])}) if party else None
            
        if not boss: boss = await world_boss_col.find_one({"is_active": True, "party_id": {"$exists": False}})
        if not boss: return await interaction.followup.send("❌ There are no active Bosses right now!")
            
        embed = self.generate_boss_embed(boss)
        msg = await interaction.followup.send(embed=embed, view=CombatView(self), wait=True)
        await world_boss_col.update_one({"_id": boss["_id"]}, {"$push": {"active_messages": {"channel_id": interaction.channel.id, "message_id": msg.id, "is_interaction": True}}})
        if not self.live_boss_update_loop.is_running(): self.live_boss_update_loop.start()

    async def toggle_auto_attack(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        
        if user_id in self.auto_attackers:
            self.auto_attackers.discard(user_id)
            self.auto_attack_cache.pop(user_id, None)
            await interaction.followup.send("🛑 **Auto-Attack DEACTIVATED.**", ephemeral=True)
        else:
            self.auto_attackers.add(user_id)
            self.auto_attack_cache[user_id] = 0
            await interaction.followup.send("🤖 **Auto-Attack ACTIVATED!** Damage syncs every 20 seconds.", ephemeral=True)
            self.bot.loop.create_task(self.auto_attack_loop(user_id, interaction.user.display_name, interaction))

    async def auto_attack_loop(self, user_id: int, user_name: str, interaction: discord.Interaction):
        HITS_PER_INTERVAL = 2
        
        while user_id in self.auto_attackers:
            await asyncio.sleep(10)
            if user_id not in self.auto_attackers: break

            player = await rpg_profiles_col.find_one({"user_id": user_id})
            party = await parties_col.find_one({"members.user_id": user_id})
            boss = await world_boss_col.find_one({"is_active": True, "party_id": str(party["_id"]) if party else {"$exists": False}})

            if not boss or not player or player.get("current_hp", 0) <= 0:
                self.auto_attackers.discard(user_id)
                self.auto_attack_cache.pop(user_id, None)
                try:
                    await interaction.followup.send("❌ **The battle is over or your Digimon is defeated!** Auto-Attack stopped.", ephemeral=True)
                except (discord.NotFound, discord.HTTPException): pass
                break

            digimon = self.get_active_digimon(player)
            stats = self.get_total_stats(player)
            attr_mult = self.get_attribute_multiplier(digimon["attr"], boss.get("attr", "Unknown"))

            # Tính toán sát thương tích lũy
            batch_dmg = 0
            for _ in range(HITS_PER_INTERVAL):
                raw_dmg = stats["atk"] + random.randint(-5, 10)
                if random.randint(1, 100) <= stats["crit_rate"]: raw_dmg *= stats["crit_dmg"]
                if "skill" in digimon and random.random() < digimon["skill"]["chance"]: raw_dmg *= digimon["skill"]["dmg_mult"]
                batch_dmg += int(raw_dmg * attr_mult * (1.25 if attr_mult > 1 else 1.0))

            self.auto_attack_cache[user_id] = self.auto_attack_cache.get(user_id, 0) + batch_dmg
            dmg_to_sync = self.auto_attack_cache[user_id]

            # ĐỒNG BỘ ĐỒN ĐÁNH VÀO DB (Chỉ thực hiện khi Boss còn đang Active)
            result = await world_boss_col.find_one_and_update(
                {"_id": boss["_id"], "is_active": True}, 
                {"$inc": {"current_hp": -dmg_to_sync, "hp": -dmg_to_sync, f"damage_log.{str(user_id)}": dmg_to_sync}, 
                 "$addToSet": {"participants": user_id}},
                return_document=pymongo.ReturnDocument.AFTER
            )
            
            # Nếu Boss đã bị hạ gục trước đó bởi người khác
            if not result:
                self.auto_attackers.discard(user_id)
                self.auto_attack_cache.pop(user_id, None)
                break
                
            self.auto_attack_cache[user_id] = 0 
            current_hp = result.get('current_hp', result.get('hp', 0))

            # Logic phản đòn của Boss
            if current_hp > 0 and random.random() < 0.30:
                boss_dmg = random.randint(250, 600)
                if player.get("is_protecting"):
                    boss_dmg = int(boss_dmg * 0.2)
                    await rpg_profiles_col.update_one({"user_id": user_id}, {"$unset": {"is_protecting": ""}})
                
                new_hp = max(0, player.get("current_hp", 0) - boss_dmg)
                await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {"current_hp": new_hp}})
                
                if new_hp == 0:
                    try:
                        await interaction.followup.send(f"💀 **WARNING:** Your Digimon has been defeated by a counterattack!", ephemeral=True)
                    except (discord.NotFound, discord.HTTPException): pass
                    self.auto_attackers.discard(user_id)
                    break

            # Xử lý khi Boss chết từ đòn đánh này
            if current_hp <= 0:
                await self.distribute_boss_loot(result)
                try:
                    await interaction.followup.send("🎉 **BOSS DEFEATED!** Auto-Attack chain complete.", ephemeral=True)
                except (discord.NotFound, discord.HTTPException): pass
                self.auto_attackers.discard(user_id)
                break

    def get_attribute_multiplier(self, attacker_attr: str, defender_attr: str) -> float:
        if attacker_attr == defender_attr: return 1.0
        adv = {"Vaccine": "Virus", "Virus": "Data", "Data": "Vaccine"}
        return 1.25 if adv.get(attacker_attr) == defender_attr else 0.8           
    
    async def handle_manual_attack(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) 
        current_time = int(time.time())
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})

        if profile and current_time - profile.get("last_manual_atk", 0) < 4:
            return await interaction.followup.send("⏳ **Cooldown!** Slow down your strikes.", ephemeral=True)

        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"last_manual_atk": current_time}})
        msg, should_stop = await self.execute_combat_turn(interaction.user.id, interaction.user.display_name)

        if msg: 
            await interaction.followup.send(msg, ephemeral=True)
        if should_stop: 
            self.auto_attackers.discard(interaction.user.id)
            self.auto_attack_cache.pop(interaction.user.id, None)

    async def handle_protect(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        current_time = int(time.time())
        if profile and current_time - profile.get("last_protect", 0) < 45: 
            return await interaction.followup.send("⏳ Protect Cooldown!", ephemeral=True)
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"is_protecting": True, "last_protect": current_time}})
        await interaction.followup.send("🛡️ **Defensive Guard Active!**", ephemeral=True)

    async def execute_combat_turn(self, user_id: int, user_name: str) -> tuple:
        party = await parties_col.find_one({"members.user_id": user_id})
        boss = await world_boss_col.find_one({"is_active": True, "party_id": str(party["_id"])}) if party else None
        if not boss: boss = await world_boss_col.find_one({"is_active": True, "party_id": {"$exists": False}})
        if not boss: return ("❌ **No active Boss found.**", True)

        player = await rpg_profiles_col.find_one({"user_id": user_id})
        digimon = self.get_active_digimon(player)
        if not player or not digimon: return ("❌ **No Digimon partnered.**", True)
        if player.get("current_hp", 0) <= 0: return (f"☠️ <@{user_id}> **Fainted!** Please Heal.", True)

        stats = self.get_total_stats(player)
        raw_dmg = stats["atk"] + random.randint(-5, 10)
        if random.randint(1, 100) <= stats["crit_rate"]: raw_dmg *= stats["crit_dmg"]
        
        skill_msg = ""
        if "skill" in digimon and random.random() < digimon["skill"]["chance"]:
            raw_dmg *= digimon["skill"]["dmg_mult"]
            skill_msg = f"\n🌟 **SKILL!** **{digimon['skill']['name']}**!"
            
        attr_mult = self.get_attribute_multiplier(digimon["attr"], boss.get("attr", "Unknown"))
        final_dmg = int(raw_dmg * attr_mult * (1.25 if attr_mult > 1 else 1.0))
        
        result = await world_boss_col.find_one_and_update(
            {"_id": boss["_id"], "is_active": True}, 
            {"$inc": {"current_hp": -final_dmg, "hp": -final_dmg, f"damage_log.{str(user_id)}": final_dmg}, 
             "$addToSet": {"participants": user_id}},
            return_document=pymongo.ReturnDocument.AFTER
        )
        if not result: return ("❌ **Boss has already been defeated!**", True)
        
        current_hp = result.get('current_hp', result.get('hp', 0))
        msg = f"💥 **{user_name}** dealt **{final_dmg} DMG**. (Boss HP: {max(0, current_hp):,}){skill_msg}"

        if random.random() < 0.30 and current_hp > 0:
            boss_dmg = random.randint(250, 600)
            if player.get("is_protecting"):
                boss_dmg = int(boss_dmg * 0.2)
                msg += f"\n🛡️ **GUARDED!** Took only **{boss_dmg} DMG**."
                await rpg_profiles_col.update_one({"user_id": user_id}, {"$unset": {"is_protecting": ""}})
            else:
                msg += f"\n🚨 <@{user_id}> **BOSS COUNTERED** for **{boss_dmg} DMG**!"
                
            new_hp = max(0, player["current_hp"] - boss_dmg)
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {"current_hp": new_hp}})
            if new_hp == 0: return (msg + "\n💀 **YOUR PARTNER FAINTED!**", True)

        if current_hp <= 0:
            await self.distribute_boss_loot(result)
            return (msg + "\n🎉 **BOSS DEFEATED!**", True)
        return (msg, False)

    async def distribute_boss_loot(self, boss_data: dict):
        # KHÓA NGUYÊN TỬ (Atomic Lock): Đảm bảo chỉ 1 thread thực thi việc phát quà thành công
        actual_boss = await world_boss_col.find_one_and_update(
            {"_id": boss_data["_id"], "is_active": True},
            {"$set": {"is_active": False}},
            return_document=pymongo.ReturnDocument.BEFORE
        )
        if not actual_boss: return  # Nếu đã có thread khác xử lý thành công, thoát ngay.

        if "party_id" not in boss_data:
            await world_boss_col.update_one({"type": "spawn_config"}, {"$set": {"next_spawn": int(time.time()) + 3600}}, upsert=True)
        
        sorted_log = sorted(boss_data.get("damage_log", {}).items(), key=lambda x: x[1], reverse=True)
        total_hp = boss_data.get("max_hp", 1)

        participant_ids = [int(uid_str) for uid_str, _ in sorted_log]
        if participant_ids: 
            await rpg_profiles_col.update_many({"user_id": {"$in": participant_ids}}, {"$inc": {"myk_coin": 1}})

        for rank, (uid_str, dmg) in enumerate(sorted_log, 1):
            user_id = int(uid_str)
            dmg_percent = dmg / total_hp
            orbs_earned = max(1, int(dmg_percent * 10)) + (10 if rank == 1 else 5 if rank <= 3 else 0)
            
            reward_str = f"+{orbs_earned} orb & +1 MyK"
            update_query = {"$inc": {"orb": orbs_earned}}

            if rank <= 3 and random.random() < 0.30:
                reward_str += "\n🍎 Size Reroll Fruit"
                update_query.setdefault("$push", {})["inventory"] = "Size Reroll Fruit"
                
            if random.random() < (0.20 / rank) + dmg_percent:
                divine_drop = random.choice(["Divine Blade (Unlocked)", "Divine Aegis (Unlocked)", "Divine Vice (Unlocked)"])
                reward_str += f"\n👑 {divine_drop}"
                update_query.setdefault("$push", {})
                if "inventory" in update_query["$push"]: 
                    if isinstance(update_query["$push"]["inventory"], dict) and "$each" in update_query["$push"]["inventory"]:
                        update_query["$push"]["inventory"]["$each"].append(divine_drop)
                    else:
                        prev = update_query["$push"]["inventory"]
                        update_query["$push"]["inventory"] = {"$each": [prev, divine_drop]}
                else: 
                    update_query["$push"]["inventory"] = divine_drop
                
            await rpg_profiles_col.update_one({"user_id": user_id}, update_query)
            
            try:
                user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                if user:
                    dm_msg = (
                        f"🎉 **BOSS {boss_data['name']} HAS BEEN DEFEATED!**\n\n"
                        f"📊 **Your achievements:**\n"
                        f"🔹 Rank: `#{rank}`\n"
                        f"🔹 Damage inflicted: `{dmg:,}` ({dmg_percent*100:.1f}%)\n\n"
                        f"🏆 **Rewards received:**\n"
                        f"{reward_str}"
                    )
                    await user.send(dm_msg)
            except Exception as e:
                print(f"Cant send DM for {user_id}: {e}")
                
        # Kích hoạt chuỗi Boss tiếp theo sau khi phát thưởng thành công
        await self.trigger_chain_boss_respawn(boss_data.get("participants", []))

    async def process_boss_damage(self, interaction: discord.Interaction, boss_id: str, damage_dealt: int):
        user_id = interaction.user.id
        
        # Sửa lỗi: Thực hiện trừ HP thật vào database thông qua find_one_and_update
        updated_boss = await world_boss_col.find_one_and_update(
            {"boss_id": boss_id, "is_active": True},
            {"$inc": {"current_hp": -damage_dealt, "hp": -damage_dealt, f"damage_log.{str(user_id)}": damage_dealt},
             "$addToSet": {"participants": user_id}},
            return_document=pymongo.ReturnDocument.AFTER
        )
        if not updated_boss: return

        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"You have dealt {damage_dealt:,} damage to {updated_boss['name']}.", ephemeral=True)
        except Exception: pass

        current_hp = updated_boss.get("current_hp", updated_boss.get("hp", 0))
        if current_hp <= 0:
            # Sửa lỗi: Gọi phân phối phần thưởng thay vì xóa hoàn toàn thực thể Boss khỏi DB
            await self.distribute_boss_loot(updated_boss)

    async def trigger_chain_boss_respawn(self, participants: list):
        total_participant_atk = 0
        if participants:
            async for profile in rpg_profiles_col.find({"user_id": {"$in": participants}}):
                active_id = profile.get("active_digimon_id")
                active_digi = next((d for d in profile.get("digimon_list", []) if d["id"] == active_id), None)
                if active_digi:
                    total_participant_atk += active_digi.get("atk", 150)
        
        if total_participant_atk == 0: total_participant_atk = 3000

        boss_names_pool = ["Omnimon Zwart", "Alphamon Ouryuken", "Beelzemon X", "Gallantmon X", "Mastemon", "Lucemon Larva", "Susanoomon"]
        random_name = f"Vanguard {random.choice(boss_names_pool)} [Chain Raid]"
        
        calculated_hp = random.randint(total_participant_atk * 15, total_participant_atk * 30)
        calculated_atk = random.randint(int(total_participant_atk * 0.15), int(total_participant_atk * 0.3))

        new_boss = {
            "boss_id": str(uuid.uuid4()), "name": random_name, "hp": calculated_hp, "current_hp": calculated_hp, "max_hp": calculated_hp,
            "atk": calculated_atk, "participants": [], "is_active": True, "damage_log": {}, "active_messages": [], "spawned_at": datetime.utcnow()
        }
        
        result = await world_boss_col.insert_one(new_boss)
        new_boss["_id"] = result.inserted_id
       
        await self.broadcast_initial_boss(new_boss)    

    @app_commands.command(name="setup_boss_channel", description="Setup cross-server chat")
    async def setup_boss_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        is_admin = interaction.permissions.administrator if interaction.guild else False
        if not (is_admin or interaction.user.id in OWNER_IDS): 
            return await interaction.followup.send("❌ Access Denied!", ephemeral=True)
            
        try:
            webhook = next((w for w in await channel.webhooks() if w.user == self.bot.user), None) or await channel.create_webhook(name="DMW Relay")
            await boss_channels_col.update_one({"guild_id": interaction.guild_id}, {"$set": {"channel_id": channel.id, "webhook_url": webhook.url}}, upsert=True)
            await interaction.followup.send("✅ Success! The Global channel has been set up.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Error: Lack of `Manage Webhooks` permission.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)    

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild: return
        channel_config = await boss_channels_col.find_one({"guild_id": message.guild.id})
        if not channel_config or channel_config.get("channel_id") != message.channel.id: return
            
        other_channels = await boss_channels_col.find({"channel_id": {"$ne": message.channel.id}}).to_list(None)
        if not other_channels: return

        content = message.content
        if message.attachments: 
            content += ("\n" if content else "") + "\n".join([att.url for att in message.attachments])
            
        # Sửa lỗi: Ngăn chặn gửi chuỗi rỗng gây lỗi Webhook 400 Bad Request
        if not content.strip(): return

        formatted_username = f"[{message.guild.name[:15]}] {message.author.display_name}"
        if len(formatted_username) > 80:
            formatted_username = formatted_username[:77] + "..."
            
        sent_targets = []
        async with aiohttp.ClientSession() as session:
            for c in other_channels:
                if url := c.get("webhook_url"):
                    try:
                        webhook = discord.Webhook.from_url(url, session=session)
                        sent_msg = await webhook.send(content=content, username=formatted_username, avatar_url=message.author.display_avatar.url, wait=True)
                        sent_targets.append({"webhook_url": url, "channel_id": c.get("channel_id"), "message_id": sent_msg.id})
                    except Exception as e: print(f"⚠️ Relay error: {e}")

        if sent_targets:
            await cross_messages_col.insert_one({"source_msg_id": message.id, "source_channel_id": message.channel.id, "targets": sent_targets, "created_at": datetime.utcnow()})

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if after.author.bot or not after.guild: return
        log = await cross_messages_col.find_one({"source_msg_id": before.id})
        if not log: return

        new_content = after.content
        if after.attachments: 
            new_content += ("\n" if new_content else "") + "\n".join([att.url for att in after.attachments])
        if not new_content.strip(): return  # Không cho phép sửa thành tin nhắn rỗng gây crash Webhook

        async with aiohttp.ClientSession() as session:
            tasks = []
            for target in log.get("targets", []):
                webhook = discord.Webhook.from_url(target["webhook_url"], session=session)
                tasks.append(webhook.edit_message(target["message_id"], content=new_content))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True) # Xử lý song song tăng tốc độ phản hồi

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot or not message.guild: return
        log = await cross_messages_col.find_one({"source_msg_id": message.id})
        if not log: return

        async with aiohttp.ClientSession() as session:
            tasks = []
            for target in log.get("targets", []):
                webhook = discord.Webhook.from_url(target["webhook_url"], session=session)
                tasks.append(webhook.delete_message(target["message_id"]))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True) # Xử lý xóa song song chống nghẽn luồng
                
        await cross_messages_col.delete_one({"_id": log["_id"]})

    async def broadcast_system_message(self, content: str):
        channels = await boss_channels_col.find({}).to_list(None)
        async with aiohttp.ClientSession() as session:
            tasks = []
            for c in channels:
                if url := c.get("webhook_url"):
                    webhook = discord.Webhook.from_url(url, session=session)
                    tasks.append(webhook.send(content=content, username="SYSTEM RAID"))
            if tasks: await asyncio.gather(*tasks, return_exceptions=True)

    #===============================================================
    #                          RPB PROFILE 
    #==============================================================
    def get_active_digimon(self, profile: dict) -> dict:
        digimon_list = profile.get("digimon_list", [])
        active_id = profile.get("active_digimon_id")
        for digi in digimon_list:
            if digi.get("id") == active_id: return digi
        return {}

    def update_active_digimon(self, profile: dict, new_data: dict) -> list:
        digimon_list = profile.get("digimon_list", [])
        active_id = profile.get("active_digimon_id")
        for idx, digi in enumerate(digimon_list):
            if digi.get("id") == active_id:
                digimon_list[idx].update(new_data)
                break
        return digimon_list

    def clean_item_name(self, item_name: str) -> str:
        if not item_name: return "None"
        return item_name.replace(" (Unlocked)", "").replace(" (Locked)", "")

    def get_total_stats(self, profile: dict) -> dict:
        digimon = self.get_active_digimon(profile)
        total_hp = digimon.get("hp", 0) + digimon.get("trained_hp", 0)
        total_atk = digimon.get("atk", 0) + digimon.get("trained_atk", 0)
        total_def, total_crit_rate, total_crit_dmg = 10, 0, 1.0

        gear = profile.get("gear", {"weapon": "None", "armor": "None", "vice": "None"})
        w_name = self.clean_item_name(gear.get("weapon"))
        if w_name in self.ITEMS: total_atk += self.ITEMS[w_name].get("atk", 0)
        a_name = self.clean_item_name(gear.get("armor"))
        if a_name in self.ITEMS:
            total_hp += self.ITEMS[a_name].get("hp", 0)
            total_def += self.ITEMS[a_name].get("def", 0)
        v_name = self.clean_item_name(gear.get("vice"))
        if v_name in self.ITEMS:
            total_crit_rate += self.ITEMS[v_name].get("crit_rate", 0)
            total_crit_dmg += self.ITEMS[v_name].get("crit_dmg", 0)
        return {"hp": total_hp, "atk": total_atk, "def": total_def, "crit_rate": total_crit_rate, "crit_dmg": total_crit_dmg}

    async def refresh_profile_message(self, message: discord.Message, user_id: int):
        """Hàm phụ trợ: Tự động tải lại và làm mới nội dung Embed Profile ngay lập tức khi click nút"""
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        digimon = self.get_active_digimon(profile)
        stats = self.get_total_stats(profile)
        gear = profile.get("gear", {})
        is_premium = profile.get("premium_ui", False)
        
        embed = discord.Embed(
            title=f"{'🌟 PREMIUM TAMER' if is_premium else '📱 Tamer'} {profile.get('ign')}", 
            color=discord.Color.gold() if is_premium else discord.Color.teal()
        )
        if digimon:
            size_display = f"{digimon.get('size', 1.0) * 100:.1f}%"
            embed.set_thumbnail(url=digimon.get("img", ""))
            skill_info = f"\n**Skill:** {digimon.get('skill', {}).get('name')}" if "skill" in digimon else ""
            train_info = f"\n**Trained:** +{digimon.get('trained_atk', 0)} ATK | +{digimon.get('trained_hp', 0)} HP"
            embed.description = f"**Partner:** {digimon.get('name')} ({digimon.get('stage')})\n**Attr:** {digimon.get('attr')}\n**Size:** `{size_display}`{skill_info}{train_info}"
            embed.add_field(name="❤️ HP", value=f"{profile.get('current_hp')}/{stats['hp']}", inline=True)
            embed.add_field(name="⚔️ ATK", value=str(stats['atk']), inline=True)
            embed.add_field(name="🎯 CRIT", value=f"{stats['crit_rate']}% (x{stats['crit_dmg']})", inline=True)
            
        embed.add_field(name="💰 Assets", value=f"🌐 **{profile.get('digibit', 0):.2f} Bits** | 🔮 **{profile.get('hatch_core', 0)} Cores** | 🔮 **{profile.get('orb', 0)} orb**", inline=False)
        embed.add_field(name="Equipment", value=f"⚔️ {gear.get('weapon', 'None')}\n🛡️ {gear.get('armor', 'None')}\n📿 {gear.get('vice', 'None')}", inline=False)
        await message.edit(embed=embed, view=ProfileView(profile, self))

    @app_commands.command(name="rpg_profile", description="View profiles and manage Digimon.")
    async def rpg_profile(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        is_new = False
        # 1. Khởi tạo profile tự động có sẵn 15 Hatch Core nếu chưa từng đăng ký
        if not profile:
            is_new = True
            profile = {
                "user_id": user_id, "ign": interaction.user.display_name, "gold": 0, "digibit": 0.0, "hatch_core": 15, "myk_coin": 0, "premium_ui": False,
                "current_hp": 0, "gear": {"weapon": "None", "armor": "None", "vice": "None"}, "inventory": [], "is_vip": False, 
                "digimon_list": [], "active_digimon_id": None, "is_auto_mining": False, "auto_dungeon": None, "farm_logs": []
            }

        # 2. Tự động Hatch 1 Digimon khởi đầu hoàn toàn miễn phí nếu túi rỗng
        if not profile.get("digimon_list"):
            is_vip = profile.get("is_vip", False)
            available = [name for name, data in self.DIGIMON_DATA["rookie"].items() if not data["vip"] or is_vip]
            hatched_name = random.choice(available)
            base_stats = self.DIGIMON_DATA["rookie"][hatched_name]
            size_pct = round(random.uniform(1.00 if is_vip else 0.85, 1.30 if is_vip else 1.25), 3)

            actual_hp, actual_atk = int(base_stats["hp"] * size_pct), int(base_stats["atk"] * size_pct)
            new_digi_id = str(uuid.uuid4())
            
            starter_digimon = {
                "id": new_digi_id, "name": hatched_name, "stage": "Rookie", "attr": base_stats["attr"], 
                "size": size_pct, "hp": actual_hp, "atk": actual_atk, "img": base_stats["img"], "trained_hp": 0, "trained_atk": 0
            }
            profile["digimon_list"].append(starter_digimon)
            profile["active_digimon_id"] = new_digi_id
            profile["current_hp"] = actual_hp
            
            if is_new:
                await rpg_profiles_col.insert_one(profile)
            else:
                await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {"digimon_list": profile["digimon_list"], "active_digimon_id": new_digi_id, "current_hp": actual_hp}})
            
            await interaction.channel.send(f"🎉 Congratulations to new player {interaction.user.mention}! You have been awarded **15 Hatch Cores** and the system has automatically hatched your starter Digimon: **{hatched_name}** ({size_pct*100:.1f}%)!")
        elif is_new:
            await rpg_profiles_col.insert_one(profile)

        # Kết xuất hiển thị
        digimon = self.get_active_digimon(profile)
        stats, gear = self.get_total_stats(profile), profile.get("gear", {})
        is_premium = profile.get("premium_ui", False)
        
        embed = discord.Embed(title=f"{'🌟 PREMIUM TAMER' if is_premium else '📱 Tamer'} {profile.get('ign')}", color=discord.Color.gold() if is_premium else discord.Color.teal())
        if digimon:
            size_display = f"{digimon.get('size', 1.0) * 100:.1f}%"
            embed.set_thumbnail(url=digimon.get("img", ""))
            skill_info = f"\n**Skill:** {digimon.get('skill', {}).get('name')}" if "skill" in digimon else ""
            train_info = f"\n**Trained:** +{digimon.get('trained_atk', 0)} ATK | +{digimon.get('trained_hp', 0)} HP"
            embed.description = f"**Partner:** {digimon.get('name')} ({digimon.get('stage')})\n**Attr:** {digimon.get('attr')}\n**Size:** `{size_display}`{skill_info}{train_info}"
            embed.add_field(name="❤️ HP", value=f"{profile.get('current_hp')}/{stats['hp']}", inline=True)
            embed.add_field(name="⚔️ ATK", value=str(stats['atk']), inline=True)
            embed.add_field(name="🎯 CRIT", value=f"{stats['crit_rate']}% (x{stats['crit_dmg']})", inline=True)
            
        embed.add_field(name="💰 Assets", value=f"🌐 **{profile.get('digibit', 0):.2f} Bits** | 🔮 **{profile.get('hatch_core', 0)} Cores** | 🔮 **{profile.get('orb', 0)} orb**", inline=False)
        embed.add_field(name="Equipment", value=f"⚔️ {gear.get('weapon', 'None')}\n🛡️ {gear.get('armor', 'None')}\n📿 {gear.get('vice', 'None')}", inline=False)
        
        await interaction.followup.send(embed=embed, view=ProfileView(profile, self))

    async def handle_hatch_action(self, interaction: discord.Interaction):
        """Hàm gộp xử lý ấp trứng từ nút bấm"""
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})

        res = await rpg_profiles_col.update_one(
            {"user_id": user_id, "hatch_core": {"$gte": 5}},
            {"$inc": {"hatch_core": -5}}
        )
        if res.modified_count == 0:
            return await interaction.followup.send("❌ Bạn không đủ Hatch Core (Yêu cầu 5 lõi).", ephemeral=True)

        is_vip = profile.get("is_vip", False)
        available = [name for name, data in self.DIGIMON_DATA["rookie"].items() if not data["vip"] or is_vip]
        hatched_name = random.choice(available)
        base_stats = self.DIGIMON_DATA["rookie"][hatched_name]
        size_pct = round(random.uniform(1.00 if is_vip else 0.85, 1.30 if is_vip else 1.25), 3)

        actual_hp, actual_atk = int(base_stats["hp"] * size_pct), int(base_stats["atk"] * size_pct)
        new_digi_id = str(uuid.uuid4())
        
        digimon_stats = {
            "id": new_digi_id, "name": hatched_name, "stage": "Rookie", "attr": base_stats["attr"], 
            "size": size_pct, "hp": actual_hp, "atk": actual_atk, "img": base_stats["img"], "trained_hp": 0, "trained_atk": 0
        }

        updates = {"$push": {"digimon_list": digimon_stats}}
        if not profile.get("active_digimon_id"):
            updates["$set"] = {"active_digimon_id": new_digi_id, "current_hp": actual_hp}

        await rpg_profiles_col.update_one({"user_id": user_id}, updates)
        await interaction.followup.send(f"🥚 Ấp trứng thành công! Nhận được **{hatched_name}** ({size_pct * 100:.1f}%)", ephemeral=True)
        await self.refresh_profile_message(interaction.message, user_id)

    async def handle_train_action(self, interaction: discord.Interaction, stat: str):
        """Hàm gộp xử lý Huấn luyện chỉ số từ nút bấm"""
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        active_digi = self.get_active_digimon(profile)
        if not active_digi: return await interaction.followup.send("❌ Choose a Digimon companion first..", ephemeral=True)
        
        MAX_TRAIN_ATK, MAX_TRAIN_HP = 1000, 5000
        current_train_atk, current_train_hp = active_digi.get("trained_atk", 0), active_digi.get("trained_hp", 0)
        
        updates = {}
        if stat == "atk":
            if current_train_atk >= MAX_TRAIN_ATK: return await interaction.followup.send("❌ Reached ATK training limit.", ephemeral=True)
            updates["trained_atk"] = current_train_atk + 20
        else:
            if current_train_hp >= MAX_TRAIN_HP: return await interaction.followup.send("❌ Reached the HP training limit.", ephemeral=True)
            updates["trained_hp"] = current_train_hp + 100
            
        new_list = self.update_active_digimon(profile, updates)
        res = await rpg_profiles_col.update_one(
            {"user_id": user_id, "digibit": {"$gte": 500}}, 
            {"$set": {"digimon_list": new_list}, "$inc": {"digibit": -500}}
        )
        if res.modified_count == 0:
            return await interaction.followup.send("❌ Insufficient Digibits (500 Bits required).", ephemeral=True)
            
        await interaction.followup.send(f"🏋️ Trained successfully! **+{20 if stat == 'atk' else 100} {stat.upper()}** cho {active_digi['name']}.", ephemeral=True)
        await self.refresh_profile_message(interaction.message, user_id)

    async def handle_inventory_use(self, interaction: discord.Interaction, item_name: str):
        """SỬA LỖI: Hỗ trợ tìm kiếm thông minh đối chiếu cả String thường lẫn Object Dictionary trong hòm đồ"""
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        if not profile: return await interaction.followup.send("❌Profile does not exist.", ephemeral=True)
        
        inventory = profile.get("inventory", [])
        
        # Vòng lặp giải quyết lỗi: Quét tìm vật phẩm bất kể cấu trúc dữ liệu cũ hay mới
        found_item = None
        for item in inventory:
            if isinstance(item, dict) and item.get("name") == item_name:
                found_item = item
                break
            elif isinstance(item, str) and item == item_name:
                found_item = item
                break

        if not found_item: 
            return await interaction.followup.send(f"❌ No item `{item_name}` was found in your inventory.", ephemeral=True)

        if item_name == "Size Reroll Fruit":
            inventory.remove(found_item) # Xóa chính xác phần tử tìm được
            digimon = self.get_active_digimon(profile)
            if not digimon: return await interaction.followup.send("❌ No Digimon activated.", ephemeral=True)

            new_size = round(random.uniform(1.00 if profile.get("is_vip") else 0.85, 1.30 if profile.get("is_vip") else 1.25), 3)
            stage_lower = digimon.get("stage", "Rookie").lower()
            base_stats = self.DIGIMON_DATA.get(stage_lower, {}).get(digimon.get("name"))

            actual_hp, actual_atk = int(base_stats["hp"] * new_size), int(base_stats["atk"] * new_size)
            new_list = self.update_active_digimon(profile, {"size": new_size, "hp": actual_hp, "atk": actual_atk})
            
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {"inventory": inventory, "digimon_list": new_list, "current_hp": actual_hp + digimon.get("trained_hp", 0)}})
            await interaction.followup.send(f"🍎Using fruit successfully! New roll size: **{new_size * 100:.1f}%**!", ephemeral=True)
        else:
            cleaned_base = self.clean_item_name(item_name)
            if cleaned_base not in self.ITEMS: return await interaction.followup.send("❌ Invalid item data.", ephemeral=True)
            
            slot_type = self.ITEMS[cleaned_base]["type"]
            # Lưu trữ chuỗi tên trang bị lên vị trí gear slot
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {f"gear.{slot_type}": item_name}})
            await interaction.followup.send(f"🛡️ **Successfully equipped:** {item_name} -> Type `{slot_type.upper()}`", ephemeral=True)
    
    async def handle_heal(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id

        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        if not profile or not self.get_active_digimon(profile):
            return await interaction.followup.send("❌ No Digimon found.", ephemeral=True)

        # Lấy Max HP
        max_hp = self.get_total_stats(profile)["hp"]
        
        # Nếu máu đã đầy thì không cần hồi
        if profile.get("current_hp", 0) >= max_hp:
            return await interaction.followup.send("✨ Digimon's HP is full, no recovery needed.!", ephemeral=True)

        # Sử dụng hàm tiện ích lõi
        success = await self.attempt_auto_heal(user_id, profile, max_hp)
        
        if not success:
            last_heal_time = profile.get("last_heal", 0)
            remaining = 120 - (int(time.time()) - last_heal_time)
            return await interaction.followup.send(f"⏳ **Cooldown!** Please wait. {max(0, remaining)}s.", ephemeral=True)

        await interaction.followup.send("✨ **Healed!* The Digimon's HP has been fully restored.", ephemeral=True)

    async def handle_evolve(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id

        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        if not profile:
            return await interaction.followup.send("❌ Profile not found.", ephemeral=True)

        digimon = self.get_active_digimon(profile)
        if not digimon:
            return await interaction.followup.send("❌ No Active Digimon.", ephemeral=True)
            
        current_stage = digimon.get("stage", "rookie").lower()
        if current_stage == "mega":
            return await interaction.followup.send("❌ Max Level (Mega) reached.", ephemeral=True)

        TRAIN_COST = 1000
        if profile.get("digibit", 0) < TRAIN_COST:
            return await interaction.followup.send(f"❌ You need **{TRAIN_COST:,} Digibits** to evolve.", ephemeral=True)

        next_form_name = self.EVOLUTION_LINE.get(digimon["name"])
        if not next_form_name:
            return await interaction.followup.send("❌ This Digimon has no next evolution line.", ephemeral=True)

        # Tối ưu hóa chuẩn hóa Stage tự động
        next_stage_map = {
            "rookie": "champion",
            "champion": "ultimate",
            "ultimate": "mega",
        }
        next_stage_key = next_stage_map.get(current_stage)

        base_next_stats = self.DIGIMON_DATA[next_stage_key][next_form_name]
        current_size = digimon.get("size", 1.0)
        actual_hp = int(base_next_stats["hp"] * current_size)
        actual_atk = int(base_next_stats["atk"] * current_size)

        digimon_id = digimon["id"]

        set_updates = {
            "current_hp": actual_hp + digimon.get("trained_hp", 0),
            "digimon_list.$[elem].name": next_form_name,
            "digimon_list.$[elem].stage": next_stage_key.capitalize(),
            "digimon_list.$[elem].attr": base_next_stats["attr"],
            "digimon_list.$[elem].hp": actual_hp,
            "digimon_list.$[elem].atk": actual_atk,
            "digimon_list.$[elem].img": base_next_stats["img"],
        }
        if "skill" in base_next_stats:
            set_updates["digimon_list.$[elem].skill"] = base_next_stats["skill"]

        res = await rpg_profiles_col.update_one(
            {
                "user_id": user_id,
                "digibit": {"$gte": TRAIN_COST},
                "digimon_list.id": digimon_id,
            },
            {"$inc": {"digibit": -TRAIN_COST}, "$set": set_updates},
            array_filters=[{"elem.id": digimon_id}],
        )

        if res.modified_count == 0:
            return await interaction.followup.send("❌ Evolution failed! Check your balance or try again.", ephemeral=True)

        await interaction.followup.send(f"✨ **EVOLVED!** Your partner has successfully digivolved into **{next_form_name}**!", ephemeral=True)

    async def attempt_auto_heal(self, user_id: int, profile: dict, max_hp: int) -> bool:
        """
        Hàm tự động hồi máu.
        Trả về True nếu tự động hồi máu thành công, False nếu đang trong Cooldown.
        """
        current_time = int(time.time())
        
        # Cập nhật DB nguyên tử (Atomic Update)
        res = await rpg_profiles_col.update_one(
            {
                "user_id": user_id,
                "$or": [
                    {"last_heal": {"$exists": False}},
                    {"last_heal": {"$lte": current_time - 120}},
                ],
            },
            {"$set": {"current_hp": max_hp, "last_heal": current_time}},
        )
        
        if res.modified_count > 0:
            # Cập nhật thành công -> Bơm đầy máu trên object profile hiện tại để dùng tiếp
            profile["current_hp"] = max_hp
            profile["last_heal"] = current_time
            return True
            
        return False
    # ========================================================================
    # MARKET COMMANDS & HANDLERS
    # ========================================================================
    async def initialize_market_mega_products(self):
        """Tối ưu hóa: Dễ dàng thêm Digimon mới vào NEW_MEGA_POOL về sau mà không sợ lỗi trùng lặp"""
        for mega in NEW_MEGA_POOL:
            await market_col.update_one(
                {"item_name": mega["name"], "is_system": True},
                {"$setOnInsert": {
                    "listing_id": str(uuid.uuid4())[:8],
                    "item_name": mega["name"],
                    "price": float(mega["base_price"]),
                    "seller_name": "System Market",
                    "seller_id": "system",
                    "is_system": True,
                    "currency": "orb",
                    "listing_type": "digimon",  # Phân loại rõ ràng để điều hướng kho lưu trữ
                    "item_data": {
                        "id": str(uuid.uuid4()),
                        "name": mega["name"],
                        "stage": "Mega",
                        "obtained_at": int(time.time())
                    },
                    "created_at": int(time.time())
                }},
                upsert=True # Nếu chưa có tên quái thú này trên chợ hệ thống -> tự động chèn thêm
            )

    async def handle_market_buy(self, interaction: discord.Interaction, listing_id: str):
        await interaction.response.defer(ephemeral=True)
        
        # 1. Tìm món hàng và kiểm tra tồn tại
        item = await market_col.find_one({"listing_id": listing_id})
        if not item:
            return await interaction.followup.send("❌ This item is no longer available on the market or has already been sold!", ephemeral=True)
            
        buyer_id = interaction.user.id
        seller_id = item.get("seller_id")
        price = float(item["price"])
        is_system = item.get("is_system", False)
        listing_type = item.get("listing_type", "item") # Mặc định là item nếu dòng cũ không có
        
        # Ngăn chặn tự mua đồ của chính mình (chỉ áp dụng khi mua từ người chơi khác)
        if not is_system and buyer_id == seller_id:
            return await interaction.followup.send("❌ You cannot buy items yourself!", ephemeral=True)
            
        # 2. Kiểm tra số dư orb của người mua
        buyer_profile = await rpg_profiles_col.find_one({"user_id": buyer_id})
        if not buyer_profile or buyer_profile.get("orb", 0) < price:
            return await interaction.followup.send("❌ You don't have enough orb to complete this transaction.!", ephemeral=True)
            
        # 3. Thực hiện khấu trừ và luân chuyển tài chính
        # Trừ tiền người mua
        await rpg_profiles_col.update_one({"user_id": buyer_id}, {"$inc": {"orb": -price}})
        
        # Cộng tiền cho người bán (Chỉ thực hiện nếu đây là giao dịch giữa người chơi với nhau)
        if not is_system and seller_id != "system":
            await rpg_profiles_col.update_one({"user_id": seller_id}, {"$inc": {"orb": price}})
        
        # 4. Điều hướng phần thưởng (Gia tăng phân loại Digimon / Item)
        if listing_type == "digimon":
            # Nếu sản phẩm là Digimon -> Đẩy thẳng vào danh sách Digimon_list
            await rpg_profiles_col.update_one(
                {"user_id": buyer_id}, 
                {"$push": {"digimon_list": item["item_data"]}}
            )
            success_msg = f"Digimon **{item['item_name']}**It has been placed in your Digimon bag.!"
        else:
            # Nếu sản phẩm là Trang bị/vật phẩm thường -> Đẩy vào inventory như cũ
            await rpg_profiles_col.update_one(
                {"user_id": buyer_id}, 
                {"$push": {"inventory": item["item_data"]}} 
            )
            success_msg = f"The item **{item['item_name']}** has been moved to your inventory!"
            
        # 5. Xóa vật phẩm khỏi marketplace sau khi giao dịch hoàn tất
        await market_col.delete_one({"listing_id": listing_id})
        
        await interaction.followup.send(f"🛍️ **Transaction successful!** {success_msg} (Cost: {price:.0f} orb)", ephemeral=True)

    @app_commands.command(name="market", description="Open Digital Marketplace Shop")
    async def market_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # Lấy tối đa 25 sản phẩm mới nhất để vừa khít giới hạn hiển thị của Select Menu
        listings = await market_col.find({}).sort("created_at", -1).to_list(25)

        embed = discord.Embed(title="🏪 Digital Marketplace Shop", color=discord.Color.purple())
        
        if not listings:
            embed.description = "*Market is currently empty. Please check back later.*"
        else:
            desc = ""
            for item in listings:
                # Gắn nhãn hiển thị loại mặt hàng trực quan trên Embed
                type_tag = "🧬 [DIGIMON]" if item.get("listing_type") == "digimon" else "⚔️ [EQUIP]"
                desc += f"{type_tag} **{item['item_name']}**\n🆔 ID: `{item['listing_id']}` | 💰 **{item['price']:.2f} orb** | 👤 Seller: {item['seller_name']}\n\n"
            embed.description = desc[:4000]

        # Truyền trực tiếp list hàng hóa lấy từ DB vào View để xử lý đồng bộ
        await interaction.followup.send(embed=embed, view=MarketShopView(listings, self), ephemeral=True)

async def setup(bot):
    await bot.add_cog(RPGSystemCog(bot))