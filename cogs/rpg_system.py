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

class RPGSystemCog(commands.Cog):
    # Cấu hình danh mục trang bị 3 Bậc (Rusty -> Chrome -> Divine)
    ITEMS = {
        "Rusty Sword": {"type": "weapon", "atk": 15},
        "Rusty Armor": {"type": "armor", "hp": 150, "def": 10},
        "Rusty Vice": {"type": "vice", "crit_rate": 5, "crit_dmg": 1.2},
        "Chrome Dagger": {"type": "weapon", "atk": 45},
        "Chrome Cloak": {"type": "armor", "hp": 350, "def": 25},
        "Chrome Vice": {"type": "vice", "crit_rate": 10, "crit_dmg": 1.5},
        "Divine Blade": {"type": "weapon", "atk": 120},
        "Divine Aegis": {"type": "armor", "hp": 800, "def": 60},
        "Divine Vice": {"type": "vice", "crit_rate": 20, "crit_dmg": 2.0}
    }

    # Cấu hình Phụ bản PvE 
    DUNGEONS = {
        "digital_forest": {"name": "Digital Forest", "description": "Farms Weapons (Rusty / Chrome)."},
        "factorial_town": {"name": "Factorial Town", "description": "Farms Armors (Rusty / Chrome)."},
        "server_continent": {"name": "Server Continent", "description": "Farms Vices (Rusty / Chrome)."}
    }

    # Cấu hình dữ liệu Digimon
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

    EVOLUTION_LINE = {
        "Agumon": "Greymon", "Gabumon": "Garurumon", "Guilmon": "Growlmon",
        "Lucemon": "Lucemon FM", "V-mon": "ExVeemon"
    }

    # Chi phí Core để ấp trứng
    HATCH_CORE_COST = 5

    def __init__(self, bot):
        self.bot = bot
        self.auto_spawn_boss.start()

    def cog_unload(self):
        self.auto_spawn_boss.cancel()

    # ========================================================================
    # PART 1: HELPER METHODS (HÀM TÍNH TOÁN CHỈ SỐ & THUỘC TÍNH)
    # ========================================================================

    def clean_item_name(self, item_name: str) -> str:
        if not item_name: return "None"
        return item_name.replace(" (Unlocked)", "").replace(" (Locked)", "")

    def get_total_stats(self, profile: dict) -> dict:
        digimon = profile.get("digimon", {})
        total_hp = digimon.get("hp", 0)
        total_atk = digimon.get("atk", 0)
        total_def = 10 
        total_crit_rate = 0
        total_crit_dmg = 1.0

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
        if adv.get(attacker_attr) == defender_attr: return 1.25 
        return 0.8 

    async def verify_and_refresh_cores(self, user_id: int, profile: dict) -> int:
        current_date = datetime.utcnow().strftime("%Y-%m-%d")
        if profile.get("last_core_reset") != current_date:
            max_cores = 30 if profile.get("is_vip") else 20
            await rpg_profiles_col.update_one(
                {"user_id": user_id},
                {"$set": {"digicore": max_cores, "last_core_reset": current_date}}
            )
            return max_cores
        return profile.get("digicore", 20)

    def roll_pve_loot(self, dungeon: str) -> str:
        is_high_tier = random.random() < 0.10
        if dungeon == "digital_forest":
            loot_base = "Chrome Dagger" if is_high_tier else "Rusty Sword"
        elif dungeon == "factorial_town":
            loot_base = "Digivice Shield" if is_high_tier else "Rusty Armor"
        else: 
            loot_base = "Chrome Vice" if is_high_tier else "Rusty Vice"
            
        is_unlocked = random.random() < 0.20
        return f"{loot_base}{' (Unlocked)' if is_unlocked else ' (Locked)'}"

    # ========================================================================
    # PART 2: DIGIMON SYSTEM (ẤP TRỨNG, TIẾN HÓA & TRÁI CÂY SIZE)
    # ========================================================================

    @app_commands.command(name="hatch", description=f"Hatch a Rookie Digimon (Costs 5 Hatch Cores)")
    @app_commands.describe(confirm_replace="Set to True to permanently replace your current Digimon")
    async def hatch(self, interaction: discord.Interaction, confirm_replace: bool = False):
        """Lệnh ấp trứng yêu cầu Hatch Core và áp dụng cơ chế Size ngẫu nhiên"""
        await interaction.response.defer()
        user_id = interaction.user.id
        
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        if not profile:
            profile = {
                "user_id": user_id, "ign": interaction.user.display_name, "gold": 0, "digibit": 0.0, 
                "orb": 0, "hatch_core": 0, "current_hp": 0, 
                "gear": {"weapon": "None", "armor": "None", "vice": "None"},
                "inventory": [], "digicore": 20, "is_vip": False, "last_core_reset": datetime.utcnow().strftime("%Y-%m-%d")
            }
            await rpg_profiles_col.insert_one(profile)

        if profile.get("hatch_core", 0) < self.HATCH_CORE_COST:
            return await interaction.followup.send(f"❌ **Missing Materials!** You need **{self.HATCH_CORE_COST} Hatch Cores** to hatch an egg. (You have: {profile.get('hatch_core', 0)})")

        if profile.get("digimon") and not confirm_replace:
            return await interaction.followup.send("⚠️ **Warning!** You already have an active Digimon partner. Hatching a new one will **PERMANENTLY REPLACE** it. Re-run with `confirm_replace: True` to proceed.")

        await rpg_profiles_col.update_one({"user_id": user_id}, {"$inc": {"hatch_core": -self.HATCH_CORE_COST}})

        is_vip = profile.get("is_vip", False)
        available_digimon = [name for name, data in self.DIGIMON_DATA["rookie"].items() if not data["vip"] or is_vip]
        
        hatched_name = random.choice(available_digimon)
        base_stats = self.DIGIMON_DATA["rookie"][hatched_name]

        min_size, max_size = (1.00, 1.30) if is_vip else (0.85, 1.25)
        size_pct = round(random.uniform(min_size, max_size), 3)

        actual_hp = int(base_stats["hp"] * size_pct)
        actual_atk = int(base_stats["atk"] * size_pct)

        digimon_stats = {
            "name": hatched_name, "stage": "Rookie", "attr": base_stats["attr"],
            "size": size_pct, "hp": actual_hp, "atk": actual_atk, "img": base_stats["img"]
        }

        await rpg_profiles_col.update_one(
            {"user_id": user_id},
            {"$set": {"digimon": digimon_stats, "current_hp": actual_hp}}
        )

        size_display = f"{size_pct * 100:.1f}%"
        embed_color = discord.Color.gold() if size_pct >= 1.25 else discord.Color.green() if size_pct >= 1.00 else discord.Color.red()

        embed = discord.Embed(title="🥚 Egg Hatched Successfully!", description=f"Spent {self.HATCH_CORE_COST} Hatch Cores.\nYou obtained **{hatched_name}**!", color=embed_color)
        embed.set_image(url=digimon_stats["img"])
        embed.add_field(name="🧬 Potential Size", value=f"**{size_display}**")
        embed.add_field(name="⚔️ Scaled ATK", value=str(actual_atk))
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="evolve", description="Consume 50 Orbs to evolve your Digimon to Champion stage")
    async def evolve(self, interaction: discord.Interaction):
        """Tiến hóa áp dụng lại Size hiện tại để scale chỉ số mới"""
        await interaction.response.defer()
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        
        if not profile or not profile.get("digimon"): return await interaction.followup.send("❌ **Error!** You need to `/hatch` a Digimon first.")

        digimon = profile["digimon"]
        if digimon.get("stage") != "Rookie": return await interaction.followup.send("❌ **Max Level!** Your Digimon has already evolved beyond Rookie.")
        if profile.get("orb", 0) < 50: return await interaction.followup.send(f"❌ **Insufficient Materials!** You need **50 Orbs** to evolve.")

        next_form_name = self.EVOLUTION_LINE.get(digimon["name"])
        if not next_form_name: return await interaction.followup.send("❌ **Unknown Line!** Evolution data missing.")

        base_next_stats = self.DIGIMON_DATA["champion"][next_form_name]
        current_size = digimon.get("size", 1.0)

        actual_hp = int(base_next_stats["hp"] * current_size)
        actual_atk = int(base_next_stats["atk"] * current_size)

        next_stats = {
            "name": next_form_name, "stage": "Champion", "attr": base_next_stats["attr"],
            "size": current_size, "hp": actual_hp, "atk": actual_atk, "img": base_next_stats["img"]
        }

        await rpg_profiles_col.update_one(
            {"user_id": interaction.user.id},
            {"$inc": {"orb": -50}, "$set": {"digimon": next_stats, "current_hp": actual_hp}}
        )

        embed = discord.Embed(title="✨ EVOLUTION COMPLETED!", description=f"Your Digimon evolved into **{next_form_name}**!\nSize Maintained: **{current_size * 100:.1f}%**", color=discord.Color.purple())
        embed.set_image(url=next_stats["img"])
        embed.add_field(name="New HP", value=str(actual_hp), inline=True)
        embed.add_field(name="New ATK", value=str(actual_atk), inline=True)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="use_fruit", description="Use a Size Reroll Fruit to randomize your Digimon's size")
    async def use_fruit(self, interaction: discord.Interaction):
        """Sử dụng trái cây để thay đổi phần trăm kích thước của Digimon"""
        await interaction.response.defer()
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})

        if not profile or not profile.get("digimon"):
            return await interaction.followup.send("❌ **Error!** You don't have an active Digimon.")

        inventory = profile.get("inventory", [])
        if "Size Reroll Fruit" not in inventory:
            return await interaction.followup.send("❌ **Not Found!** You don't have a Size Reroll Fruit in your inventory.")

        # Xóa 1 trái cây bằng Python tránh lỗi MongoDB
        inventory.remove("Size Reroll Fruit")
        
        is_vip = profile.get("is_vip", False)
        min_size, max_size = (1.00, 1.30) if is_vip else (0.85, 1.25)
        new_size = round(random.uniform(min_size, max_size), 3)

        digimon = profile.get("digimon")
        stage = digimon.get("stage", "Rookie").lower()
        name = digimon.get("name")
        
        # Lấy lại base stats theo form hiện tại
        base_stats = self.DIGIMON_DATA.get(stage, {}).get(name)
        if not base_stats:
            return await interaction.followup.send("❌ **Error!** Could not fetch base stats data.")

        actual_hp = int(base_stats["hp"] * new_size)
        actual_atk = int(base_stats["atk"] * new_size)

        digimon["size"] = new_size
        digimon["hp"] = actual_hp
        digimon["atk"] = actual_atk

        await rpg_profiles_col.update_one(
            {"user_id": user_id},
            {"$set": {"inventory": inventory, "digimon": digimon, "current_hp": actual_hp}}
        )

        embed = discord.Embed(title="🍎 Fruit Consumed!", color=discord.Color.green())
        embed.description = f"Your **{name}** ate the Size Reroll Fruit!"
        embed.add_field(name="New Size", value=f"**{new_size * 100:.1f}%**", inline=False)
        embed.add_field(name="New Base Stats", value=f"❤️ HP: {actual_hp} | ⚔️ ATK: {actual_atk}", inline=False)
        await interaction.followup.send(embed=embed)

    # ========================================================================
    # PART 3: PVE & MINING SYSTEM
    # ========================================================================

    @app_commands.command(name="mine", description="Mine for Digibits (No energy cost, low success rate)")
    @app_commands.checks.cooldown(1, 10, key=lambda i: i.user.id) 
    async def mine(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if random.random() < 0.40:
            await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$inc": {"digibit": 0.25}})
            await interaction.followup.send("⛏️ **Clink!** You successfully mined **0.25 Digibits**!")
        else:
            await interaction.followup.send("💨 **Swoosh!** You found nothing but rocks this time.")

    @mine.error
    async def mine_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(f"⏳ **Mining Fatigue!** Rest for **{error.retry_after:.1f}s**.", ephemeral=True)

    @app_commands.command(name="auto_mine", description="VIP ONLY: Simulate 6 hours of mining instantly (1 per day)")
    async def auto_mine(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        if not profile or not profile.get("is_vip"):
            return await interaction.followup.send("👑 **VIP Exclusive!** Only VIP members can deploy Auto-Miners.", ephemeral=True)

        current_date = datetime.utcnow().strftime("%Y-%m-%d")
        if profile.get("last_automine") == current_date:
            return await interaction.followup.send("❌ **Cooldown!** You have already used your 6-hour Auto-Miner today.")

        successes = sum(1 for _ in range(360) if random.random() < 0.40)
        total_bits = successes * 0.25

        await rpg_profiles_col.update_one(
            {"user_id": user_id},
            {"$inc": {"digibit": total_bits}, "$set": {"last_automine": current_date}}
        )

        embed = discord.Embed(title="🤖 VIP Auto-Miner Report", color=discord.Color.blue())
        embed.description = "Your drones have finished scanning the sector for 6 hours."
        embed.add_field(name="Successful Strikes", value=f"{successes}/360 attempts", inline=True)
        embed.add_field(name="Digibits Mined", value=f"**+{total_bits:.2f} Bits**", inline=True)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="farm_dungeon", description="Spend 1 Digicore to farm gear, Digibits, and Hatch Cores")
    @app_commands.choices(dungeon=[
        app_commands.Choice(name="Digital Forest (Weapons)", value="digital_forest"),
        app_commands.Choice(name="Factorial Town (Armors)", value="factorial_town"),
        app_commands.Choice(name="Server Continent (Vices)", value="server_continent")
    ])
    async def farm_dungeon(self, interaction: discord.Interaction, dungeon: str):
        """Phụ bản rơi trang bị, Digibit và Hatch Core"""
        await interaction.response.defer()
        user_id = interaction.user.id
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        if not profile or not profile.get("digimon"): return await interaction.followup.send("❌ **No Digimon!** Hatch an egg first.")
            
        current_cores = await self.verify_and_refresh_cores(user_id, profile)
        if current_cores <= 0: return await interaction.followup.send("❌ **Out of Energy!**")

        is_vip = profile.get("is_vip", False)
        
        # Core: VIP rơi 100%, thường rơi 60%
        core_dropped = 1 if (is_vip or random.random() < 0.60) else 0
        drop_rate = 0.07 if is_vip else 0.05
        
        await rpg_profiles_col.update_one(
            {"user_id": user_id}, 
            {"$inc": {"digicore": -1, "digibit": 1.00, "hatch_core": core_dropped}}
        )
        
        loot_dropped = None
        if random.random() < drop_rate:
            loot_dropped = self.roll_pve_loot(dungeon)
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$push": {"inventory": loot_dropped}})

        embed = discord.Embed(title=f"🏰 Dungeon Cleared: {self.DUNGEONS[dungeon]['name']}", color=discord.Color.green())
        reward_text = f"🌐 **+1.00 Digibit**\n"
        if core_dropped > 0: reward_text += f"🧬 **+1 Hatch Core**\n"
            
        embed.add_field(name="Rewards Received", value=reward_text, inline=True)
        if loot_dropped:
            embed.add_field(name="💥 Rare Drop!", value=f"🎉 **{loot_dropped}**", inline=False)
            embed.color = discord.Color.gold()
        await interaction.followup.send(embed=embed)

    # ========================================================================
    # PART 4: COMBAT & WORLD BOSS MECHANICS
    # ========================================================================

    @tasks.loop(minutes=1)
    async def auto_spawn_boss(self):
        config = await world_boss_col.find_one({"type": "spawn_config"})
        if not config or "next_spawn" not in config or int(time.time()) < config["next_spawn"]:
            return

        if await world_boss_col.find_one({"is_active": True}): return
        await world_boss_col.update_one({"type": "spawn_config"}, {"$unset": {"next_spawn": ""}})

        boss_list = [
            {"name": "Devimon", "hp": 100000, "attr": "Virus", "img": "https://digimon.net/cimages/digimon/devimon.jpg"},
            {"name": "Myotismon", "hp": 300000, "attr": "Virus", "img": "https://digimon.net/cimages/digimon/myotismon.jpg"},
            {"name": "MetalSeadramon", "hp": 600000, "attr": "Data", "img": "https://digimon.net/cimages/digimon/metalseadramon.jpg"},
            {"name": "Wargreymon", "hp": 1000000, "attr": "Vaccine", "img": "https://digimon.net/cimages/digimon/wargreymon.jpg"}
        ]
        boss = random.choice(boss_list)
        boss.update({"is_active": True, "damage_log": {}})
        await world_boss_col.insert_one(boss)

        msg = f"🚨 **WARNING!** World Boss **{boss['name']}** ({boss['attr']}) has appeared with **{boss['hp']:,} HP**!"
        await self.broadcast_system_message(msg)

    @auto_spawn_boss.before_loop
    async def before_auto_spawn(self): await self.bot.wait_until_ready()

    @app_commands.command(name="protect", description="Take a defensive stance to block the next Boss Rage attack")
    @app_commands.checks.cooldown(1, 45, key=lambda i: i.user.id)
    async def protect(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"is_protecting": True}})
        await interaction.followup.send("🛡️ **Defensive Stance Active!** Your Digimon will drastically reduce damage from the next Boss Rage.")

    @app_commands.command(name="attack", description="Command your Digimon to attack the World Boss")
    @app_commands.checks.cooldown(1, 4, key=lambda i: i.user.id)
    async def attack(self, interaction: discord.Interaction):
        await interaction.response.defer()

        boss = await world_boss_col.find_one({"is_active": True})
        if not boss: return await interaction.followup.send("❌ **No active World Boss.**")

        player = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not player or not player.get("digimon"): return await interaction.followup.send("❌ **You need to `/hatch` a Digimon first!**")
        if player.get("current_hp", 0) <= 0: return await interaction.followup.send("☠️ **Your Digimon fainted!** Use `/heal` to revive.")

        stats = self.get_total_stats(player)
        digimon = player["digimon"]
        
        raw_dmg = stats["atk"] + random.randint(-5, 10)
        is_crit = random.randint(1, 100) <= stats["crit_rate"]
        if is_crit: raw_dmg *= stats["crit_dmg"]
            
        attr_mult = self.get_attribute_multiplier(digimon["attr"], boss["attr"])
        final_dmg = int(raw_dmg * attr_mult * (1.25 if attr_mult > 1 else 1.0))
        
        user_str = str(interaction.user.id)
        result = await world_boss_col.find_one_and_update(
            {"is_active": True},
            {"$inc": {"current_hp": -final_dmg, f"damage_log.{user_str}": final_dmg}},
            return_document=discord.pymongo.ReturnDocument.AFTER
        )

        crit_tag = "🔥 **CRITICAL HIT!** " if is_crit else ""
        attr_tag = "*(Effective)* " if attr_mult > 1 else "*(Resisted)* " if attr_mult < 1 else ""
        msg = f"{crit_tag}💥 **{digimon['name']}** used attack! Dealt **{final_dmg}** {attr_tag}DMG. (Boss HP: {max(0, result['current_hp']):,})"

        if random.random() < 0.30 and result['current_hp'] > 0:
            boss_dmg = random.randint(250, 600)
            if player.get("is_protecting"):
                boss_dmg = int(boss_dmg * 0.2) 
                msg += f"\n🛡️ **GUARDED!** You blocked the Boss Rage! Took only **{boss_dmg} DMG**."
                await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$unset": {"is_protecting": ""}})
            else:
                msg += f"\n💢 **BOSS RAGE!** The boss countered for **{boss_dmg} DMG**!"
                
            new_hp = max(0, player["current_hp"] - boss_dmg)
            await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"current_hp": new_hp}})
            if new_hp == 0: msg += "\n💀 **YOUR DIGIMON FAINTED!**"

        if result['current_hp'] <= 0:
            await self.distribute_boss_loot(interaction, result)
        else:
            await interaction.followup.send(msg)

    async def distribute_boss_loot(self, interaction: discord.Interaction, boss_data: dict):
        """Phân bổ chiến lợi phẩm World Boss với tỷ lệ rớt mới"""
        await world_boss_col.update_one({"_id": boss_data["_id"]}, {"$set": {"is_active": False}})
        delay = random.randint(1800, 5400) 
        await world_boss_col.update_one({"type": "spawn_config"}, {"$set": {"next_spawn": int(time.time()) + delay}}, upsert=True)

        announcement = f"🎉 **THE WORLD BOSS HAS FALLEN!**\n\n**🏆 Leaderboard Rewards:**\n"
        log = boss_data.get("damage_log", {})
        sorted_log = sorted(log.items(), key=lambda x: x[1], reverse=True)
        total_hp = boss_data.get("max_hp", 1)
        divine_pool = ["Divine Blade (Unlocked)", "Divine Aegis (Unlocked)", "Divine Vice (Unlocked)"]

        for rank, (uid_str, dmg) in enumerate(sorted_log, 1):
            dmg_percent = dmg / total_hp
            divine_chance = (0.20 / rank) + dmg_percent
            
            # Cân bằng Orb rơi rớt do giá Evolution giảm
            orbs_earned = max(1, int(dmg_percent * 10)) 
            if rank == 1: orbs_earned += 10 
            elif rank <= 3: orbs_earned += 5
            
            reward_str = f"+{orbs_earned} Orbs"
            update_query = {"$inc": {"orb": orbs_earned}}

            # Tỷ lệ rớt Trái cây Size Reroll cho Top 3
            if rank <= 3 and random.random() < 0.30:
                reward_str += " & 🍎 **Size Reroll Fruit**"
                update_query["$push"] = {"inventory": "Size Reroll Fruit"}
            
            # Đẩy Divine Gear vào mảng inventory an toàn
            if random.random() < divine_chance:
                divine_drop = random.choice(divine_pool)
                reward_str += f" & 👑 **{divine_drop}**"
                if "$push" not in update_query:
                    update_query["$push"] = {"inventory": divine_drop}
                else:
                    update_query["$push"]["inventory"] = {"$each": ["Size Reroll Fruit", divine_drop]} if "Size Reroll Fruit" in reward_str else divine_drop
                
            await rpg_profiles_col.update_one({"user_id": int(uid_str)}, update_query)
            if rank <= 10: announcement += f"#{rank} <@{uid_str}>: {dmg:,} DMG ➡️ {reward_str}\n"

        await interaction.followup.send(announcement)
        await self.broadcast_system_message(announcement)

    # ========================================================================
    # PART 5: MARKETPLACE SYSTEM (CHỢ GIAO DỊCH LIÊN SERVER)
    # ========================================================================

    @app_commands.command(name="market_sell", description="List an item or material on the market for Digibits")
    @app_commands.choices(item_type=[
        app_commands.Choice(name="Equipment (From Inventory)", value="equipment"),
        app_commands.Choice(name="Boss Orb (Material)", value="orb"),
        app_commands.Choice(name="Hatch Core (Material)", value="core")
    ])
    @app_commands.describe(
        target_name="Exact name of equipment OR quantity if selling material (e.g. '5')",
        price="Total selling price in Digibits (e.g. 12.50)"
    )
    async def market_sell(self, interaction: discord.Interaction, item_type: str, target_name: str, price: float):
        """Đăng bán vật phẩm/tài nguyên trên Chợ chung"""
        await interaction.response.defer()
        user_id = interaction.user.id
        
        if price <= 0: return await interaction.followup.send("❌ **Invalid Price!** Price must be greater than 0.")
        price = round(price, 2)
        
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        if not profile: return await interaction.followup.send("❌ You don't have an active RPG profile.")

        listing_id = f"LIT-{random.randint(1000, 9999)}"
        display_name = ""

        if item_type == "equipment":
            inventory = profile.get("inventory", [])
            if target_name not in inventory:
                return await interaction.followup.send(f"❌ **Item Not Found!** '{target_name}' is not in your inventory.")
            if not target_name.endswith("(Unlocked)"):
                return await interaction.followup.send("❌ **Listing Failed!** Only items with the **(Unlocked)** tag can be sold.")
            inventory.remove(target_name)
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {"inventory": inventory}})
            display_name = target_name

        elif item_type == "orb":
            try:
                qty = int(target_name)
                if qty <= 0: raise ValueError
            except ValueError:
                return await interaction.followup.send("❌ **Error!** Please input a valid positive integer quantity for Orbs.")
            if profile.get("orb", 0) < qty:
                return await interaction.followup.send(f"❌ **Insufficient Stock!** You only have {profile.get('orb', 0)} Orbs.")
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$inc": {"orb": -qty}})
            display_name = f"{qty}x World Boss Orb"

        elif item_type == "core":
            try:
                qty = int(target_name)
                if qty <= 0: raise ValueError
            except ValueError:
                return await interaction.followup.send("❌ **Error!** Please input a valid positive integer quantity for Cores.")
            if profile.get("hatch_core", 0) < qty:
                return await interaction.followup.send(f"❌ **Insufficient Stock!** You only have {profile.get('hatch_core', 0)} Hatch Cores.")
            await rpg_profiles_col.update_one({"user_id": user_id}, {"$inc": {"hatch_core": -qty}})
            display_name = f"{qty}x Hatch Core"

        await market_col.insert_one({
            "listing_id": listing_id, "seller_id": user_id, "seller_name": interaction.user.name,
            "item_type": item_type, "item_name": display_name, "raw_gear_name": target_name if item_type == "equipment" else "",
            "quantity": qty if item_type != "equipment" else 1, "price": price, "created_at": int(time.time())
        })

        embed = discord.Embed(title="🏪 Marketplace Listing Created", color=discord.Color.blue())
        embed.description = f"Successfully listed **{display_name}** on the public server market."
        embed.add_field(name="Listing ID", value=f"`{listing_id}`", inline=True)
        embed.add_field(name="Price", value=f"🌐 {price:.2f} Digibits", inline=True)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="market_view", description="Browse all active listings on the marketplace")
    async def market_view(self, interaction: discord.Interaction):
        await interaction.response.defer()
        listings = await market_col.find({}).sort("created_at", -1).to_list(25) 
        if not listings:
            return await interaction.followup.send("🏪 **The marketplace is empty right now.** Use `/market_sell` to list something!")

        embed = discord.Embed(title="🏪 Digital World Marketplace", color=discord.Color.purple())
        embed.description = "Use `/market_buy [listing_id]` to purchase an item."
        for item in listings:
            embed.add_field(
                name=f"📦 {item['item_name']}",
                value=f"🆔 ID: `{item['listing_id']}`\n💰 Price: **{item['price']:.2f} Digibits**\n👤 Seller: {item['seller_name']}",
                inline=False
            )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="market_buy", description="Buy an item from the marketplace using your Digibits")
    async def market_buy(self, interaction: discord.Interaction, listing_id: str):
        """Mua vật phẩm/tài nguyên trên Chợ"""
        await interaction.response.defer()
        buyer_id = interaction.user.id
        
        listing = await market_col.find_one({"listing_id": listing_id.upper()})
        if not listing: return await interaction.followup.send("❌ **Listing Not Found!** This listing may have been bought or expired.")
        if listing["seller_id"] == buyer_id: return await interaction.followup.send("❌ **Action Denied!** You cannot purchase your own listed items.")

        buyer_profile = await rpg_profiles_col.find_one({"user_id": buyer_id})
        if not buyer_profile or buyer_profile.get("digibit", 0.0) < listing["price"]:
            return await interaction.followup.send(f"❌ **Transaction Failed!** Insufficient Digibits. (Required: {listing['price']:.2f})")

        price = listing["price"]
        await rpg_profiles_col.update_one({"user_id": buyer_id}, {"$inc": {"digibit": -price}})
        await rpg_profiles_col.update_one({"user_id": listing["seller_id"]}, {"$inc": {"digibit": price}})

        item_type = listing["item_type"]
        if item_type == "equipment":
            await rpg_profiles_col.update_one({"user_id": buyer_id}, {"$push": {"inventory": listing["raw_gear_name"]}})
        elif item_type == "orb":
            await rpg_profiles_col.update_one({"user_id": buyer_id}, {"$inc": {"orb": listing["quantity"]}})
        elif item_type == "core":
            await rpg_profiles_col.update_one({"user_id": buyer_id}, {"$inc": {"hatch_core": listing["quantity"]}})

        await market_col.delete_one({"_id": listing["_id"]})

        embed = discord.Embed(title="🛍️ Deal Completed Successfully!", color=discord.Color.green())
        embed.description = f"You bought **{listing['item_name']}** from **{listing['seller_name']}**."
        embed.add_field(name="Amount Paid", value=f"🌐 -{price:.2f} Digibits", inline=True)
        await interaction.followup.send(embed=embed)

    # ========================================================================
    # PART 6: PROFILE & UTILITIES
    # ========================================================================

    @app_commands.command(name="rpg_profile", description="View your Digimon Tamer profile")
    async def rpg_profile(self, interaction: discord.Interaction):
        await interaction.response.defer()
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        
        if not profile: return await interaction.followup.send("❌ **Welcome to Digital World!** Please use `/hatch` to start your adventure.")

        digimon = profile.get("digimon", {})
        stats = self.get_total_stats(profile)
        gear = profile.get("gear", {})
        
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
        
        inv = ", ".join(profile.get("inventory", [])) or "Empty"
        embed.add_field(name="🎒 Inventory", value=f"```{inv}```", inline=False)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="equip_gear", description="Equip a weapon or armor from your inventory to boost your total stats")
    async def equip_gear(self, interaction: discord.Interaction, item_name: str):
        await interaction.response.defer()
        user_id = interaction.user.id
        
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        if not profile: return await interaction.followup.send("❌ **Profile not found!**")

        inventory = profile.get("inventory", [])
        matched_item = next((item for item in inventory if item.lower() == item_name.lower()), None)
        if not matched_item: return await interaction.followup.send(f"❌ **Equip Failed!** You do not possess any item named '{item_name}'.")

        cleaned_base = self.clean_item_name(matched_item)
        slot_type = self.ITEMS[cleaned_base]["type"]

        await rpg_profiles_col.update_one({"user_id": user_id}, {"$set": {f"gear.{slot_type}": matched_item}})
        await interaction.followup.send(f"🛡️ **Success!** You have equipped **{matched_item}** into your `{slot_type.upper()}` slot.")

    @app_commands.command(name="heal", description="Recover Digimon HP (120s Cooldown)")
    @app_commands.checks.cooldown(1, 120, key=lambda i: i.user.id) 
    async def heal(self, interaction: discord.Interaction):
        await interaction.response.defer()
        profile = await rpg_profiles_col.find_one({"user_id": interaction.user.id})
        if not profile or not profile.get("digimon"): return await interaction.followup.send("❌ **No Digimon found!**")
            
        max_hp = self.get_total_stats(profile)["hp"]
        await rpg_profiles_col.update_one({"user_id": interaction.user.id}, {"$set": {"current_hp": max_hp}})
        await interaction.followup.send(f"✨ **Healed!** HP restored to **{max_hp}/{max_hp}**.")

    # ========================================================================
    # PART 7: SETUP, ADMIN & WEBHOOK EVENT LISTENERS
    # ========================================================================

    @app_commands.command(name="setup_boss_channel", description="Setup the live World Boss battlefield and cross-server chat")
    @app_commands.describe(channel="Choose a text channel")
    async def setup_boss_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        is_owner = await self.bot.is_owner(interaction.user)
        if not (interaction.user.guild_permissions.administrator or is_owner):
            return await interaction.followup.send("❌ **Access Denied!** You need Administrator permissions.", ephemeral=True)

        try:
            existing_webhooks = await channel.webhooks()
            webhook = next((w for w in existing_webhooks if w.user == self.bot.user), None)
            if not webhook:
                webhook = await channel.create_webhook(name="DMW Cross-Server Relay")
                
            await boss_channels_col.update_one(
                {"guild_id": interaction.guild_id},
                {"$set": {"channel_id": channel.id, "webhook_url": webhook.url}},
                upsert=True
            )
            await interaction.followup.send(f"✅ **Success!** Battlefield has been established at {channel.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ **Error!** Bot lacks 'Manage Webhooks' permission.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ **Error occurred:** {e}", ephemeral=True)

    @app_commands.command(name="spawn_boss", description="Admin: Force spawn a World Boss to trigger the cycle")
    async def spawn_boss(self, interaction: discord.Interaction, name: str, hp: int):
        if not interaction.user.guild_permissions.administrator: return await interaction.response.send_message("❌ **Access Denied!** Admin privileges required.", ephemeral=True)
            
        await world_boss_col.insert_one({"name": name, "max_hp": hp, "current_hp": hp, "attr": "Virus", "img": "", "is_active": True, "damage_log": {}})
        await interaction.response.send_message(f"⚔️ **World Boss {name} forced to spawn!**")
        await self.broadcast_system_message(f"🚨 **WARNING!** **{name}** has arrived with **{hp:,} HP**!")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        current_channel_config = await boss_channels_col.find_one({"channel_id": message.channel.id})
        if not current_channel_config: return 

        other_channels = await boss_channels_col.find({"channel_id": {"$ne": message.channel.id}}).to_list(length=None)
        if not other_channels: return 

        tasks = []
        for config in other_channels:
            webhook_url = config.get("webhook_url")
            if webhook_url:
                sender_name = f"[{message.guild.name[:10]}] {message.author.display_name}"
                tasks.append(self.send_webhook_message(
                    webhook_url=webhook_url, content=message.content, username=sender_name,
                    avatar_url=message.author.display_avatar.url, attachments=message.attachments
                ))
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)

    async def send_webhook_message(self, webhook_url, content, username, avatar_url, attachments):
        try:
            async with aiohttp.ClientSession() as session:
                webhook = discord.Webhook.from_url(webhook_url, session=session)
                files_content = ""
                if attachments: files_content = "\n" + "\n".join([att.url for att in attachments])
                final_content = content + files_content
                if final_content.strip() == "": return 
                await webhook.send(content=final_content, username=username, avatar_url=avatar_url)
        except Exception as e:
            print(f"Relay webhook error: {e}")

    async def broadcast_system_message(self, content: str):
        all_channels = await boss_channels_col.find({}).to_list(None)
        tasks = []
        for config in all_channels:
            if url := config.get("webhook_url"): tasks.append(self._send_system_webhook(url, content))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_system_webhook(self, webhook_url, content):
        try:
            async with aiohttp.ClientSession() as session:
                webhook = discord.Webhook.from_url(webhook_url, session=session)
                await webhook.send(content=content, username="WORLD BOSS SYSTEM", avatar_url=self.bot.user.display_avatar.url)
        except Exception:
            pass

async def setup(bot):
    await bot.add_cog(RPGSystemCog(bot))