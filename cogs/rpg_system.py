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
import math
import copy
farm_logs_buffer = {}
cross_messages_col = rpg_profiles_col.database["cross_chat_logs"]
market_col = rpg_profiles_col.database["rpg_marketplace"]
OWNER_IDS = [1283689737567211581]

# ========================================================================
# GLOBAL CONSTANTS & POOLS
# ========================================================================

NEW_MEGA_POOL = [
    {"name": "ShineGreymon BM", "stage": "Mega", "attr": "Vaccine", "base_atk": 1270, "base_hp": 15500, "base_price": 600, "img": "https://digimon.net/cimages/digimon/shinegreymon_bm.jpg", "skill": {"name": "Final Shining Burst", "dmg_mult": 1.8, "chance": 0.15}},
    {"name": "MirageGaogamon BM", "stage": "Mega", "attr": "Data", "base_atk": 1200, "base_hp": 14800, "base_price": 600, "img": "https://digimon.net/cimages/digimon/miragegaogamon_bm.jpg", "skill": {"name": "Full Moon Meteor Impact", "dmg_mult": 1.7, "chance": 0.18}},
    {"name": "Rosemon BM", "stage": "Mega", "attr": "Data", "base_atk": 1100, "base_hp": 14200, "base_price": 600, "img": "https://digimon.net/cimages/digimon/rosemon_bm.jpg", "skill": {"name": "Aguichant Lèvres", "dmg_mult": 1.6, "chance": 0.20}},
    {"name": "Ravemon BM", "stage": "Mega", "attr": "Vaccine", "base_atk": 1255, "base_hp": 14000, "base_price": 600, "img": "https://digimon.net/cimages/digimon/ravemon_bm.jpg", "skill": {"name": "Mourning Dance", "dmg_mult": 1.6, "chance": 0.20}},
    {"name": "BlackWarGreymon", "stage": "Mega", "attr": "Virus", "base_atk": 1250, "base_hp": 16500, "base_price": 600,  "img": "https://digimon.net/cimages/digimon/blackwargreymon.jpg", "skill": {"name": "Terra Destroyer", "dmg_mult": 1.8, "chance": 0.15}},
    {"name": "MetalSeadramon", "stage": "Mega", "attr": "Data", "base_atk": 1140, "base_hp": 15800, "base_price": 600, "img": "https://digimon.net/cimages/digimon/metalseadramon.jpg", "skill": {"name": "River of Power", "dmg_mult": 1.7, "chance": 0.18}},
    {"name": "Piedmon", "stage": "Mega", "attr": "Virus", "base_atk": 1230, "base_hp": 15000, "base_price": 600, "img": "https://digimon.net/cimages/digimon/piemon.jpg", "skill": {"name": "Trump Sword", "dmg_mult": 1.9, "chance": 0.12}},
    {"name": "Valkyrimon", "stage": "Mega", "attr": "Vaccine", "base_atk": 1210, "base_hp": 13800, "base_price": 600, "img": "https://digimon.net/cimages/digimon/valkyrimon.jpg", "skill": {"name": "Fenrir Sword", "dmg_mult": 1.6, "chance": 0.20}},
    {"name": "Vikemon", "stage": "Mega", "attr": "Free", "base_atk": 1280, "base_hp": 16800, "base_price": 600, "img": "https://digimon.net/cimages/digimon/vikemon.jpg", "skill": {"name": "Arctic Blizzard", "dmg_mult": 1.7, "chance": 0.18}},
    { "name": "GranKuwagamon", "stage": "Mega", "attr": "Virus", "base_atk": 1130, "base_hp": 14500, "base_price": 600, "img": "https://digimon.net/cimages/digimon/grankuwagamon.jpg", "skill": {"name": "Dimension Scissor", "dmg_mult": 1.8, "chance": 0.15}}
]

HIGH_TIER_GEARS = [
    {"name": "Omega Artifact Sword", "type": "weapon", "atk": 650, "rarity": "Mythic"},
    {"name": "Alpha Absolute Shield", "type": "armor", "def": 550, "hp": 1500, "rarity": "Mythic"},
    {"name": "Ultimate Omegamon Vice", "type": "vice", "crit_rate": 20, "crit_dmg": 5.0,"rarity": "Mythic"},
    {"name": "Crimson End Armor", "type": "armor", "def": 600, "hp": 3500, "rarity": "Mythic"},
    {"name": "Miracle Origin Vice", "type": "vice", "crit_rate": 50, "crit_dmg":3.0, "rarity": "Mythic"}
]

OLYMPOS_XII_DATA = {
    "Jupitermon": "Vaccine", "Junomon": "Virus", "Neptunemon": "Vaccine", 
    "Ceresmon": "Data", "Apollomon": "Vaccine", "Dianamon": "Data", 
    "Vulcanusmon": "Data", "Marsmon": "Vaccine", "Minervamon": "Virus", 
    "Mercurymon": "Virus", "Venusmon": "Vaccine", "Bacchusmon": "Virus"
}

# Định nghĩa chỉ số trang bị Origin (Vượt trội hơn Mythic)
ORIGIN_GEAR_TEMPLATES = {
    "weapon": {
        "name": "Origin Eternal Judgement (Weapon)",
        "rarity": "Origin",
        "rarity": {"atk": 1200, "def": 0, "hp": 1000},
        "description": "The low chance causes a small portion of the player's ATK to become damage."
    },
    "armor": {
        "name": "Origin Aegis of Olympus (Armor)",
        "rarity": "Origin",
        "stats": {"def": 600, "hp": 4500},
        "description": "Low chance of blocking a certain amount of incoming damage and restoring HP.."
    },
    "vice": {
        "name": "Origin Cosmic Chrono (Vice)",
        "rarity": "Origin",
        "stats": {"crit_dmg":5, "crit_rate":70},
        "description": "Low chance of significantly increasing damage when triggering a critical hit.."
    }
}
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
        # === [PHẦN GOM NHÓM VÀ ĐƯA CÁC VẬT PHẨM TRONG TÚI VÀO DANH SÁCH] ===
        string_counts = {}
        dict_items = [] # THAY ĐỔI: Sẽ lưu dưới dạng tuple (vị trí_index, món_đồ)
        
        for idx, gear_item in enumerate(inventory):
            if isinstance(gear_item, str):
                string_counts[gear_item] = string_counts.get(gear_item, 0) + 1
            elif isinstance(gear_item, dict):
                dict_items.append((idx, gear_item)) # Lưu kèm vị trí index gốc
        
        # Vòng lặp 1: Dành cho vật phẩm thường dạng chuỗi (Giữ nguyên cũ)
        for gear_str, count in string_counts.items():
            if len(options) >= 25: break
            cleaned_name = cog_instance.clean_item_name(gear_str)
            gear_data = cog_instance.ITEMS.get(cleaned_name, {})
            stats = []
            if "atk" in gear_data: stats.append(f"ATK +{gear_data['atk']}")
            if "def" in gear_data: stats.append(f"DEF +{gear_data['def']}")
            if "hp" in gear_data: stats.append(f"HP +{gear_data['hp']}")
            if "crit_rate" in gear_data: stats.append(f"CT +{gear_data['crit_rate']}%")
            if "crit_dmg" in gear_data: stats.append(f"CD +{gear_data['crit_dmg']}%")
            stat_desc = " | ".join(stats) if stats else "Consumable"
            quantity_label = f" x{count}" if count > 1 else ""
            options.append(discord.SelectOption(
                label=f"{cleaned_name}{quantity_label}",
                description=f"Type: {gear_data.get('type', 'item').upper()} | {stat_desc}",
                value=gear_str 
            ))
            
        # Vòng lặp 2: Dành cho vật phẩm chỉ số dạng Dict (Mythic / Origin)
        for idx, gear_dict in dict_items:
            if len(options) >= 25: break
            
            gear_name_lower = gear_dict.get('name', '').lower()
            is_vice = (gear_dict.get('type') == 'vice' or 'vice' in gear_name_lower or 'chrono' in gear_name_lower)
            
            if "stats" in gear_dict:
                if is_vice and ("atk" in gear_dict["stats"] or "hp" in gear_dict["stats"]):
                    gear_dict["stats"] = {"crit_rate": 70, "crit_dmg": 12.0}
                target_stats = gear_dict["stats"]
            else:
                if is_vice and ("atk" in gear_dict or "hp" in gear_dict):
                    for old_key in ["atk", "def", "hp"]:
                        if old_key in gear_dict: del gear_dict[old_key]
                    gear_dict["crit_rate"] = 70 
                    gear_dict["crit_dmg"] = 5.0
                target_stats = gear_dict
            
            if is_vice:
                gear_dict["type"] = "vice"

            stats = []
            if "atk" in target_stats: stats.append(f"ATK +{target_stats['atk']}")
            if "def" in target_stats: stats.append(f"DEF +{target_stats['def']}")
            if "hp" in target_stats: stats.append(f"HP +{target_stats['hp']}")
            if "crit_rate" in target_stats: stats.append(f"CT +{target_stats['crit_rate']}%")
            if "crit_dmg" in target_stats: stats.append(f"CD +{target_stats['crit_dmg']}%")
            
            stat_desc = " | ".join(stats) if stats else "No Stats"
            rarity_label = gear_dict.get('rarity', gear_dict.get('tier', 'Common'))
            
            # SỬA LỖI TẠI ĐÂY: Thêm chỉ số biến 'idx' vào giữa để bảo đảm value luôn độc nhất độc bản
            fallback_id = f"no_id_{idx}_{gear_dict.get('name', 'Unknown')}"
            
            options.append(discord.SelectOption(
                label=f"{gear_dict.get('name', 'Unknown')} ({rarity_label})",
                description=f"Type: {gear_dict.get('type', 'N/A').upper()} | {stat_desc}",
                value=gear_dict.get("id", fallback_id)[:100]
            ))
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
                
                # [AUTO REFRESH] Cập nhật giao diện kho đồ sau khi gỡ
                updated_profile = await rpg_profiles_col.find_one({"user_id": user_id})
                try:
                    await interaction.message.edit(embed=generate_inventory_embed(updated_profile), view=InventoryView(profile=updated_profile, cog_instance=self.cog))
                except Exception: pass

                return await interaction.followup.send(f"🔓 I have removed **{item_name}** from position **[{slot.upper()}]** and put it in the storage!", ephemeral=True)
            else:
                return await interaction.followup.send("❌ Error: This location is not equipped.", ephemeral=True)

        selected_value = self.values[0]
        inventory = profile.get("inventory", [])
        
        target_item = None
        is_dict = False
        
        # SỬA LỖI TẠI ĐÂY: Nếu trúng fallback_id dạng định danh độc nhất, bóc tách lấy thẳng vị trí item
        if selected_value.startswith("no_id_"):
            try:
                parts = selected_value.split("_")
                target_idx = int(parts[2]) # Lấy giá trị biến idx (vị trí phần tử thứ 2 sau dấu _)
                if target_idx < len(inventory):
                    target_item = inventory[target_idx]
                    is_dict = isinstance(target_item, dict)
            except Exception:
                pass

        # Biện pháp Back-up: Nếu không phải fallback_id hoặc trích xuất lỗi, dùng lại logic quét cũ
        if target_item is None:
            for item in inventory:
                if isinstance(item, str) and item == selected_value:
                    target_item = item
                    break
                elif isinstance(item, dict):
                    if item.get("id") == selected_value:
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
            
            # [AUTO REFRESH] Cập nhật giao diện sau khi dùng Fruit
            updated_profile = await rpg_profiles_col.find_one({"user_id": user_id})
            try:
                await interaction.message.edit(embed=generate_inventory_embed(updated_profile), view=InventoryView(profile=updated_profile, cog_instance=self.cog))
            except Exception: pass

            return await interaction.followup.send(f"🍎 **{item_name}** has been used on **{active_digi['name']}**!\n📏 New size: **{new_size * 100:.1f}%**", ephemeral=True)
            
        cleaned_name = self.cog.clean_item_name(item_name)
        gear_base_data = self.cog.ITEMS.get(cleaned_name, {}) if not is_dict else target_item
        
        # 1. Cố gắng lấy type từ dữ liệu sẵn có
        gear_type = gear_base_data.get("type")
        
        # 2. SỬA LỖI TẠI ĐÂY: Nếu đồ Origin/Mythic cũ trong DB bị thiếu key "type", tự động đoán qua tên
        if not gear_type and is_dict:
            name_lower = item_name.lower()
            if "weapon" in name_lower or "sword" in name_lower or "judgement" in name_lower:
                gear_type = "weapon"
            elif "armor" in name_lower or "aegis" in name_lower or "shield" in name_lower:
                gear_type = "armor"
            elif "vice" in name_lower or "chrono" in name_lower:
                gear_type = "vice"
        
        # 3. Tiếp tục logic mặc đồ
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
            
            # [AUTO REFRESH] Cập nhật giao diện sau khi mặc đồ mới
            updated_profile = await rpg_profiles_col.find_one({"user_id": user_id})
            try:
                await interaction.message.edit(embed=generate_inventory_embed(updated_profile), view=InventoryView(profile=updated_profile, cog_instance=self.cog))
            except Exception: pass

            return await interaction.followup.send(f"✅ **{item_name}** has been placed in position **[{gear_type.upper()}]**!", ephemeral=True)
            
        await interaction.followup.send(f"📦 Item **{item_name}** cannot be used directly here..", ephemeral=True)


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

