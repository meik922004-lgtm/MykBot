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

    # COMPLETE DATA SET WITH 10 COMPLETE LINES FROM ROOKIE TO MEGA
    DIGIMON_DATA = {
        "rookie": {
            "Agumon": {"attr": "Vaccine", "atk": 60, "hp": 1200, "vip": False, "img": "https://digimon.net/cimages/digimon/agumon.jpg"},
            "Gabumon": {"attr": "Data", "atk": 55, "hp": 1300, "vip": False, "img": "https://digimon.net/cimages/digimon/gabumon.jpg"},
            "Guilmon": {"attr": "Virus", "atk": 65, "hp": 1100, "vip": False, "img": "https://digimon.net/cimages/digimon/guilmon.jpg"},
            "Lucemon": {"attr": "Virus", "atk": 90, "hp": 1000, "vip": True, "img": "https://digimon.net/cimages/digimon/lucemon.jpg"},
            "V-mon": {"attr": "Vaccine", "atk": 75, "hp": 1250, "vip": True, "img": "https://digimon.net/cimages/digimon/v-mon.jpg"},
            "Patamon": {"attr": "Data", "atk": 50, "hp": 1150, "vip": False, "img": ""},
            "DemiDevimon": {"attr": "Virus", "atk": 65, "hp": 1050, "vip": False, "img": ""},
            "Palmon": {"attr": "Data", "atk": 60, "hp": 1250, "vip": False, "img": ""},
            "Tentomon": {"attr": "Vaccine", "atk": 65, "hp": 1200, "vip": False, "img": ""},
            "Psychemon": {"attr": "Data", "atk": 70, "hp": 1100, "vip": False, "img": ""}
        },
        "champion": {
            "Greymon": {"attr": "Vaccine", "atk": 180, "hp": 3000, "img": "https://digimon.net/cimages/digimon/greymon.jpg"},
            "Garurumon": {"attr": "Data", "atk": 160, "hp": 3200, "img": "https://digimon.net/cimages/digimon/garurumon.jpg"},
            "Growlmon": {"attr": "Virus", "atk": 190, "hp": 2800, "img": "https://digimon.net/cimages/digimon/growlmon.jpg"},
            "ExVeemon": {"attr": "Vaccine", "atk": 210, "hp": 3100, "img": "https://digimon.net/cimages/digimon/exveemon.jpg"},
            "Lucemon FM": {"attr": "Virus", "atk": 250, "hp": 2500, "img": "https://digimon.net/cimages/digimon/lucemon_falldown_mode.jpg"},
            "Angemon": {"attr": "Vaccine", "atk": 200, "hp": 2900, "img": ""},
            "Devimon": {"attr": "Virus", "atk": 220, "hp": 2600, "img": ""},
            "Togemon": {"attr": "Data", "atk": 170, "hp": 3300, "img": ""},
            "Kabuterimon": {"attr": "Vaccine", "atk": 195, "hp": 3100, "img": ""},
            "Gururumon": {"attr": "Vaccine", "atk": 190, "hp": 3000, "img": ""}
        },
        "ultimate": {
            "MetalGreymon": {"attr": "Vaccine", "atk": 450, "hp": 7500, "img": ""},
            "WereGarurumon": {"attr": "Data", "atk": 420, "hp": 8000, "img": ""},
            "WarGrowlmon": {"attr": "Virus", "atk": 480, "hp": 7000, "img": ""},
            "Paildramon": {"attr": "Data", "atk": 460, "hp": 7200, "img": ""},
            "Lucemon SM": {"attr": "Virus", "atk": 600, "hp": 6500, "img": ""},
            "MagnaAngemon": {"attr": "Vaccine", "atk": 470, "hp": 7400, "img": ""},
            "Myotismon": {"attr": "Virus", "atk": 500, "hp": 6800, "img": ""},
            "Lillymon": {"attr": "Data", "atk": 410, "hp": 7800, "img": ""},
            "MegaKabuterimon": {"attr": "Vaccine", "atk": 460, "hp": 7600, "img": ""},
            "Astamon": {"attr": "Virus", "atk": 480, "hp": 7200, "img": ""}
        },
        "mega": {
            "WarGreymon": {"attr": "Vaccine", "atk": 1200, "hp": 20000, "img": "", "skill": {"name": "Terra Force", "dmg_mult": 2.5, "chance": 0.2}},
            "MetalGarurumon": {"attr": "Data", "atk": 1100, "hp": 22000, "img": "", "skill": {"name": "Metal Wolf Claw", "dmg_mult": 2.2, "chance": 0.25}},
            "Gallantmon": {"attr": "Virus", "atk": 1250, "hp": 19000, "img": "", "skill": {"name": "Lightning Joust", "dmg_mult": 2.8, "chance": 0.15}},
            "Imperialdramon": {"attr": "Vaccine", "atk": 1150, "hp": 21000, "img": "", "skill": {"name": "Positron Laser", "dmg_mult": 2.3, "chance": 0.2}},
            "Lucemon X": {"attr": "Virus", "atk": 1500, "hp": 15000, "img": "", "skill": {"name": "Seventh Cross", "dmg_mult": 3.2, "chance": 0.12}},
            "Seraphimon": {"attr": "Vaccine", "atk": 1300, "hp": 18000, "img": "", "skill": {"name": "Seven Heavens", "dmg_mult": 3.0, "chance": 0.1}},
            "VenomMyotismon": {"attr": "Virus", "atk": 1350, "hp": 17500, "img": "", "skill": {"name": "Venom Infusion", "dmg_mult": 2.6, "chance": 0.15}},
            "Rosemon": {"attr": "Data", "atk": 1050, "hp": 23000, "img": "", "skill": {"name": "Forbidden Temptation", "dmg_mult": 2.0, "chance": 0.3}},
            "HerculesKabuterimon": {"attr": "Vaccine", "atk": 1180, "hp": 22500, "img": "", "skill": {"name": "Giga Blaster", "dmg_mult": 2.4, "chance": 0.2}},
            "Mekurimon": {"attr": "Virus", "atk": 1400, "hp": 16000, "img": "", "skill": {"name": "Spark", "dmg_mult": 2.9, "chance": 0.15}}
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

    def cog_unload(self):
        self.auto_spawn_boss.cancel()

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
            max_cores = 60 if profile.get("is_vip") else 50
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
    # GM TOOLS (DEVELOPER ONLY)
    # ========================================================================
    
    @app_commands.command(name="gm_add", description="[GM Tool] Add currency/items to a player")
    async def gm_add(self, interaction: discord.Interaction, user: discord.Member, field: str, amount: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ **Access Denied!** Developer only.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        
        valid_fields = ["digibit", "orb", "hatch_core", "digicore"]
        if field not in valid_fields:
            return await interaction.followup.send(f"❌ Invalid field. Choose from: {', '.join(valid_fields)}")
            
        await rpg_profiles_col.update_one({"user_id": user.id}, {"$inc": {field: amount}})
        await interaction.followup.send(f"✅ Added **{amount} {field}** to {user.display_name}.")

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
        await interaction.response.defer()
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile: return await interaction.followup.send("❌ Profile does not exist.")
        
        digimon_list = profile.get("digimon_list", [])
        if not digimon_list: return await interaction.followup.send("❌ You don't have any Digimon.")
        
        embed = discord.Embed(title="🐾 Your Digimon Bag", description=f"Quantity: {len(digimon_list)}", color=discord.Color.gold())
        await interaction.followup.send(embed=embed, view=BagView(digimon_list, profile.get("active_digimon_id"), self))

    async def handle_switch_digimon(self, interaction: discord.Interaction, digimon_id: str):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"active_digimon_id": digimon_id}})
        new_active = next((d for d in profile.get("digimon_list", []) if d["id"] == digimon_id), None)
        if new_active:
            total_hp = new_active.get("hp", 0) + new_active.get("trained_hp", 0)
            await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"current_hp": total_hp}})
            
        await interaction.followup.send("✅ Successfully switched active Digimon!")

    @app_commands.command(name="train_digimon", description="Train Digimon with Orbs to increase stats")
    @app_commands.choices(stat=[app_commands.Choice(name="ATK (+20 ATK / 5 Orbs)", value="atk"), app_commands.Choice(name="HP (+100 HP / 5 Orbs)", value="hp")])
    async def train_digimon(self, interaction: discord.Interaction, stat: str):
        await interaction.response.defer()
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile or profile.get("orb", 0) < 5:
            return await interaction.followup.send("❌ You do not have enough 5 Orbs.")
            
        active_digi = self.get_active_digimon(profile)
        if not active_digi: return await interaction.followup.send("❌ Equip a Digimon first.")
        
        MAX_TRAIN_ATK = 1000
        MAX_TRAIN_HP = 5000
        
        current_train_atk = active_digi.get("trained_atk", 0)
        current_train_hp = active_digi.get("trained_hp", 0)
        
        updates = {}
        if stat == "atk":
            if current_train_atk >= MAX_TRAIN_ATK: return await interaction.followup.send("❌ ATK training limit reached.")
            updates["trained_atk"] = current_train_atk + 20
        else:
            if current_train_hp >= MAX_TRAIN_HP: return await interaction.followup.send("❌ HP training limit reached.")
            updates["trained_hp"] = current_train_hp + 100
            
        new_list = self.update_active_digimon(profile, updates)
        await rpg_profiles_col.update_one(
            {"user_id": interaction.user.id}, 
            {"$set": {"digimon_list": new_list}, "$inc": {"orb": -5}}
        )
        await interaction.followup.send(f"🏋️ **Training successful!** {stat.upper()} increased for {active_digi['name']}.")

    # ========================================================================
    # UI HANDLERS & EVOLVE
    # ========================================================================
    
    async def handle_inventory_use(self, interaction: discord.Interaction, item_name: str):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        inventory = profile.get("inventory", [])
        
        if item_name not in inventory: return await interaction.followup.send("❌ Item not found.")

        if item_name == "Size Reroll Fruit":
            inventory.remove(item_name)
            digimon = self.get_active_digimon(profile)
            if not digimon: return await interaction.followup.send("❌ No Active Digimon.")

            new_size = round(random.uniform(1.00 if profile.get("is_vip") else 0.85, 1.30 if profile.get("is_vip") else 1.25), 3)
            stage_lower = digimon.get("stage", "Rookie").lower()
            base_stats = self.DIGIMON_DATA.get(stage_lower, {}).get(digimon.get("name"))

            actual_hp, actual_atk = int(base_stats["hp"] * new_size), int(base_stats["atk"] * new_size)
            new_list = self.update_active_digimon(profile, {"size": new_size, "hp": actual_hp, "atk": actual_atk})
            
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {"inventory": inventory, "digimon_list": new_list, "current_hp": actual_hp + digimon.get("trained_hp", 0)}})
            await interaction.followup.send(f"🍎 **Fruit Consumed!** Size rerolled to **{new_size * 100:.1f}%**!")
        else:
            cleaned_base = self.clean_item_name(item_name)
            slot_type = self.ITEMS[cleaned_base]["type"]
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {f"gear.{slot_type}": item_name}})
            await interaction.followup.send(f"🛡️ **Equipped:** {item_name} -> `{slot_type.upper()}`")

    async def handle_heal(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile or not self.get_active_digimon(profile): return await interaction.followup.send("❌ No Digimon found.")

        current_time = int(time.time())
        if current_time - profile.get("last_heal", 0) < 120:
            return await interaction.followup.send(f"⏳ **Cooldown!** Wait {120 - (current_time - profile.get('last_heal', 0))}s.")

        max_hp = self.get_total_stats(profile)["hp"]
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"current_hp": max_hp, "last_heal": current_time}})
        await interaction.followup.send(f"✨ **Healed!** HP: **{max_hp}/{max_hp}**.")

    async def handle_evolve(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        digimon = self.get_active_digimon(profile)
        
        if not digimon: return await interaction.followup.send("❌ No Active Digimon.")
        if digimon.get("stage") == "Mega": return await interaction.followup.send("❌ Max Level (Mega) reached.")
        if profile.get("orb", 0) < 50: return await interaction.followup.send("❌ Need **50 Orbs**.")

        next_form_name = self.EVOLUTION_LINE.get(digimon["name"])
        if not next_form_name: return await interaction.followup.send("❌ This Digimon has no next evolution.")

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
        await interaction.followup.send(f"✨ **EVOLVED!** Partner is now **{next_form_name}**!")

    # ========================================================================
    # MARKET HANDLERS
    # ========================================================================
    async def handle_market_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        listings = await market_col.find({}).sort("created_at", -1).to_list(15) 
        if not listings: return await interaction.followup.send("🏪 Market is empty.")
        embed = discord.Embed(title="🏪 Active Listings", color=discord.Color.purple())
        for item in listings: embed.add_field(name=f"📦 {item['item_name']}", value=f"🆔 `{item['listing_id']}` | 💰 **{item['price']:.2f} Bits** | 👤 {item['seller_name']}", inline=False)
        await interaction.followup.send(embed=embed)

    async def handle_market_buy(self, interaction: discord.Interaction, listing_id: str):
        await interaction.response.defer()
        buyer_id = interaction.user.id
        listing = await market_col.find_one({"listing_id": listing_id.upper()})
        if not listing: return await interaction.followup.send("❌ **Listing Not Found!**")
        if listing["seller_id"] == buyer_id: return await interaction.followup.send("❌ Cannot buy your own item.")
        buyer_profile = await rpg_profiles_col.find_one({"user_id": buyer_id})
        if not buyer_profile or buyer_profile.get("digibit", 0.0) < listing["price"]: return await interaction.followup.send("❌ **Insufficient Digibits.**")
        price = listing["price"]
        await rpg_profiles_col.update_one({"user_id": buyer_id}, {"$inc": {"digibit": -price}})
        await rpg_profiles_col.update_one({"user_id": listing["seller_id"]}, {"$inc": {"digibit": price}})
        if listing["item_type"] == "gear": await rpg_profiles_col.update_one({"user_id": buyer_id}, {"$push": {"inventory": listing["raw_gear_name"]}})
        elif listing["item_type"] == "orb": await rpg_profiles_col.update_one({"user_id": buyer_id}, {"$inc": {"orb": listing["quantity"]}})
        elif listing["item_type"] == "core": await rpg_profiles_col.update_one({"user_id": buyer_id}, {"$inc": {"hatch_core": listing["quantity"]}})
        await market_col.delete_one({"_id": listing["_id"]})
        await interaction.followup.send(f"🛍️ **Purchased {listing['item_name']} for {price:.2f} Digibits!**")

    async def handle_market_sell(self, interaction: discord.Interaction, item_type: str, target: str, price_str: str):
        await interaction.response.defer()
        try: price = round(float(price_str), 2)
        except: return await interaction.followup.send("❌ Invalid price format.")
        if price <= 0: return await interaction.followup.send("❌ Price must be > 0.")
        if item_type not in ["gear", "orb", "core"]: return await interaction.followup.send("❌ Type must be 'gear', 'orb', or 'core'.")
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        display_name, qty = "", 1
        if item_type == "gear":
            if target not in profile.get("inventory", []) or not target.endswith("(Unlocked)"): return await interaction.followup.send("❌ Item not found or locked.")
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$pull": {"inventory": target}})
            display_name = target
        else:
            qty = int(target)
            db_field = "orb" if item_type == "orb" else "hatch_core"
            if profile.get(db_field, 0) < qty: return await interaction.followup.send("❌ Insufficient quantity.")
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$inc": {db_field: -qty}})
            display_name = f"{qty}x {'World Boss Orb' if item_type == 'orb' else 'Hatch Core'}"
        listing_id = f"LIT-{random.randint(1000, 9999)}"
        await market_col.insert_one({"listing_id": listing_id, "seller_id": user_id, "seller_name": interaction.user.name, "item_type": item_type, "item_name": display_name, "raw_gear_name": target if item_type == "gear" else "", "quantity": qty, "price": price, "created_at": int(time.time())})
        await interaction.followup.send(f"🏪 **Listed {display_name} for {price:.2f} Bits!** (ID: `{listing_id}`)")

    # ========================================================================
    # COMBAT ENGINE
    # ========================================================================
    
    async def toggle_auto_attack(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        if user_id in self.auto_attackers:
            self.auto_attackers.discard(user_id)
            await interaction.followup.send("🛑 **Auto-Attack DEACTIVATED.**")
        else:
            self.auto_attackers.add(user_id)
            await interaction.followup.send("🤖 **Auto-Attack ACTIVATED!** Initiating sequence...")
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
        await interaction.response.defer()
        current_time = int(time.time())
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        
        if profile and current_time - profile.get("last_manual_atk", 0) < 4:
            return await interaction.followup.send("⏳ **Cooldown!** Too fast.", ephemeral=True)
            
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"last_manual_atk": current_time}})
        msg, should_stop = await self.execute_combat_turn(interaction.user.id, interaction.user.display_name)
        if msg: await interaction.followup.send(msg)
        if should_stop: self.auto_attackers.discard(interaction.user.id)

    async def handle_protect(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        current_time = int(time.time())
        if profile and current_time - profile.get("last_protect", 0) < 45: return await interaction.followup.send("⏳ **Protect Cooldown!**", ephemeral=True)
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"is_protecting": True, "last_protect": current_time}})
        await interaction.followup.send("🛡️ **Defensive Stance Active!**")

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
        await world_boss_col.update_one({"type": "spawn_config"}, {"$set": {"next_spawn": int(time.time()) + random.randint(1800, 5400)}}, upsert=True)
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
                update_query["$push"] = {"inventory": "Size Reroll Fruit"}
            if random.random() < (0.20 / rank) + dmg_percent:
                divine_drop = random.choice(["Divine Blade (Unlocked)", "Divine Aegis (Unlocked)", "Divine Vice (Unlocked)"])
                reward_str += f" & 👑"
                update_query.setdefault("$push", {})
                if "inventory" in update_query["$push"]: update_query["$push"]["inventory"] = {"$each": ["Size Reroll Fruit", divine_drop]}
                else: update_query["$push"]["inventory"] = divine_drop
                
            await rpg_profiles_col.update_one({"user_id": int(uid_str)}, update_query)
            if rank <= 10: announcement += f"#{rank} <@{uid_str}>: {dmg:,} DMG ➡️ {reward_str}\n"

        await self.broadcast_system_message(announcement)

    # ========================================================================
    # PVE / MINE / UTILITIES COMMANDS
    # ========================================================================
    
    @app_commands.command(name="mine", description="Mine for Digibits (Cooldown: 2 hours)")
    async def mine(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        if not profile: return await interaction.followup.send("❌ You don't have a profile.")
        
        current_time = int(time.time())
        last_mine = profile.get("last_mine", 0)
        
        if current_time - last_mine < 7200: # 2 Hours
            remaining = 7200 - (current_time - last_mine)
            return await interaction.followup.send(f"⏳ **Resting!** Please try again in {remaining//60} minutes.")
            
        bonus = 1.5 if profile.get("is_vip") else 1.0
        amount = random.uniform(10.0, 25.0) * bonus
        
        await rpg_profiles_col.update_one(
            {"user_id": user_id}, 
            {"$inc": {"digibit": amount}, "$set": {"last_mine": current_time}}
        )
        await interaction.followup.send(f"⛏️ You worked hard and obtained **{amount:.2f} Digibits**!")

    @app_commands.command(name="hatch", description=f"Hatch a Rookie Digimon (Costs 5 Hatch Cores)")
    async def hatch(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        if not profile:
            profile = {
                "user_id": user_id, "ign": interaction.user.display_name, 
                "gold": 0, "digibit": 0.0, "orb": 0, "hatch_core": 10,
                "current_hp": 0, "gear": {"weapon": "None", "armor": "None", "vice": "None"}, 
                "inventory": [], "digicore": 50, "is_vip": False, 
                "last_core_reset": datetime.utcnow().strftime("%Y-%m-%d"),
                "digimon_list": [], "active_digimon_id": None
            }
            await rpg_profiles_col.insert_one(profile)

        if profile.get("hatch_core", 0) < self.HATCH_CORE_COST: return await interaction.followup.send("❌ Missing Hatch Cores.")

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
        embed.add_field(name="🧬 Size", value=f"**{size_pct * 100:.1f}%**")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="auto_dungeon", description="Automatically clear Dungeon using all Energy")
    @app_commands.choices(dungeon=[app_commands.Choice(name="Digital Forest (Weapons)", value="digital_forest"), app_commands.Choice(name="Factorial Town (Armors)", value="factorial_town"), app_commands.Choice(name="Server Continent (Vices)", value="server_continent")])
    async def auto_dungeon(self, interaction: discord.Interaction, dungeon: str):
        await interaction.response.defer()
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        if not profile or not self.get_active_digimon(profile): return await interaction.followup.send("❌ Equip a Digimon first.")
        
        current_energy = await self.verify_and_refresh_cores(user_id, profile)
        if current_energy <= 0: return await interaction.followup.send("❌ Out of Energy (Digicore).")

        is_vip = profile.get("is_vip", False)
        
        total_runs = current_energy
        total_bits = 1.00 * total_runs
        
        cores_dropped = sum(1 for _ in range(total_runs) if (is_vip or random.random() < 0.60))
        loot_dropped = [self.roll_pve_loot(dungeon) for _ in range(total_runs) if random.random() < (0.07 if is_vip else 0.05)]
        
        updates = {"$set": {"digicore": 0}, "$inc": {"digibit": total_bits, "hatch_core": cores_dropped}}
        if loot_dropped:
            updates["$push"] = {"inventory": {"$each": loot_dropped}}
            
        await rpg_profiles_col.update_one({"user_id": user_id}, updates)

        embed = discord.Embed(title=f"🏰 Auto-Clear {self.DUNGEONS[dungeon]['name']} ({total_runs} runs)", color=discord.Color.blue())
        embed.add_field(name="Rewards", value=f"🌐 +{total_bits:.2f} Digibit\n🧬 +{cores_dropped} Hatch Core")
        if loot_dropped: 
            loot_display = "\n".join([f"🎉 {l}" for l in loot_dropped[:5]]) + ("\n... and more!" if len(loot_dropped)>5 else "")
            embed.add_field(name="Rare Drops!", value=loot_display, inline=False)
            
        await interaction.followup.send(embed=embed)

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
        if not interaction.user.guild_permissions.administrator: return await interaction.followup.send("❌ Access Denied!")
        webhook = next((w for w in await channel.webhooks() if w.user == self.bot.user), None) or await channel.create_webhook(name="DMW Relay")
        await boss_channels_col.update_one({"guild_id": interaction.guild_id}, {"$set": {"channel_id": channel.id, "webhook_url": webhook.url}}, upsert=True)
        await interaction.followup.send("✅ Success!")

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