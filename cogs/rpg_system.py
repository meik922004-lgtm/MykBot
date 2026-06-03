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
    {"name": "ShineGreymon BM", "stage": "Mega", "attr": "Vaccine", "atk": 1090, "hp": 15500, "base_price": 600, "img": "https://digimon.net/cimages/digimon/shinegreymon_bm.jpg", "skill": {"name": "Final Shining Burst", "dmg_mult": 1.8, "chance": 0.15}},
    {"name": "MirageGaogamon BM", "stage": "Mega", "attr": "Data", "atk": 990, "hp": 14800, "base_price": 600, "img": "https://digimon.net/cimages/digimon/miragegaogamon_bm.jpg", "skill": {"name": "Full Moon Meteor Impact", "dmg_mult": 1.7, "chance": 0.18}},
    {"name": "Rosemon BM", "stage": "Mega", "attr": "Data", "atk": 1100, "hp": 14200, "base_price": 600, "img": "https://digimon.net/cimages/digimon/rosemon_bm.jpg", "skill": {"name": "Aguichant Lèvres", "dmg_mult": 1.6, "chance": 0.20}},
    {"name": "Ravemon BM", "stage": "Mega", "attr": "Vaccine", "atk": 1000, "hp": 14000, "base_price": 600, "img": "https://digimon.net/cimages/digimon/ravemon_bm.jpg", "skill": {"name": "Mourning Dance", "dmg_mult": 1.6, "chance": 0.20}},
    {"name": "BlackWarGreymon", "stage": "Mega", "attr": "Virus", "atk": 1045, "hp": 16500, "base_price": 600,  "img": "https://digimon.net/cimages/digimon/blackwargreymon.jpg", "skill": {"name": "Terra Destroyer", "dmg_mult": 1.8, "chance": 0.15}},
    {"name": "MetalSeadramon", "stage": "Mega", "attr": "Data", "atk": 1019, "hp": 15800, "base_price": 600, "img": "https://digimon.net/cimages/digimon/metalseadramon.jpg", "skill": {"name": "River of Power", "dmg_mult": 1.7, "chance": 0.18}},
    {"name": "Piedmon", "stage": "Mega", "attr": "Virus", "atk": 1066, "hp": 15000, "base_price": 600, "img": "https://digimon.net/cimages/digimon/piemon.jpg", "skill": {"name": "Trump Sword", "dmg_mult": 1.9, "chance": 0.12}},
    {"name": "Valkyrimon", "stage": "Mega", "attr": "Vaccine", "atk": 980, "hp": 13800, "base_price": 600, "img": "https://digimon.net/cimages/digimon/valkyrimon.jpg", "skill": {"name": "Fenrir Sword", "dmg_mult": 1.6, "chance": 0.20}},
    {"name": "Vikemon", "stage": "Mega", "attr": "Free", "atk": 999, "hp": 16800, "base_price": 600, "img": "https://digimon.net/cimages/digimon/vikemon.jpg", "skill": {"name": "Arctic Blizzard", "dmg_mult": 1.7, "chance": 0.18}},
    { "name": "GranKuwagamon", "stage": "Mega", "attr": "Virus", "atk": 1930, "hp": 14500, "base_price": 600, "img": "https://digimon.net/cimages/digimon/grankuwagamon.jpg", "skill": {"name": "Dimension Scissor", "dmg_mult": 1.8, "chance": 0.15}}
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
        gear = profile.get("gear", {}) 
        
        # 1. Đưa các trang bị ĐANG MẶC vào đầu danh sách để dễ Gỡ (Unequip)
        for slot in ["weapon", "armor", "vice"]:
            item = gear.get(slot)
            if item and item != "None":
                item_name = item if isinstance(item, str) else item.get("name", "Unknown")
                options.append(discord.SelectOption(
                    label=f"[Wearing] {item_name}",
                    description=f"Click to remove from slot {slot.upper()}",
                    value=f"unequip_{slot}", 
                    emoji="🔓"
                ))

        # 2. Gom nhóm và đưa các vật phẩm TRONG TÚI vào danh sách
        string_counts = {}
        dict_items = []
        
        for gear_item in inventory:
            if isinstance(gear_item, str):
                string_counts[gear_item] = string_counts.get(gear_item, 0) + 1
            elif isinstance(gear_item, dict):
                dict_items.append(gear_item)
        
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
        gear = profile.get("gear", {})

        if selected_value.startswith("unequip_"):
            slot = selected_value.replace("unequip_", "")
            item_to_remove = gear.get(slot)
            
            if item_to_remove:
                inventory.append(item_to_remove) 
                gear[slot] = "None"          
                
                await rpg_profiles_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"inventory": inventory, "gear": gear}}
                )
                item_name = item_to_remove if isinstance(item_to_remove, str) else item_to_remove.get("name")
                return await interaction.followup.send(f"🔓 I have removed **{item_name}** from position **[{slot.upper()}]** and put it in the storage!", ephemeral=True)
            else:
                return await interaction.followup.send("❌ Error: This location is not equipped.", ephemeral=True)

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
        
        if "Fruit" in item_name:
            active_id = profile.get("active_digimon_id")
            digimon_list = profile.get("digimon_list", [])
            active_digi = next((d for d in digimon_list if d["id"] == active_id), None)
            
            if not active_digi:
                return await interaction.followup.send("❌ You need to activate a Digimon before using a Fruit.!", ephemeral=True)
                
            new_size = round(random.uniform(1, 1.30), 2)
            active_digi["size"] = new_size
            inventory.remove(target_item)
            
            await rpg_profiles_col.update_one(
                {"user_id": user_id},
                {"$set": {"inventory": inventory, "digimon_list": digimon_list}}
            )
            return await interaction.followup.send(f"🍎 **{item_name}** has been used on **{active_digi['name']}**!\n📏 New size: **{new_size * 100:.1f}%**", ephemeral=True)
            
        cleaned_name = self.cog.clean_item_name(item_name)
        gear_base_data = self.cog.ITEMS.get(cleaned_name, {}) if not is_dict else target_item
        gear_type = gear_base_data.get("type")
        
        if gear_type in ["weapon", "armor", "vice"]:
            old_gear = gear.get(gear_type)
            
            if old_gear and old_gear != "None":
                inventory.append(old_gear)
                
            gear[gear_type] = target_item
            inventory.remove(target_item)
            
            await rpg_profiles_col.update_one(
                {"user_id": user_id},
                {"$set": {"inventory": inventory, "gear": gear}}
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
        await self.cog.handle_set_active_digimon(interaction, self.values[0])

class BulkSellDigiSelect(discord.ui.Select):
    def __init__(self, digimon_list, active_id, cog_instance):
        self.cog = cog_instance
        options = []
        
        for d in digimon_list:
            is_active = "✅ [Active] " if d["id"] == active_id else ""
            options.append(discord.SelectOption(
                label=f"{is_active}{d['name']}",
                value=d["id"],
                description=f"Stage: {d['stage']} | Size: {d.get('size', 1)*100:.0f}%"
            ))
        
        if not options:
            options = [discord.SelectOption(label="Empty bag", value="none")]
            super().__init__(placeholder="💰No Digimon for sale...", options=options, disabled=True)
        else:
            # Giới hạn số lượng chọn tối đa bằng số Digimon đang có (tối đa 25 theo giới hạn của Discord)
            max_vals = min(len(options), 25)
            super().__init__(
                placeholder="💰 Choose one or more Digimon to sell in bulk...",
                options=options,
                min_values=1,
                max_values=max_vals
            )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none": 
            return
        # Gọi hàm xử lý bán hàng loạt ở Cog
        await self.cog.handle_bulk_sell_digimon(interaction, self.values)

# --- UI MỚI CHO TÚI DIGIMON CHỨA CẢ MENU CHỌN VÀ NÚT BÁN ---
class DigiBagView(discord.ui.View):
    def __init__(self, digimon_list, active_id, cog_instance, timeout=180):
        super().__init__(timeout=timeout)
        self.cog = cog_instance
        
        # Menu 1: Chọn 1 Digimon để kích hoạt làm bạn đồng hành
        self.add_item(DigiBagSelect(digimon_list, active_id, cog_instance))
        
        # Menu 2: Chọn nhiều Digimon để bán lấy Digibits
        self.add_item(BulkSellDigiSelect(digimon_list, active_id, cog_instance))

class InventoryView(discord.ui.View):
    def __init__(self, select_menu=None, profile=None, cog_instance=None, timeout=180):
        super().__init__(timeout=timeout)
        if select_menu:
            self.add_item(select_menu)
        elif profile and cog_instance:
            self.add_item(GearInventorySelect(profile, cog_instance))   

def generate_inventory_embed(profile: dict) -> discord.Embed:
    embed = discord.Embed(title="🎒 Inventory", color=discord.Color.blue())
    
    gear = profile.get("gear", {})
    w_name = gear.get("weapon")
    a_name = gear.get("armor")
    v_name = gear.get("vice")
    
    w_display = w_name if isinstance(w_name, str) else w_name.get("name", "Empty") if w_name else "Empty"
    a_display = a_name if isinstance(a_name, str) else a_name.get("name", "Empty") if a_name else "Empty"
    v_display = v_name if isinstance(v_name, str) else v_name.get("name", "Empty") if v_name else "Empty"
    
    gear_text = f"⚔️ **Weapon:** {w_display}\n🛡️ **Armor:** {a_display}\n📿 **Vice:** {v_display}"
    embed.add_field(name="👕 Equipment currently worn", value=gear_text, inline=False)
    
    inventory = profile.get("inventory", [])
    if not inventory:
        embed.add_field(name="📦Storage", value="*Your equipment storage is empty.*", inline=False)
    else:
        string_counts = {}
        dict_items = []
        for item in inventory:
            if isinstance(item, str):
                string_counts[item] = string_counts.get(item, 0) + 1
            else:
                dict_items.append(item)
                
        inv_text = ""
        for name, count in string_counts.items():
            qty = f" (x{count})" if count > 1 else ""
            inv_text += f"🔹 {name}{qty}\n"
            
        for item in dict_items:
            rarity = item.get("rarity", "Rare")
            inv_text += f"🌟 {item.get('name', 'Unknown')} `[{rarity}]`\n"
            
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

    @discord.ui.button(label="🥚 Hatch Digi (50 Cores)", style=discord.ButtonStyle.primary, row=0)
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

    @discord.ui.button(label="Digimon bag", style=discord.ButtonStyle.secondary, emoji="🐾", row=1)
    async def open_digi_bag(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile:
            return await interaction.followup.send("❌ Character data not found.", ephemeral=True)
        
        digi_list = profile.get("digimon_list", [])
        
        if not digi_list:
            return await interaction.followup.send("❌ Your bag is empty! You need to catch some Digimon first.", ephemeral=True)
        
        options = digi_list[:25]
        
        embed = discord.Embed(
            title="🐾 Your Digimon Bag", 
            description=f"You have {len(digi_list)} Digimon in your bag.", 
            color=discord.Color.gold()
        )
        
        # SỬ DỤNG DigiBagView ĐỂ HIỂN THỊ CẢ MENU CHỌN VÀ NÚT BÁN
        view = DigiBagView(options, profile.get("active_digimon_id"), self.cog) 
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Equipment storage", style=discord.ButtonStyle.primary, emoji="🎒", row=2)
    async def open_inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile:
            return await interaction.followup.send("❌ No Data.", ephemeral=True)
            
        embed = generate_inventory_embed(profile)
        view = InventoryView(profile=profile, cog_instance=self.cog)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # --- THÊM NÚT DAILY CHECK ---
    @discord.ui.button(label="📅 Daily Check", style=discord.ButtonStyle.success, row=2)
    async def daily_check_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_daily_check(interaction)

    # --- THÊM NÚT REFRESH ---
    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=2)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cog.refresh_profile_message(interaction.message, interaction.user.id)


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


# ========================================================================
#                            MAIN COG SYSTEM
# ========================================================================
class RPGSystemCog(commands.Cog):
    ITEMS = {
        "Rusty Sword": {"type": "weapon", "atk": 15}, "Rusty Armor": {"type": "armor", "hp": 150, "def": 10}, "Rusty Vice": {"type": "vice", "crit_rate": 5, "crit_dmg": 1.2},
        "Chrome Dagger": {"type": "weapon", "atk": 45}, "Chrome Cloak": {"type": "armor", "hp": 350, "def": 25}, "Chrome Vice": {"type": "vice", "crit_rate": 10, "crit_dmg": 1.5},
        "Divine Blade": {"type": "weapon", "atk": 120}, "Divine Aegis": {"type": "armor", "hp": 800, "def": 60}, "Divine Vice": {"type": "vice", "crit_rate": 20, "crit_dmg": 2.0}
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
        self.live_boss_update_loop.cancel()
        

    # ========================================================================
    #                       HELPER METHODS
    # ========================================================================

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
        if not actual_boss: return  # Đã có process khác nhận lệnh này

        if "party_id" not in boss_data:
            await world_boss_col.update_one({"type": "spawn_config"}, {"$set": {"next_spawn": int(time.time()) + 3600}}, upsert=True)
        
        sorted_log = sorted(boss_data.get("damage_log", {}).items(), key=lambda x: x[1], reverse=True)
        total_hp = boss_data.get("max_hp", 1)

        for rank, (uid_str, dmg) in enumerate(sorted_log, 1):
            user_id = int(uid_str)
            dmg_percent = dmg / total_hp
            
            # --- PHẦN THƯỞNG CHẮC CHẮN 100% CỐ ĐỊNH CHO TẤT CẢ ---
            base_orb = random.randint(10, 20)
            base_digibit = 100
            base_myk = 1
            
            # --- CÁC BIẾN CHỨA PHẦN THƯỞNG DÙNG ĐỂ GỬI UPDATE_QUERY ---
            inc_data = {"orb": base_orb, "digibit": base_digibit, "myk_coin": base_myk}
            inventory_rewards = []
            reward_str = f"➕ **{base_orb}** orb\n➕ **{base_digibit}** digibit\n➕ **{base_myk}** MyK Coin"

            # --- TỈ LỆ GACHA (Dựa trên xếp hạng và phần trăm sát thương) ---
            # Xếp hạng càng cao, phần trăm tỉ lệ cộng thêm càng lớn
            bonus_chance = 0.0
            if rank == 1: bonus_chance = 0.15      # Top 1 cộng thêm 15%
            elif rank <= 3: bonus_chance = 0.08    # Top 2-3 cộng thêm 8%
            else: bonus_chance = dmg_percent       # Các hạng sau phụ thuộc độ đóng góp sát thương

            # 1. Tỉ lệ 10% nhận High-Tier Item (Mythic/Divine)
            high_tier_rate = 0.10 + bonus_chance
            if random.random() < high_tier_rate:
                # Random giữa Mythic Gear (Dict) và Divine Gear (String)
                if random.random() < 0.5:
                    mythic_item = random.choice(self.HIGH_TIER_GEARS).copy()
                    mythic_item["id"] = str(uuid.uuid4())
                    mythic_item["obtained_at"] = int(time.time())
                    inventory_rewards.append(mythic_item)
                    reward_str += f"\n👑 **{mythic_item['name']}** [{mythic_item['rarity']}]"
                else:
                    divine_item = random.choice(["Divine Blade", "Divine Aegis", "Divine Vice"])
                    inventory_rewards.append(divine_item)
                    reward_str += f"\n🌟 **{divine_item}**"

            # 2. Tỉ lệ 20% nhận Item Thường (Rusty/Chrome)
            normal_rate = 0.20 + (bonus_chance * 0.5)
            if random.random() < normal_rate:
                normal_item = random.choice(["Rusty Sword", "Rusty Armor", "Rusty Vice", "Chrome Dagger", "Chrome Cloak", "Chrome Vice"])
                inventory_rewards.append(normal_item)
                reward_str += f"\n🛡️ **{normal_item}**"

            # 3. Tỉ lệ 30% nhận Size Reroll Fruit
            fruit_rate = 0.30 + (bonus_chance * 0.5)
            if random.random() < fruit_rate:
                inventory_rewards.append("Size Reroll Fruit")
                reward_str += "\n🍎 **Size Reroll Fruit**"

            # --- TỔNG HỢP VÀ CẬP NHẬT LÊN DATABASE (Sạch sẽ, chống lỗi) ---
            update_query = {"$inc": inc_data}
            if inventory_rewards:
                # Cách viết này đảm bảo MongoDB push một mảng dữ liệu cực kỳ an toàn
                update_query["$push"] = {"inventory": {"$each": inventory_rewards}}
                
            await rpg_profiles_col.update_one({"user_id": user_id}, update_query)
            
            # --- GỬI TIN NHẮN BÁO CÁO QUA DM ---
            try:
                user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                if user:
                    dm_msg = (
                        f"🎉 **BOSS {boss_data['name']} HAS BEEN DEFEATED!**\n\n"
                        f"📊 **Combat Report:**\n"
                        f"🔹 Rank: `#{rank}`\n"
                        f"🔹 Damage inflicted: `{dmg:,}` ({dmg_percent*100:.1f}%)\n\n"
                        f"🏆 **Your reward:**\n{reward_str}"
                    )
                    await user.send(dm_msg)
            except Exception as e:
                print(f"Error: Unable to send DM {user_id}: {e}")
                
        # Kích hoạt chuỗi Boss tiếp theo
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

            await interaction.channel.send(f"🎉 Congratulations to new player {interaction.user.mention}! You have been awarded **50 Hatch Cores** and the system has automatically hatched your starter Digimon: **{hatched_name}** ({size_pct*100:.1f}%)!")
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
            {"user_id": user_id, "hatch_core": {"$gte": 50}},
            {"$inc": {"hatch_core": -50}}
        )
        if res.modified_count == 0:
            return await interaction.followup.send("❌ You don't have enough Hatch Cores (50 cores required).", ephemeral=True)

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
        await interaction.followup.send(f"🥚Egg hatching successful! Received **{hatched_name}** ({size_pct * 100:.1f}%)", ephemeral=True)
        await self.refresh_profile_message(interaction.message, user_id)

    def get_active_digimon(self, profile: dict) -> dict:
        digimon_list = profile.get("digimon_list", [])
        active_id = profile.get("active_digimon_id")
        for digi in digimon_list:
            if digi.get("id") == active_id: return digi
        return {}

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
        # ĐÃ LOẠI BỎ HOÀN TOÀN CÁC THÀNH PHẦN LIÊN QUAN TỚI FARM Ở ĐÂY
        if not profile:
            is_new = True
            profile = {
                "user_id": user_id, "ign": interaction.user.display_name, "gold": 0, "digibit": 0.0, "hatch_core": 15, "myk_coin": 0, "premium_ui": False,
                "current_hp": 0, "gear": {"weapon": "None", "armor": "None", "vice": "None"}, "inventory": [], "is_vip": False, 
                "digimon_list": [], "active_digimon_id": None
            }

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
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})

        res = await rpg_profiles_col.update_one(
            {"user_id": user_id, "hatch_core": {"$gte": 5}},
            {"$inc": {"hatch_core": -5}}
        )
        if res.modified_count == 0:
            return await interaction.followup.send("❌ You don't have enough Hatch Cores (5 cores required).", ephemeral=True)

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
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        if not profile: return await interaction.followup.send("❌ Profile does not exist.", ephemeral=True)
        
        inventory = profile.get("inventory", [])
        
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
            inventory.remove(found_item) 
            digimon = self.get_active_digimon(profile)
            if not digimon: return await interaction.followup.send("❌ No Digimon activated.", ephemeral=True)

            new_size = round(random.uniform(1.00 if profile.get("is_vip") else 0.85, 1.30 if profile.get("is_vip") else 1.25), 3)
            stage_lower = digimon.get("stage", "Rookie").lower()
            base_stats = self.DIGIMON_DATA.get(stage_lower, {}).get(digimon.get("name"))

            actual_hp, actual_atk = int(base_stats["hp"] * new_size), int(base_stats["atk"] * new_size)
            new_list = self.update_active_digimon(profile, {"size": new_size, "hp": actual_hp, "atk": actual_atk})
            
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {"inventory": inventory, "digimon_list": new_list, "current_hp": actual_hp + digimon.get("trained_hp", 0)}})
            await interaction.followup.send(f"🍎 Using fruit successfully! New roll size: **{new_size * 100:.1f}%**!", ephemeral=True)
        else:
            cleaned_base = self.clean_item_name(item_name)
            if cleaned_base not in self.ITEMS: return await interaction.followup.send("❌ Invalid item data.", ephemeral=True)
            
            slot_type = self.ITEMS[cleaned_base]["type"]
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {f"gear.{slot_type}": item_name}})
            await interaction.followup.send(f"🛡️ **Successfully gear:** {item_name} -> Type `{slot_type.upper()}`", ephemeral=True)
    
    async def handle_heal(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id

        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        if not profile or not self.get_active_digimon(profile):
            return await interaction.followup.send("❌ No Digimon found.", ephemeral=True)

        max_hp = self.get_total_stats(profile)["hp"]
        
        if profile.get("current_hp", 0) >= max_hp:
            return await interaction.followup.send("✨ Digimon's HP is full, no recovery needed.!", ephemeral=True)

        success = await self.attempt_auto_heal(user_id, profile, max_hp)
        
        if not success:
            last_heal_time = profile.get("last_heal", 0)
            remaining = 120 - (int(time.time()) - last_heal_time)
            return await interaction.followup.send(f"⏳ **Cooldown!** Please wait. {max(0, remaining)}s.", ephemeral=True)

        await interaction.followup.send("✨ **Healed!** The Digimon's HP has been fully restored.", ephemeral=True)


    # ====================================================================================
    # LÔ-GÍC XỬ LÝ MỚI: HÀM DAILY CHECK & HÀM BÁN DIGIMON (ADD VÀO COG)
    # ====================================================================================

    async def handle_daily_check(self, interaction: discord.Interaction):
        """Xử lý điểm danh hàng ngày: Cộng 1000 Digibits và 100 Hatch Cores"""
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        if not profile:
            return await interaction.followup.send("❌ Character data not found.", ephemeral=True)
            
        today = datetime.now().date().isoformat()

        last_check = profile.get("last_daily_check")
        
        # Kiểm tra xem hôm nay người chơi đã điểm danh chưa
        if last_check == today:
            return await interaction.followup.send("❌ You've already checked in today! Please come back tomorrow..", ephemeral=True)
            
        new_streak = profile.get("daily_streak", 0) + 1
        
        # Cập nhật trực tiếp vào cơ sở dữ liệu tài sản của người chơi
        await rpg_profiles_col.update_one(
            {"user_id": user_id},
            {
                "$inc": {"digibit": 1000, "hatch_core": 100},
                "$set": {"last_daily_check": today, "daily_streak": new_streak}
            }
        )
        
        await interaction.followup.send(
            f"🎉 **Attendance check successful.!**\n"
            f"📅 Congratulations on your attendance! **{new_streak}** day!\n"
            f"🎁 Rewards received: **+1,000 Digibits** and **+100 Hatch Cores**!",
            ephemeral=True
        )
        # Làm mới lại UI Profile ngay lập tức
        try:
            await self.refresh_profile_message(interaction.message, user_id)
        except Exception:
            pass

    async def handle_bulk_sell_digimon(self, interaction: discord.Interaction, selected_ids: list):
        """Xử lý bán hàng loạt các Digimon được chọn từ Select Menu"""
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        if not profile:
            return await interaction.followup.send("❌Character data not found.", ephemeral=True)
            
        digi_list = profile.get("digimon_list", [])
        active_id = profile.get("active_digimon_id")
        
        # 🛡️ KIỂM TRA AN TOÀN: Người chơi không được phép bán hết toàn bộ Digimon
        if len(selected_ids) >= len(digi_list):
            return await interaction.followup.send(
                "❌ **Action blocked!* You cannot sell all Digimon in your inventory. You must keep at least one companion.", 
                ephemeral=True
            )
            
        # Phân loại: Giữ lại những con không bị chọn, thu thập tên những con bị bán
        remaining_digi_list = [d for d in digi_list if d["id"] not in selected_ids]
        sold_digimon_names = [d["name"] for d in digi_list if d["id"] in selected_ids]
        
        # Tính toán phần thưởng kinh tế: 100 bits cho mỗi Digimon bị xóa
        total_reward_bits = len(selected_ids) * 100
        
        # Kiểm tra xem con Digimon đang kích hoạt (Active) có nằm trong danh sách bị bán hay không
        is_active_sold = active_id in selected_ids
        
        updates = {
            "$set": {
                "digimon_list": remaining_digi_list
            },
            "$inc": {"digibit": total_reward_bits}
        }
        
        # 🐾 NẾU BÁN MẤT CON ACTIVE: Tự động chuyển sang con đầu tiên còn lại trong túi
        if is_active_sold:
            new_active = remaining_digi_list[0]
            updates["$set"]["active_digimon_id"] = new_active["id"]
            # Đồng bộ lại máu Root theo lượng máu của con Digimon mới được đôn lên làm Active
            updates["$set"]["current_hp"] = new_active.get("hp", 100)
            
        # Cập nhật một lần duy nhất vào Database
        await rpg_profiles_col.update_one({"user_id": user_id}, updates)
        
        # Tạo chuỗi văn bản hiển thị danh sách tên các con đã bán
        sold_names_str = ", ".join(sold_digimon_names)
        
        status_msg = (
            f"💰 **Successful bulk sales!**\n"
            f"🗑️ Liberation **{len(selected_ids)}** Digimon: `[{sold_names_str}]`.\n"
            f"💵 Gain: **+{total_reward_bits:.0f} Digibits**!"
        )
        
        if is_active_sold:
            status_msg += f"\n🐾 *Because the previous Digimon companion has been sold., **{remaining_digi_list[0]['name']}** đã tự động lên thay thế!*"
            
        await interaction.followup.send(status_msg, ephemeral=True)
        
        # Cập nhật lại giao diện Profile chính phía ngoài để hiển thị số tiền mới
        try:
            await self.refresh_profile_message(interaction.message, user_id)
        except Exception:
            pass

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
    
    async def handle_set_active_digimon(self, interaction, digimon_id):
        await interaction.response.defer(ephemeral=True)
        # 1. Cập nhật active_digimon_id trong database
        await rpg_profiles_col.update_one(
            {"user_id": interaction.user.id},
            {"$set": {"active_digimon_id": digimon_id}}
        )
        
        # 2. Phản hồi cho người chơi
        await interaction.followup.send(f"✅ Digimon with ID {digimon_id} has been activated!", ephemeral=True)
    # ========================================================================
    # MARKET COMMANDS & HANDLERS
    # ========================================================================
    async def initialize_market_mega_products(self):
        """Khởi tạo Market với dữ liệu trực tiếp từ NEW_MEGA_POOL, khắc phục lỗi rỗng Skill và Attr"""

        for mega in NEW_MEGA_POOL:
            mega_name = mega["name"]
            
            # Lấy toàn bộ chỉ số trực tiếp từ Dictionary trong NEW_MEGA_POOL
            base_hp = int(mega.get("hp", 15000))
            base_atk = int(mega.get("atk", 1500))
            attr = mega.get("attr", "Unknown")
            img = mega.get("img", "")
            
            # Khởi tạo Object skill chuẩn, đề phòng trường hợp nhập thiếu sẽ có fallback
            fallback_skill = {"name": "Basic Strike", "dmg_mult": 1.5, "chance": 0.1}
            skill = mega.get("skill", fallback_skill)

            await market_col.update_one(
                {"item_name": mega_name, "is_system": True},
                {"$setOnInsert": {
                    "listing_id": str(uuid.uuid4())[:8],
                    "item_name": mega_name,
                    "price": float(mega["base_price"]),
                    "seller_name": "System Market",
                    "seller_id": "system",
                    "is_system": True,
                    "currency": "orb",
                    "listing_type": "digimon",  
                    "item_data": {
                        "id": str(uuid.uuid4()),
                        "name": mega_name,
                        "stage": "Mega",
                        "attr": attr,
                        "hp": base_hp,
                        "atk": base_atk,
                        "current_hp": base_hp,
                        "size": 1.0,  # Nên để size 1.0 lúc mua, tránh việc scale chỉ số ảo quá cao
                        "img": img,
                        "skill": skill,  # Sẽ lưu đúng định dạng Object (Dictionary)
                        "trained_hp": 0,
                        "trained_atk": 0,
                        "obtained_at": int(time.time())
                    },
                    "created_at": int(time.time())
                }},
                upsert=True 
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
        count = await market_col.count_documents({})

        # Nếu chợ trống, tự động nạp hàng hóa hệ thống vào
        if count == 0:
            await self.initialize_market_mega_products()
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