class BulkSellGearSelect(discord.ui.Select):
    def __init__(self, profile: dict, cog_instance):
        self.cog = cog_instance
        options = []
        
        # Lấy kho đồ nguyên bản để xử lý theo từng vị trí (index)
        inventory = profile.get("inventory", [])
        
        # Sử dụng enumerate để lấy chính xác vị trí index của từng món đồ
        for index, item in enumerate(inventory):
            if len(options) >= 25: 
                break  # Giới hạn tối đa của một Select Menu trong Discord là 25 options
                
            # 1. Đưa các trang bị thường (String) vào danh sách bán theo từng ô độc lập
            if isinstance(item, str):
                if "Fruit" in item: 
                    continue  # Bỏ qua Size Reroll Fruit để tránh người chơi bán nhầm
                    
                cleaned_name = cog_instance.clean_item_name(item)
                options.append(discord.SelectOption(
                    label=f"Sell: {cleaned_name}",
                    description="Click to select | Price: 200 Digibits",
                    value=f"sell_idx_{index}",  # Định danh bằng INDEX để tạo ra các checkbox riêng biệt
                    emoji="💰"
                ))
                
            # 2. Đưa các trang bị chỉ số (Dict - Mythic) vào danh sách bán
            elif isinstance(item, dict):
                options.append(discord.SelectOption(
                    label=f"Sell: {item.get('name', 'Unknown')} ({item.get('rarity', 'Common')})",
                    description="Click to select | Price: 200 Digibits",
                    value=f"sell_idx_{index}",  # Định danh bằng INDEX
                    emoji="👑"
                ))

        if not options:
            options = [discord.SelectOption(label="No equipment available to sell.", value="none")]
            super().__init__(placeholder="💰 Bulk Sell Storage (Empty)...", options=options, disabled=True)
        else:
            # max_values tự động co giãn bằng tổng số lượng option đang hiển thị (cho phép đa chọn)
            super().__init__(
                placeholder="💰 Select multiple items to bulk sell...", 
                options=options,
                min_values=1,
                max_values=len(options)
            )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        if not profile:
            return await interaction.followup.send("❌ Character data not found.", ephemeral=True)
        inventory = profile.get("inventory", [])
        selected_values = self.values  # Nhận về danh sách các index được tích chọn (ví dụ: ['sell_idx_2', 'sell_idx_5'])
        
        # Trích xuất danh sách các index dạng số
        indices_to_remove = []
        for val in selected_values:
            if val.startswith("sell_idx_"):
                try:
                    idx = int(val.replace("sell_idx_", ""))
                    indices_to_remove.append(idx)
                except ValueError:
                    continue
        if not indices_to_remove:
            return await interaction.followup.send("❌ No valid items were selected for sale.", ephemeral=True)
        # ⚠️ QUAN TRỌNG: Sắp xếp các chỉ mục index theo thứ tự GIẢM DẦN (từ lớn đến nhỏ)
        # Nếu xóa từ đầu mảng (index nhỏ trước), các vật phẩm phía sau sẽ bị đẩy dịch vị trí lên, gây xóa nhầm đồ!
        indices_to_remove.sort(reverse=True)
        sold_count = 0
        # Tiến hành bốc tách và xóa đồ ra khỏi inventory theo vị trí index ngược từ dưới lên
        for idx in indices_to_remove:
            if 0 <= idx < len(inventory):
                inventory.pop(idx)
                sold_count += 1
        if sold_count == 0:
            return await interaction.followup.send("❌ No valid items were processed for sale.", ephemeral=True)
        # Tính toán tiền tệ và cập nhật Database tài sản
        earned_bits = sold_count * 200
        await rpg_profiles_col.update_one(
            {"user_id": user_id},
            {"$set": {"inventory": inventory}, "$inc": {"digibit": float(earned_bits)}}
        )

        # Gửi tin nhắn phản hồi thành công bí mật (ephemeral)
        await interaction.followup.send(f"💰 **Bulk sale successful!** Sold {sold_count} items and earned **{earned_bits:.2f} Digibits**!", ephemeral=True)

        # ==========================================
        # [AUTO REFRESH] Cập nhật giao diện Chợ/Kho đồ lập tức
        # ==========================================
        updated_profile = await rpg_profiles_col.find_one({"user_id": user_id})
        new_embed = generate_inventory_embed(updated_profile)
        new_view = InventoryView(profile=updated_profile, cog_instance=self.cog)
        try:
            await interaction.message.edit(embed=new_embed, view=new_view)
        except Exception:
            pass

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
    def __init__(self, full_digimon_list, active_id, cog_instance, timeout=180):
        super().__init__(timeout=timeout)
        self.cog = cog_instance
        self.full_digimon_list = full_digimon_list
        self.active_id = active_id
        
        # Thiết lập phân trang
        self.current_page = 0
        self.items_per_page = 25
        self.max_pages = max(1, math.ceil(len(full_digimon_list) / self.items_per_page))
        
        # Khởi tạo giao diện lần đầu
        self.update_components()

    def update_components(self):
        """Xóa các thành phần cũ và vẽ lại dựa trên trang hiện tại."""
        self.clear_items()
        
        # Cắt danh sách Digimon cho trang hiện tại
        start_idx = self.current_page * self.items_per_page
        end_idx = start_idx + self.items_per_page
        current_page_digimon = self.full_digimon_list[start_idx:end_idx]

        # Thêm Menu 1: Chọn 1 Digimon để kích hoạt
        self.add_item(DigiBagSelect(current_page_digimon, self.active_id, self.cog))
        
        # Thêm Menu 2: Chọn nhiều Digimon để bán
        self.add_item(BulkSellDigiSelect(current_page_digimon, self.active_id, self.cog))

        # Nếu danh sách dài hơn 1 trang, vẽ thêm nút chuyển trang
        if self.max_pages > 1:
            # Nút Prev
            btn_prev = discord.ui.Button(
                label="⬅️ Prev", 
                style=discord.ButtonStyle.primary, 
                disabled=(self.current_page == 0)
            )
            btn_prev.callback = self.prev_page_callback
            self.add_item(btn_prev)

            # Nút hiển thị số trang (Chỉ để nhìn, không bấm được)
            btn_page_indicator = discord.ui.Button(
                label=f"Page {self.current_page + 1}/{self.max_pages}", 
                style=discord.ButtonStyle.secondary, 
                disabled=True
            )
            self.add_item(btn_page_indicator)

            # Nút Next
            btn_next = discord.ui.Button(
                label="Next ➡️", 
                style=discord.ButtonStyle.primary, 
                disabled=(self.current_page == self.max_pages - 1)
            )
            btn_next.callback = self.next_page_callback
            self.add_item(btn_next)

    async def prev_page_callback(self, interaction: discord.Interaction):
        self.current_page -= 1
        self.update_components()
        await self.refresh_message(interaction)

    async def next_page_callback(self, interaction: discord.Interaction):
        self.current_page += 1
        self.update_components()
        await self.refresh_message(interaction)
        
    async def refresh_message(self, interaction: discord.Interaction):
        """Cập nhật lại tin nhắn sau khi bấm chuyển trang"""
        # Cập nhật footer của Embed để khớp số trang
        embed = interaction.message.embeds[0]
        embed.set_footer(text=f"Trang {self.current_page + 1}/{self.max_pages} | Tổng: {len(self.full_digimon_list)} Digimon")
        await interaction.response.edit_message(embed=embed, view=self)
class InventoryView(discord.ui.View):
    def __init__(self, select_menu=None, profile=None, cog_instance=None, timeout=180):
        super().__init__(timeout=timeout)
        if select_menu:
            self.add_item(select_menu)
        elif profile and cog_instance:
            # Menu 1: Mặc đồ / Gỡ đồ cũ
            self.add_item(GearInventorySelect(profile, cog_instance))   
            # Menu 2: Chọn nhiều món để bán tháo giải phóng dung lượng (Mới)
            self.add_item(BulkSellGearSelect(profile, cog_instance)) 

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
class TrainMultiplierView(discord.ui.View):
    def __init__(self, stat: str, cog_instance, original_msg: discord.Message):
        super().__init__(timeout=60)
        self.stat = stat
        self.cog = cog_instance
        self.original_msg = original_msg  # Lưu lại tin nhắn Profile gốc để Refresh sau khi Train

    @discord.ui.button(label="Train x1 (500 Bits)", style=discord.ButtonStyle.primary)
    async def train_x1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_train_action(interaction, self.stat, multiplier=1, original_msg=self.original_msg)

    @discord.ui.button(label="Train x5 (2500 Bits)", style=discord.ButtonStyle.danger)
    async def train_x5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_train_action(interaction, self.stat, multiplier=5, original_msg=self.original_msg)

class ProfileView(discord.ui.View):
    def __init__(self, profile: dict, cog_instance):
        super().__init__(timeout=180)
        self.profile = profile
        self.cog = cog_instance

    # --- ROW 0: Sinh sản, Đột biến, Tiến hóa ---
    @discord.ui.button(label="🥚 Hatch Digi", style=discord.ButtonStyle.primary, row=0)
    async def hatch_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_hatch_action(interaction)

    @discord.ui.button(label="🍎 Reroll Size", style=discord.ButtonStyle.success, row=0)
    async def reroll_size_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_quick_reroll(interaction)

    @discord.ui.button(label="🧬 Evolve", style=discord.ButtonStyle.danger, row=0)
    async def evolve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_evolve(interaction)

    # --- ROW 1: Huấn luyện & Hồi phục ---
    @discord.ui.button(label="🏋️ Train ATK", style=discord.ButtonStyle.secondary, row=1)
    async def train_atk_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Mở menu ẩn chọn x1 hoặc x5
        view = TrainMultiplierView(stat="atk", cog_instance=self.cog, original_msg=interaction.message)
        await interaction.response.send_message("🏋️ **Select training multiplier for ATK:**", view=view, ephemeral=True)

    @discord.ui.button(label="🏋️ Train HP", style=discord.ButtonStyle.secondary, row=1)
    async def train_hp_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = TrainMultiplierView(stat="hp", cog_instance=self.cog, original_msg=interaction.message)
        await interaction.response.send_message("🏋️ **Select training multiplier for HP:**", view=view, ephemeral=True)

    @discord.ui.button(label="🩹 Heal Partner", style=discord.ButtonStyle.success, row=1)
    async def heal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_heal(interaction)

    # --- ROW 2: Túi đồ & Kho bãi ---
    @discord.ui.button(label="Digimon bag", style=discord.ButtonStyle.secondary, emoji="🐾", row=2)
    async def open_digi_bag(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile: return await interaction.followup.send("❌ Character data not found.", ephemeral=True)
        digi_list = profile.get("digimon_list", [])
        if not digi_list: return await interaction.followup.send("❌ Your bag is empty!", ephemeral=True)
        
        embed = discord.Embed(title="🐾 Your Digimon Bag", description=f"You have {len(digi_list)} Digimon.", color=discord.Color.gold())
        embed.set_footer(text=f"Trang 1/{max(1, math.ceil(len(digi_list)/25))} | Tổng: {len(digi_list)} Digimon")
        
        # SỬA Ở ĐÂY: Truyền digi_list thay vì digi_list[:25]
        await interaction.followup.send(embed=embed, view=DigiBagView(digi_list, profile.get("active_digimon_id"), self.cog), ephemeral=True)
    @discord.ui.button(label="Equipment storage", style=discord.ButtonStyle.primary, emoji="🎒", row=2)
    async def open_inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile: return await interaction.followup.send("❌ No Data.", ephemeral=True)
        await interaction.followup.send(embed=generate_inventory_embed(profile), view=InventoryView(profile=profile, cog_instance=self.cog), ephemeral=True)

    # --- ROW 3: Tiện ích ---
    @discord.ui.button(label="📅 Daily Check", style=discord.ButtonStyle.success, row=3)
    async def daily_check_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_daily_check(interaction)

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=3)
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


import asyncio  # 🔥 Bắt buộc phải có ở đầu file để chạy độ trễ

