import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import aiohttp
import random
import time
import uuid
from datetime import datetime

# Import collections from Database.py
from Database import rpg_profiles_col, world_boss_col, boss_channels_col

market_col = rpg_profiles_col.database["rpg_marketplace"]

# ========================================================================
# UI INTERFACE CLASSES (VIEWS & MODALS)
# ========================================================================

class DigiBagSelect(discord.ui.Select):
    def __init__(self, digimon_list: list, current_active_id: str, cog_instance):
        self.cog = cog_instance
        options = []
        for digi in digimon_list[:25]:
            is_active = "✅ (Active)" if digi["id"] == current_active_id else ""
            options.append(discord.SelectOption(
                label=f"{digi['name']} {is_active}".strip(),
                description=f"Stage: {digi['stage']} | ATK: {digi['atk']} | HP: {digi['hp']}",
                value=digi["id"],
                emoji="🐾"
            ))
        if not options:
            options = [discord.SelectOption(label="Empty", value="empty")]
            
        super().__init__(placeholder="🐾 Choose a Digimon to accompany...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "empty":
            return await interaction.response.send_message("❌ **Digimon Bag is empty!**", ephemeral=True)
        await self.cog.handle_switch_digimon(interaction, self.values[0])

class BagView(discord.ui.View):
    def __init__(self, digimon_list: list, current_active_id: str, cog_instance):
        super().__init__(timeout=120)
        self.add_item(DigiBagSelect(digimon_list, current_active_id, cog_instance))

class InventorySelect(discord.ui.Select):
    def __init__(self, inventory: list, cog_instance):
        self.cog = cog_instance
        interactable_items = [item for item in inventory if "(Unlocked)" in item or item == "Size Reroll Fruit"]
        
        if not interactable_items:
            options = [discord.SelectOption(label="Empty Inventory", value="empty")]
        else:
            unique_items = list(set(interactable_items))[:25]
            options = [
                discord.SelectOption(
                    label=item, 
                    description="Consume Fruit" if item == "Size Reroll Fruit" else "Equip Gear",
                    emoji="🍎" if item == "Size Reroll Fruit" else "🛡️"
                ) for item in unique_items
            ]
        super().__init__(placeholder="🎒 Select an item to use/equip...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "empty": return await interaction.response.send_message("❌ **No usable items.**", ephemeral=True)
        await self.cog.handle_inventory_use(interaction, self.values[0])

class ProfileView(discord.ui.View):
    def __init__(self, profile: dict, cog_instance):
        super().__init__(timeout=300)
        self.user_id = profile.get("user_id")
        self.cog = cog_instance
        self.add_item(InventorySelect(profile.get("inventory", []), cog_instance))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ **Access Denied!** Not your profile.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Heal (120s CD)", style=discord.ButtonStyle.success, custom_id="btn_heal", emoji="✨")
    async def heal_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_heal(interaction)

    @discord.ui.button(label="Evolve (50 Orbs)", style=discord.ButtonStyle.primary, custom_id="btn_evolve", emoji="🧬")
    async def evolve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_evolve(interaction)

# --- MARKET UI ---
class SellModal(discord.ui.Modal, title='Sell to Marketplace'):
    item_type = discord.ui.TextInput(label='Type (gear / orb / core)', placeholder='gear', max_length=10)
    item_target = discord.ui.TextInput(label='Exact Gear Name OR Quantity', placeholder='e.g., Chrome Dagger (Unlocked) OR 10')
    price = discord.ui.TextInput(label='Price in Digibits', placeholder='e.g., 15.5')
    def __init__(self, cog_instance):
        super().__init__()
        self.cog = cog_instance
    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.handle_market_sell(interaction, self.item_type.value.lower(), self.item_target.value, self.price.value)

class BuyModal(discord.ui.Modal, title='Buy from Marketplace'):
    listing_id = discord.ui.TextInput(label='Listing ID', placeholder='e.g., LIT-1234', max_length=15)
    def __init__(self, cog_instance):
        super().__init__()
        self.cog = cog_instance
    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.handle_market_buy(interaction, self.listing_id.value)

class MarketView(discord.ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=None)
        self.cog = cog_instance

    @discord.ui.button(label="View Market", style=discord.ButtonStyle.blurple, emoji="🔄")
    async def view_market(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_market_view(interaction)
    @discord.ui.button(label="Buy Item", style=discord.ButtonStyle.success, emoji="🛒")
    async def buy_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BuyModal(self.cog))
    @discord.ui.button(label="Sell Item", style=discord.ButtonStyle.danger, emoji="📦")
    async def sell_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SellModal(self.cog))

# --- COMBAT UI ---
class CombatView(discord.ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=None)
        self.cog = cog_instance

    @discord.ui.button(label="Attack", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def attack_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_manual_attack(interaction)
    @discord.ui.button(label="Toggle Auto-Attack", style=discord.ButtonStyle.primary, emoji="🤖")
    async def auto_attack_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.toggle_auto_attack(interaction)
    @discord.ui.button(label="Protect (45s CD)", style=discord.ButtonStyle.secondary, emoji="🛡️")
    async def protect_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_protect(interaction)

# --- FARM & MINE UI ---
class FarmDungeonSelect(discord.ui.Select):
    def __init__(self, cog_instance):
        self.cog = cog_instance
        options = [
            discord.SelectOption(label="Digital Forest (Weapons)", value="digital_forest", emoji="🌲"),
            discord.SelectOption(label="Factorial Town (Armors)", value="factorial_town", emoji="🏭"),
            discord.SelectOption(label="Server Continent (Vices)", value="server_continent", emoji="🏜️"),
            discord.SelectOption(label="🛑 Stop Auto Dungeon", value="stop", emoji="⏹️")
        ]
        super().__init__(placeholder="🏰 Set Auto-Dungeon location...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await self.cog.handle_toggle_auto_dungeon(interaction, self.values[0])

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
        "server_continent": {"name": "Server Continent", "description": "Farms Vices."}
    }

    # DIGIMON DATA WITH IMAGES
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

    def cog_unload(self):
        self.auto_spawn_boss.cancel()
        self.farm_system_loop.cancel()

    # --- HELPER METHODS ---
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

    async def verify_and_refresh_cores(self, user_id: int, profile: dict) -> int:
        current_date = datetime.utcnow().strftime("%Y-%m-%d")
        if profile.get("last_core_reset") != current_date:
            max_cores = 120 if profile.get("is_vip") else 100
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {"digicore": max_cores, "last_core_reset": current_date}})
            return max_cores
        return profile.get("digicore", 0)

    def roll_pve_loot(self, dungeon: str) -> str:
        is_high_tier = random.random() < 0.10
        if dungeon == "digital_forest": loot_base = "Chrome Dagger" if is_high_tier else "Rusty Sword"
        elif dungeon == "factorial_town": loot_base = "Digivice Shield" if is_high_tier else "Rusty Armor"
        else: loot_base = "Chrome Vice" if is_high_tier else "Rusty Vice"
        return f"{loot_base}{' (Unlocked)' if random.random() < 0.20 else ' (Locked)'}"

    # ========================================================================
    # DASHBOARD & PROFILE COMMANDS
    # ========================================================================

    @app_commands.command(name="rpg_profile", description="View your Tamer profile")
    async def rpg_profile(self, interaction: discord.Interaction):
        await interaction.response.defer()
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile: return await interaction.followup.send("❌ Please use `/hatch` to create a profile.")

        digimon = self.get_active_digimon(profile)
        stats, gear = self.get_total_stats(profile), profile.get("gear", {})
        embed = discord.Embed(title=f"📱 Tamer {profile.get('ign')}", color=discord.Color.teal())
        
        if digimon:
            size_display = f"{digimon.get('size', 1.0) * 100:.1f}%"
            embed.set_thumbnail(url=digimon.get("img", interaction.user.display_avatar.url))
            skill_info = f"\n**Skill:** {digimon.get('skill', {}).get('name')}" if "skill" in digimon else ""
            train_info = f"\n**Trained:** +{digimon.get('trained_atk', 0)} ATK | +{digimon.get('trained_hp', 0)} HP"
            embed.description = f"**Partner:** {digimon.get('name')} ({digimon.get('stage')})\n**Attr:** {digimon.get('attr')}\n**Size:** `{size_display}`{skill_info}{train_info}"
            embed.add_field(name="❤️ HP", value=f"{profile.get('current_hp')}/{stats['hp']}", inline=True)
            embed.add_field(name="⚔️ ATK", value=str(stats['atk']), inline=True)
            embed.add_field(name="🎯 CRIT", value=f"{stats['crit_rate']}% (x{stats['crit_dmg']})", inline=True)
            
        embed.add_field(name="💰 Assets", value=f"🌐 **{profile.get('digibit', 0):.2f} Digibits**\n🔮 **{profile.get('orb', 0)} Orbs**\n🧬 **{profile.get('hatch_core', 0)} Hatch Cores**\n⚡ **{profile.get('digicore', 0)} Energy**", inline=False)
        embed.add_field(name="Equipment", value=f"⚔️ {gear.get('weapon', 'None')}\n🛡️ {gear.get('armor', 'None')}\n📿 {gear.get('vice', 'None')}", inline=False)
        
        await interaction.followup.send(embed=embed, view=ProfileView(profile, self))

    @app_commands.command(name="bag", description="Open Digimon bag")
    async def bag(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile: return await interaction.followup.send("❌ Profile does not exist.", ephemeral=True)
        
        digimon_list = profile.get("digimon_list", [])
        if not digimon_list: return await interaction.followup.send("❌ You don't have any Digimon.", ephemeral=True)
        
        embed = discord.Embed(title="🐾 Your Digimon Bag", description=f"Quantity: {len(digimon_list)}", color=discord.Color.gold())
        await interaction.followup.send(embed=embed, view=BagView(digimon_list, profile.get("active_digimon_id"), self), ephemeral=True)

    @app_commands.command(name="hatch", description=f"Hatch a Rookie Digimon (Costs 5 Hatch Cores)")
    async def hatch(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        if not profile:
            profile = {
                "user_id": user_id, "ign": interaction.user.display_name, 
                "gold": 0, "digibit": 0.0, "orb": 0, "hatch_core": 15, # Đã sửa thành 15 Hatch Cores
                "current_hp": 0, "gear": {"weapon": "None", "armor": "None", "vice": "None"}, 
                "inventory": [], "digicore": 100, "is_vip": False, 
                "last_core_reset": datetime.utcnow().strftime("%Y-%m-%d"),
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

    @app_commands.command(name="train_digimon", description="Train Digimon with Orbs to increase stats")
    @app_commands.choices(stat=[app_commands.Choice(name="ATK (+20 ATK / 5 Orbs)", value="atk"), app_commands.Choice(name="HP (+100 HP / 5 Orbs)", value="hp")])
    async def train_digimon(self, interaction: discord.Interaction, stat: str):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile or profile.get("orb", 0) < 5:
            return await interaction.followup.send("❌ You do not have enough 5 Orbs.", ephemeral=True)
            
        active_digi = self.get_active_digimon(profile)
        if not active_digi: return await interaction.followup.send("❌ Equip a Digimon first.", ephemeral=True)
        
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
        await rpg_profiles_col.update_one(
            {"user_id": interaction.user.id}, 
            {"$set": {"digimon_list": new_list}, "$inc": {"orb": -5}}
        )
        await interaction.followup.send(f"🏋️ **Training successful!** {stat.upper()} increased for {active_digi['name']}.", ephemeral=True)

    # ========================================================================
    # FARM & MINE SYSTEM (AUTO & UI)
    # ========================================================================
    
    @app_commands.command(name="farm", description="Open Farming & Mining Dashboard")
    async def farm_dashboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        if not profile: return await interaction.followup.send("❌ Please use `/hatch` to create a profile.", ephemeral=True)
        
        energy = await self.verify_and_refresh_cores(user_id, profile)
        is_auto_mine = profile.get("is_auto_mining", False)
        auto_dungeon = profile.get("auto_dungeon")
        
        embed = discord.Embed(title="🚜 Farming Dashboard", color=discord.Color.green())
        embed.description = "Quản lý việc cày cuốc tự động hoặc thủ công tại đây."
        embed.add_field(name="⚡ Current Energy", value=f"**{energy}**", inline=True)
        embed.add_field(name="⛏️ Auto-Mine Status", value="🟢 **ON**" if is_auto_mine else "🔴 **OFF**", inline=True)
        embed.add_field(name="🏰 Auto-Dungeon Status", value=f"🟢 **{self.DUNGEONS.get(auto_dungeon, {}).get('name', 'Unknown')}**" if auto_dungeon else "🔴 **OFF**", inline=False)
        
        await interaction.followup.send(embed=embed, view=FarmView(self), ephemeral=True)

    async def handle_manual_mine(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        current_time = int(time.time())
        last_mine = profile.get("last_manual_mine", 0)
        
        if current_time - last_mine < 300: # 5 Minutes cooldown
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
        await interaction.followup.send(f"🏰 **Auto-Dungeon set to {self.DUNGEONS[target_dungeon]['name']}!** The bot will clear it every 5 minutes.", ephemeral=True)

    async def handle_view_logs(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        logs = profile.get("farm_logs", [])
        
        embed = discord.Embed(title="📜 System Farm Logs", color=discord.Color.dark_gray())
        if not logs:
            embed.description = "Chưa có dữ liệu cày cuốc tự động."
        else:
            embed.description = "```\n" + "\n".join(logs) + "\n```"
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tasks.loop(minutes=5)
    async def farm_system_loop(self):
        """Chạy ngầm mỗi 5 phút để xử lý Auto Mine & Auto Dungeon"""
        profiles = await rpg_profiles_col.find({"$or": [{"is_auto_mining": True}, {"auto_dungeon": {"$ne": None}}]}).to_list(None)
        
        for profile in profiles:
            user_id = profile["user_id"]
            log_msgs = []
            updates = {"$inc": {}, "$push": {}}
            
            # 1. Processing Auto-Mining (0.25 bit / 1h => ~0.02 bit / 5 min)
            if profile.get("is_auto_mining"):
                updates["$inc"]["digibit"] = updates["$inc"].get("digibit", 0) + 0.02
                log_msgs.append("⛏️ Auto-mine: +0.02 Bits")
                
            # 2. Processing Auto-Dungeon (Consume 5 energy max per 5 mins)
            dungeon = profile.get("auto_dungeon")
            if dungeon:
                energy = profile.get("digicore", 0)
                if energy <= 0:
                    updates["$set"] = {"auto_dungeon": None}
                    log_msgs.append("🛑 No Energy. Stopped Auto-Dungeon.")
                else:
                    runs = min(energy, 5) # 5 runs per cycle to be efficient
                    is_vip = profile.get("is_vip", False)
                    cores = sum(1 for _ in range(runs) if (is_vip or random.random() < 0.60))
                    loot_dropped = [self.roll_pve_loot(dungeon) for _ in range(runs) if random.random() < (0.07 if is_vip else 0.05)]
                    
                    updates["$inc"]["digicore"] = updates["$inc"].get("digicore", 0) - runs
                    updates["$inc"]["digibit"] = updates["$inc"].get("digibit", 0) + runs
                    if cores > 0: updates["$inc"]["hatch_core"] = updates["$inc"].get("hatch_core", 0) + cores
                    if loot_dropped: updates["$push"]["inventory"] = {"$each": loot_dropped}
                        
                    loot_str = f", {cores} Cores, {len(loot_dropped)} Gears" if cores or loot_dropped else ""
                    log_msgs.append(f"🏰 DG({runs}): +{runs} Bits{loot_str}")

            if log_msgs:
                log_entry = f"[{datetime.utcnow().strftime('%H:%M')}] " + " | ".join(log_msgs)
                if "farm_logs" not in updates["$push"]:
                    updates["$push"]["farm_logs"] = {"$each": [log_entry], "$slice": -10} # Lưu tối đa 10 log gần nhất
                    
                # Clean up empty operators to avoid MongoDB errors
                if not updates["$inc"]: del updates["$inc"]
                if not updates["$push"]: del updates["$push"]
                
                await rpg_profiles_col.update_one({"user_id": user_id}, updates)

    @farm_system_loop.before_loop
    async def before_farm_system_loop(self):
        await self.bot.wait_until_ready()

    # ========================================================================
    # UI HANDLERS & EVOLVE
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
        await interaction.followup.send(f"✨ **Healed!** HP: **{max_hp}/{max_hp}**.", ephemeral=True)

    async def handle_evolve(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        digimon = self.get_active_digimon(profile)
        
        if not digimon: return await interaction.followup.send("❌ No Active Digimon.", ephemeral=True)
        if digimon.get("stage") == "Mega": return await interaction.followup.send("❌ Max Level (Mega) reached.", ephemeral=True)
        if profile.get("orb", 0) < 50: return await interaction.followup.send("❌ Need **50 Orbs**.", ephemeral=True)

        next_form_name = self.EVOLUTION_LINE.get(digimon["name"])
        if not next_form_name: return await interaction.followup.send("❌ This Digimon has no next evolution.", ephemeral=True)

        current_stage = digimon.get("stage")
        next_stage_map = {"Rookie": "champion", "Champion": "ultimate", "Ultimate": "mega"}
        next_stage_key = next_stage_map.get(current_stage)
        
        base_next_stats = self.DIGIMON_DATA[next_stage_key][next_form_name]
        current_size = digimon.get("size", 1.0)
        actual_hp, actual_atk = int(base_next_stats["hp"] * current_size), int(base_next_stats["atk"] * current_size)

        updates = {
            "name": next_form_name, 
            "stage": next_stage_key.capitalize(), 
            "attr": base_next_stats["attr"], 
            "hp": actual_hp, 
            "atk": actual_atk, 
            "img": base_next_stats["img"]
        }
        if "skill" in base_next_stats:
            updates["skill"] = base_next_stats["skill"]

        new_list = self.update_active_digimon(profile, updates)
        await rpg_profiles_col.update_one(
            {"user_id": interaction.user.id}, 
            {"$inc": {"orb": -50}, "$set": {"digimon_list": new_list, "current_hp": actual_hp + digimon.get("trained_hp", 0)}}
        )
        await interaction.followup.send(f"✨ **EVOLVED!** Partner is now **{next_form_name}**!", ephemeral=True)

    # ========================================================================
    # MARKET HANDLERS
    # ========================================================================
    async def handle_market_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        listings = await market_col.find({}).sort("created_at", -1).to_list(15) 
        if not listings: return await interaction.followup.send("🏪 Market is empty.", ephemeral=True)
        embed = discord.Embed(title="🏪 Active Listings", color=discord.Color.purple())
        for item in listings: embed.add_field(name=f"📦 {item['item_name']}", value=f"🆔 `{item['listing_id']}` | 💰 **{item['price']:.2f} Bits** | 👤 {item['seller_name']}", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def handle_market_buy(self, interaction: discord.Interaction, listing_id: str):
        await interaction.response.defer(ephemeral=True)
        buyer_id = interaction.user.id
        listing = await market_col.find_one({"listing_id": listing_id.upper()})
        if not listing: return await interaction.followup.send("❌ **Listing Not Found!**", ephemeral=True)
        if listing["seller_id"] == buyer_id: return await interaction.followup.send("❌ Cannot buy your own item.", ephemeral=True)
        buyer_profile = await rpg_profiles_col.find_one({"user_id": buyer_id})
        if not buyer_profile or buyer_profile.get("digibit", 0.0) < listing["price"]: return await interaction.followup.send("❌ **Insufficient Digibits.**", ephemeral=True)
        price = listing["price"]
        await rpg_profiles_col.update_one({"user_id": buyer_id}, {"$inc": {"digibit": -price}})
        await rpg_profiles_col.update_one({"user_id": listing["seller_id"]}, {"$inc": {"digibit": price}})
        if listing["item_type"] == "gear": await rpg_profiles_col.update_one({"user_id": buyer_id}, {"$push": {"inventory": listing["raw_gear_name"]}})
        elif listing["item_type"] == "orb": await rpg_profiles_col.update_one({"user_id": buyer_id}, {"$inc": {"orb": listing["quantity"]}})
        elif listing["item_type"] == "core": await rpg_profiles_col.update_one({"user_id": buyer_id}, {"$inc": {"hatch_core": listing["quantity"]}})
        await market_col.delete_one({"_id": listing["_id"]})
        await interaction.followup.send(f"🛍️ **Purchased {listing['item_name']} for {price:.2f} Digibits!**", ephemeral=True)

    async def handle_market_sell(self, interaction: discord.Interaction, item_type: str, target: str, price_str: str):
        await interaction.response.defer(ephemeral=True)
        try: price = round(float(price_str), 2)
        except: return await interaction.followup.send("❌ Invalid price format.", ephemeral=True)
        if price <= 0: return await interaction.followup.send("❌ Price must be > 0.", ephemeral=True)
        if item_type not in ["gear", "orb", "core"]: return await interaction.followup.send("❌ Type must be 'gear', 'orb', or 'core'.", ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        display_name, qty = "", 1
        if item_type == "gear":
            if target not in profile.get("inventory", []) or not target.endswith("(Unlocked)"): return await interaction.followup.send("❌ Item not found or locked.", ephemeral=True)
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$pull": {"inventory": target}})
            display_name = target
        else:
            qty = int(target)
            db_field = "orb" if item_type == "orb" else "hatch_core"
            if profile.get(db_field, 0) < qty: return await interaction.followup.send("❌ Insufficient quantity.", ephemeral=True)
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$inc": {db_field: -qty}})
            display_name = f"{qty}x {'World Boss Orb' if item_type == 'orb' else 'Hatch Core'}"
        listing_id = f"LIT-{random.randint(1000, 9999)}"
        await market_col.insert_one({"listing_id": listing_id, "seller_id": user_id, "seller_name": interaction.user.name, "item_type": item_type, "item_name": display_name, "raw_gear_name": target if item_type == "gear" else "", "quantity": qty, "price": price, "created_at": int(time.time())})
        await interaction.followup.send(f"🏪 **Listed {display_name} for {price:.2f} Bits!** (ID: `{listing_id}`)", ephemeral=True)

    # ========================================================================
    # COMBAT ENGINE
    # ========================================================================
    # ========================================================================
    # WORLD BOSS & REAL-TIME LEADERBOARD SYSTEM
    # ========================================================================

    async def broadcast_initial_boss(self, boss_data: dict):
        embed = self.generate_boss_embed(boss_data)
        channels = await boss_channels_col.find({}).to_list(None)
        
        active_messages = []
        for c in channels:
            if url := c.get("webhook_url"):
                try:
                    async with aiohttp.ClientSession() as s:
                        webhook = discord.Webhook.from_url(url, session=s)
                        # Gửi tin nhắn mới qua Webhook
                        msg = await webhook.send(embed=embed, username="SYSTEM RAID", wait=True)
                        active_messages.append({
                            "channel_id": c["channel_id"],
                            "message_id": msg.id
                        })
                except Exception as e:
                    print(f"Không thể gửi thông báo Boss tới kênh {c['channel_id']}: {e}")
                    
        # Lưu toàn bộ Message IDs vào Database để loop update
        if active_messages:
            await world_boss_col.update_one({"_id": boss_data["_id"]}, {"$set": {"active_messages": active_messages}})
        
        # Bắt đầu vòng lặp Live Update nếu nó chưa chạy
        if not self.live_boss_update_loop.is_running():
            self.live_boss_update_loop.start()

    @tasks.loop(minutes=1)
    async def auto_spawn_boss(self):
        config = await world_boss_col.find_one({"type": "spawn_config"})
        if not config or "next_spawn" not in config or int(time.time()) < config["next_spawn"]: return
        if await world_boss_col.find_one({"is_active": True}): return
        
        await world_boss_col.update_one({"type": "spawn_config"}, {"$unset": {"next_spawn": ""}})
        
        # Nâng mức HP cho liên server
        boss_roster = [
            {"name": "Devimon", "hp": 25_000_000, "attr": "Virus", "img": "https://digimon.net/cimages/digimon/devimon.jpg"}, 
            {"name": "WarGreymon", "hp": 100_000_000, "attr": "Vaccine", "img": "https://digimon.net/cimages/digimon/wargreymon.jpg"},
            {"name": "Apocalymon", "hp": 250_000_000, "attr": "Unknown", "img": "https://digimon.net/cimages/digimon/apocalymon.jpg"}
        ]
        chosen_boss = random.choice(boss_roster)
        
        new_boss = {
            "name": chosen_boss["name"], 
            "max_hp": chosen_boss["hp"], 
            "current_hp": chosen_boss["hp"], 
            "attr": chosen_boss["attr"], 
            "img": chosen_boss.get("img", ""), 
            "is_active": True, 
            "damage_log": {},
            "active_messages": [] # Chuẩn bị mảng rỗng để hứng Message IDs
        }
        
        result = await world_boss_col.insert_one(new_boss)
        new_boss["_id"] = result.inserted_id
        
        await self.broadcast_initial_boss(new_boss)

    @app_commands.command(name="spawn_boss", description="[Admin] Force spawn a World Boss")
    async def spawn_boss(self, interaction: discord.Interaction, name: str, hp: int):
        if not interaction.user.guild_permissions.administrator: 
            return await interaction.response.send_message("❌ **Access Denied!** Admin privileges required.", ephemeral=True)
        
        # Dọn dẹp boss cũ nếu có
        await world_boss_col.update_many({"is_active": True}, {"$set": {"is_active": False}})
        
        new_boss = {
            "name": name, 
            "max_hp": hp, 
            "current_hp": hp, 
            "attr": "Unknown", 
            "img": "", 
            "is_active": True, 
            "damage_log": {},
            "active_messages": []
        }
        
        result = await world_boss_col.insert_one(new_boss)
        new_boss["_id"] = result.inserted_id
        
        await interaction.response.send_message(f"⚔️ Đã cưỡng chế gọi Boss **{name}**!", ephemeral=True)
        await self.broadcast_initial_boss(new_boss)
    def generate_boss_embed(self, boss_data: dict) -> discord.Embed:
        max_hp = boss_data.get("max_hp", 1)
        current_hp = max(0, boss_data.get("current_hp", 0))
        hp_percent = current_hp / max_hp
        
        # Tạo thanh máu (HP Bar) bằng emoji
        filled_blocks = int(hp_percent * 10)
        empty_blocks = 10 - filled_blocks
        hp_bar = "🟥" * filled_blocks + "⬛" * empty_blocks

        embed = discord.Embed(
            title=f"🚨 WORLD BOSS: {boss_data['name']} 🚨", 
            description=f"**Hệ:** {boss_data.get('attr', 'Unknown')}\n\n**HP:** {current_hp:,} / {max_hp:,}\n{hp_bar} ({hp_percent * 100:.1f}%)",
            color=discord.Color.dark_red()
        )
        if boss_data.get("img"):
            embed.set_thumbnail(url=boss_data["img"])

        # Xử lý Bảng xếp hạng sát thương (Leaderboard)
        damage_log = boss_data.get("damage_log", {})
        if damage_log:
            # Sắp xếp top người chơi gây sát thương cao nhất
            sorted_log = sorted(damage_log.items(), key=lambda x: x[1], reverse=True)[:5] # Lấy Top 5
            lb_text = ""
            medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
            for idx, (uid_str, dmg) in enumerate(sorted_log):
                lb_text += f"{medals[idx]} <@{uid_str}>: **{dmg:,}** DMG\n"
            embed.add_field(name="🏆 TOP SÁT THƯƠNG", value=lb_text, inline=False)
        else:
            embed.add_field(name="🏆 TOP SÁT THƯƠNG", value="Chưa có ai tấn công...", inline=False)

        embed.set_footer(text="Đang cập nhật trực tiếp (Real-time)...")
        return embed
    
    @tasks.loop(seconds=5)
    async def live_boss_update_loop(self):
        boss = await world_boss_col.find_one({"is_active": True})
        if not boss: return

        embed = self.generate_boss_embed(boss)
        active_messages = boss.get("active_messages", [])
        updated_messages = []

        for msg_info in active_messages:
            try:
                channel = self.bot.get_channel(msg_info["channel_id"])
                if not channel:
                    channel = await self.bot.fetch_channel(msg_info["channel_id"])
                
                # Fetch webhook message if using webhook, or bot message
                webhook = next((w for w in await channel.webhooks() if w.user == self.bot.user), None)
                if webhook:
                    await webhook.edit_message(msg_info["message_id"], embed=embed)
                    updated_messages.append(msg_info)
            except discord.NotFound:
                pass # Tin nhắn đã bị xóa, bỏ qua
            except Exception as e:
                print(f"Lỗi cập nhật Boss UI: {e}")
                updated_messages.append(msg_info) # Giữ lại để thử lại sau

        # Cập nhật lại danh sách tin nhắn hợp lệ vào DB
        if len(active_messages) != len(updated_messages):
            await world_boss_col.update_one({"_id": boss["_id"]}, {"$set": {"active_messages": updated_messages}})

    @live_boss_update_loop.before_loop
    async def before_live_boss_update(self):
        await self.bot.wait_until_ready()  
    async def toggle_auto_attack(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        if user_id in self.auto_attackers:
            self.auto_attackers.discard(user_id)
            await interaction.followup.send("🛑 **Auto-Attack DEACTIVATED.**", ephemeral=True)
        else:
            self.auto_attackers.add(user_id)
            await interaction.followup.send("🤖 **Auto-Attack ACTIVATED!** Initiating sequence...", ephemeral=True)
            self.bot.loop.create_task(self.auto_attack_loop(user_id, interaction.user.display_name, interaction.channel))

    async def auto_attack_loop(self, user_id: int, user_name: str, channel: discord.TextChannel):
        while user_id in self.auto_attackers:
            msg, should_stop = await self.execute_combat_turn(user_id, user_name)
            if msg: await channel.send(msg)
            if should_stop:
                self.auto_attackers.discard(user_id)
                break
            await asyncio.sleep(4.5)

    async def handle_manual_attack(self, interaction: discord.Interaction):
        # Trả lời ẩn cho riêng người bấm nút
        await interaction.response.defer(ephemeral=False) 
        
        current_time = int(time.time())
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        
        if profile and current_time - profile.get("last_manual_atk", 0) < 4:
            return await interaction.followup.send("⏳ **Cooldown!** You is hit too fast.", ephemeral=True)
            
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"last_manual_atk": current_time}})
        
        # GỌI HÀM TÍNH DAMAGE (đã có ở bản trước)
        msg, should_stop = await self.execute_combat_turn(interaction.user.id, interaction.user.display_name)
        
        if msg: 
            await interaction.followup.send(msg, ephemeral=True)
        if should_stop: 
            self.auto_attackers.discard(interaction.user.id)

    async def handle_protect(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        current_time = int(time.time())
        if profile and current_time - profile.get("last_protect", 0) < 45: return await interaction.followup.send("⏳ **Protect Cooldown!**", ephemeral=True)
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"is_protecting": True, "last_protect": current_time}})
        await interaction.followup.send("🛡️ **Defensive Stance Active!**", ephemeral=True)

    async def execute_combat_turn(self, user_id: int, user_name: str) -> tuple:
        boss = await world_boss_col.find_one({"is_active": True})
        if not boss: return ("❌ **No active World Boss.**", True)

        player = await rpg_profiles_col.find_one({"user_id": user_id})
        digimon = self.get_active_digimon(player)
        if not player or not digimon: return ("❌ **No Digimon!** Hatch an egg.", True)
        if player.get("current_hp", 0) <= 0: return (f"☠️ <@{user_id}> **Your Digimon fainted!** Use Heal.", True)

        stats = self.get_total_stats(player)
        raw_dmg = stats["atk"] + random.randint(-5, 10)
        is_crit = random.randint(1, 100) <= stats["crit_rate"]
        if is_crit: raw_dmg *= stats["crit_dmg"]
        
        skill_msg = ""
        if "skill" in digimon:
            skill_data = digimon["skill"]
            if random.random() < skill_data["chance"]:
                raw_dmg *= skill_data["dmg_mult"]
                skill_msg = f"\n🌟 **SKILL PROC!** Exploding **{skill_data['name']}**!"
            
        attr_mult = self.get_attribute_multiplier(digimon["attr"], boss["attr"])
        final_dmg = int(raw_dmg * attr_mult * (1.25 if attr_mult > 1 else 1.0))
        
        result = await world_boss_col.find_one_and_update(
            {"is_active": True}, {"$inc": {"current_hp": -final_dmg, f"damage_log.{str(user_id)}": final_dmg}},
            return_document=discord.pymongo.ReturnDocument.AFTER
        )

        msg = f"💥 **{user_name}** dealt **{final_dmg} DMG**. (Boss: {max(0, result['current_hp']):,}){skill_msg}"

        if random.random() < 0.30 and result['current_hp'] > 0:
            boss_dmg = random.randint(250, 600)
            if player.get("is_protecting"):
                boss_dmg = int(boss_dmg * 0.2) 
                msg += f"\n🛡️ **GUARDED!** Blocked Rage! Took **{boss_dmg} DMG**."
                await rpg_profiles_col.update_one({"user_id": user_id}, {"$unset": {"is_protecting": ""}})
            else:
                msg += f"\n🚨 <@{user_id}> **BOSS RAGE DETECTED!** Countered for **{boss_dmg} DMG**!"
                
            new_hp = max(0, player["current_hp"] - boss_dmg)
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {"current_hp": new_hp}})
            if new_hp == 0: 
                msg += "\n💀 **YOUR DIGIMON FAINTED!**"
                return (msg, True)

        if result['current_hp'] <= 0:
            await self.distribute_boss_loot(result)
            return (msg + "\n🎉 **BOSS DEFEATED!**", True)
            
        return (msg, False)

    async def distribute_boss_loot(self, boss_data: dict):
        await world_boss_col.update_one({"_id": boss_data["_id"]}, {"$set": {"is_active": False}})
        # Spawn con boss tiếp theo đúng 1 giờ (3600 giây) sau khi chết
        await world_boss_col.update_one({"type": "spawn_config"}, {"$set": {"next_spawn": int(time.time()) + 3600}}, upsert=True)
        
        announcement = f"🎉 **THE WORLD BOSS HAS FALLEN!**\n\n**🏆 Leaderboard Rewards:**\n"
        sorted_log = sorted(boss_data.get("damage_log", {}).items(), key=lambda x: x[1], reverse=True)
        total_hp = boss_data.get("max_hp", 1)

        for rank, (uid_str, dmg) in enumerate(sorted_log, 1):
            dmg_percent = dmg / total_hp
            orbs_earned = max(1, int(dmg_percent * 10)) + (10 if rank == 1 else 5 if rank <= 3 else 0)
            reward_str = f"+{orbs_earned} Orbs"
            update_query = {"$inc": {"orb": orbs_earned}}

            if rank <= 3 and random.random() < 0.30:
                reward_str += " & 🍎"
                update_query.setdefault("$push", {})
                update_query["$push"]["inventory"] = "Size Reroll Fruit"
                
            if random.random() < (0.20 / rank) + dmg_percent:
                divine_drop = random.choice(["Divine Blade (Unlocked)", "Divine Aegis (Unlocked)", "Divine Vice (Unlocked)"])
                reward_str += f" & 👑"
                update_query.setdefault("$push", {})
                if "inventory" in update_query["$push"]: 
                    update_query["$push"]["inventory"] = {"$each": ["Size Reroll Fruit", divine_drop]}
                else: 
                    update_query["$push"]["inventory"] = divine_drop
                
            await rpg_profiles_col.update_one({"user_id": int(uid_str)}, update_query)
            if rank <= 10: announcement += f"#{rank} <@{uid_str}>: {dmg:,} DMG ➡️ {reward_str}\n"

        await self.broadcast_system_message(announcement)

    @app_commands.command(name="spawn_boss", description="[Admin] Force spawn a World Boss to trigger the cycle")
    async def spawn_boss(self, interaction: discord.Interaction, name: str, hp: int):
        if not interaction.user.guild_permissions.administrator: 
            return await interaction.response.send_message("❌ **Access Denied!** Admin privileges required.", ephemeral=True)
            
        await world_boss_col.insert_one({"name": name, "max_hp": hp, "current_hp": hp, "attr": "Virus", "img": "", "is_active": True, "damage_log": {}})
        await interaction.response.send_message(f"⚔️ **World Boss {name} forced to spawn!**", ephemeral=True)
        await self.broadcast_system_message(f"🚨 **WARNING!** **{name}** has arrived with **{hp:,} HP**!")

    @tasks.loop(minutes=1)
    async def auto_spawn_boss(self):
        config = await world_boss_col.find_one({"type": "spawn_config"})
        if not config or "next_spawn" not in config or int(time.time()) < config["next_spawn"]: return
        if await world_boss_col.find_one({"is_active": True}): return
        
        await world_boss_col.update_one({"type": "spawn_config"}, {"$unset": {"next_spawn": ""}})
        boss = random.choice([{"name": "Devimon", "hp": 100000, "attr": "Virus"}, {"name": "Wargreymon", "hp": 1000000, "attr": "Vaccine"}])
        boss.update({"is_active": True, "damage_log": {}})
        await world_boss_col.insert_one(boss)
        await self.broadcast_system_message(f"🚨 **WARNING!** World Boss **{boss['name']}** appeared with **{boss['hp']:,} HP**!")

    @auto_spawn_boss.before_loop
    async def before_auto_spawn(self): await self.bot.wait_until_ready()

    @app_commands.command(name="setup_boss_channel", description="Setup cross-server chat")
    async def setup_boss_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator: return await interaction.followup.send("❌ Access Denied!", ephemeral=True)
        webhook = next((w for w in await channel.webhooks() if w.user == self.bot.user), None) or await channel.create_webhook(name="DMW Relay")
        await boss_channels_col.update_one({"guild_id": interaction.guild_id}, {"$set": {"channel_id": channel.id, "webhook_url": webhook.url}}, upsert=True)
        await interaction.followup.send("✅ Success!", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        if not await boss_channels_col.find_one({"channel_id": message.channel.id}): return 
        others = await boss_channels_col.find({"channel_id": {"$ne": message.channel.id}}).to_list(None)
        tasks = [self._send_relay(c["webhook_url"], message.content, f"[{message.guild.name[:10]}] {message.author.display_name}", message.author.display_avatar.url, message.attachments) for c in others if "webhook_url" in c]
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_relay(self, url, content, username, avatar_url, attachments):
        async with aiohttp.ClientSession() as s:
            w = discord.Webhook.from_url(url, session=s)
            files = "\n" + "\n".join([a.url for a in attachments]) if attachments else ""
            if (content + files).strip(): await w.send(content=content + files, username=username, avatar_url=avatar_url)

    async def broadcast_system_message(self, content: str):
        channels = await boss_channels_col.find({}).to_list(None)
        tasks = []
        for c in channels:
            if url := c.get("webhook_url"):
                async def send(u, msg):
                    async with aiohttp.ClientSession() as s: await discord.Webhook.from_url(u, session=s).send(content=msg, username="SYSTEM")
                tasks.append(send(url, content))
        await asyncio.gather(*tasks, return_exceptions=True)

async def setup(bot):
    await bot.add_cog(RPGSystemCog(bot))