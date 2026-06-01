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

cross_messages_col = rpg_profiles_col.database["cross_chat_logs"]
market_col = rpg_profiles_col.database["rpg_marketplace"]
OWNER_IDS = [1283689737567211581]

# ========================================================================
# GLOBAL CONSTANTS & POOLS
# ========================================================================

NEW_MEGA_POOL = [
    {"name": "ShineGreymon BM", "stage": "Mega", "atk": 1250, "hp": 15500, "base_price": 850000},
    {"name": "MirageGaogamon BM", "stage": "Mega", "atk": 1200, "hp": 14800, "base_price": 820000},
    {"name": "Rosemon BM", "stage": "Mega", "atk": 1150, "hp": 14200, "base_price": 780000},
    {"name": "Ravemon BM", "stage": "Mega", "atk": 1180, "hp": 14000, "base_price": 790000},
    {"name": "BlackWarGreymon", "stage": "Mega", "atk": 1300, "hp": 16500, "base_price": 950000},
    {"name": "MetalSeadramon", "stage": "Mega", "atk": 1220, "hp": 15800, "base_price": 880000},
    {"name": "Piedmon", "stage": "Mega", "atk": 1260, "hp": 15000, "base_price": 920000},
    {"name": "Valkyrimon", "stage": "Mega", "atk": 1100, "hp": 13800, "base_price": 720000},
    {"name": "Vikemon", "stage": "Mega", "atk": 1120, "hp": 16800, "base_price": 750000},
    {"name": "GranKuwagamon", "stage": "Mega", "atk": 1190, "hp": 14500, "base_price": 770000}
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

class DigiBagSelect(discord.ui.Select):
    def __init__(self, digimon_list: list, current_active_id: str, cog_instance):
        self.cog = cog_instance
        options = []
        for digi in digimon_list[:25]:
            is_active = "✅ (Active)" if digi["id"] == current_active_id else ""
            size = digi.get("size", 1.0) * 100 
            options.append(discord.SelectOption(
                label=f"{digi['name']} {is_active}".strip(),
                description=f"Stage: {digi['stage']} | ATK: {digi['atk']} | HP: {digi['hp']} | Size: {size:.1f}%",
                value=digi["id"]
            ))
        super().__init__(placeholder="Chọn Digimon...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "empty":
            return await interaction.response.send_message("❌ **Your Digimon Bag is empty!**", ephemeral=True)
        await self.cog.handle_switch_digimon(interaction, self.values[0])


class DigiSellSelect(discord.ui.Select):
    def __init__(self, digimon_list: list, current_active_id: str, cog_instance):
        self.cog = cog_instance
        options = []
        extra_digis = [d for d in digimon_list if d["id"] != current_active_id]
        
        for digi in extra_digis[:25]:
            options.append(discord.SelectOption(
                label=f"Sell: {digi['name']}",
                description=f"Stage: {digi['stage']} -> Get 2.0 Digibits",
                value=digi["id"],
                emoji="♻️"
            ))
        if not options:
            options = [discord.SelectOption(label="No extra Digimon to sell", value="empty")]
        super().__init__(placeholder="♻️ Select an extra Digimon to sell (2 DB)...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "empty":
            return await interaction.response.send_message("❌ **No redundant Digimon available to sell!**", ephemeral=True)
        await self.cog.handle_sell_digimon(interaction, self.values[0])


class BagView(discord.ui.View):
    def __init__(self, digimon_list: list, current_active_id: str, cog_instance):
        super().__init__(timeout=120)
        self.add_item(DigiBagSelect(digimon_list, current_active_id, cog_instance))
        self.add_item(DigiSellSelect(digimon_list, current_active_id, cog_instance))


class GearInventorySelect(discord.ui.Select):
    def __init__(self, gear_list: list, cog_instance):
        options = []
        for gear in gear_list[:25]:
            stats = []
            if "atk" in gear: stats.append(f"ATK +{gear['atk']}")
            if "def" in gear: stats.append(f"DEF +{gear['def']}")
            if "hp" in gear: stats.append(f"HP +{gear['hp']}")
            stat_desc = " | ".join(stats) if stats else "No Stats"
            
            options.append(discord.SelectOption(
                label=f"{gear.get('name', 'Unknown')} ({gear.get('rarity', 'Common')})",
                description=f"Loại: {gear.get('type', 'N/A').upper()} | {stat_desc}",
                value=gear.get("id", str(uuid.uuid4()))
            ))
        if not options:
            options = [discord.SelectOption(label="Kho đồ trống", value="empty")]
        super().__init__(placeholder="Xem danh sách trang bị...", options=options)


class ProfileView(discord.ui.View):
    def __init__(self, profile: dict, cog_instance):
        super().__init__(timeout=300)
        self.user_id = profile.get("user_id")
        self.cog = cog_instance
        self.add_item(GearInventorySelect(profile.get("inventory", []), cog_instance))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ **Access Denied!** This profile option is not yours.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Heal (120s CD)", style=discord.ButtonStyle.success, custom_id="btn_heal", emoji="✨")
    async def heal_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_heal(interaction)

    @discord.ui.button(label="Evolve (50,000 Bits)", style=discord.ButtonStyle.primary, custom_id="btn_evolve", emoji="🧬")
    async def evolve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_evolve(interaction)


class MarketBuySelect(discord.ui.Select):
    def __init__(self, listings: list, cog_instance):
        self.cog = cog_instance
        options = []
        for item in listings[:25]:
            options.append(discord.SelectOption(
                label=f"{item['item_name']} - {item['price']:.2f} DB",
                description=f"Seller: {item['seller_name']} | ID: {item['listing_id']}",
                value=item['listing_id'],
                emoji="🛒"
            ))
        if not options:
            options = [discord.SelectOption(label="Marketplace is empty", value="empty")]
        super().__init__(placeholder="🛒 Choose an item to purchase...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "empty":
            return await interaction.response.send_message("❌ No items available.", ephemeral=True)
        await self.cog.handle_market_buy(interaction, self.values[0])


class MarketSellSelect(discord.ui.Select):
    def __init__(self, inventory: list, cog_instance):
        self.cog = cog_instance
        options = []
        unique_items = list(set(inventory))[:25]
        for item in unique_items:
            options.append(discord.SelectOption(label=item, value=item, emoji="📦"))
        if not options:
            options = [discord.SelectOption(label="Your inventory is empty", value="empty")]
        super().__init__(placeholder="📦 Choose an item from your bag to sell...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "empty":
            return await interaction.response.send_message("❌ You have nothing to sell.", ephemeral=True)
        await interaction.response.send_modal(MarketPriceModal(self.values[0], self.cog))


class MarketPriceModal(discord.ui.Modal, title="Set Listing Price"):
    price = discord.ui.TextInput(label="Price in Digibits", placeholder="e.g., 25.50", max_length=12)

    def __init__(self, item_name: str, cog_instance):
        super().__init__()
        self.item_name = item_name
        self.cog = cog_instance

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.handle_market_sell_enhanced(interaction, self.item_name, self.price.value)


class MarketShopView(discord.ui.View):
    def __init__(self, cog_instance, user_id: int):
        super().__init__(timeout=180)
        self.cog = cog_instance
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This market interaction is not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Buy Item (Select)", style=discord.ButtonStyle.success, emoji="🛒")
    async def buy_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        listings = await market_col.find({}).sort("created_at", -1).to_list(25)
        new_view = discord.ui.View(timeout=60)
        new_view.add_item(MarketBuySelect(listings, self.cog))
        await interaction.followup.send("🛒 **Select an item from the marketplace list below:**", view=new_view, ephemeral=True)

    @discord.ui.button(label="Sell Item (Select from Bag)", style=discord.ButtonStyle.danger, emoji="📦")
    async def sell_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        inventory = profile.get("inventory", []) if profile else []
        new_view = discord.ui.View(timeout=60)
        new_view.add_item(MarketSellSelect(inventory, self.cog))
        await interaction.followup.send("📦 **Select an item from your bag to sell:**", view=new_view, ephemeral=True)


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
            discord.SelectOption(label="Digital Forest (Weapons)", value="digital_forest", emoji="🌲"),
            discord.SelectOption(label="Factorial Town (Armors)", value="factorial_town", emoji="🏭"),
            discord.SelectOption(label="Server Continent (Vices)", value="server_continent", emoji="🏜️"),
            discord.SelectOption(label="Core Sanctuary (Hatch Cores)", value="core_sanctuary", emoji="🔮"),
            discord.SelectOption(label="🛑 Stop Auto Dungeon", value="stop", emoji="⏹️")
        ]
        super().__init__(placeholder="🏰 Set Auto-Dungeon location...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await self.cog.handle_toggle_auto_dungeon(interaction, self.values[0])


class FarmDigiMinerSelect(discord.ui.Select):
    def __init__(self, eligible_digimon: list):
        options = []
        for d in eligible_digimon[:25]:
            options.append(discord.SelectOption(
                label=d["name"],
                description=f"Stage: {d['stage']} | Performance support level",
                value=d["id"]
            ))
        max_vals = min(6, len(options)) if options else 1
        super().__init__(
            placeholder="Select a maximum of 6 Digimon in your Bag to optimize your mining...",
            min_values=1,
            max_values=max_vals,
            options=options if options else [discord.SelectOption(label="No empty Digimon", value="none")]
        )

    async def callback(self, interaction: discord.Interaction):
        if "none" in self.values:
            return await interaction.response.send_message("There are no valid Digimon to choose from.", ephemeral=True)
            
        stage_multipliers = {"rookie": 1, "champion": 2, "ultimate": 3, "mega": 4}
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        
        if not profile:
            return await interaction.response.send_message("Character data not found.", ephemeral=True)
            
        selected_digis = [d for d in profile.get("bag", []) if d["id"] in self.values]
        
        total_efficiency = 0
        for d in selected_digis:
            stage_key = d.get("stage", "rookie").lower()
            total_efficiency += stage_multipliers.get(stage_key, 1)
            
        await rpg_profiles_col.update_one(
            {"user_id": interaction.user.id},
            {"$set": {
                "mining_assistants": self.values,
                "mining_efficiency_bonus": total_efficiency
            }}
        )
        await interaction.response.send_message(
            f"⚡ Distributed {len(selected_digis)} Digimon enters the mine! Total performance increase: +{total_efficiency * 10}% mining rate.", 
            ephemeral=True
        )


class FarmView(discord.ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=300)
        self.cog = cog_instance
        self.add_item(FarmDungeonSelect(cog_instance))

    @discord.ui.button(label="Manual Mine (5m CD)", style=discord.ButtonStyle.success, emoji="⛏️")
    async def manual_mine(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_manual_mine(interaction)
        
    @discord.ui.button(label="Toggle Auto-Mine", style=discord.ButtonStyle.primary, emoji="⚙️")
    async def toggle_automine(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_toggle_automine(interaction)

    @discord.ui.button(label="View Farm Logs", style=discord.ButtonStyle.secondary, emoji="📜")
    async def view_logs(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_view_logs(interaction)


# ========================================================================
# MAIN COG SYSTEM
# ========================================================================

class RPGSystemCog(commands.Cog):
    ITEMS = {
        "Rusty Sword": {"type": "weapon", "atk": 15}, "Rusty Armor": {"type": "armor", "hp": 150, "def": 10}, "Rusty Vice": {"type": "vice", "crit_rate": 5, "crit_dmg": 1.2},
        "Chrome Dagger": {"type": "weapon", "atk": 45}, "Chrome Cloak": {"type": "armor", "hp": 350, "def": 25}, "Chrome Vice": {"type": "vice", "crit_rate": 10, "crit_dmg": 1.5},
        "Divine Blade": {"type": "weapon", "atk": 120}, "Divine Aegis": {"type": "armor", "hp": 800, "def": 60}, "Divine Vice": {"type": "vice", "crit_rate": 20, "crit_dmg": 2.0}
    }

    DUNGEONS = {
        "digital_forest": {"name": "Digital Forest", "description": "Farms Weapons."},
        "factorial_town": {"name": "Factorial Town", "description": "Farms Armors."},
        "server_continent": {"name": "Server Continent", "description": "Farms Vices."},
        "core_sanctuary": {"name": "Core Sanctuary", "description": "Farms Hatch Cores exclusively."}
    }

    DIGIMON_DATA = {
        "rookie": {
            "Agumon": {"attr": "Vaccine", "atk": 60, "hp": 1200, "vip": False, "img": "https://digimon.net/cimages/digimon/agumon.jpg"},
            "Gabumon": {"attr": "Data", "atk": 55, "hp": 1300, "vip": False, "img": "https://digimon.net/cimages/digimon/gabumon.jpg"},
            "Guilmon": {"attr": "Virus", "atk": 65, "hp": 1100, "vip": False, "img": "https://digimon.net/cimages/digimon/guilmon.jpg"},
            "Lucemon": {"attr": "Virus", "atk": 90, "hp": 1000, "vip": True, "img": "https://digimon.net/cimages/digimon/lucemon.jpg"},
            "V-mon": {"attr": "Vaccine", "atk": 75, "hp": 1250, "vip": True, "img": "https://digimon.net/cimages/digimon/v-mon.jpg"},
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

    def cog_unload(self):
        self.auto_spawn_boss.cancel()
        self.farm_system_loop.cancel()
        self.live_boss_update_loop.cancel()

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def get_active_digimon(self, profile: dict) -> dict:
        digimon_list = profile.get("digimon_list", [])
        active_id = profile.get("active_digimon_id")
        for digi in digimon_list:
            if digi.get("id") == active_id:
                return digi
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

    def get_attribute_multiplier(self, attacker_attr: str, defender_attr: str) -> float:
        if attacker_attr == defender_attr: return 1.0
        adv = {"Vaccine": "Virus", "Virus": "Data", "Data": "Vaccine"}
        return 1.25 if adv.get(attacker_attr) == defender_attr else 0.8 

    def roll_pve_loot(self, dungeon: str) -> str:
        is_high_tier = random.random() < 0.10
        if dungeon == "digital_forest": loot_base = "Chrome Dagger" if is_high_tier else "Rusty Sword"
        elif dungeon == "factorial_town": loot_base = "Divine Aegis" if is_high_tier else "Rusty Armor"
        else: loot_base = "Chrome Vice" if is_high_tier else "Rusty Vice"
        return loot_base

    async def process_auto_dungeon_rewards(self, user_id: int):
        drop_chance = random.random()
        drop_gear = None
        
        if drop_chance <= 0.015:  
            chosen_gear_template = random.choice(HIGH_TIER_GEARS)
            drop_gear = {
                "id": str(uuid.uuid4()),
                "name": chosen_gear_template["name"],
                "type": chosen_gear_template["type"],
                "rarity": chosen_gear_template["rarity"],
                "atk": chosen_gear_template.get("atk", 0),
                "def": chosen_gear_template.get("def", 0),
                "hp": chosen_gear_template.get("hp", 0),
                "obtained_at": datetime.utcnow()
            }
            
            await rpg_profiles_col.update_one(
                {"user_id": user_id},
                {"$push": {"gears_inventory": drop_gear}}
            )
        return drop_gear

    async def initialize_market_mega_products(self):
        for mega in NEW_MEGA_POOL:
            exists = await market_col.find_one({"name": mega["name"]})
            if not exists:
                fluctuated_price = int(mega["base_price"] * random.uniform(0.9, 1.25))
                market_item = {
                    "item_id": str(uuid.uuid4()),
                    "name": mega["name"],
                    "stage": mega["stage"],
                    "atk": mega["atk"],
                    "hp": mega["hp"],
                    "price": fluctuated_price,
                    "is_limited": True,
                    "stock": random.randint(3, 7)
                }
                await market_col.insert_one(market_item)

    # ========================================================================
    # PROFILE & BAG SYSTEM 
    # ========================================================================

    @app_commands.command(name="upgrade_ui", description="Use 100 MyK Coins to upgrade to Premium UI")
    async def upgrade_ui(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile: return await interaction.followup.send("❌ Profile not found.", ephemeral=True)
        
        myk_coin = profile.get("myk_coin", 0)
        if myk_coin < 100:
            return await interaction.followup.send(f"❌ Not enough MyK Coins! You have: `{myk_coin}/100` Coins.", ephemeral=True)
            
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$inc": {"myk_coin": -100}, "$set": {"premium_ui": True}})
        await interaction.followup.send("🎉 **Congratulations!** You have successfully upgraded to the Premium UI!", ephemeral=True)

    @app_commands.command(name="rpg_profile", description="View your Tamer profile")
    async def rpg_profile(self, interaction: discord.Interaction):
        await interaction.response.defer()
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile: return await interaction.followup.send("❌ Please use `/hatch` to create a profile first.")

        digimon = self.get_active_digimon(profile)
        stats, gear = self.get_total_stats(profile), profile.get("gear", {})
        is_premium = profile.get("premium_ui", False)
        
        embed = discord.Embed(
            title=f"{'🌟 PREMIUM TAMER' if is_premium else '📱 Tamer'} {profile.get('ign')}", 
            color=discord.Color.gold() if is_premium else discord.Color.teal()
        )
        
        if digimon:
            size_display = f"{digimon.get('size', 1.0) * 100:.1f}%"
            embed.set_thumbnail(url=digimon.get("img", interaction.user.display_avatar.url))
            skill_info = f"\n**Skill:** {digimon.get('skill', {}).get('name')}" if "skill" in digimon else ""
            train_info = f"\n**Trained:** +{digimon.get('trained_atk', 0)} ATK | +{digimon.get('trained_hp', 0)} HP"
            embed.description = f"**Partner:** {digimon.get('name')} ({digimon.get('stage')})\n**Attr:** {digimon.get('attr')}\n**Size:** `{size_display}`{skill_info}{train_info}"
            embed.add_field(name="❤️ HP", value=f"{profile.get('current_hp')}/{stats['hp']}", inline=True)
            embed.add_field(name="⚔️ ATK", value=str(stats['atk']), inline=True)
            embed.add_field(name="🎯 CRIT", value=f"{stats['crit_rate']}% (x{stats['crit_dmg']})", inline=True)
            
        embed.add_field(name="💰 Assets", value=f"🌐 **{profile.get('digibit', 0):.2f} Digibits** | 🔮 **{profile.get('hatch_core', 0)} Cores**", inline=False)
        embed.add_field(name="Equipment", value=f"⚔️ {gear.get('weapon', 'None')}\n🛡️ {gear.get('armor', 'None')}\n📿 {gear.get('vice', 'None')}", inline=False)
        
        await interaction.followup.send(embed=embed, view=ProfileView(profile, self))

    @app_commands.command(name="bag", description="Open Digimon bag & manage/sell extras")
    async def bag(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile: return await interaction.followup.send("❌ Profile does not exist.", ephemeral=True)
        
        digimon_list = profile.get("digimon_list", [])
        if not digimon_list: return await interaction.followup.send("❌ You don't have any Digimon.", ephemeral=True)
        
        embed = discord.Embed(title="🐾 Your Digimon Bag", description=f"Total: {len(digimon_list)} Digimon\n\n*Use dropdown below to either partner or sell extra ones for 2 DB.*", color=discord.Color.gold())
        await interaction.followup.send(embed=embed, view=BagView(digimon_list, profile.get("active_digimon_id"), self), ephemeral=True)

    @app_commands.command(name="hatch", description=f"Hatch a Rookie Digimon (Costs 5 Hatch Cores)")
    async def hatch(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        if not profile:
            profile = {
                "user_id": user_id, "ign": interaction.user.display_name, 
                "gold": 0, "digibit": 0.0, "hatch_core": 15, "myk_coin": 0, "premium_ui": False,
                "current_hp": 0, "gear": {"weapon": "None", "armor": "None", "vice": "None"}, 
                "inventory": [], "is_vip": False, 
                "digimon_list": [], "active_digimon_id": None,
                "is_auto_mining": False, "auto_dungeon": None, "farm_logs": []
            }
            await rpg_profiles_col.insert_one(profile)

        if profile.get("hatch_core", 0) < self.HATCH_CORE_COST: return await interaction.followup.send("❌ Missing Hatch Cores.", ephemeral=True)

        await rpg_profiles_col.update_one({"user_id": user_id}, {"$inc": {"hatch_core": -self.HATCH_CORE_COST}})
        is_vip = profile.get("is_vip", False)
        available = [name for name, data in self.DIGIMON_DATA["rookie"].items() if not data["vip"] or is_vip]
        
        hatched_name = random.choice(available)
        base_stats = self.DIGIMON_DATA["rookie"][hatched_name]
        size_pct = round(random.uniform(1.00 if is_vip else 0.85, 1.30 if is_vip else 1.25), 3)

        actual_hp, actual_atk = int(base_stats["hp"] * size_pct), int(base_stats["atk"] * size_pct)
        new_digi_id = str(uuid.uuid4())
        
        digimon_stats = {
            "id": new_digi_id, "name": hatched_name, "stage": "Rookie", 
            "attr": base_stats["attr"], "size": size_pct, "hp": actual_hp, 
            "atk": actual_atk, "img": base_stats["img"],
            "trained_hp": 0, "trained_atk": 0
        }

        updates = {"$push": {"digimon_list": digimon_stats}}
        if not profile.get("active_digimon_id"):
            updates["$set"] = {"active_digimon_id": new_digi_id, "current_hp": actual_hp}

        await rpg_profiles_col.update_one({"user_id": user_id}, updates)
        embed = discord.Embed(title="🥚 Hatched Successfully!", description=f"Obtained **{hatched_name}**!", color=discord.Color.green())
        embed.set_thumbnail(url=base_stats["img"])
        embed.add_field(name="🧬 Size", value=f"**{size_pct * 100:.1f}%**")
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def handle_switch_digimon(self, interaction: discord.Interaction, digimon_id: str):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"active_digimon_id": digimon_id}})
        new_active = next((d for d in profile.get("digimon_list", []) if d["id"] == digimon_id), None)
        if new_active:
            total_hp = new_active.get("hp", 0) + new_active.get("trained_hp", 0)
            await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"current_hp": total_hp}})
            
        await interaction.followup.send("✅ Successfully switched active Digimon!", ephemeral=True)

    async def handle_sell_digimon(self, interaction: discord.Interaction, digimon_id: str):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile: return await interaction.followup.send("❌ Profile not found.", ephemeral=True)

        if digimon_id == profile.get("active_digimon_id"):
            return await interaction.followup.send("❌ Cannot sell your currently active Digimon partner!", ephemeral=True)

        digimon_list = profile.get("digimon_list", [])
        target_digi = next((d for d in digimon_list if d["id"] == digimon_id), None)
        if not target_digi:
            return await interaction.followup.send("❌ Digimon not found in bag.", ephemeral=True)

        await rpg_profiles_col.update_one(
            {"user_id": interaction.user.id},
            {"$pull": {"digimon_list": {"id": digimon_id}}, "$inc": {"digibit": 2.0}}
        )
        await interaction.followup.send(f"♻️ Successfully sold extra **{target_digi['name']}** for **+2.0 Digibits**!", ephemeral=True)

    @app_commands.command(name="train_digimon", description="Train Digimon (Costs 5000 Digibits)")
    @app_commands.choices(stat=[app_commands.Choice(name="ATK (+20 ATK / 5k Bits)", value="atk"), app_commands.Choice(name="HP (+100 HP / 5k Bits)", value="hp")])
    async def train_digimon(self, interaction: discord.Interaction, stat: str):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile or profile.get("digibit", 0) < 5000:
            return await interaction.followup.send("❌ Not enough Digibits (Requires 5,000).", ephemeral=True)
            
        active_digi = self.get_active_digimon(profile)
        if not active_digi: return await interaction.followup.send("❌ Please equip a Digimon first.", ephemeral=True)
        
        MAX_TRAIN_ATK = 1000
        MAX_TRAIN_HP = 5000
        current_train_atk = active_digi.get("trained_atk", 0)
        current_train_hp = active_digi.get("trained_hp", 0)
        
        updates = {}
        if stat == "atk":
            if current_train_atk >= MAX_TRAIN_ATK: return await interaction.followup.send("❌ ATK training limit reached.", ephemeral=True)
            updates["trained_atk"] = current_train_atk + 20
        else:
            if current_train_hp >= MAX_TRAIN_HP: return await interaction.followup.send("❌ HP training limit reached.", ephemeral=True)
            updates["trained_hp"] = current_train_hp + 100
            
        new_list = self.update_active_digimon(profile, updates)
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"digimon_list": new_list}, "$inc": {"digibit": -5000}})
        await interaction.followup.send(f"🏋️ **Training successful!** {stat.upper()} increased for {active_digi['name']}.", ephemeral=True)

    # ========================================================================
    # FARM & MINE SYSTEM 
    # ========================================================================
    
    @app_commands.command(name="farm", description="Open Farming & Mining Dashboard")
    async def farm_dashboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        if not profile: return await interaction.followup.send("❌ Please use `/hatch` to create a profile.", ephemeral=True)
        
        is_auto_mine = profile.get("is_auto_mining", False)
        auto_dungeon = profile.get("auto_dungeon")
        
        embed = discord.Embed(title="🚜 Farming Dashboard", color=discord.Color.green())
        embed.description = "Manage your automated and manual farming activities here.\n*Note: Auto Dungeon runs every 2 Minutes.*"
        embed.add_field(name="⛏️ Auto-Mine Status", value="🟢 **ON**" if is_auto_mine else "🔴 **OFF**", inline=True)
        embed.add_field(name="🏰 Auto-Dungeon", value=f"🟢 **{self.DUNGEONS.get(auto_dungeon, {}).get('name', 'Unknown')}**" if auto_dungeon else "🔴 **OFF**", inline=False)
        
        await interaction.followup.send(embed=embed, view=FarmView(self), ephemeral=True)

    async def handle_manual_mine(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        current_time = int(time.time())
        last_mine = profile.get("last_manual_mine", 0)
        
        if current_time - last_mine < 300:
            remaining = 300 - (current_time - last_mine)
            return await interaction.followup.send(f"⏳ **Tool is resting!** Try again in {remaining}s.", ephemeral=True)
            
        await rpg_profiles_col.update_one({"user_id": user_id}, {"$inc": {"digibit": 0.40}, "$set": {"last_manual_mine": current_time}})
        await interaction.followup.send(f"⛏️ You mined **+0.40 Digibits** manually!", ephemeral=True)

    async def handle_toggle_automine(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        current_status = profile.get("is_auto_mining", False)
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"is_auto_mining": not current_status}})
        status_text = "🟢 **ACTIVATED**" if not current_status else "🔴 **DEACTIVATED**"
        await interaction.followup.send(f"⚙️ Auto-Mine has been {status_text}.", ephemeral=True)

    async def handle_toggle_auto_dungeon(self, interaction: discord.Interaction, target_dungeon: str):
        await interaction.response.defer(ephemeral=True)
        if target_dungeon == "stop":
            await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"auto_dungeon": None}})
            return await interaction.followup.send("🛑 **Auto-Dungeon stopped.**", ephemeral=True)
            
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"auto_dungeon": target_dungeon}})
        await interaction.followup.send(f"🏰 **Auto-Dungeon set to {self.DUNGEONS[target_dungeon]['name']}!**", ephemeral=True)

    async def handle_view_logs(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        logs = profile.get("farm_logs", [])
        
        embed = discord.Embed(title="📜 System Farm Logs", color=discord.Color.dark_gray())
        embed.description = "No automated farming data yet." if not logs else "```\n" + "\n".join(logs) + "\n ```"
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tasks.loop(minutes=2)
    async def farm_system_loop(self):
        profiles = await rpg_profiles_col.find({"$or": [{"is_auto_mining": True}, {"auto_dungeon": {"$ne": None}}]}).to_list(None)
        
        for profile in profiles:
            user_id = profile["user_id"]
            log_msgs = []
            updates = {"$inc": {}, "$push": {}}
            
            if profile.get("is_auto_mining"):
                updates["$inc"]["digibit"] = updates["$inc"].get("digibit", 0) + 0.02
                log_msgs.append("⛏️ Mine: +0.02 Bits")
                
            dungeon = profile.get("auto_dungeon")
            if dungeon:
                runs = 1
                is_vip = profile.get("is_vip", False)
                is_premium = profile.get("premium_ui", False)
                
                if dungeon == "core_sanctuary":
                    cores = sum(random.randint(2, 3) if is_vip else random.randint(1, 2) for _ in range(runs))
                    loot_dropped = []
                else:
                    cores = sum(1 for _ in range(runs) if (is_vip or random.random() < 0.60))
                    drop_chance = 0.015 if is_premium else 0.01
                    loot_dropped = [f"{self.roll_pve_loot(dungeon)} (Unlocked)" for _ in range(runs) if random.random() < drop_chance]
                
                updates["$inc"]["digibit"] = updates["$inc"].get("digibit", 0) + runs
                if cores > 0: updates["$inc"]["hatch_core"] = updates["$inc"].get("hatch_core", 0) + cores
                if loot_dropped: updates["$push"]["inventory"] = {"$each": loot_dropped}
                
                # Check auto dungeon reward for high tier items
                high_tier_gear = await self.process_auto_dungeon_rewards(user_id)
                if high_tier_gear:
                    log_msgs.append(f"🌟 LỘC LỚN: Tìm thấy {high_tier_gear['name']}")
                    
                loot_str = f", {cores} Cores" if dungeon == "core_sanctuary" else (f", {cores} Cores, {len(loot_dropped)} Gears" if cores or loot_dropped else "")
                log_msgs.append(f"🏰 DG: +{runs} Bits{loot_str}")

            if log_msgs:
                log_entry = f"[{datetime.utcnow().strftime('%H:%M')}] " + " | ".join(log_msgs)
                if "farm_logs" not in updates["$push"]:
                    updates["$push"]["farm_logs"] = {"$each": [log_entry], "$slice": -10} 
                    
                if not updates["$inc"]: del updates["$inc"]
                if not updates["$push"]: del updates["$push"]
                if updates: await rpg_profiles_col.update_one({"user_id": user_id}, updates)

    @farm_system_loop.before_loop
    async def before_farm_system_loop(self):
        await self.bot.wait_until_ready()

    # ========================================================================
    # INVENTORY USE & EVOLUTION 
    # ========================================================================
    
    async def handle_inventory_use(self, interaction: discord.Interaction, item_name: str):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        inventory = profile.get("inventory", [])
        
        if item_name not in inventory: return await interaction.followup.send("❌ Item not found.", ephemeral=True)

        if item_name == "Size Reroll Fruit":
            inventory.remove(item_name)
            digimon = self.get_active_digimon(profile)
            if not digimon: return await interaction.followup.send("❌ No Active Digimon.", ephemeral=True)

            new_size = round(random.uniform(1.00 if profile.get("is_vip") else 0.85, 1.30 if profile.get("is_vip") else 1.25), 3)
            stage_lower = digimon.get("stage", "Rookie").lower()
            base_stats = self.DIGIMON_DATA.get(stage_lower, {}).get(digimon.get("name"))

            actual_hp, actual_atk = int(base_stats["hp"] * new_size), int(base_stats["atk"] * new_size)
            new_list = self.update_active_digimon(profile, {"size": new_size, "hp": actual_hp, "atk": actual_atk})
            
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {"inventory": inventory, "digimon_list": new_list, "current_hp": actual_hp + digimon.get("trained_hp", 0)}})
            await interaction.followup.send(f"🍎 **Fruit Consumed!** Size rerolled to **{new_size * 100:.1f}%**!", ephemeral=True)
        else:
            cleaned_base = self.clean_item_name(item_name)
            slot_type = self.ITEMS[cleaned_base]["type"]
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {f"gear.{slot_type}": item_name}})
            await interaction.followup.send(f"🛡️ **Equipped:** {item_name} -> `{slot_type.upper()}`", ephemeral=True)

    async def handle_heal(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile or not self.get_active_digimon(profile): return await interaction.followup.send("❌ No Digimon found.", ephemeral=True)

        current_time = int(time.time())
        if current_time - profile.get("last_heal", 0) < 120:
            return await interaction.followup.send(f"⏳ **Cooldown!** Wait {120 - (current_time - profile.get('last_heal', 0))}s.", ephemeral=True)

        max_hp = self.get_total_stats(profile)["hp"]
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"current_hp": max_hp, "last_heal": current_time}})
        await interaction.followup.send(f"✨ **Healed!** HP reset to Max.", ephemeral=True)

    async def handle_evolve(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        digimon = self.get_active_digimon(profile)
        
        if not digimon: return await interaction.followup.send("❌ No Active Digimon.", ephemeral=True)
        if digimon.get("stage") == "Mega": return await interaction.followup.send("❌ Max Level (Mega) reached.", ephemeral=True)
        
        TRAIN_COST = 50000
        if profile.get("digibit", 0) < TRAIN_COST: return await interaction.followup.send(f"❌ Need **{TRAIN_COST:,} Digibits**.", ephemeral=True)

        next_form_name = self.EVOLUTION_LINE.get(digimon["name"])
        if not next_form_name: return await interaction.followup.send("❌ This Digimon has no next evolution.", ephemeral=True)

        current_stage = digimon.get("stage")
        next_stage_map = {"Rookie": "champion", "Champion": "ultimate", "Ultimate": "mega"}
        next_stage_key = next_stage_map.get(current_stage)
        
        base_next_stats = self.DIGIMON_DATA[next_stage_key][next_form_name]
        current_size = digimon.get("size", 1.0)
        actual_hp, actual_atk = int(base_next_stats["hp"] * current_size), int(base_next_stats["atk"] * current_size)

        updates = {"name": next_form_name, "stage": next_stage_key.capitalize(), "attr": base_next_stats["attr"], "hp": actual_hp, "atk": actual_atk, "img": base_next_stats["img"]}
        if "skill" in base_next_stats: updates["skill"] = base_next_stats["skill"]

        new_list = self.update_active_digimon(profile, updates)
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$inc": {"digibit": -TRAIN_COST}, "$set": {"digimon_list": new_list, "current_hp": actual_hp + digimon.get("trained_hp", 0)}})
        await interaction.followup.send(f"✨ **EVOLVED!** Partner is now **{next_form_name}**!", ephemeral=True)

    # ========================================================================
    # MARKET COMMANDS & HANDLERS 
    # ========================================================================

    @app_commands.command(name="market", description="Open Marketplace to buy or sell items via Dynamic Dropdowns")
    async def market_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        listings = await market_col.find({}).sort("created_at", -1).to_list(15)
        
        embed = discord.Embed(title="🏪 Digital Marketplace Shop", color=discord.Color.purple())
        if not listings:
            embed.description = "*Market is currently empty. Use the buttons below to sell or purchase.*"
        else:
            desc = ""
            for item in listings:
                desc += f"📦 **{item['item_name']}**\n🆔 ID: `{item['listing_id']}` | 💰 **{item['price']:.2f} Bits** | 👤 Seller: {item['seller_name']}\n\n"
            embed.description = desc[:4000]
            
        await interaction.followup.send(embed=embed, view=MarketShopView(self, interaction.user.id), ephemeral=True)

    async def handle_market_buy(self, interaction: discord.Interaction, listing_id: str):
        await interaction.response.defer(ephemeral=True)
        buyer_id = interaction.user.id
        listing = await market_col.find_one({"listing_id": listing_id.upper()})
        if not listing: return await interaction.followup.send("❌ **Listing Not Found!**", ephemeral=True)
        if listing.get("seller_id") == buyer_id: return await interaction.followup.send("❌ Cannot buy your own listing.", ephemeral=True)
        
        buyer_profile = await rpg_profiles_col.find_one({"user_id": buyer_id})
        if not buyer_profile or buyer_profile.get("digibit", 0.0) < listing["price"]: 
            return await interaction.followup.send("❌ **Insufficient Digibits.**", ephemeral=True)
            
        price = listing["price"]
        await rpg_profiles_col.update_one({"user_id": buyer_id}, {"$inc": {"digibit": -price}, "$push": {"inventory": listing.get("raw_gear_name", listing.get("name"))}})
        
        if listing.get("seller_id"):
            await rpg_profiles_col.update_one({"user_id": listing["seller_id"]}, {"$inc": {"digibit": price}})
            
        await market_col.delete_one({"_id": listing["_id"]})
        await interaction.followup.send(f"🛍️ **Purchased {listing.get('item_name', listing.get('name'))} for {price:.2f} Digibits!**", ephemeral=True)

    async def handle_market_sell_enhanced(self, interaction: discord.Interaction, target: str, price_str: str):
        await interaction.response.defer(ephemeral=True)
        try: price = round(float(price_str), 2)
        except: return await interaction.followup.send("❌ Invalid price format.", ephemeral=True)
        if price <= 0: return await interaction.followup.send("❌ Price must be > 0.", ephemeral=True)
        
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        if not profile or target not in profile.get("inventory", []):
            return await interaction.followup.send("❌ Item not found in your inventory bag.", ephemeral=True)
            
        await rpg_profiles_col.update_one({"user_id": user_id}, {"$pull": {"inventory": target}})
        listing_id = f"LIT-{random.randint(1000, 9999)}"
        
        await market_col.insert_one({
            "listing_id": listing_id, "seller_id": user_id, "seller_name": interaction.user.name, 
            "item_type": "gear", "item_name": target, "raw_gear_name": target, "quantity": 1, 
            "price": price, "created_at": int(time.time())
        })
        await interaction.followup.send(f"🏪 **Successfully listed {target} for {price:.2f} Bits!** (ID: `{listing_id}`)", ephemeral=True)

    # ========================================================================
    # WORLD BOSS & REAL-TIME LEADERBOARD SYSTEM
    # ========================================================================

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
        embed = self.generate_boss_embed(boss_data)
        channels = await boss_channels_col.find({}).to_list(None)
        active_messages = []
        
        for c in channels:
            if url := c.get("webhook_url"):
                try:
                    async with aiohttp.ClientSession() as s:
                        webhook = discord.Webhook.from_url(url, session=s)
                        msg = await webhook.send(content="🚨 **WORLD BOSS HAS SPAWNED! PREPARE FOR BATTLE!**", embed=embed, view=CombatView(self), username="SYSTEM RAID", wait=True)
                        active_messages.append({"channel_id": c["channel_id"], "message_id": msg.id})
                except Exception as e:
                    print(f"Announcement failed: {e}")
                    
        if active_messages: await world_boss_col.update_one({"_id": boss_data["_id"]}, {"$set": {"active_messages": active_messages}})
        if not self.live_boss_update_loop.is_running(): self.live_boss_update_loop.start()

    @tasks.loop(seconds=5)
    async def live_boss_update_loop(self):
        bosses = await world_boss_col.find({"is_active": True}).to_list(None)
        for boss in bosses:
            embed = self.generate_boss_embed(boss)
            active_messages = boss.get("active_messages", [])
            updated_messages = []

            for msg_info in active_messages:
                try:
                    channel = self.bot.get_channel(msg_info["channel_id"]) or await self.bot.fetch_channel(msg_info["channel_id"])
                    if msg_info.get("is_interaction"):
                        msg = await channel.fetch_message(msg_info["message_id"])
                        await msg.edit(embed=embed, view=CombatView(self))
                        updated_messages.append(msg_info)
                    else:
                        webhook = next((w for w in await channel.webhooks() if w.user == self.bot.user), None)
                        if webhook:
                            await webhook.edit_message(msg_info["message_id"], embed=embed, view=CombatView(self))
                            updated_messages.append(msg_info)
                except discord.NotFound: pass 
                except Exception: updated_messages.append(msg_info) 

            if len(active_messages) != len(updated_messages):
                await world_boss_col.update_one({"_id": boss["_id"]}, {"$set": {"active_messages": updated_messages}})

    @live_boss_update_loop.before_loop
    async def before_live_boss_update(self): await self.bot.wait_until_ready()  

    @app_commands.command(name="spawn_boss", description="[Admin] Force spawn a World Boss")
    async def spawn_boss(self, interaction: discord.Interaction, name: str, hp: int):
        if not interaction.user.guild_permissions.administrator: 
            return await interaction.response.send_message("❌ Admin privileges required.", ephemeral=True)
        await world_boss_col.update_many({"is_active": True, "party_id": {"$exists": False}}, {"$set": {"is_active": False}})
        
        new_boss = {"boss_id": str(uuid.uuid4()), "name": name, "max_hp": hp, "current_hp": hp, "hp": hp, "attr": "Unknown", "img": "", "is_active": True, "damage_log": {}, "active_messages": [], "participants": []}
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
            {"name": "Devimon", "hp": 25_000_000, "attr": "Virus", "img": "https://digimon.net/cimages/digimon/devimon.jpg"}, 
            {"name": "WarGreymon", "hp": 100_000_000, "attr": "Vaccine", "img": "https://digimon.net/cimages/digimon/wargreymon.jpg"},
            {"name": "Apocalymon", "hp": 250_000_000, "attr": "Unknown", "img": "https://digimon.net/cimages/digimon/apocalymon.jpg"}
        ]
        chosen = random.choice(boss_roster)
        new_boss = {"boss_id": str(uuid.uuid4()), "name": chosen["name"], "max_hp": chosen["hp"], "current_hp": chosen["hp"], "hp": chosen["hp"], "attr": chosen["attr"], "img": chosen["img"], "is_active": True, "damage_log": {}, "active_messages": [], "participants": []}
        
        result = await world_boss_col.insert_one(new_boss)
        new_boss["_id"] = result.inserted_id
        await self.broadcast_initial_boss(new_boss)

    @auto_spawn_boss.before_loop
    async def before_auto_spawn(self): await self.bot.wait_until_ready()

    # ========================================================================
    # COMBAT LOGIC COMMAND SYSTEM
    # ========================================================================
    
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
        user_id = interaction.user.id
        if user_id in self.auto_attackers:
            self.auto_attackers.remove(user_id)
            if user_id in auto_attack_cache:
                del auto_attack_cache[user_id]
            await interaction.response.send_message("🔴 **Auto-Attack Disabled.**", ephemeral=True)
        else:
            self.auto_attackers.add(user_id)
            party = await parties_col.find_one({"members.user_id": user_id})
            boss = await world_boss_col.find_one({"is_active": True, "party_id": str(party["_id"])}) if party else None
            if not boss: boss = await world_boss_col.find_one({"is_active": True, "party_id": {"$exists": False}})
            if boss:
                await self.process_auto_attack_interaction(interaction, boss.get("boss_id", str(boss["_id"])), 500) 
            else:
                await interaction.response.send_message("❌ **No active Boss found.**", ephemeral=True)

    async def process_auto_attack_interaction(self, interaction: discord.Interaction, boss_id: str, base_dmg: int):
        user_id = interaction.user.id
        current_time = time.time()
        
        if user_id not in auto_attack_cache:
            auto_attack_cache[user_id] = {
                "boss_id": boss_id,
                "accumulated_dmg": 0,
                "last_notify": current_time
            }
            
        auto_attack_cache[user_id]["accumulated_dmg"] += base_dmg
        
        if current_time - auto_attack_cache[user_id]["last_notify"] >= 30.0:
            final_dmg = auto_attack_cache[user_id]["accumulated_dmg"]
            
            auto_attack_cache[user_id]["accumulated_dmg"] = 0
            auto_attack_cache[user_id]["last_notify"] = current_time
            
            await world_boss_col.update_one(
                {"boss_id": boss_id},
                {"$inc": {"hp": -final_dmg, "current_hp": -final_dmg}, "$addToSet": {"participants": user_id}}
            )
            
            await self.process_boss_damage(interaction, boss_id, final_dmg)
            
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"🔄 [Auto-Combat] The system has been fully synchronized: {final_dmg:,} Damage dealt to the Boss in the last 30 seconds.", 
                    ephemeral=True
                )
        else:
            if not interaction.response.is_done():
                await interaction.response.send_message("⚔️ The auto-attack continues to accumulate damage..", ephemeral=True)

    async def handle_manual_attack(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) 
        current_time = int(time.time())
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        
        if profile and current_time - profile.get("last_manual_atk", 0) < 4:
            return await interaction.followup.send("⏳ **Cooldown!** Slow down your strikes.", ephemeral=True)
            
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"last_manual_atk": current_time}})
        msg, should_stop = await self.execute_combat_turn(interaction.user.id, interaction.user.display_name)
        
        if msg: await interaction.followup.send(msg, ephemeral=True)
        if should_stop: self.auto_attackers.discard(interaction.user.id)

    async def handle_protect(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        current_time = int(time.time())
        if profile and current_time - profile.get("last_protect", 0) < 45: return await interaction.followup.send("⏳ Protect Cooldown!", ephemeral=True)
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
            {"_id": boss["_id"]}, {"$inc": {"current_hp": -final_dmg, "hp": -final_dmg, f"damage_log.{str(user_id)}": final_dmg}, "$addToSet": {"participants": user_id}},
            return_document=pymongo.ReturnDocument.AFTER
        )
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
            await self.trigger_chain_boss_respawn(result.get("participants", []))
            return (msg + "\n🎉 **BOSS DEFEATED!**", True)
        return (msg, False)

    async def distribute_boss_loot(self, boss_data: dict):
        await world_boss_col.update_one({"_id": boss_data["_id"]}, {"$set": {"is_active": False}})
        if "party_id" not in boss_data:
            await world_boss_col.update_one({"type": "spawn_config"}, {"$set": {"next_spawn": int(time.time()) + 3600}}, upsert=True)
        
        announcement = f"🎉 **BOSS {boss_data['name']} DEFEATED!**\n\n**🏆 Rewards Summary:**\n"
        sorted_log = sorted(boss_data.get("damage_log", {}).items(), key=lambda x: x[1], reverse=True)
        total_hp = boss_data.get("max_hp", 1)

        participant_ids = [int(uid_str) for uid_str, _ in sorted_log]
        if participant_ids: await rpg_profiles_col.update_many({"user_id": {"$in": participant_ids}}, {"$inc": {"myk_coin": 1}})

        for rank, (uid_str, dmg) in enumerate(sorted_log, 1):
            dmg_percent = dmg / total_hp
            orbs_earned = max(1, int(dmg_percent * 10)) + (10 if rank == 1 else 5 if rank <= 3 else 0)
            reward_str = f"+{orbs_earned} Orbs & 1 MyK"
            update_query = {"$inc": {"orb": orbs_earned}}

            if rank <= 3 and random.random() < 0.30:
                reward_str += " & 🍎"
                update_query.setdefault("$push", {})["inventory"] = "Size Reroll Fruit"
                
            if random.random() < (0.20 / rank) + dmg_percent:
                divine_drop = random.choice(["Divine Blade (Unlocked)", "Divine Aegis (Unlocked)", "Divine Vice (Unlocked)"])
                reward_str += f" & 👑 Divine Gear"
                update_query.setdefault("$push", {})
                if "inventory" in update_query["$push"]: update_query["$push"]["inventory"] = {"$each": ["Size Reroll Fruit", divine_drop]}
                else: update_query["$push"]["inventory"] = divine_drop
                
            await rpg_profiles_col.update_one({"user_id": int(uid_str)}, update_query)
            if rank <= 10: announcement += f"#{rank} <@{uid_str}>: {dmg:,} DMG -> {reward_str}\n"

        if "party_id" not in boss_data: await self.broadcast_system_message(announcement)
        else:
            party = await parties_col.find_one({"_id": ObjectId(boss_data["party_id"])})
            if party: await handle_cross_server_chat(self.bot, party, msg_override=announcement)
            
    async def process_boss_damage(self, interaction: discord.Interaction, boss_id: str, damage_dealt: int):
        user_id = interaction.user.id
        boss = await world_boss_col.find_one({"boss_id": boss_id})
        if not boss: return

        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Bạn đã gây {damage_dealt:,} sát thương lên {boss['name']}.", ephemeral=True)
        except Exception:
            pass

        updated_boss = await world_boss_col.find_one({"boss_id": boss_id})
        current_hp = updated_boss.get("current_hp", updated_boss.get("hp", 0))
        if updated_boss and current_hp <= 0:
            await world_boss_col.delete_one({"boss_id": boss_id})
            await self.trigger_chain_boss_respawn(updated_boss.get("participants", []))

    async def trigger_chain_boss_respawn(self, participants: list):
        total_participant_atk = 0
        
        if participants:
            async for profile in rpg_profiles_col.find({"user_id": {"$in": participants}}):
                active_id = profile.get("active_digimon_id")
                active_digi = next((d for d in profile.get("digimon_list", []) if d["id"] == active_id), None)
                if active_digi:
                    total_participant_atk += active_digi.get("atk", 150)
        
        if total_participant_atk == 0:
            total_participant_atk = 3000

        boss_names_pool = ["Omnimon Zwart", "Alphamon Ouryuken", "Beelzemon X", "Gallantmon X", "Mastemon", "Lucemon Larva", "Susanoomon"]
        random_name = f"Vanguard {random.choice(boss_names_pool)} [Chain Raid]"
        
        calculated_hp = random.randint(total_participant_atk * 15, total_participant_atk * 30)
        calculated_atk = random.randint(int(total_participant_atk * 0.15), int(total_participant_atk * 0.3))

        new_boss = {
            "boss_id": str(uuid.uuid4()),
            "name": random_name,
            "hp": calculated_hp,
            "current_hp": calculated_hp,
            "max_hp": calculated_hp,
            "atk": calculated_atk,
            "participants": [],
            "is_active": True,
            "damage_log": {},
            "active_messages": [],
            "spawned_at": datetime.utcnow()
        }
        
        result = await world_boss_col.insert_one(new_boss)
        new_boss["_id"] = result.inserted_id
        
        cross_server_announcement = "🚨 **[SYSTEM RAID]** Raid boss spawned, please use `/combat` to join!"
        await self.broadcast_system_message(content=cross_server_announcement)   
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
            await interaction.followup.send("✅ Success! Kênh Boss đã được thiết lập.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Lỗi: Thiếu quyền `Manage Webhooks`.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Lỗi: {e}", ephemeral=True)    

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild: return
        channel_config = await boss_channels_col.find_one({"guild_id": message.guild.id})
        if not channel_config or channel_config.get("channel_id") != message.channel.id: return
            
        other_channels = await boss_channels_col.find({"channel_id": {"$ne": message.channel.id}}).to_list(None)
        if not other_channels: return

        content = message.content
        if message.attachments: content += "\n" + "\n".join([att.url for att in message.attachments])
            
        formatted_username = f"[{message.guild.name[:15]}] {message.author.display_name}"[:77] + "..." if len(f"[{message.guild.name[:15]}] {message.author.display_name}") > 80 else f"[{message.guild.name[:15]}] {message.author.display_name}"
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
        if after.attachments: new_content += "\n" + "\n".join([att.url for att in after.attachments])

        async with aiohttp.ClientSession() as session:
            for target in log.get("targets", []):
                try:
                    webhook = discord.Webhook.from_url(target["webhook_url"], session=session)
                    await webhook.edit_message(target["message_id"], content=new_content)
                except Exception: pass

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot or not message.guild: return
        log = await cross_messages_col.find_one({"source_msg_id": message.id})
        if not log: return

        async with aiohttp.ClientSession() as session:
            for target in log.get("targets", []):
                try:
                    webhook = discord.Webhook.from_url(target["webhook_url"], session=session)
                    await webhook.delete_message(target["message_id"])
                except Exception: pass
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

async def setup(bot):
    await bot.add_cog(RPGSystemCog(bot))