class SoloCombatView(discord.ui.View):
    def __init__(self, cog, user_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.action_locked = False  # 🟢 CƠ CHẾ KHÓA MỚI: Tránh double-click
        self.update_button_states()

    def update_button_states(self):
        """Mở khóa lại các nút và kiểm tra Cooldown chiêu hồi máu"""
        battle = self.cog.active_solo_battles.get(self.user_id)
        
        self.attack_btn.disabled = False
        if battle:
            if battle.get("defend_cd", 0) > 0:
                self.defend_btn.disabled = True
                self.defend_btn.label = f"Defend (CD: {battle['defend_cd']})"
            else:
                self.defend_btn.disabled = False
                self.defend_btn.label = "🛡️ DEFEND"

        if battle and battle["heal_cd"] > 0:
            self.heal_btn.disabled = True
            self.heal_btn.label = f"Heal (CD: {battle['heal_cd']} turn)"
        else:
            self.heal_btn.disabled = False
            self.heal_btn.label = "🧪 HEAL"
            
    # 🟢 THÊM NÚT NÀY: Giúp người chơi chủ động thoát trận nếu muốn đổi Boss hoặc kẹt UI
    @discord.ui.button(label="🏳️ FLEE", style=discord.ButtonStyle.secondary, row=1)
    async def flee_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.action_locked: return
        self.action_locked = True
        await interaction.response.defer()
        
        try:
            # Xóa trận đấu khỏi bộ nhớ để mở khóa cho người chơi
            self.cog.active_solo_battles.pop(self.user_id, None)
            
            # Khóa toàn bộ nút bấm
            for child in self.children:
                child.disabled = True
                
            embed = interaction.message.embeds[0]
            embed.description = "🏳️ **BATTLE CANCELED!** You successfully escaped the dungeon."
            
            # Gắn thêm nút New Game ngay sau khi bỏ cuộc
            new_battle_btn = discord.ui.Button(label="🔄 New Battle", style=discord.ButtonStyle.primary)
            async def new_battle_callback(btn_interaction: discord.Interaction):
                if btn_interaction.user.id != self.user_id:
                    return await btn_interaction.response.send_message("❌ This is not your battle!", ephemeral=True)
                await btn_interaction.response.defer()
                await self.cog.start_solo_battle(btn_interaction, self.user_id)
                
            new_battle_btn.callback = new_battle_callback
            self.add_item(new_battle_btn)
            
            await interaction.edit_original_response(embed=embed, view=self)
        finally:
            self.action_locked = False

    async def on_timeout(self) -> None:
        if self.user_id in self.cog.active_solo_battles:
            self.cog.active_solo_battles.pop(self.user_id, None)
        for child in self.children:
            child.disabled = True
        if hasattr(self, 'message') and self.message:
            try:
                embed = self.message.embeds[0]
                embed.description = "⌛ **BATTLE TIMED OUT!** The match was canceled due to inactivity."
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        """Kích hoạt tự động nếu có lỗi vặt bên trong View"""
        # 🛑 ĐÃ XÓA LỆNH .pop() Ở ĐÂY ĐỂ NGĂN CHẶN VIỆC RESET TRẬN ĐẤU KHI LỖI MẠNG
        
        if not interaction.response.is_done():
            await interaction.response.send_message(f"⚠️ CThere's a slight network interruption! Please press the button again..\nError: `{error}`", ephemeral=True)
        else:
            await interaction.followup.send(f"⚠️ There's a network interruption! Please press the button again. \nError: `{error}`", ephemeral=True)
            
        import traceback
        traceback.print_exception(type(error), error, error.__traceback__)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your match!", ephemeral=True)
            return False
        return True

    async def process_turn(self, interaction: discord.Interaction, player_action: str):
        battle = self.cog.active_solo_battles.get(self.user_id)
        if not battle:
            return await interaction.edit_original_response(content="❌ This match has ended or no longer exists.", view=None)

        # 1. Khóa giao diện tạm thời
        for child in self.children:
            child.disabled = True

        embed_waiting = interaction.message.embeds[0].copy()
        embed_waiting.description = "⏳ **IN BATTLE...** "
        # 🟢 VÌ ĐÃ DEFER Ở NÚT BẤM, TA DÙNG edit_original_response THAY VÌ response.edit_message
        await interaction.edit_original_response(embed=embed_waiting, view=self)

        await asyncio.sleep(1)

        player = await rpg_profiles_col.find_one({"user_id": self.user_id})
        digimon = self.cog.get_active_digimon(player)
        stats = self.cog.get_total_stats(player)
        digi_size = digimon.get("size", 1.0)
        player_def = stats.get("def", 50) 
        
        # 🟢 LẤY CHỈ SỐ SPEED (Nếu Profile chưa có thì random từ 50-150)
        player_speed = stats.get("speed", random.randint(50, 150))

        log_msgs = []
        is_protecting = False

        # ==========================================
        # 2. XỬ LÝ LƯỢT NGƯỜI CHƠI (PLAYER TURN)
        # ==========================================
        if battle.get("debuff_duration", 0) > 0:
            if battle.get("player_debuff") == "stun":
                log_msgs.append(f"💫 **STUNNED!** **{digimon['name']}** is paralyzed!")
                player_action = "skip"
            elif battle.get("player_debuff") == "blind" and player_action == "attack":
                if random.random() < 0.70:
                    log_msgs.append(f"🌫️ **BLINDED!** **{digimon['name']}**'s attack missed completely.")
                    player_action = "miss"

            battle["debuff_duration"] -= 1
            if battle["debuff_duration"] <= 0:
                battle["player_debuff"] = None

        if player_action == "attack":
            raw_dmg = stats["atk"] + random.randint(-5, 10)
            if random.randint(1, 100) <= stats.get("crit_rate", 5):
                raw_dmg *= stats.get("crit_dmg", 1.5)
                log_msgs.append("🌟 **CRITICAL HIT!**")

            attr_mult = self.cog.get_attribute_multiplier(digimon["attr"], battle["boss_attr"])
            base_dmg = int(raw_dmg * attr_mult * (1.25 if attr_mult > 1 else 1.0) * digi_size)
            
            boss_def = battle.get("boss_def", 50)
            boss_def_mult = 100 / (100 + boss_def)
            final_dmg = int(base_dmg * boss_def_mult)
            
            battle["boss_hp"] = max(0, battle["boss_hp"] - final_dmg)
            log_msgs.append(f"⚔️ **{digimon['name']}** attacks, dealing **{final_dmg:,} DMG**.")

        elif player_action == "defend":
            is_protecting = True
            battle["defend_cd"] = 3
            log_msgs.append("🛡️ You choose to **Defend**, blocking incoming damage!")

        elif player_action == "heal":
            heal_amt = int(battle["player_max_hp"] * 0.15)
            battle["player_hp"] = min(battle["player_max_hp"], battle["player_hp"] + heal_amt)
            battle["heal_cd"] = 3 
            log_msgs.append(f"🧪 You use a potion, restoring **{heal_amt:,} HP**.")

        if player_action != "heal" and battle["heal_cd"] > 0:
            battle["heal_cd"] -= 1
        if player_action != "defend" and battle.get("defend_cd", 0) > 0:
            battle["defend_cd"] -= 1

        # ==========================================
        # 3. KIỂM TRA TRẢ THƯỞNG KHI BOSS CHẾT
        # ==========================================
        if battle["boss_hp"] <= 0:
            rew_config = battle.get("rewards_config", {})
            won_digibits = random.randint(rew_config.get("digibits", [50, 100])[0], rew_config.get("digibits", [50, 100])[1])
            won_hatch_cores = random.randint(rew_config.get("hatch_cores", [1, 3])[0], rew_config.get("hatch_cores", [1, 3])[1])
            won_fruits = random.randint(rew_config.get("size_fruits", [0, 2])[0], rew_config.get("size_fruits", [0, 2])[1])
            
            reward_text = (
                f"\n\n🎁 **VICTORY REWARDS:**\n"
                f"➕ **{won_digibits:,}** Digibits\n"
                f"➕ **{won_hatch_cores}** Hatch Cores\n"
                f"➕ **{won_fruits}** Size Reroll Fruits"
            )
            
            # Chia nhỏ query cập nhật để tránh lỗi cấu hình Array của MongoDB làm hỏng toàn bộ phần thưởng
            try:
                # 1. Cộng tiền tệ cơ bản trước (Luôn thành công)
                await rpg_profiles_col.update_one(
                    {"user_id": self.user_id}, 
                    {"$inc": {"digibit": won_digibits, "hatch_core": won_hatch_cores}}
                )
                
                # 2. Đẩy vật phẩm vào túi đồ (Nếu lỗi cấu hình mảng hỗn hợp sẽ bộc lộ ở đây)
                if won_fruits > 0:
                    push_items = ["Size Reroll Fruit"] * won_fruits
                    await rpg_profiles_col.update_one(
                        {"user_id": self.user_id},
                        {"$push": {"inventory": {"$each": push_items}}}
                    )
            except Exception as db_err:
                print(f"[DATABASE ERROR] Error recording player rewards {self.user_id}: {db_err}")
                reward_text += "\n⚠️ *Lưu ý:cError recording player rewards"

            battle["log"] = "\n".join(log_msgs) + f"\n\n🎉 **VICTORY!**You have successfully conquered .{battle['boss_name']}!{reward_text}"
            embed = self.cog.generate_solo_embed(self.user_id)
            
            self.clear_items()
            new_battle_btn = discord.ui.Button(label="🔄 New Battle", style=discord.ButtonStyle.success)
            async def new_battle_callback(btn_interaction: discord.Interaction):
                if btn_interaction.user.id != self.user_id:
                    return await btn_interaction.response.send_message("❌ This is not your battle!", ephemeral=True)
                await btn_interaction.response.defer()
                await self.cog.start_solo_battle(btn_interaction, self.user_id)
                
            new_battle_btn.callback = new_battle_callback
            self.add_item(new_battle_btn)
            await interaction.edit_original_response(embed=embed, view=self)
            self.cog.active_solo_battles.pop(self.user_id, None)
            return

        # ==========================================
        # 4. XỬ LÝ LƯỢT BOSS + SPEED EXTRA TURN
        # ==========================================
        is_boss_attacking = True

        # 🟢 CƠ CHẾ ĐI THÊM LƯỢT (SPEED)
        # Công thức: Tốc độ càng cao, % được thêm lượt càng lớn (Max 40%)
        extra_turn_chance = min(player_speed / 1000.0, 0.4) 
        if random.random() < extra_turn_chance:
            log_msgs.append(f"⚡ **EXTRA TURN!** **{digimon['name']}** is too fast (Speed: {player_speed}) and takes another action!")
            is_boss_attacking = False  # Boss bị mất lượt vì tốc độ của bạn quá nhanh

        # Boss Hồi máu
        boss_max_hp = battle.get("boss_max_hp", battle["boss_hp"] * 4)
        if (battle["boss_hp"] < (boss_max_hp * 0.4) and random.random() < 0.20 and not battle.get("boss_heal_used", False)):
            if is_boss_attacking: # Chỉ hồi máu nếu Boss không bị mất lượt bởi Speed
                boss_heal_amt = int(boss_max_hp * 0.1)
                battle["boss_hp"] = min(boss_max_hp, battle["boss_hp"] + boss_heal_amt)
                battle["boss_heal_used"] = True 
                log_msgs.append(f"💚 **BOSS RECOVERY:** **{battle['boss_name']}** recovers **{boss_heal_amt:,} HP**!")
                is_boss_attacking = False 

        # Boss Tấn công
        if is_boss_attacking:
            boss_raw_dmg = battle["boss_atk"] + random.randint(-5, 15)
            boss_attr_mult = self.cog.get_attribute_multiplier(battle["boss_attr"], digimon["attr"])
            
            boss_skills = {
                "Vaccine": {"name": "LIGHT OF JUDGMENT", "mult": 1.4},
                "Virus": {"name": "DARKNESS CORRUPTION", "mult": 1.4},
                "Data": {"name": "DATA RESTRUCTING", "mult": 1.4}
            }
            
            if random.random() < 0.25:
                skill = boss_skills.get(battle["boss_attr"], {"name": "Powerful Strike", "mult": 1.4})
                boss_raw_dmg = int(boss_raw_dmg * skill["mult"])
                log_msgs.append(f"⚠️ **BOSS SKILL:** {battle['boss_name']} ACTIVATES **[{skill['name']}]**!")
                if random.random() < 0.40 and not is_protecting:
                    effect = random.choice(["stun", "blind"])
                    battle["player_debuff"] = effect
                    battle["debuff_duration"] = 1 
                    eff_log = "STUNNED (Skip next turn)" if effect == "stun" else "BLINDED (Accuracy reduced)"
                    log_msgs.append(f"🌀 **DEBUFF INFLICTED:** Your Digimon is **{eff_log}**!")

            player_def_mult = 100 / (100 + player_def)
            boss_final_dmg = int(boss_raw_dmg * boss_attr_mult * player_def_mult)

            if is_protecting:
                boss_final_dmg = int(boss_final_dmg * 0.20)
                log_msgs.append(f"🛡️ SUCCESSFUL BLOCK! YOU ONLY TAKE **{boss_final_dmg:,} DMG**.")
            else:
                log_msgs.append(f"💥 {battle['boss_name']} COUNTER ATTACKS, DEALING **{boss_final_dmg:,} DMG**.")

            battle["player_hp"] = max(0, battle["player_hp"] - boss_final_dmg)

        # Kiểm tra nếu người chơi chết
        if battle["player_hp"] <= 0:
            battle["log"] = "\n".join(log_msgs) + f"\n\n☠️ **DEFEAT!** You have been defeated by {battle['boss_name']}..."
            embed = self.cog.generate_solo_embed(self.user_id)
            
            self.clear_items()
            new_battle_btn = discord.ui.Button(label="🔄 Try Again", style=discord.ButtonStyle.primary)
            async def new_battle_callback(btn_interaction: discord.Interaction):
                if btn_interaction.user.id != self.user_id:
                    return await btn_interaction.response.send_message("❌ This is not your battle!", ephemeral=True)
                await btn_interaction.response.defer()
                await self.cog.start_solo_battle(btn_interaction, self.user_id)
                
            new_battle_btn.callback = new_battle_callback
            self.add_item(new_battle_btn)
            await interaction.edit_original_response(embed=embed, view=self)
            self.cog.active_solo_battles.pop(self.user_id, None)
            return

        # ==========================================
        # 5. KẾT THÚC LƯỢT
        # ==========================================
        battle["turn"] += 1
        battle["log"] = "\n".join(log_msgs)
        
        self.update_button_states()
        embed = self.cog.generate_solo_embed(self.user_id)
        await interaction.edit_original_response(embed=embed, view=self)

    # ==========================================
    # CÁC NÚT BẤM VỚI CƠ CHẾ DEFER MỚI CỰC KỲ AN TOÀN
    # ==========================================
    @discord.ui.button(label="⚔️ ATTACK", style=discord.ButtonStyle.danger, row=0)
    async def attack_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.action_locked: return  # Chặn spam 2 lần
        self.action_locked = True
        await interaction.response.defer() # 🟢 Trả lời Discord ngay lập tức để không bị lỗi Timeout
        try:
            await self.process_turn(interaction, "attack")
        finally:
            self.action_locked = False

    @discord.ui.button(label="🛡️ DEFEND", style=discord.ButtonStyle.primary, row=0)
    async def defend_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.action_locked: return
        self.action_locked = True
        await interaction.response.defer()
        try:
            await self.process_turn(interaction, "defend")
        finally:
            self.action_locked = False

    @discord.ui.button(label="🧪 RECOVERY", style=discord.ButtonStyle.success, row=0)
    async def heal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.action_locked: return
        self.action_locked = True
        await interaction.response.defer()
        try:
            await self.process_turn(interaction, "heal")
        finally:
            self.action_locked = False
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
            "Psychemon": {"attr": "Data", "atk": 70, "hp": 1100, "vip": False, "img": "https://digimon.net/cimages/digimon/psychemon.jpg"},
            "Impmon": {"attr": "Virus", "atk": 85, "hp": 1050, "vip": False, "img": "https://digimon.net/cimages/digimon/impmon.jpg"},
            "Sistermon Blanc": {"attr": "Vaccine", "atk": 65, "hp": 1250, "vip": False, "img": "https://digimon.net/cimages/digimon/sistermon_blanc.jpg"},
            "Renamon": {"attr": "Data", "atk": 70, "hp": 1150, "vip": False, "img": "https://digimon.net/cimages/digimon/renamon.jpg"},
            "Terriermon": {"attr": "Vaccine", "atk": 55, "hp": 1280, "vip": False, "img": "https://digimon.net/cimages/digimon/terriermon.jpg"},
            "Lopmon": {"attr": "Data", "atk": 60, "hp": 1200, "vip": False, "img": "https://digimon.net/cimages/digimon/lopmon.jpg"},
            "Hagurumon": {"attr": "Virus", "atk": 50, "hp": 1300, "vip": False, "img": "https://digimon.net/cimages/digimon/hagurumon.jpg"},
            "Biyomon": {"attr": "Vaccine", "atk": 65, "hp": 1150, "vip": False, "img": "https://digimon.net/cimages/digimon/piyomon.jpg"},
            "Keramon": {"attr": "Virus", "atk": 80, "hp": 1050, "vip": False, "img": "https://digimon.net/cimages/digimon/keramon.jpg"},
            "Dorumon": {"attr": "Data", "atk": 75, "hp": 1200, "vip": False, "img": "https://digimon.net/cimages/digimon/dorumon.jpg"},
            "Muchomon": {"attr": "Data", "atk": 180, "hp": 1400, "img": "https://digimon.net/cimages/digimon/muchomon.jpg"},
        "Syakomon": {"attr": "Virus", "atk": 160, "hp": 1500, "img": "https://digimon.net/cimages/digimon/syakomon.jpg"},
        "Tsukaimon": {"attr": "Virus", "atk": 190, "hp": 1200, "img": "https://digimon.net/cimages/digimon/tsukaimon.jpg"},
        "Otamamon": {"attr": "Virus", "atk": 140, "hp": 1600, "img": "https://digimon.net/cimages/digimon/otamamon.jpg"},
        "Kunemon": {"attr": "Virus", "atk": 170, "hp": 1300, "img": "https://digimon.net/cimages/digimon/kunemon.jpg"},
        "Tinkermon": {"attr": "Virus", "atk": 150, "hp": 1100, "img": "https://digimon.net/cimages/digimon/tinkermon.jpg"},
        "Zubamon": {"attr": "Vaccine", "atk": 210, "hp": 1400, "img": "https://digimon.net/cimages/digimon/zubamon.jpg"},
        "Ludomon": {"attr": "Data", "atk": 130, "hp": 1800, "img": "https://digimon.net/cimages/digimon/ludomon.jpg"},
        "Hackmon": {"attr": "Data", "atk": 220, "hp": 1500, "img": "https://digimon.net/cimages/digimon/hackmon.jpg"},
        "Coronamon": {"attr": "Vaccine", "atk": 200, "hp": 1400, "img": "https://digimon.net/cimages/digimon/coronamon.jpg"},
        "Lunamon": {"attr": "Data", "atk": 190, "hp": 1500, "img": "https://digimon.net/cimages/digimon/lunamon.jpg"},
        "Liollmon": {"attr": "Vaccine", "atk": 200, "hp": 1300, "img": "https://digimon.net/cimages/digimon/liollmon.jpg"},
        "Dracmon": {"attr": "Virus", "atk": 180, "hp": 1200, "img": "https://digimon.net/cimages/digimon/dracmon.jpg"},
        "Penguinmon": {"attr": "Vaccine", "atk": 150, "hp": 1600, "img": "https://digimon.net/cimages/digimon/penguinmon.jpg"},
        "Mushmon": {"attr": "Virus", "atk": 160, "hp": 1500, "img": "https://digimon.net/cimages/digimon/mushmon.jpg"},
        "Tapirmon": {"attr": "Vaccine", "atk": 140, "hp": 1400, "img": "https://digimon.net/cimages/digimon/bakumon.jpg"},
        "Candlemon": {"attr": "Data", "atk": 170, "hp": 1100, "img": "https://digimon.net/cimages/digimon/candmon.jpg"},
        "Gizamon": {"attr": "Virus", "atk": 190, "hp": 1200, "img": "https://digimon.net/cimages/digimon/gizamon.jpg"},
        "Chuumon": {"attr": "Virus", "atk": 120, "hp": 1800, "img": "https://digimon.net/cimages/digimon/tyumon.jpg"}
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
            "Gururumon": {"attr": "Vaccine", "atk": 190, "hp": 3000, "img": "https://digimon.net/cimages/digimon/gururumon.jpg"},
            "Witchmon": {"attr": "Data", "atk": 230, "hp": 2600, "img": "https://digimon.net/cimages/digimon/witchmon.jpg"},
            "Sistermon Noir": {"attr": "Virus", "atk": 190, "hp": 2900, "img": "https://digimon.net/cimages/digimon/sistermon_noir.jpg"},
            "Kyubimon": {"attr": "Data", "atk": 185, "hp": 3050, "img": "https://digimon.net/cimages/digimon/kyubimon.jpg"},
            "Gargomon": {"attr": "Vaccine", "atk": 175, "hp": 3250, "img": "https://digimon.net/cimages/digimon/galgomon.jpg"},
            "Wendigomon": {"attr": "Virus", "atk": 200, "hp": 2800, "img": "https://digimon.net/cimages/digimon/wendimon.jpg"},
            "Guardromon": {"attr": "Virus", "atk": 165, "hp": 3300, "img": "https://digimon.net/cimages/digimon/guardromon.jpg"},
            "Birdramon": {"attr": "Vaccine", "atk": 180, "hp": 2950, "img": "https://digimon.net/cimages/digimon/birdramon.jpg"},
            "Chrysalimon": {"attr": "Virus", "atk": 240, "hp": 2550, "img": "https://digimon.net/cimages/digimon/chrysalimon.jpg"},
            "Dorugamon": {"attr": "Data", "atk": 210, "hp": 3100, "img": "https://digimon.net/cimages/digimon/dorugamon.jpg"},
            "Diatrymon": {"attr": "Data", "atk": 380, "hp": 3800, "img": "https://digimon.net/cimages/digimon/diatrymon.jpg"},
        "Octomon": {"attr": "Virus", "atk": 350, "hp": 4000, "img": "https://digimon.net/cimages/digimon/octmon.jpg"},
        "Devidramon": {"attr": "Virus", "atk": 420, "hp": 3500, "img": "https://digimon.net/cimages/digimon/devidramon.jpg"},
        "Gekomon": {"attr": "Virus", "atk": 320, "hp": 4200, "img": "https://digimon.net/cimages/digimon/gekomon.jpg"},
        "Flymon": {"attr": "Virus", "atk": 390, "hp": 3600, "img": "https://digimon.net/cimages/digimon/flymon.jpg"},
        "Kinkakumon": {"attr": "Virus", "atk": 400, "hp": 3800, "img": "https://digimon.net/cimages/digimon/kinkakumon.jpg"},
        "Zubaeagermon": {"attr": "Vaccine", "atk": 450, "hp": 4100, "img": "https://digimon.net/cimages/digimon/zubaeagermon.jpg"},
        "TiaLudomon": {"attr": "Data", "atk": 310, "hp": 5000, "img": "https://digimon.net/cimages/digimon/tialudomon.jpg"},
        "BaoHuckmon": {"attr": "Data", "atk": 440, "hp": 4200, "img": "https://digimon.net/cimages/digimon/baohuckmon.jpg"},
        "Firamon": {"attr": "Vaccine", "atk": 430, "hp": 4000, "img": "https://digimon.net/cimages/digimon/firamon.jpg"},
        "Lekismon": {"attr": "Data", "atk": 410, "hp": 4200, "img": "https://digimon.net/cimages/digimon/lekismon.jpg"},
        "Liamon": {"attr": "Vaccine", "atk": 420, "hp": 3900, "img": "https://digimon.net/cimages/digimon/liamon.jpg"},
        "Sangloupmon": {"attr": "Virus", "atk": 400, "hp": 3400, "img": "https://digimon.net/cimages/digimon/sangloupmon.jpg"},
        "Dolphmon": {"attr": "Vaccine", "atk": 340, "hp": 4500, "img": "https://digimon.net/cimages/digimon/irukamon.jpg"},
        "Woodmon": {"attr": "Virus", "atk": 370, "hp": 4200, "img": "https://digimon.net/cimages/digimon/jyureimon.jpg"},
        "Unimon": {"attr": "Vaccine", "atk": 380, "hp": 3800, "img": "https://digimon.net/cimages/digimon/unimon.jpg"},
        "Wizardmon": {"attr": "Data", "atk": 410, "hp": 3500, "img": "https://digimon.net/cimages/digimon/wizarmon.jpg"},
        "Cyclonemon": {"attr": "Virus", "atk": 420, "hp": 3600, "img": "https://digimon.net/cimages/digimon/cyclomon.jpg"},
        "Scumon": {"attr": "Virus", "atk": 250, "hp": 5500, "img": "https://digimon.net/cimages/digimon/scumon.jpg"}
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
            "Astamon": {"attr": "Virus", "atk": 480, "hp": 7200, "img": "https://digimon.net/cimages/digimon/astamon.jpg"},
            "LadyDevimon": {"attr": "Virus", "atk": 490, "hp": 6900, "img": "https://digimon.net/cimages/digimon/ladydevimon.jpg"},
            "Sistermon Ciel": {"attr": "Data", "atk": 450, "hp": 7500, "img": "https://digimon.net/cimages/digimon/sistermon_ciel.jpg"},
            "Taomon": {"attr": "Data", "atk": 440, "hp": 7600, "img": "https://digimon.net/cimages/digimon/taomon.jpg"},
            "Rapidmon": {"attr": "Vaccine", "atk": 430, "hp": 7900, "img": "https://digimon.net/cimages/digimon/rapidmon.jpg"},
            "Antylamon": {"attr": "Virus", "atk": 470, "hp": 7300, "img": "https://digimon.net/cimages/digimon/andiramon.jpg"},
            "Andromon": {"attr": "Vaccine", "atk": 420, "hp": 8000, "img": "https://digimon.net/cimages/digimon/andromon.jpg"},
            "Garudamon": {"attr": "Vaccine", "atk": 460, "hp": 7400, "img": "https://digimon.net/cimages/digimon/garudamon.jpg"},
            "Infermon": {"attr": "Virus", "atk": 550, "hp": 6600, "img": "https://digimon.net/cimages/digimon/infermon.jpg"},
            "DoruGreymon": {"attr": "Data", "atk": 480, "hp": 7700, "img": "https://digimon.net/cimages/digimon/dorugremon.jpg"},
            "Sinduramon": {"attr": "Data", "atk": 680, "hp": 8500, "img": "https://digimon.net/cimages/digimon/sinduramon.jpg"},
        "Dragomon": {"attr": "Virus", "atk": 700, "hp": 8800, "img": "https://digimon.net/cimages/digimon/dagomon.jpg"},
        "Gigadramon": {"attr": "Virus", "atk": 750, "hp": 9000, "img": "https://digimon.net/cimages/digimon/gigadramon.jpg"},
        "ShogunGekomon": {"attr": "Virus", "atk": 620, "hp": 9200, "img": "https://digimon.net/cimages/digimon/tonosamagekomon.jpg"},
        "Dinobeemon": {"attr": "Virus", "atk": 720, "hp": 8500, "img": "https://digimon.net/cimages/digimon/dinobeemon.jpg"},
        "Cho-Hakkaimon": {"attr": "Data", "atk": 650, "hp": 8900, "img": "https://digimon.net/cimages/digimon/cho-hakkaimon.jpg"},
        "Duramon": {"attr": "Vaccine", "atk": 780, "hp": 9200, "img": "https://digimon.net/cimages/digimon/duramon.jpg"},
        "RaijiLudomon": {"attr": "Data", "atk": 580, "hp": 11000, "img": "https://digimon.net/cimages/digimon/raijiludomon.jpg"},
        "SaviorHuckmon": {"attr": "Data", "atk": 760, "hp": 9500, "img": "https://digimon.net/cimages/digimon/saviorhuckmon.jpg"},
        "Flaremon": {"attr": "Vaccine", "atk": 740, "hp": 9000, "img": "https://digimon.net/cimages/digimon/flaremon.jpg"},
        "Crescemon": {"attr": "Data", "atk": 710, "hp": 9200, "img": "https://digimon.net/cimages/digimon/crescemon.jpg"},
        "Panjyamon": {"attr": "Vaccine", "atk": 730, "hp": 8800, "img": "https://digimon.net/cimages/digimon/panjyamon.jpg"},
        "Matadormon": {"attr": "Virus", "atk": 680, "hp": 8800, "img": "https://digimon.net/cimages/digimon/matadrmon.jpg"},
        "Whamon": {"attr": "Vaccine", "atk": 600, "hp": 10500, "img": "https://digimon.net/cimages/digimon/whamon_perfect.jpg"},
        "Cherrymon": {"attr": "Virus", "atk": 640, "hp": 9500, "img": "https://digimon.net/cimages/digimon/jyureimon.jpg"},
        "Piximon": {"attr": "Data", "atk": 650, "hp": 8600, "img": "https://digimon.net/cimages/digimon/piccolomon.jpg"},
        "Mistymon": {"attr": "Data", "atk": 700, "hp": 8500, "img": "https://digimon.net/cimages/digimon/mistymon.jpg"},
        "Megadramon": {"attr": "Virus", "atk": 720, "hp": 9000, "img": "https://digimon.net/cimages/digimon/megadramon.jpg"},
        "Garbagemon": {"attr": "Virus", "atk": 500, "hp": 12000, "img": "https://digimon.net/cimages/digimon/garbamon.jpg"}
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
            "Mekurimon": {"attr": "Virus", "atk": 1400, "hp": 16000, "img": "https://digimon.net/cimages/digimon/mercurymon.jpg", "skill": {"name": "Spark", "dmg_mult": 2.9, "chance": 0.15}},
            "BeelStarmon": {"attr": "Virus", "atk": 1450, "hp": 16000, "img": "https://digimon.net/cimages/digimon/beelstarmon.jpg", "skill": {"name": "Fly Bullet", "dmg_mult": 3.0, "chance": 0.15}},
            "Sistermon Noir (Awaken)": {"attr": "Virus", "atk": 1350, "hp": 18000, "img": "https://digimon.net/cimages/digimon/sistermon_noir_awaken.jpg", "skill": {"name": "Mickey Bullet", "dmg_mult": 2.8, "chance": 0.2}},
            "Sakuyamon": {"attr": "Data", "atk": 1200, "hp": 20500, "img": "https://digimon.net/cimages/digimon/sakuyamon.jpg", "skill": {"name": "Amethyst Mandala", "dmg_mult": 2.5, "chance": 0.2}},
            "MegaGargomon": {"attr": "Vaccine", "atk": 1150, "hp": 22000, "img": "https://digimon.net/cimages/digimon/saintgalgomon.jpg", "skill": {"name": "Giant Bazooka", "dmg_mult": 2.4, "chance": 0.25}},
            "Cherubimon": {"attr": "Virus", "atk": 1300, "hp": 18500, "img": "https://digimon.net/cimages/digimon/cherubimon_vice.jpg", "skill": {"name": "Lightning Spear", "dmg_mult": 2.7, "chance": 0.18}},
            "HiAndromon": {"attr": "Vaccine", "atk": 1100, "hp": 23000, "img": "https://digimon.net/cimages/digimon/hiandromon.jpg", "skill": {"name": "Atomic Ray", "dmg_mult": 2.2, "chance": 0.3}},
            "Hououmon": {"attr": "Vaccine", "atk": 1250, "hp": 19500, "img": "https://digimon.net/cimages/digimon/hououmon.jpg", "skill": {"name": "Starlight Explosion", "dmg_mult": 2.6, "chance": 0.2}},
            "Diaboromon": {"attr": "Virus", "atk": 1480, "hp": 15500, "img": "https://digimon.net/cimages/digimon/diablomon.jpg", "skill": {"name": "Catastrophe Cannon", "dmg_mult": 3.1, "chance": 0.12}},
            "Alphamon": {"attr": "Vaccine", "atk": 1400, "hp": 21000, "img": "https://digimon.net/cimages/digimon/alphamon.jpg", "skill": {"name": "Digitalize of Soul", "dmg_mult": 3.0, "chance": 0.15}},
            "Zhuqiaomon": {"attr": "Virus", "atk": 1350, "hp": 19000, "img": "https://digimon.net/cimages/digimon/zhuqiaomon.jpg", "skill": {"name": "Crimson Blaze", "dmg_mult": 2.8, "chance": 0.15}},
            "Neptunemon": {"attr": "Vaccine", "atk": 1250, "hp": 21000, "img": "https://digimon.net/cimages/digimon/neptunemon.jpg", "skill": {"name": "Vortex Penetrate", "dmg_mult": 2.6, "chance": 0.2}},
            "Megidramon": {"attr": "Virus", "atk": 1450, "hp": 19500, "img": "https://digimon.net/cimages/digimon/megidramon.jpg", "skill": {"name": "Megiddo Flame", "dmg_mult": 3.0, "chance": 0.15}},
            "Plesiomon": {"attr": "Data", "atk": 1100, "hp": 24000, "img": "https://digimon.net/cimages/digimon/plesiomon.jpg", "skill": {"name": "Sorrow Blue", "dmg_mult": 2.3, "chance": 0.25}},
            "TyrantKabuterimon": {"attr": "Virus", "atk": 1280, "hp": 21500, "img": "https://digimon.net/cimages/digimon/tyrantkabuterimon.jpg", "skill": {"name": "Shine of Bee", "dmg_mult": 2.7, "chance": 0.18}},
            "Venusmon": {"attr": "Vaccine", "atk": 1050, "hp": 23000, "img": "https://digimon.net/cimages/digimon/venusmon.jpg", "skill": {"name": "Healing Therapy", "dmg_mult": 2.1, "chance": 0.3}},
            "Durandamon": {"attr": "Vaccine", "atk": 1400, "hp": 18000, "img": "https://digimon.net/cimages/digimon/durandamon.jpg", "skill": {"name": "Zweihander", "dmg_mult": 2.9, "chance": 0.18}},
            "BryweLudramon": {"attr": "Data", "atk": 950, "hp": 28000, "img": "https://digimon.net/cimages/digimon/bryweludramon.jpg", "skill": {"name": "Guren Shield", "dmg_mult": 2.0, "chance": 0.35}},
            "Jesmon": {"attr": "Data", "atk": 1380, "hp": 20000, "img": "https://digimon.net/cimages/digimon/jesmon.jpg", "skill": {"name": "Judgement of the Blade", "dmg_mult": 2.8, "chance": 0.2}},
            "Apollomon": {"attr": "Vaccine", "atk": 1300, "hp": 19000, "img": "https://digimon.net/cimages/digimon/apollomon.jpg", "skill": {"name": "Sol Blaster", "dmg_mult": 2.7, "chance": 0.2}},
            "Dianamon": {"attr": "Data", "atk": 1250, "hp": 19500, "img": "https://digimon.net/cimages/digimon/dianamon.jpg", "skill": {"name": "Crescent Harken", "dmg_mult": 2.6, "chance": 0.22}},
            "HeavyLeomon": {"attr": "Data", "atk": 1150, "hp": 25000, "img": "https://digimon.net/cimages/digimon/heavyleomon.jpg", "skill": {"name": "Barrage Sweeper", "dmg_mult": 2.3, "chance": 0.25}},
            "GrandDracumon": {"attr": "Virus", "atk": 1350, "hp": 18500, "img": "https://digimon.net/cimages/digimon/granddracumon.jpg", "skill": {"name": "Crystal Revolution", "dmg_mult": 2.8, "chance": 0.15}},
            "MarineAngemon": {"attr": "Vaccine", "atk": 900, "hp": 26000, "img": "https://digimon.net/cimages/digimon/marinangemon.jpg", "skill": {"name": "Ocean Love", "dmg_mult": 2.0, "chance": 0.3}},
            "Puppetmon": {"attr": "Virus", "atk": 1200, "hp": 19000, "img": "https://digimon.net/cimages/digimon/pinocchimon.jpg", "skill": {"name": "Puppet Pummel", "dmg_mult": 2.5, "chance": 0.2}},
            "Jijimon": {"attr": "Vaccine", "atk": 1100, "hp": 22000, "img": "https://digimon.net/cimages/digimon/jijimon.jpg", "skill": {"name": "Hang on Death", "dmg_mult": 2.4, "chance": 0.2}},
            "Dynasmon": {"attr": "Data", "atk": 1350, "hp": 19500, "img": "https://digimon.net/cimages/digimon/dynasmon.jpg", "skill": {"name": "Dragon's Roar", "dmg_mult": 2.7, "chance": 0.18}},
            "Machinedramon": {"attr": "Virus", "atk": 1280, "hp": 23000, "img": "https://digimon.net/cimages/digimon/mugendramon.jpg", "skill": {"name": "Infinity Cannon", "dmg_mult": 2.6, "chance": 0.2}},
            "PlatinumNumemon": {"attr": "Virus", "atk": 800, "hp": 30000, "img": "https://digimon.net/cimages/digimon/platinum_numemon.jpg", "skill": {"name": "Platinum Junk", "dmg_mult": 1.8, "chance": 0.4}}
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
        "Psychemon": "Gururumon", "Gururumon": "Astamon", "Astamon": "Mekurimon",
        "Impmon": "Witchmon", "Witchmon": "LadyDevimon", "LadyDevimon": "BeelStarmon",
        "Sistermon Blanc": "Sistermon Noir", "Sistermon Noir": "Sistermon Ciel", "Sistermon Ciel": "Sistermon Noir (Awaken)",
        "Renamon": "Kyubimon", "Kyubimon": "Taomon", "Taomon": "Sakuyamon",
        "Terriermon": "Gargomon", "Gargomon": "Rapidmon", "Rapidmon": "MegaGargomon",
        "Lopmon": "Wendigomon", "Wendigomon": "Antylamon", "Antylamon": "Cherubimon",
        "Hagurumon": "Guardromon", "Guardromon": "Andromon", "Andromon": "HiAndromon",
        "Biyomon": "Birdramon", "Birdramon": "Garudamon", "Garudamon": "Hououmon",
        "Keramon": "Chrysalimon", "Chrysalimon": "Infermon", "Infermon": "Diaboromon",
        "Dorumon": "Dorugamon", "Dorugamon": "DoruGreymon", "DoruGreymon": "Alphamon",
        "Muchomon": "Diatrymon", "Diatrymon": "Sinduramon", "Sinduramon": "Zhuqiaomon",
        "Syakomon": "Octomon", "Octomon": "Dragomon", "Dragomon": "Neptunemon",
        "Tsukaimon": "Devidramon", "Devidramon": "Gigadramon", "Gigadramon": "Megidramon",
        "Otamamon": "Gekomon", "Gekomon": "ShogunGekomon", "ShogunGekomon": "Plesiomon",
        "Kunemon": "Flymon", "Flymon": "Dinobeemon", "Dinobeemon": "TyrantKabuterimon",
        "Tinkermon": "Kinkakumon", "Kinkakumon": "Cho-Hakkaimon", "Cho-Hakkaimon": "Venusmon",
        "Zubamon": "Zubaeagermon", "Zubaeagermon": "Duramon", "Duramon": "Durandamon",
        "Ludomon": "TiaLudomon", "TiaLudomon": "RaijiLudomon", "RaijiLudomon": "BryweLudramon",
        "Hackmon": "BaoHuckmon", "BaoHuckmon": "SaviorHuckmon", "SaviorHuckmon": "Jesmon",
        "Coronamon": "Firamon", "Firamon": "Flaremon", "Flaremon": "Apollomon",
        "Lunamon": "Lekismon", "Lekismon": "Crescemon", "Crescemon": "Dianamon",
        "Liollmon": "Liamon", "Liamon": "Panjyamon", "Panjyamon": "HeavyLeomon",
        "Dracmon": "Sangloupmon", "Sangloupmon": "Matadormon", "Matadormon": "GrandDracumon",
        "Penguinmon": "Dolphmon", "Dolphmon": "Whamon", "Whamon": "MarineAngemon",
        "Mushmon": "Woodmon", "Woodmon": "Cherrymon", "Cherrymon": "Puppetmon",
        "Tapirmon": "Unimon", "Unimon": "Piximon", "Piximon": "Jijimon",
        "Candlemon": "Wizardmon", "Wizardmon": "Mistymon", "Mistymon": "Dynasmon",
        "Gizamon": "Cyclonemon", "Cyclonemon": "Megadramon", "Megadramon": "Machinedramon",
        "Chuumon": "Scumon", "Scumon": "Garbagemon", "Garbagemon": "PlatinumNumemon"
    }

    HATCH_CORE_COST = 50
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.initialize_market_mega_products())
        self.active_solo_battles = {}
        self.solo_boss_pool = {
        "Susanoomon": {
            "name": "Susanoomon (Ancient spirit)",
            "attr": "Vaccine",
            "hp_mult": 8.0,
            "atk_mult": 0.10,
            "def_mult": 1.2,
            "image": "https://wikimon.net/images/8/87/Susanoomon.jpg",
            "rewards": {
                "digibits": (1000, 1400),
                "hatch_cores": (150, 180),
                "size_fruits": (3, 3)
            }
        },
        "Megidramon": {
            "name": "Megidramon (Evil dragon)",
            "attr": "Virus",
            "hp_mult": 8.5,
            "atk_mult": 0.12,
            "def_mult": 0.7,
            "image": "https://wikimon.net/images/c/cd/Megidramon.jpg",
            "rewards": {
                "digibits": (1000, 1400),
                "hatch_cores": (150, 180),
                "size_fruits": (3, 4)
            }
        },
        "metalgarurumon_boss": {
            "name": "MetalGarurumon (Blizzard Zone)",
            "attr": "Data",
            "hp_mult": 9.2,
            "atk_mult": 0.13,
            "def_mult": 1,
            "image": "https://wikimon.net/images/7/77/Metalgarurumon.jpg",
            "rewards": {
                "digibits": (1000, 1400),
                "hatch_cores": (150, 180),
                "size_fruits": (3, 4)
            }
        },
        "wargreymon_boss": {
            "name": "WarGreymon (Dragon Combatant)",
            "attr": "Vaccine",
            "hp_mult": 10.8,
            "atk_mult": 0.11,
            "def_mult": 0.9,
            "image": "https://wikimon.net/images/c/c8/Wargreymon.jpg",
            "rewards": {
                "digibits": (1000, 1400),
                "hatch_cores": (150, 180),
                "size_fruits": (3, 4)
            }
        },
        "Jexmon GX": {
            "name": "Jesmon GX (Savior of digital world)",
            "attr": "Data",
            "hp_mult": 10.6,
            "atk_mult": 0.14,
            "def_mult": 0.7,
            "image": "https://wikimon.net/images/6/62/Jesmon_gx.jpg",
            "rewards": {
                "digibits": (1000, 1400),
                "hatch_cores": (150, 180),
                "size_fruits": (4, 4)
            }
        },
        "Dianamon": {
            "name": "Dianamon (Omlympos XII)",
            "attr": "Data",
            "hp_mult": 10.4,
            "atk_mult": 0.15,
            "def_mult": 1,
            "image": "https://wikimon.net/images/3/36/Dianamon.jpg",
            "rewards": {
                "digibits": (1000, 1400),
                "hatch_cores": (170, 200),
                "size_fruits": (4, 5)
            }
        },
        "Beelzemon": {
            "name": "Beelzemon Blast Mode (Glutony)",
            "attr": "Virus",
            "hp_mult": 8.0,
            "atk_mult": 0.16,
            "def_mult": 0.7,
            "image": "https://wikimon.net/images/c/c3/Beelzebumon_blast.jpg",
            "rewards": {
                "digibits": (1000, 1500),
                "hatch_cores": (180, 220),
                "size_fruits": (4, 5)
            }
        },
        "Bagramon": {
            "name": "Bagramon (Sage of Death)",
            "attr": "Virus",
            "hp_mult": 10.5,
            "atk_mult": 0.12,
            "def_mult": 1.2,
            "image": "https://wikimon.net/images/0/0f/Bagramon.jpg",
            "rewards": {
                "digibits": (1150, 1600),
                "hatch_cores": (190, 230),
                "size_fruits": (4, 5)
            }
        },
        "Gracenovamon": {
            "name": "Gracenovamon (Galaxy God)",
            "attr": "Vaccine",
            "hp_mult": 10.0,
            "atk_mult": 0.13,
            "def_mult": 0.9,
            "image": "https://wikimon.net/images/3/34/Gracenovamon.jpg",
            "rewards": {
                "digibits": (1300, 1800),
                "hatch_cores": (200, 250),
                "size_fruits": (7, 7)
            }
        },
        "Zeed Milleniummon": {
            "name": "Zeed Milleniummon (Dimension Destroyer)",
            "attr": "Virus",
            "hp_mult": 12,
            "atk_mult": 0.14,
            "def_mult": 1,
            "image": "https://wikimon.net/images/8/86/Zeedmillenniumon.jpg",
            "rewards": {
                "digibits": (2100, 2500),
                "hatch_cores": (300, 500),
                "size_fruits": (10, 10)
            }
        }
    }


        

    # ========================================================================
    #                       HELPER METHODS
    # ========================================================================
    # WORLD BOSS
    #==============================================

    @app_commands.command(name="spawn_boss", description="[Admin] Force spawn a World Boss")
    async def spawn_boss(self, interaction: discord.Interaction, name: str, hp: int):
        if not interaction.user.guild_permissions.administrator: 
            return await interaction.response.send_message("❌ Admin privileges required.", ephemeral=True)

        await world_boss_col.update_many({"is_active": True, "party_id": {"$exists": False}}, {"$set": {"is_active": False}})

        new_boss = {
            "boss_id": str(uuid.uuid4()), "name": name, "max_hp": hp, "current_hp": hp, "hp": hp, 
            "attr": "Unknown", "img": "", "is_active": True, "damage_log": {}, "active_messages": [], "participants": []
        }
        result = await world_boss_col.insert_one(new_boss)
        new_boss["_id"] = result.inserted_id

        await interaction.response.send_message(f"⚔️ Spawned Boss **{name}**!", ephemeral=True)

    
    def get_attribute_multiplier(self, attacker_attr: str, defender_attr: str) -> float:
        """
        Tính toán hệ số tương khắc thuộc tính giữa Digimon tấn công và mục tiêu:
        Vaccine > Virus > Data > Vaccine
        """
        if not attacker_attr or not defender_attr:
            return 1.0

        # Chuẩn hóa chữ hoa/chữ thường và xóa khoảng trắng thừa để tránh lỗi so khớp
        att = str(attacker_attr).strip().capitalize()
        dfn = str(defender_attr).strip().capitalize()

        # Bảng ma trận khắc chế thuộc tính:
        # Nếu khắc hệ: x1.5 sát thương | Nếu bị khắc hệ: x0.5 sát thương
        matrix = {
            "Vaccine": {"Virus": 1.5, "Data": 0.5},
            "Virus": {"Data": 1.5, "Vaccine": 0.5},
            "Data": {"Vaccine": 1.5, "Virus": 0.5}
        }

        # Nếu tìm thấy cặp thuộc tính tương ứng thì trả về hệ số, ngược lại trả về 1.0 (trung tính)
        return matrix.get(att, {}).get(dfn, 1.0)
   
    @app_commands.command(name="setup_boss_channel", description="Globalchat setting")
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
        # SỬA TẠI ĐÂY: Dùng hàm format_gear_display để bóc tách tên đồ
        embed.add_field(
            name="Equipment", 
            value=f"⚔️ {self.format_gear_display(gear.get('weapon'))}\n"
                  f"🛡️ {self.format_gear_display(gear.get('armor'))}\n"
                  f"📿 {self.format_gear_display(gear.get('vice'))}", 
            inline=False)

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
        available = [name for name, data in self.DIGIMON_DATA["rookie"].items() if not data.get("vip", False) or is_vip]
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

    def clean_item_name(self, item_name):
    # Nếu là dictionary, lấy trường 'name' hoặc giá trị phù hợp
        if isinstance(item_name, dict):
            item_name = item_name.get("name", "Unknown")
        
    # Nếu là chuỗi, thực hiện replace như bình thường
        if isinstance(item_name, str):
            return item_name.replace(" (Unlocked)", "").replace(" (Locked)", "")
        
        return str(item_name) # Trả về chuỗi đại diện nếu là kiểu khác

    def format_gear_display(self, item) -> str:
       # """Hàm định dạng tên hiển thị của trang bị ra Embed tránh lỗi lộ raw dict"""
        if not item or item == "None":
            return "None"
        if isinstance(item, dict):
            name = item.get("name", "Unknown Item")
            rarity = item.get("rarity", "Mythic")
            # Trả về định dạng đẹp: **Omega Artifact Sword** [Mythic]
            return f"**{name}** [{rarity}]"
            
        # Nếu là đồ cũ (dạng Chuỗi chữ thông thường)
        return str(item)
    
    def get_total_stats(self, profile: dict) -> dict:
        digimon = self.get_active_digimon(profile)
        total_hp = digimon.get("hp", 0) + digimon.get("trained_hp", 0)
        total_atk = digimon.get("atk", 0) + digimon.get("trained_atk", 0)
        total_def, total_crit_rate, total_crit_dmg = 10, 0, 1.0

        gear = profile.get("gear", {"weapon": "None", "armor": "None", "vice": "None"})

        # Hàm helper để lấy chỉ số dù là Mythic (phẳng) hay Origin (lồng)
        def get_stats_from_item(item):
            # Nếu là None hoặc chuỗi "None" thì trả về trống
            if not item or item == "None":
                return {}
            
            # Nếu item là String (đồ thường)
            if isinstance(item, str):
                name = self.clean_item_name(item)
                return self.ITEMS.get(name, {})
            
            # Nếu item là Dict (Mythic/Origin)
            if isinstance(item, dict):
                # Ưu tiên lấy từ key "stats", nếu không có thì lấy chính nó (phẳng)
                # Đảm bảo trả về dict rỗng nếu dữ liệu bị lỗi
                return item.get("stats") if "stats" in item else item
                
            return {}

        # --- Xử lý Vũ khí ---
        w_stats = get_stats_from_item(gear.get("weapon"))
        total_atk += float(w_stats.get("atk", 0))

        # --- Xử lý Áo giáp ---
        a_stats = get_stats_from_item(gear.get("armor"))
        total_hp += int(a_stats.get("hp", 0))
        total_def += float(a_stats.get("def", 0))

        # --- Xử lý Vice ---
        v_stats = get_stats_from_item(gear.get("vice"))
        total_crit_rate += float(v_stats.get("crit_rate", 0))
        # Sửa lỗi: Nếu crit_dmg là dạng phần trăm (ví dụ: 12.0 là 12%)
        # Bạn nên quy đổi về hệ số cộng dồn. Ví dụ: 1.0 (base) + 0.12 = 1.12
        crit_dmg_bonus = float(v_stats.get("crit_dmg", 0))
        if crit_dmg_bonus > 1: # Nếu dữ liệu lưu là 12.0 thay vì 0.12
            crit_dmg_bonus /= 100
        total_crit_dmg += crit_dmg_bonus

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
        embed.add_field(
            name="Equipment", 
            value=f"⚔️ {self.format_gear_display(gear.get('weapon'))}\n"
                  f"🛡️ {self.format_gear_display(gear.get('armor'))}\n"
                  f"📿 {self.format_gear_display(gear.get('vice'))}", 
            inline=False
        )
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
            available = [name for name, data in self.DIGIMON_DATA["rookie"].items() if not data.get("vip", False) or is_vip]
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
        embed.add_field(
            name="Equipment", 
            value=f"⚔️ {self.format_gear_display(gear.get('weapon'))}\n"
                  f"🛡️ {self.format_gear_display(gear.get('armor'))}\n"
                  f"📿 {self.format_gear_display(gear.get('vice'))}", 
            inline=False
        )
        await interaction.followup.send(embed=embed, view=ProfileView(profile, self))

    async def handle_hatch_action(self, interaction: discord.Interaction):
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
        available = [name for name, data in self.DIGIMON_DATA["rookie"].items() if not data.get("vip", False) or is_vip]
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
        await interaction.followup.send(f"🥚 Egg hatching successful! Received **{hatched_name}** ({size_pct * 100:.1f}%)", ephemeral=True)
        await self.refresh_profile_message(interaction.message, user_id)

    async def handle_train_action(self, interaction: discord.Interaction, stat: str, multiplier: int = 1, original_msg: discord.Message = None):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        active_digi = self.get_active_digimon(profile)
        if not active_digi: 
            return await interaction.followup.send("❌ Choose a Digimon companion first.", ephemeral=True)
        
        MAX_TRAIN_ATK, MAX_TRAIN_HP = 1000, 5000
        current_train_atk, current_train_hp = active_digi.get("trained_atk", 0), active_digi.get("trained_hp", 0)
        
        # 1. Tính toán chi phí và lượng sức mạnh tăng thêm
        total_cost = 500 * multiplier
        updates = {}
        
        if stat == "atk":
            gain = 20 * multiplier
            if current_train_atk >= MAX_TRAIN_ATK: 
                return await interaction.followup.send("❌ Reached ATK training limit.", ephemeral=True)
            if current_train_atk + gain > MAX_TRAIN_ATK:
                return await interaction.followup.send(f"❌ Cannot train x{multiplier}. It exceeds the {MAX_TRAIN_ATK} ATK limit.", ephemeral=True)
            updates["trained_atk"] = current_train_atk + gain
        else:
            gain = 100 * multiplier
            if current_train_hp >= MAX_TRAIN_HP: 
                return await interaction.followup.send("❌ Reached the HP training limit.", ephemeral=True)
            if current_train_hp + gain > MAX_TRAIN_HP:
                return await interaction.followup.send(f"❌ Cannot train x{multiplier}. It exceeds the {MAX_TRAIN_HP} HP limit.", ephemeral=True)
            updates["trained_hp"] = current_train_hp + gain
            
        # 2. Xử lý trừ tiền và cập nhật Database
        if profile.get("digibit", 0) < total_cost:
            return await interaction.followup.send(f"❌ Insufficient Digibits ({total_cost} Bits required).", ephemeral=True)

        new_list = self.update_active_digimon(profile, updates)
        res = await rpg_profiles_col.update_one(
            {"user_id": user_id, "digibit": {"$gte": total_cost}}, 
            {"$set": {"digimon_list": new_list}, "$inc": {"digibit": -total_cost}}
        )
        if res.modified_count == 0:
            return await interaction.followup.send("❌ Transaction failed.", ephemeral=True)
            
        await interaction.followup.send(f"🏋️ Trained successfully! **+{gain} {stat.upper()}** for {active_digi['name']}.", ephemeral=True)
        
        # 3. Làm mới tin nhắn Profile bên ngoài (Nếu được bấm từ Menu x1/x5 thì dùng original_msg)
        msg_to_refresh = original_msg if original_msg else interaction.message
        try:
            await self.refresh_profile_message(msg_to_refresh, user_id)
        except Exception:
            pass

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

            new_size = round(random.uniform(1.00 if profile.get("is_vip") else 1, 1.30 if profile.get("is_vip") else 1.30), 2)
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

    async def handle_quick_reroll(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        if not profile: return await interaction.followup.send("❌ Character data not found.", ephemeral=True)

        inventory = profile.get("inventory", [])
        
        # 1. Tìm Reroll Fruit trong túi
        found_fruit = None
        for item in inventory:
            if isinstance(item, str) and item == "Size Reroll Fruit":
                found_fruit = item
                break
            elif isinstance(item, dict) and item.get("name") == "Size Reroll Fruit":
                found_fruit = item
                break
                
        if not found_fruit:
            return await interaction.followup.send("❌ You don't have any `Size Reroll Fruit` in your inventory!", ephemeral=True)

        # 2. Xử lý thông số Digimon
        active_digi = self.get_active_digimon(profile)
        if not active_digi:
            return await interaction.followup.send("❌ No Active Digimon.", ephemeral=True)

        old_size = active_digi.get("size", 1.0)
        is_vip = profile.get("is_vip", False)
        
        # 3. Chỉ quay kích thước mới (Bỏ qua hoàn toàn việc tính toán Base Stats)
        new_size = round(random.uniform(1.00 if is_vip else 1, 1.30 if is_vip else 1.30), 2)
        
        inventory.remove(found_fruit)
        
        # Chỉ cập nhật mỗi biến size vào mảng
        updates = {"size": new_size}
        new_list = self.update_active_digimon(profile, updates)

        await rpg_profiles_col.update_one(
            {"user_id": user_id},
            {"$set": {
                "inventory": inventory, 
                "digimon_list": new_list
            }}
        )
        
        trend = "📈 INCREASED" if new_size > old_size else "📉 DECREASED" if new_size < old_size else "UNCHANGED"
        await interaction.followup.send(f"🍎 **Size Reroll Fruit Used!**\n📏 Size: ~~{old_size * 100:.1f}%~~ ➡️ **{new_size * 100:.1f}%** ({trend})", ephemeral=True)
        
        # Làm mới giao diện Profile để hiển thị Size mới
        try:
            await self.refresh_profile_message(interaction.message, user_id)
        except Exception:
            pass
    
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
                "$inc": {"digibit": 5000, "hatch_core": 500},
                "$set": {"last_daily_check": today, "daily_streak": new_streak}
            }
        )
        
        await interaction.followup.send(
            f"🎉 **Attendance check successful.!**\n"
            f"📅 Congratulations on your attendance! **{new_streak}** day!\n"
            f"🎁 Rewards received: **+5,000 Digibits** and **+500 Hatch Cores**!",
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

        TRAIN_COST = 6000
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
            base_hp = int(mega.get("base_hp"))
            base_atk = int(mega.get("base_atk"))
            attr = mega.get("attr", "Unknown")
            img = mega.get("img")
                
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
                upsert=True )
   
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
            return await interaction.followup.send("❌ You don't have enough orb to complete this transaction!", ephemeral=True)
            
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
            success_msg = f"Digimon **{item['item_name']}** has been placed in your Digimon bag!"
        else:
            # Nếu sản phẩm là Trang bị/vật phẩm thường -> Đẩy vào inventory như cũ
            await rpg_profiles_col.update_one(
                {"user_id": buyer_id}, 
                {"$push": {"inventory": item["item_data"]}} 
            )
            success_msg = f"The item **{item['item_name']}** has been moved to your inventory!"
            
        # 5. Xóa vật phẩm khỏi marketplace sau khi giao dịch hoàn tất
        await market_col.delete_one({"listing_id": listing_id})
        
        # =========================================================================
        # [PHẦN THÊM MỚI] 6. Tự động restock (làm mới) hàng hệ thống
        # =========================================================================
        if is_system:
            # Tự động tạo lại món hàng hệ thống vừa bị mua mất
            await self.initialize_market_mega_products()

        # Gửi thông báo mua thành công
        await interaction.followup.send(f"🛍️ **Transaction successful!** {success_msg} (Cost: {price:.0f} orb)", ephemeral=True)

        # =========================================================================
        # [PHẦN THÊM MỚI] 7. Tự động làm mới UI của Chợ ngay lập tức
        # =========================================================================
        try:
            # Lấy lại danh sách hàng hóa mới nhất từ DB
            listings = await market_col.find({}).sort("created_at", -1).to_list(25)
            
            embed = discord.Embed(title="🏪 Digital Marketplace Shop", color=discord.Color.purple())
            if not listings:
                embed.description = "*Market is currently empty. Please check back later.*"
            else:
                desc = ""
                for itm in listings:
                    type_tag = "🧬 [DIGIMON]" if itm.get("listing_type") == "digimon" else "⚔️ [EQUIP]"
                    desc += f"{type_tag} **{itm['item_name']}**\n🆔 ID: `{itm['listing_id']}` | 💰 **{itm['price']:.2f} orb** | 👤 Seller: {itm['seller_name']}\n\n"
                embed.description = desc[:4000]

            # Chỉnh sửa (edit) lại tin nhắn Chợ ban đầu để update Menu và Embed mới
            await interaction.edit_original_response(embed=embed, view=MarketShopView(listings, self))
        except discord.errors.HTTPException:
            # Bỏ qua nếu có lỗi không thể edit tin nhắn cũ (ví dụ tin nhắn quá thời hạn)
            pass

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

