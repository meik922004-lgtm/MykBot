import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import aiohttp
import random
import time
from datetime import datetime

# Import collection từ Database.py
from Database import rpg_profiles_col, world_boss_col, boss_channels_col

market_col = rpg_profiles_col.database["rpg_marketplace"]

# ========================================================================
# CÁC LỚP GIAO DIỆN UI (VIEWS & MODALS)
# ========================================================================

class InventorySelect(discord.ui.Select):
    def __init__(self, inventory: list, cog_instance):
        self.cog = cog_instance
        interactable_items = [item for item in inventory if "(Unlocked)" in item or item == "Size Reroll Fruit"]
        
        if not interactable_items:
            options = [discord.SelectOption(label="Empty Inventory", value="empty")]
        else:
            unique_items = list(set(interactable_items))[:25] # Discord limit 25 options
            options = [
                discord.SelectOption(
                    label=item, 
                    description="Consume Fruit" if item == "Size Reroll Fruit" else "Equip Gear",
                    emoji="🍎" if item == "Size Reroll Fruit" else "🛡️"
                ) for item in unique_items
            ]
        super().__init__(placeholder="🎒 Select an item to use/equip...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "empty":
            return await interaction.response.send_message("❌ **No usable items.**", ephemeral=True)
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

    DIGIMON_DATA = {
        "rookie": {
            "Agumon": {"attr": "Vaccine", "atk": 60, "hp": 1200, "vip": False, "img": "https://digimon.net/cimages/digimon/agumon.jpg"},
            "Gabumon": {"attr": "Data", "atk": 55, "hp": 1300, "vip": False, "img": "https://digimon.net/cimages/digimon/gabumon.jpg"},
            "Guilmon": {"attr": "Virus", "atk": 65, "hp": 1100, "vip": False, "img": "https://digimon.net/cimages/digimon/guilmon.jpg"},
            "Lucemon": {"attr": "Virus", "atk": 90, "hp": 1000, "vip": True, "img": "https://digimon.net/cimages/digimon/lucemon.jpg"},
            "V-mon": {"attr": "Vaccine", "atk": 75, "hp": 1250, "vip": True, "img": "https://digimon.net/cimages/digimon/v-mon.jpg"}
        },
        "champion": {
            "Greymon": {"attr": "Vaccine", "atk": 180, "hp": 3000, "img": "https://digimon.net/cimages/digimon/greymon.jpg"},
            "Garurumon": {"attr": "Data", "atk": 160, "hp": 3200, "img": "https://digimon.net/cimages/digimon/garurumon.jpg"},
            "Growlmon": {"attr": "Virus", "atk": 190, "hp": 2800, "img": "https://digimon.net/cimages/digimon/growlmon.jpg"},
            "Lucemon FM": {"attr": "Virus", "atk": 250, "hp": 2500, "img": "https://digimon.net/cimages/digimon/lucemon_falldown_mode.jpg"},
            "ExVeemon": {"attr": "Vaccine", "atk": 210, "hp": 3100, "img": "https://digimon.net/cimages/digimon/exveemon.jpg"}
        }
    }

    EVOLUTION_LINE = {"Agumon": "Greymon", "Gabumon": "Garurumon", "Guilmon": "Growlmon", "Lucemon": "Lucemon FM", "V-mon": "ExVeemon"}
    HATCH_CORE_COST = 5

    def __init__(self, bot):
        self.bot = bot
        self.auto_attackers = set() # Quản lý danh sách người đang bật auto attack
        self.auto_spawn_boss.start()

    def cog_unload(self):
        self.auto_spawn_boss.cancel()

    # --- HELPER METHODS ---
    def clean_item_name(self, item_name: str) -> str:
        if not item_name: return "None"
        return item_name.replace(" (Unlocked)", "").replace(" (Locked)", "")

    def get_total_stats(self, profile: dict) -> dict:
        digimon = profile.get("digimon", {})
        total_hp, total_atk = digimon.get("hp", 0), digimon.get("atk", 0)
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
            max_cores = 30 if profile.get("is_vip") else 20
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {"digicore": max_cores, "last_core_reset": current_date}})
            return max_cores
        return profile.get("digicore", 20)

    def roll_pve_loot(self, dungeon: str) -> str:
        is_high_tier = random.random() < 0.10
        if dungeon == "digital_forest": loot_base = "Chrome Dagger" if is_high_tier else "Rusty Sword"
        elif dungeon == "factorial_town": loot_base = "Digivice Shield" if is_high_tier else "Rusty Armor"
        else: loot_base = "Chrome Vice" if is_high_tier else "Rusty Vice"
        return f"{loot_base}{' (Unlocked)' if random.random() < 0.20 else ' (Locked)'}"

    # ========================================================================
    # DASHBOARD COMMANDS (Slash Commands chính)
    # ========================================================================

    @app_commands.command(name="rpg_profile", description="View and manage your Digimon Tamer profile (Heal, Evolve, Equip)")
    async def rpg_profile(self, interaction: discord.Interaction):
        await interaction.response.defer()
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile: return await interaction.followup.send("❌ **Welcome to Digital World!** Please use `/hatch` to start your adventure.")

        digimon, stats, gear = profile.get("digimon", {}), self.get_total_stats(profile), profile.get("gear", {})
        embed = discord.Embed(title=f"📱 Tamer {profile.get('ign')}", color=discord.Color.teal())
        
        if digimon:
            size_display = f"{digimon.get('size', 1.0) * 100:.1f}%"
            embed.set_thumbnail(url=digimon.get("img", interaction.user.display_avatar.url))
            embed.description = f"**Partner:** {digimon.get('name')} ({digimon.get('stage')})\n**Attribute:** {digimon.get('attr')}\n**Size Scale:** `{size_display}`"
            embed.add_field(name="❤️ HP", value=f"{profile.get('current_hp')}/{stats['hp']}", inline=True)
            embed.add_field(name="⚔️ ATK", value=str(stats['atk']), inline=True)
            embed.add_field(name="🎯 CRIT", value=f"{stats['crit_rate']}% (x{stats['crit_dmg']})", inline=True)
            
        embed.add_field(name="💰 Currencies", value=f"🌐 **{profile.get('digibit', 0):.2f} Digibits**\n🔮 **{profile.get('orb', 0)} Orbs**\n🧬 **{profile.get('hatch_core', 0)} Hatch Cores**", inline=False)
        embed.add_field(name="Equipped Gear", value=f"⚔️ {gear.get('weapon', 'None')}\n🛡️ {gear.get('armor', 'None')}\n📿 {gear.get('vice', 'None')}", inline=False)
        
        await interaction.followup.send(embed=embed, view=ProfileView(profile, self))

    @app_commands.command(name="market", description="Open the Global Marketplace Dashboard")
    async def market_dashboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        embed = discord.Embed(title="🏪 Digital World Marketplace", description="Click the buttons below to interact with the market.", color=discord.Color.purple())
        await interaction.followup.send(embed=embed, view=MarketView(self))

    @app_commands.command(name="combat", description="Open the Boss Combat Panel")
    async def combat_dashboard(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⚔️ Boss Combat Interface", description="Control your attacks or toggle Auto-Attack.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, view=CombatView(self))

    # ========================================================================
    # UI HANDLERS (Xử lý các thao tác ấn nút từ Giao diện)
    # ========================================================================

    async def handle_inventory_use(self, interaction: discord.Interaction, item_name: str):
        # Nút dùng đồ từ túi
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        inventory = profile.get("inventory", [])
        
        if item_name not in inventory:
            return await interaction.followup.send("❌ Item not found.")

        if item_name == "Size Reroll Fruit":
            inventory.remove(item_name)
            digimon = profile.get("digimon")
            if not digimon: return await interaction.followup.send("❌ No Digimon.")

            new_size = round(random.uniform(1.00 if profile.get("is_vip") else 0.85, 1.30 if profile.get("is_vip") else 1.25), 3)
            base_stats = self.DIGIMON_DATA.get(digimon.get("stage", "Rookie").lower(), {}).get(digimon.get("name"))
            if not base_stats: return await interaction.followup.send("❌ Error fetching base stats.")

            actual_hp, actual_atk = int(base_stats["hp"] * new_size), int(base_stats["atk"] * new_size)
            digimon.update({"size": new_size, "hp": actual_hp, "atk": actual_atk})
            
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {"inventory": inventory, "digimon": digimon, "current_hp": actual_hp}})
            await interaction.followup.send(f"🍎 **Fruit Consumed!** Size rerolled to **{new_size * 100:.1f}%**!")
        else:
            cleaned_base = self.clean_item_name(item_name)
            slot_type = self.ITEMS[cleaned_base]["type"]
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {f"gear.{slot_type}": item_name}})
            await interaction.followup.send(f"🛡️ **Equipped:** {item_name} -> `{slot_type.upper()}`")

    async def handle_heal(self, interaction: discord.Interaction):
        # Nút Heal
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile or not profile.get("digimon"): return await interaction.followup.send("❌ No Digimon found.")

        current_time = int(time.time())
        if current_time - profile.get("last_heal", 0) < 120:
            return await interaction.followup.send(f"⏳ **Cooldown!** Wait {120 - (current_time - profile.get('last_heal', 0))}s.")

        max_hp = self.get_total_stats(profile)["hp"]
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"current_hp": max_hp, "last_heal": current_time}})
        await interaction.followup.send(f"✨ **Healed!** HP: **{max_hp}/{max_hp}**.")

    async def handle_evolve(self, interaction: discord.Interaction):
        # Nút Evolve
        await interaction.response.defer(ephemeral=True)
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        digimon = profile.get("digimon", {})
        
        if digimon.get("stage") != "Rookie": return await interaction.followup.send("❌ Max Level reached.")
        if profile.get("orb", 0) < 50: return await interaction.followup.send("❌ Need **50 Orbs**.")

        next_form_name = self.EVOLUTION_LINE.get(digimon["name"])
        base_next_stats = self.DIGIMON_DATA["champion"][next_form_name]
        current_size = digimon.get("size", 1.0)
        actual_hp, actual_atk = int(base_next_stats["hp"] * current_size), int(base_next_stats["atk"] * current_size)

        next_stats = {"name": next_form_name, "stage": "Champion", "attr": base_next_stats["attr"], "size": current_size, "hp": actual_hp, "atk": actual_atk, "img": base_next_stats["img"]}
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$inc": {"orb": -50}, "$set": {"digimon": next_stats, "current_hp": actual_hp}})
        await interaction.followup.send(f"✨ **EVOLVED!** Partner is now **{next_form_name}**!")

    # ========================================================================
    # MARKET HANDLERS
    # ========================================================================

    async def handle_market_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        listings = await market_col.find({}).sort("created_at", -1).to_list(15) 
        if not listings: return await interaction.followup.send("🏪 Market is empty.")

        embed = discord.Embed(title="🏪 Active Listings", color=discord.Color.purple())
        for item in listings:
            embed.add_field(name=f"📦 {item['item_name']}", value=f"🆔 `{item['listing_id']}` | 💰 **{item['price']:.2f} Bits** | 👤 {item['seller_name']}", inline=False)
        await interaction.followup.send(embed=embed)

    async def handle_market_buy(self, interaction: discord.Interaction, listing_id: str):
        await interaction.response.defer()
        buyer_id = interaction.user.id
        listing = await market_col.find_one({"listing_id": listing_id.upper()})
        
        if not listing: return await interaction.followup.send("❌ **Listing Not Found!**")
        if listing["seller_id"] == buyer_id: return await interaction.followup.send("❌ Cannot buy your own item.")

        buyer_profile = await rpg_profiles_col.find_one({"user_id": buyer_id})
        if not buyer_profile or buyer_profile.get("digibit", 0.0) < listing["price"]:
            return await interaction.followup.send("❌ **Insufficient Digibits.**")

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
            if target not in profile.get("inventory", []) or not target.endswith("(Unlocked)"):
                return await interaction.followup.send("❌ Item not found or locked.")
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$pull": {"inventory": target}}) # Kéo đồ ra khỏi túi
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
    # COMBAT ENGINE (Xử lý Attack Core)
    # ========================================================================

    async def toggle_auto_attack(self, interaction: discord.Interaction):
        # Bật tắt Auto Attack
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        if user_id in self.auto_attackers:
            self.auto_attackers.discard(user_id)
            await interaction.followup.send("🛑 **Auto-Attack DEACTIVATED.**")
        else:
            self.auto_attackers.add(user_id)
            await interaction.followup.send("🤖 **Auto-Attack ACTIVATED!** Initiating sequence...")
            # Tạo task chạy ngầm cho người chơi này
            self.bot.loop.create_task(self.auto_attack_loop(user_id, interaction.user.display_name, interaction.channel))

    async def auto_attack_loop(self, user_id: int, user_name: str, channel: discord.TextChannel):
        """Vòng lặp tự động đánh - Delay 4.5s"""
        while user_id in self.auto_attackers:
            msg, should_stop = await self.execute_combat_turn(user_id, user_name)
            if msg: await channel.send(msg)
            if should_stop:
                self.auto_attackers.discard(user_id)
                break
            await asyncio.sleep(4.5)

    async def handle_manual_attack(self, interaction: discord.Interaction):
        # Nút Attack tay
        await interaction.response.defer()
        current_time = int(time.time())
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        
        # Cooldown tay 4s tĩnh
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
        if profile and current_time - profile.get("last_protect", 0) < 45:
            return await interaction.followup.send("⏳ **Protect Cooldown!**", ephemeral=True)
            
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"is_protecting": True, "last_protect": current_time}})
        await interaction.followup.send("🛡️ **Defensive Stance Active!**")

    async def execute_combat_turn(self, user_id: int, user_name: str) -> tuple:
        """Core logic xử lý 1 lượt đánh. Trả về (Thông báo, Có nên dừng auto không)"""
        boss = await world_boss_col.find_one({"is_active": True})
        if not boss: return ("❌ **No active World Boss.**", True)

        player = await rpg_profiles_col.find_one({"user_id": user_id})
        if not player or not player.get("digimon"): return ("❌ **No Digimon!** Hatch an egg.", True)
        if player.get("current_hp", 0) <= 0: return (f"☠️ <@{user_id}> **Your Digimon fainted!** Use Heal.", True)

        stats, digimon = self.get_total_stats(player), player["digimon"]
        raw_dmg = stats["atk"] + random.randint(-5, 10)
        is_crit = random.randint(1, 100) <= stats["crit_rate"]
        if is_crit: raw_dmg *= stats["crit_dmg"]
            
        attr_mult = self.get_attribute_multiplier(digimon["attr"], boss["attr"])
        final_dmg = int(raw_dmg * attr_mult * (1.25 if attr_mult > 1 else 1.0))
        
        result = await world_boss_col.find_one_and_update(
            {"is_active": True}, {"$inc": {"current_hp": -final_dmg, f"damage_log.{str(user_id)}": final_dmg}},
            return_document=discord.pymongo.ReturnDocument.AFTER
        )

        msg = f"💥 **{user_name}** dealt **{final_dmg} DMG**. (Boss: {max(0, result['current_hp']):,})"

        # Logic Boss Phản công (Boss Rage 30%)
        if random.random() < 0.30 and result['current_hp'] > 0:
            boss_dmg = random.randint(250, 600)
            if player.get("is_protecting"):
                boss_dmg = int(boss_dmg * 0.2) 
                msg += f"\n🛡️ **GUARDED!** Blocked Rage! Took **{boss_dmg} DMG**."
                await rpg_profiles_col.update_one({"user_id": user_id}, {"$unset": {"is_protecting": ""}})
            else:
                # 🚨 CẢNH BÁO RAGE IN ĐẬM VÀ PING
                msg += f"\n🚨 <@{user_id}> **BOSS RAGE DETECTED!** Countered for **{boss_dmg} DMG**!"
                
            new_hp = max(0, player["current_hp"] - boss_dmg)
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {"current_hp": new_hp}})
            if new_hp == 0: 
                msg += "\n💀 **YOUR DIGIMON FAINTED!**"
                return (msg, True) # Dừng auto attack vì đã chết

        if result['current_hp'] <= 0:
            # Nếu đòn đánh này giết boss
            await self.distribute_boss_loot(result)
            return (msg + "\n🎉 **BOSS DEFEATED!**", True)
            
        return (msg, False)

    async def distribute_boss_loot(self, boss_data: dict):
        # Hàm phân chia đồ tương tự trước đó nhưng không nhận params interaction nữa
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
    # PVE / MINE / UTILITIES COMMANDS (CÁC LỆNH KHÁC)
    # ========================================================================

    @app_commands.command(name="hatch", description=f"Hatch a Rookie Digimon (Costs 5 Hatch Cores)")
    async def hatch(self, interaction: discord.Interaction, confirm_replace: bool = False):
        await interaction.response.defer()
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        if not profile:
            profile = {"user_id": user_id, "ign": interaction.user.display_name, "gold": 0, "digibit": 0.0, "orb": 0, "hatch_core": 0, "current_hp": 0, "gear": {"weapon": "None", "armor": "None", "vice": "None"}, "inventory": [], "digicore": 20, "is_vip": False, "last_core_reset": datetime.utcnow().strftime("%Y-%m-%d")}
            await rpg_profiles_col.insert_one(profile)

        if profile.get("hatch_core", 0) < self.HATCH_CORE_COST: return await interaction.followup.send("❌ Missing Hatch Cores.")
        if profile.get("digimon") and not confirm_replace: return await interaction.followup.send("⚠️ Set `confirm_replace: True` to overwrite.")

        await rpg_profiles_col.update_one({"user_id": user_id}, {"$inc": {"hatch_core": -self.HATCH_CORE_COST}})
        is_vip = profile.get("is_vip", False)
        available = [name for name, data in self.DIGIMON_DATA["rookie"].items() if not data["vip"] or is_vip]
        
        hatched_name = random.choice(available)
        base_stats = self.DIGIMON_DATA["rookie"][hatched_name]
        size_pct = round(random.uniform(1.00 if is_vip else 0.85, 1.30 if is_vip else 1.25), 3)

        actual_hp, actual_atk = int(base_stats["hp"] * size_pct), int(base_stats["atk"] * size_pct)
        digimon_stats = {"name": hatched_name, "stage": "Rookie", "attr": base_stats["attr"], "size": size_pct, "hp": actual_hp, "atk": actual_atk, "img": base_stats["img"]}

        await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {"digimon": digimon_stats, "current_hp": actual_hp}})
        embed = discord.Embed(title="🥚 Hatched Successfully!", description=f"Obtained **{hatched_name}**!", color=discord.Color.green())
        embed.add_field(name="🧬 Size", value=f"**{size_pct * 100:.1f}%**")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="farm_dungeon", description="Spend 1 Digicore to farm gear, Digibits, and Hatch Cores")
    @app_commands.choices(dungeon=[app_commands.Choice(name="Digital Forest (Weapons)", value="digital_forest"), app_commands.Choice(name="Factorial Town (Armors)", value="factorial_town"), app_commands.Choice(name="Server Continent (Vices)", value="server_continent")])
    async def farm_dungeon(self, interaction: discord.Interaction, dungeon: str):
        await interaction.response.defer()
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        if not profile or not profile.get("digimon"): return await interaction.followup.send("❌ No Digimon! Hatch an egg first.")
        if await self.verify_and_refresh_cores(user_id, profile) <= 0: return await interaction.followup.send("❌ Out of Energy!")

        is_vip = profile.get("is_vip", False)
        core_dropped = 1 if (is_vip or random.random() < 0.60) else 0
        
        await rpg_profiles_col.update_one({"user_id": user_id}, {"$inc": {"digicore": -1, "digibit": 1.00, "hatch_core": core_dropped}})
        
        loot = self.roll_pve_loot(dungeon) if random.random() < (0.07 if is_vip else 0.05) else None
        if loot: await rpg_profiles_col.update_one({"user_id": user_id}, {"$push": {"inventory": loot}})

        embed = discord.Embed(title=f"🏰 Dungeon Cleared", color=discord.Color.green())
        embed.add_field(name="Rewards", value=f"🌐 +1.00 Digibit\n" + (f"🧬 +1 Hatch Core\n" if core_dropped else ""))
        if loot: embed.add_field(name="Rare Drop!", value=f"🎉 **{loot}**", inline=False)
        await interaction.followup.send(embed=embed)

    # LOOP NGẦM SPAWN BOSS (giữ nguyên logic cũ)
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

    # WEBHOOK SETUP VÀ RELAY GIỮ NGUYÊN
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