#============================================================================
#                            SOLO DG
#============================================================================ 

    async def start_solo_battle(self, interaction: discord.Interaction, user_id: int):
        """Hàm dùng chung để khởi tạo trận Solo Boss"""
        # Xóa trận cũ trong bộ nhớ nếu có (để dọn đường cho trận mới)
        self.active_solo_battles.pop(user_id, None)

        player = await rpg_profiles_col.find_one({"user_id": user_id})
        digimon = self.get_active_digimon(player)
        
        if not player or not digimon:
            # 🟢 Sửa lại thông báo lỗi công khai
            return await interaction.followup.send("❌ You do not have an RPG profile or partner Digimon set.", ephemeral=True)
        if player.get("current_hp", 0) <= 0:
            return await interaction.edit_original_response(content="☠️ Your Digimon is exhausted. Please heal before entering the battle.", embed=None, view=None)

        stats = self.get_total_stats(player)
        player_max_hp = player.get("max_hp", 3000)

        # 🎲 Bốc ngẫu nhiên Boss từ bể
        boss_id = random.choice(list(self.solo_boss_pool.keys()))
        boss_template = self.solo_boss_pool[boss_id]

        boss_max_hp = int(player_max_hp * boss_template["hp_mult"])
        boss_atk = int(stats["atk"] * boss_template["atk_mult"])
        # 🛡️ Tính toán Giáp (DEF) của Boss
        player_def = stats.get("def", 50) # Mặc định là 50 nếu profile chưa có chỉ số def
        boss_def = int(player_def * boss_template.get("def_mult", 1.0))
        
        self.active_solo_battles[user_id] = {
            "player_hp": player_max_hp,
            "player_max_hp": player_max_hp,
            "boss_name": boss_template["name"],
            "boss_hp": boss_max_hp,
            "boss_max_hp": boss_max_hp,
            "boss_atk": boss_atk,
            "boss_attr": boss_template["attr"],
            "heal_cd": 0,
            "defend_cd": 0,
            "boss_def": boss_def,
            "boss_image": boss_template.get("image", ""), # 🖼️ LƯU ẢNH BOSS VÀO ĐÂY
            "boss_heal_used": False,
            "player_debuff": None,   # 🔥 Trạng thái hiện tại (stun/blind)
            "debuff_duration": 0,
            "turn": 1,
            "log": "The battle has begun! Good luck.",
            "rewards_config": boss_template["rewards"] 
        }
        
        view = SoloCombatView(self, user_id)
        embed = self.generate_solo_embed(user_id)
        
        # Cập nhật tin nhắn hiện tại thành trận đấu mới
        # Cập nhật tin nhắn hiện tại thành trận đấu mới
        try:
            msg = await interaction.edit_original_response(content=None, embed=embed, view=view)
            view.message = msg  # 🟢 LƯU LẠI MESSAGE VÀO VIEW
        except discord.errors.NotFound:
            msg = await interaction.followup.send(embed=embed, view=view)
            view.message = msg  # 🟢 LƯU LẠI MESSAGE VÀO VIEW
    def generate_solo_embed(self, user_id: int) -> discord.Embed:
        battle = self.active_solo_battles[user_id]
    
    # Tính toán thanh máu % cho Player và Boss
        p_percent = max(0.0, min(1.0, battle["player_hp"] / battle["player_max_hp"]))
        b_percent = max(0.0, min(1.0, battle["boss_hp"] / battle["boss_max_hp"]))
        
        p_bar = "🟩" * int(p_percent * 10) + "⬛" * (10 - int(p_percent * 10))
        b_bar = "🟥" * int(b_percent * 10) + "⬛" * (10 - int(b_percent * 10))
        
        embed = discord.Embed(
            title=f"🏟️ SOLO ARENA - TURN {battle['turn']}",
            description="🟢 **YOUR TURN!** Please choose an action below.",
            color=discord.Color.dark_red()
        )
        
        # 🖼️ HIỂN THỊ HÌNH ẢNH CỦA BOSS LÊN GÓC PHẢI GIAO DIỆN
        if battle.get("boss_image"):
            embed.set_thumbnail(url=battle["boss_image"])
        if battle["player_hp"] <= 0 or battle["boss_hp"] <= 0:
            embed.description = "🏁 **BATTLE ENDED**"
        embed.add_field(
            name=f"👤 You (HP: {battle['player_hp']:,} / {battle['player_max_hp']:,})",
            value=f"{p_bar} ({p_percent * 100:.1f}%)",
            inline=False
        )
        
        embed.add_field(
            name=f"😈 BOSS: {battle['boss_name']} [{battle['boss_attr']}] (HP: {battle['boss_hp']:,} / {battle['boss_max_hp']:,})",
            value=f"{b_bar} ({b_percent * 100:.1f}%)",
            inline=False
        )
        
        embed.add_field(
            name="📜 Battle logs", 
            value=f"```md\n{battle['log']}```", 
            inline=False
        )
        
        embed.set_footer(text="Think carefully before choosing your next action.!")
        return embed

    @app_commands.command(name="solo_dungeon", description="Challenger with Turn-base mode")
    async def solo_boss(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_id = interaction.user.id
        
        # 🟢 Xử lý chống kẹt (Soft-lock): 
        # Nếu họ đang có trận đang dở mà gõ lại lệnh, tự động dọn dẹp trận cũ thay vì chặn
        if user_id in self.active_solo_battles:
            self.active_solo_battles.pop(user_id, None)
            
        # Gọi hàm tạo trận mới
        await self.start_solo_battle(interaction, user_id)
#==================================================================
#                              WORLD BOSS
#==================================================================

# ========================================================================
# CẤU HÌNH BỂ TƯỚNG OLYMPOS XII & TRANG BỊ ORIGIN
# ========================================================================
OLYMPOS_XII = [
    "Jupitermon", "Junomon", "Neptunemon", "Ceresmon", "Apollomon", 
    "Dianamon", "Vulcanusmon", "Marsmon", "Minervamon", "Mercurymon", 
    "Venusmon", "Bacchusmon"]

OORIGIN_GEAR_TEMPLATES = {
    "weapon": {
        "name": "Origin Eternal Judgement (Weapon)",
        "tier": "Origin",
        "type": "weapon",
        "stats": {"atk": 1200, "def": 0, "hp": 1000},
        "description": "The low chance causes a small portion of the player's ATK to become damage."
    },
    "armor": {
        "name": "Origin Aegis of Olympus (Armor)",
        "tier": "Origin",
        "type": "armor",
        "stats": {"atk": 0, "def": 600, "hp": 4500},
        "description": "Low chance of blocking a certain amount of incoming damage and restoring HP.."
    },
    "vice": {
        "name": "Origin Cosmic Chrono (Vice)",
        "tier": "Origin",
        "type": "vice",
        "stats": {"crit_rate": 70, "crit_dmg": 12.0}, # ĐÃ ĐỔI: Sử dụng crit_rate (CT) và crit_dmg (CD) vượt trội hơn Mythic
        "description": "Low chance of significantly increasing damage when triggering a critical hit.."
    }
}

# ========================================================================
# VIEW ĐIỀU KHIỂN GIAO DIỆN CÔNG KHAI
# ========================================================================
class WorldBossView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Check DPS", style=discord.ButtonStyle.secondary, emoji="📊", custom_id="wb_check_dps_btn")
    async def check_dps_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        p = await rpg_profiles_col.find_one({"user_id": user_id})
        
        if not p or "active_digimon_id" not in p:
            return await interaction.response.send_message("❌ You haven't activated any Digimon yet.!", ephemeral=True)

        active_id = p.get("active_digimon_id")
        digi = next((d for d in p.get("digimon_list", []) if d.get("id") == active_id), {})
        if not digi:
            return await interaction.response.send_message("❌ No Digimon data found!", ephemeral=True)

        # ==============================================================
        # SỬA LỖI Ở ĐÂY: Mượn hàm tính toán chuẩn xác từ RPGSystemCog
        # ==============================================================
        rpg_cog = self.cog.bot.get_cog("RPGSystemCog")
        total_atk = rpg_cog.get_total_stats(p)["atk"]
        
        gear = p.get("gear", {})

        # 2. Tính toán hệ số nhân
        size_mult = digi.get("size", 1.0)
        attr_mult = 1.0
        
        boss_attr = self.cog.boss_state.get("attribute", "Unknown")
        player_attr = digi.get("attr", "Unknown")
        
        # Bảng khắc hệ tiêu chuẩn
        matrix = {
            "Vaccine": {"Virus": 1.3, "Data": 0.7},
            "Virus": {"Data": 1.3, "Vaccine": 0.7},
            "Data": {"Vaccine": 1.3, "Virus": 0.7}
        }
        attr_mult = matrix.get(player_attr, {}).get(boss_attr, 1.0)
        
        attr_text = "Advantage (+30%)" if attr_mult > 1.0 else "Disadvantage (-30%)" if attr_mult < 1.0 else "Same attribute"

        # 3. Tính toán các mốc sát thương
        manual_hit_dmg = int(total_atk * size_mult * attr_mult)
        auto_base_dmg = int(manual_hit_dmg * 3.5)
        
        is_mega = digi.get("stage") == "Mega"
        tier = self.cog.boss_state.get("tier", 1)
        tier_penalty_text = ""
        
        if not is_mega or auto_base_dmg < 2000:
            auto_base_dmg = int(auto_base_dmg * 1.6)
            tier_penalty_text = "\n🛡️ **Newbie Buff:** `+60% damage`"
        else:
            tier_penalty = {1: 0.90, 2: 0.95, 3: 1, 4: 1, 5: 1}
            penalty = tier_penalty.get(tier, 1.0)
            auto_base_dmg = int(auto_base_dmg * penalty)
            if penalty < 1.0:
                tier_penalty_text = f"\n📉 **Tier Boss pressure:** `Decrease {(1 - penalty)*100:.0f}% damage`"

        # 4. Hiển thị trang bị Origin / Passive
        has_origin_weapon = gear.get("weapon", {}).get("rarity") == "Origin" if isinstance(gear.get("weapon"), dict) else False
        has_origin_vice = gear.get("vice", {}).get("rarity") == "Origin" if isinstance(gear.get("vice"), dict) else False
        
        passive_text = ""
        if is_mega:
            passive_text += "- 🌟 There is a 5% chance to gain `+30% ATK` or `+20% Bonus Attack` every 20 seconds..\n"
        if has_origin_weapon:
            passive_text += f"- ⚔️ An 8% chance to activate Origin Weapon deals additional damage. `{int(total_atk * 0.15):,}` DMG.\n"
        if has_origin_vice:
            passive_text += "- 📿 10% chance to activate Origin Vice `x1.4` total DMG.\n"

        if not passive_text:
            passive_text = "*There is no particular intrinsic trigger.*"

        report_msg = (
            f"📊 **DPS ANALYSIS TABLE**\n\n"
            f"**1. Baseline Index:**\n"
            f"- Size Ratio: `{size_mult * 100:.1f}%`\n"
            f"- Total ATK (Base + Gear): `{total_atk:,}`\n"
            f"- Counter-system ({player_attr} vs {boss_attr}): `{attr_text}`\n"
            f"{tier_penalty_text}\n\n"
            f"**2. Estimated Damage:**\n"
            f"🗡️ **Manual Attack (1 Hit):** `~ {manual_hit_dmg:,}` DMG\n"
            f"🤖 **Auto Attack (every 20s):** `~ {auto_base_dmg:,}` DMG *(not including luck)*\n\n"
            f"**3. Hidden Passive Activation Rate (RNG):**\n"
            f"{passive_text}"
        )

        await interaction.response.send_message(report_msg, ephemeral=True)

    @discord.ui.button(label="Toggle Auto Attack", style=discord.ButtonStyle.success, custom_id="wb_auto_btn")
    async def auto_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        if user_id in self.cog.persistent_auto_attackers:
            del self.cog.persistent_auto_attackers[user_id]
            await interaction.response.send_message("🔴 You have **TURNED OFF** Auto Attack mode.", ephemeral=True)
        else:
            p = await rpg_profiles_col.find_one({"user_id": user_id})
            if p and p.get("current_hp", 0) <= 0:
                return await interaction.response.send_message("❌ Your Digimon has 0 HP. Please heal it first.!", ephemeral=True)
            self.cog.persistent_auto_attackers[user_id] = time.time() - 15
            await interaction.response.send_message("🟢 Auto Attack AFK mode successfully activated!", ephemeral=True)

    @discord.ui.button(label="Activate Protect", style=discord.ButtonStyle.secondary, custom_id="wb_protect_btn")
    async def protect_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        if user_id not in self.cog.boss_state["participants"]: 
            self.cog.boss_state["participants"][user_id] = {"protect": False}
        self.cog.boss_state["participants"][user_id]["protect"] = True
        await interaction.response.send_message("🛡️ You have activated the defensive state for the Boss's turn.!", ephemeral=True)

    @discord.ui.button(label="Heal", style=discord.ButtonStyle.primary, emoji="💊", custom_id="wb_heal_btn")
    async def heal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        p = await rpg_profiles_col.find_one({"user_id": user_id})
        if not p: return await interaction.response.send_message("❌ Your profile could not be found!", ephemeral=True)
        
        active_id = p.get("active_digimon_id")
        digi = next((d for d in p.get("digimon_list", []) if d.get("id") == active_id), {})
        base_hp = digi.get("base_hp", 1000) + digi.get("train_hp", 0)
        gear_hp = sum(g.get("hp", 0) for g in p.get("gear", {}).values() if isinstance(g, dict))
        max_hp = base_hp + gear_hp
        
        curr_time = int(time.time())
        if curr_time - p.get("last_heal", 0) < 15:
            return await interaction.response.send_message(f"⏳ Healing is on cooldown! Wait. {15 - (curr_time - p.get('last_heal', 0))}s.", ephemeral=True)
        
        await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {"current_hp": max_hp, "last_heal": curr_time}})
        await interaction.response.send_message(f"💊 Full Blood Recovered (**{max_hp:,} HP**)!Auto Attack will continue if it is enabled..", ephemeral=True)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="wb_refresh_btn")
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = self.cog.generate_boss_embed()
        await interaction.response.edit_message(embed=embed)


class WorldBossTurnBased(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.persistent_auto_attackers = {}
        self.active_dashboards = {}  # {channel_id: message_object} để Auto-Refresh
        self.HIGH_TIER_GEARS = [
            {"name": "Omega Artifact Sword", "type": "weapon", "atk": 650, "rarity": "Mythic"},
            {"name": "Alpha Absolute Shield", "type": "armor", "def": 550, "hp": 1500, "rarity": "Mythic"},
            {"name": "Ultimate Omegamon Vice", "type": "vice", "crit_rate": 20, "crit_dmg": 5.0, "rarity": "Mythic"},
            {"name": "Crimson End Armor", "type": "armor", "def": 600, "hp": 3500, "rarity": "Mythic"},
            {"name": "Miracle Origin Vice", "type": "vice", "crit_rate": 50, "crit_dmg": 3.0, "rarity": "Mythic"}
        ]
        self.boss_state = {
            "active": False,
            "boss_name": "",
            "tier": 1,
            "max_hp": 30000,
            "hp": 30000,
            "base_atk": 200,
            "phase": "PLAYER_TURN",  
            "phase_timer": 60,       
            "turn_damage": {},      # Sát thương trong 1 turn (để trừ máu Boss)
            "total_damage": {},     # Sát thương tổng để xếp hạng Top 10
            "participants": {},     
            "upcoming_aoe": False    
        }
        self.world_boss_loop.start()

    def cog_unload(self):
        self.world_boss_loop.cancel()

    # ========================================================================
    # TẠO GIAO DIỆN EMBED (CHUẨN FORM ẢNH)
    # ========================================================================
    def generate_boss_embed(self):
        color = discord.Color.red() if self.boss_state["phase"] == "BOSS_TURN" else discord.Color.green()
        boss_attr = self.boss_state.get("attribute", "Unknown") # LẤY HỆ TỪ STATE

        embed = discord.Embed(
            title="⚔️ THE BATTLE HALL OF THE GODS",
            description=f"Current boss: **{self.boss_state.get('boss_name', 'Unknown')}**\n🧬 Attribute: **{boss_attr}**",
            color=color
        )
        embed.add_field(
            name="HP Boss", 
            value=f"❤️ {max(0, self.boss_state['hp']):,} / {self.boss_state['max_hp']:,}", 
            inline=False
        )

        status_text = f"⏳ turn: **{self.boss_state['phase']}** ({self.boss_state['phase_timer']}s left)"
        embed.add_field(name="Status", value=status_text, inline=False)

        leaderboard_text = ""
        if not self.boss_state["total_damage"]:
            leaderboard_text = "*No one has inflicted any damage*"
        else:
            sorted_dmg = sorted(self.boss_state["total_damage"].items(), key=lambda x: x[1], reverse=True)[:10]
            for idx, (uid, dmg) in enumerate(sorted_dmg, 1):
                medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else "🔹"
                leaderboard_text += f"{medal} <@{uid}> - **{dmg:,}** dmg\n"

        embed.add_field(name="🏆 TOP 10 DAMAGE", value=leaderboard_text, inline=False)
        return embed

    async def spawn_olympos_boss(self):
        boss_meta = await world_boss_col.find_one({"meta_id": "current_boss"})
        
        current_tier = boss_meta.get("tier", 0) if boss_meta else 0
        next_tier = (current_tier % 5) + 1
        
        # CHỌN BOSS TỪ TỪ ĐIỂN ĐỂ LẤY THUỘC TÍNH (HỆ)
        base_boss_name = random.choice(list(OLYMPOS_XII_DATA.keys()))
        boss_attr = OLYMPOS_XII_DATA[base_boss_name]
        boss_full_name = f"[Tier {next_tier}] {base_boss_name}"
        
        max_hp = 25000 * (next_tier ** 2)
        base_atk = 200 * (next_tier ** 1.5)

        update_data = {
            "active": True, 
            "boss_name": boss_full_name,
            "attribute": boss_attr, # LƯU HỆ
            "tier": next_tier, 
            "max_hp": int(max_hp), 
            "hp": int(max_hp),
            "base_atk": int(base_atk), 
            "phase": "PLAYER_TURN",
            "phase_timer": 30,  # GIẢM TURN XUỐNG 30S
            "turn_damage": {}, 
            "total_damage": {}, 
            "participants": {}, 
            "upcoming_aoe": False
        }
        self.boss_state.update(update_data)

        await world_boss_col.update_one(
            {"meta_id": "current_boss"},
            {"$set": {
                "name": base_boss_name, 
                "boss_name": boss_full_name, 
                "attribute": boss_attr, # LƯU HỆ VÀO DATABASE
                "tier": next_tier, 
                "hp": int(max_hp), 
                "max_hp": int(max_hp), 
                "status": "alive"
            }},
            upsert=True
        )
    # ========================================================================
    # VÒNG LẶP ĐIỀU PHỐI (CÓ AUTO-REFRESH MESSAGE)
    # ========================================================================
    @tasks.loop(seconds=1)
    async def world_boss_loop(self):
        if not self.boss_state["active"]:
            await self.spawn_olympos_boss()
            return

        if self.boss_state["phase_timer"] % 10 == 0:
            for channel_id, msg in list(self.active_dashboards.items()):
                try:
                    await msg.edit(embed=self.generate_boss_embed())
                except discord.NotFound:
                    del self.active_dashboards[channel_id] 
                except Exception:
                    pass

        if self.boss_state["phase"] == "PLAYER_TURN":
            self.boss_state["phase_timer"] -= 1
            current_now = time.time()
            
            for user_id in list(self.persistent_auto_attackers.keys()):
                # ✅ Lấy thời gian an toàn
                last_attack_time = self.persistent_auto_attackers.get(user_id)
                if last_attack_time is None:
                    continue
                
                # ✅ SỬA LỖI TẠI ĐÂY: Sử dụng trực tiếp biến last_attack_time
                if current_now - last_attack_time >= 10:
                    profile = await rpg_profiles_col.find_one({"user_id": user_id})
                    if not profile or profile.get("current_hp", 0) <= 0:
                        if user_id in self.persistent_auto_attackers:
                            del self.persistent_auto_attackers[user_id]
                        await self.send_dm_safely(user_id, "💀 **Auto Attack has stopped:** Your Digimon has run out of HP. Please use the Heal button to continue AFK!")
                        continue
                    
                    if user_id not in self.boss_state["participants"]:
                        self.boss_state["participants"][user_id] = {"protect": False}
                    
                    await self.process_auto_attack(user_id)
                    self.persistent_auto_attackers[user_id] = current_now

            if self.boss_state["phase_timer"] <= 0:
                await self.transition_to_boss_turn()

        elif self.boss_state["phase"] == "BOSS_TURN":
            await self.execute_boss_turn()

    async def spawn_olympos_boss(self):
        # 1. Lấy thông tin boss hiện tại để đi theo chu kỳ Tier 1 -> 5
        boss_meta = await world_boss_col.find_one({"meta_id": "current_boss"})
        
        current_tier = boss_meta.get("tier", 0) if boss_meta else 0
        next_tier = (current_tier % 5) + 1
        
        # 2. Định nghĩa biến rõ ràng
        base_boss_name = random.choice(OLYMPOS_XII) # Trong file bạn đang có array OLYMPOS_XII
        # Tạm gán Attribute random nếu bạn chưa sửa Array thành Dict ở trên cùng file
        attr_pool = ["Vaccine", "Data", "Virus"]
        boss_attr = random.choice(attr_pool) 
        
        boss_full_name = f"[Tier {next_tier}] {base_boss_name}"
        
        # Chỉ số: Máu giảm nhẹ đi một chút để người chơi kịp nhận thưởng
        max_hp = 25000 * (next_tier ** 2)
        base_atk = 200 * (next_tier ** 1.5)

        # 3. Cập nhật State ĐỦ KEY
        update_data = {
            "active": True, 
            "boss_name": boss_full_name,
            "attribute": boss_attr,
            "tier": next_tier, 
            "max_hp": int(max_hp), 
            "hp": int(max_hp),
            "base_atk": int(base_atk), 
            "phase": "PLAYER_TURN",
            "phase_timer": 60, 
            "turn_damage": {}, 
            "total_damage": {}, 
            "participants": {}, 
            "upcoming_aoe": False
        }
        self.boss_state.update(update_data)

        # 4. Lưu DB ĐỦ KEY
        await world_boss_col.update_one(
            {"meta_id": "current_boss"},
            {"$set": {
                "name": base_boss_name, 
                "boss_name": boss_full_name, # Lưu dự phòng boss_name để Embed không bị None
                "attribute": boss_attr,
                "tier": next_tier, 
                "hp": int(max_hp), 
                "max_hp": int(max_hp), 
                "status": "alive"
            }},
            upsert=True
        )
    # ========================================================================
    # XỬ LÝ SÁT THƯƠNG AUTO ATTACK
    # ========================================================================
    async def process_auto_attack(self, user_id):
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        if not profile: return

        active_id = profile.get("active_digimon_id")
        digi = next((d for d in profile.get("digimon_list", []) if d.get("id") == active_id), {})
        if not digi: return

        # SỬA Ở ĐÂY: Dùng hàm tính chuẩn từ RPGSystem
        rpg_cog = self.bot.get_cog("RPGSystemCog")
        total_atk = rpg_cog.get_total_stats(profile)["atk"]
        
        gear = profile.get("gear", {})
        has_origin_weapon = gear.get("weapon", {}).get("rarity") == "Origin" if isinstance(gear.get("weapon"), dict) else False
        has_origin_vice = gear.get("vice", {}).get("rarity") == "Origin" if isinstance(gear.get("vice"), dict) else False

        size_mult = digi.get("size", 1.5)
        attr_mult = 1.0
        
        # Bắt thuộc tính chéo chuẩn xác hơn
        boss_attr = self.boss_state.get("attribute", "Unknown")
        player_attr = digi.get("attr", "Unknown")
        matrix = {"Vaccine": {"Virus": 1.3, "Data": 0.7}, "Virus": {"Data": 1.3, "Vaccine": 0.7}, "Data": {"Vaccine": 1.3, "Virus": 0.7}}
        attr_mult = matrix.get(player_attr, {}).get(boss_attr, 1.0)

        calculated_dmg = total_atk * size_mult * attr_mult * 3.5

        is_mega = digi.get("stage") == "Mega"
        if is_mega:
            if random.random() < 0.05: calculated_dmg *= 1.3
            if random.random() < 0.05: calculated_dmg *= 1.2

        if has_origin_weapon and random.random() < 0.08: calculated_dmg += (total_atk * 0.15)
        if has_origin_vice and random.random() < 0.10: calculated_dmg *= 1.4

        if not is_mega or calculated_dmg < 2000:
            calculated_dmg *= 1.6
        else:
            tier_penalty = {1: 0.9, 2: 0.95, 3: 1, 4: 1.2, 5: 1.4}
            calculated_dmg *= tier_penalty.get(self.boss_state.get("tier", 1), 1.0)

        final_dmg = int(calculated_dmg)
        self.boss_state["turn_damage"][user_id] = self.boss_state["turn_damage"].get(user_id, 0) + final_dmg
        self.boss_state["total_damage"][user_id] = self.boss_state["total_damage"].get(user_id, 0) + final_dmg

    # ========================================================================
    async def transition_to_boss_turn(self):
        self.boss_state["hp"] -= sum(self.boss_state["turn_damage"].values())
        self.boss_state["turn_damage"] = {} # Reset sát thương của turn
        
        if self.boss_state["hp"] <= 0:
            # ĐÁNH DẤU BOSS CHẾT NGAY LẬP TỨC để chặn vòng lặp vô hạn
            self.boss_state["active"] = False 
            
            # An toàn gọi hàm trao quà, nếu lỗi cũng không làm kẹt Boss mới
            try:
                await self.distribute_rewards()
            except Exception as e:
                print(f"[WorldBoss] Error calc reward: {e}")
            return
            
        self.boss_state["phase"] = "BOSS_TURN"

    # ========================================================================
    # BOSS PHẢN CÔNG & QUÉT ĐỘC CHIÊU AOE
    # ========================================================================
    async def execute_boss_turn(self):
        tier = self.boss_state.get("tier", 1)
        tier_damage_map = {1: 200, 2: 300, 3: 400, 4: 500, 5: 600}
        base_boss_dmg = tier_damage_map.get(tier, 200)
        
        rpg_cog = self.bot.get_cog("RPGSystemCog")

        for user_id in list(self.boss_state["participants"].keys()):
            profile = await rpg_profiles_col.find_one({"user_id": user_id})
            if not profile: continue

            active_id = profile.get("active_digimon_id")
            digi = next((d for d in profile.get("digimon_list", []) if d.get("id") == active_id), {})
            
            is_mega = digi.get("stage") == "Mega"
            has_protect = self.boss_state["participants"][user_id]["protect"]

            # SỬA Ở ĐÂY: Dùng hàm lấy HP chuẩn để tính AOE chính xác
            max_hp = rpg_cog.get_total_stats(profile)["hp"]

            final_received_dmg = base_boss_dmg

            if self.boss_state.get("upcoming_aoe", False):
                aoe_percent_map = {1: 0.3, 2: 0.4, 3: 0.5, 4: 0.6, 5: 0.7}
                final_received_dmg = int(max_hp * aoe_percent_map.get(tier, 0.3))
                if has_protect: final_received_dmg = int(final_received_dmg * 0.5)
            else:
                if not is_mega: final_received_dmg *= 0.7
                if has_protect: final_received_dmg *= 0.3

            has_origin_armor = profile.get("gear", {}).get("armor", {}).get("rarity") == "Origin" if isinstance(profile.get("gear", {}).get("armor"), dict) else False

            if has_origin_armor and random.random() < 0.12:
                final_received_dmg = int(final_received_dmg * 0.7)
                await rpg_profiles_col.update_one({"user_id": user_id}, {"$inc": {"current_hp": int(max_hp * 0.10)}})

            await rpg_profiles_col.update_one({"user_id": user_id}, {"$inc": {"current_hp": -int(final_received_dmg)}})

            updated_profile = await rpg_profiles_col.find_one({"user_id": user_id})
            if updated_profile and updated_profile.get("current_hp", 0) <= 0:
                if user_id in self.persistent_auto_attackers:
                    del self.persistent_auto_attackers[user_id]
                await self.send_dm_safely(user_id, "💀 **You have died!** Your Digimon has run out of HP. Press the 💊 Health button in the lobby to continue!")

        self.boss_state["upcoming_aoe"] = random.random() < 0.05

        if self.boss_state["upcoming_aoe"]:
            for u_id in self.boss_state["participants"].keys():
                await self.send_dm_safely(u_id, f"⚠️ **WARNING** Boss `{self.boss_state.get('boss_name', 'Unknown')}` preparing to use AOE skill.")

        self.boss_state.update({"phase": "PLAYER_TURN", "phase_timer": 30})
    async def distribute_rewards(self):
        tier = self.boss_state["tier"]
        reward_config = {
            1: {"digibit": (300, 500), "orb": (20, 30), "core": (50, 60), "coin": (1, 1)},
            2: {"digibit": (500, 600), "orb": (30, 40), "core": (60, 70), "coin": (1, 2)},
            3: {"digibit": (700, 800), "orb": (40, 50), "core": (71, 100), "coin": (2, 2)},
            4: {"digibit": (800, 900), "orb": (50, 60), "core": (100, 150), "coin": (2, 3)},
            5: {"digibit": (1000, 1500), "orb": (70, 70), "core": (150, 200), "coin": (3, 3)}
        }
        cfg = reward_config.get(tier, reward_config[1])

        import copy
        import uuid
        import time

        for user_id, accumulated_dmg in self.boss_state["total_damage"].items():
            if accumulated_dmg <= 0: continue

            try:
                r_digibit = random.randint(*cfg["digibit"])
                r_orb = random.randint(*cfg["orb"])
                r_core = random.randint(*cfg["core"])
                r_coin = random.randint(*cfg["coin"])

                await rpg_profiles_col.update_one(
                    {"user_id": user_id},
                    {"$inc": {
                        "digibit": r_digibit, 
                        "orb": r_orb, 
                        "hatch_core": r_core, 
                        "myk_coin": r_coin
                    }}
                )

                dropped_gear_raw = None
                roll = random.random()
                
                if tier == 4 and roll < 0.10:
                    dropped_gear_raw = random.choice(self.HIGH_TIER_GEARS)
                elif tier == 5:
                    if roll < 0.15: 
                        # Đảm bảo bạn đã khai báo ORIGIN_GEAR_TEMPLATES ở Global
                        dropped_gear_raw = ORIGIN_GEAR_TEMPLATES[random.choice(["weapon", "armor", "vice"])]
                    elif roll < 0.25: 
                        dropped_gear_raw = random.choice(self.HIGH_TIER_GEARS)

                # Khởi tạo tin nhắn cơ bản trước
                reward_msg = f"🏆 **BOSS DEFEATED:** You dealt **{accumulated_dmg:,}** dmg\n🎁 **Rewards:** `{r_digibit}` Bits | `{r_orb}` Orbs | `{r_core}` Cores | `{r_coin}` MyK Coins"

                # Chỉ xử lý trang bị NẾU người chơi thực sự rớt đồ
                if dropped_gear_raw:
                    dropped_gear = copy.deepcopy(dropped_gear_raw)
                    dropped_gear["id"] = str(uuid.uuid4()) # Gắn ID chuẩn
                    dropped_gear["obtained_at"] = int(time.time())

                    await rpg_profiles_col.update_one(
                        {"user_id": user_id}, 
                        {"$push": {"inventory": dropped_gear}}
                    )

                    # ✅ SỬA LỖI KEYERROR TẠI ĐÂY
                    rarity_label = dropped_gear.get('rarity', dropped_gear.get('tier', 'Origin'))
                    reward_msg += f"\n🔥 **ITEM DROPPED:** [{rarity_label}] **{dropped_gear['name']}**!"

                await self.send_dm_safely(user_id, reward_msg)
                
            except Exception as e:
                print(f"[WorldBoss] Lỗi trao quà cho {user_id}: {e}")
    async def send_dm_safely(self, user_id, message_str):
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            if user: await user.send(message_str)
        except Exception: pass

    # ========================================================================
    # COMMAND GỌI BẢNG ĐIỀU KHIỂN CÔNG KHAI
    # ========================================================================
    @app_commands.command(name="combat", description="World Boss Battle Hall Open (Public)")
    async def worldboss(self, interaction: discord.Interaction):
        # Không dùng ephemeral=True nữa để tin nhắn hiển thị công khai
        await interaction.response.defer(ephemeral=False)
        if not self.boss_state["active"]:
            return await interaction.followup.send("Currently, no World Bosses are present..", ephemeral=True)

        embed = self.generate_boss_embed()
        view = WorldBossView(self)
        
        msg = await interaction.followup.send(embed=embed, view=view)
        
        # Lưu tin nhắn vào hệ thống để Vòng lặp tự động cập nhật
        self.active_dashboards[interaction.channel_id] = msg


async def setup(bot):
    await bot.add_cog(RPGSystemCog(bot))
    await bot.add_cog(WorldBossTurnBased(bot))