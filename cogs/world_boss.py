import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
import time
import asyncio
from pymongo import UpdateOne
# --- CẤU HÌNH CƠ BẢN ---
OWNER_IDS = [1283689737567211581] # Thay ID của bạn vào đây

OLYMPOS_XII = [
    {"name": "Jupitermon", "attr": "VA", "img": "https://imgur.com/link_jupitermon.png"},
    {"name": "Junomon", "attr": "VI", "img": "https://imgur.com/link_junomon.png"},
    {"name": "Ceresmon", "attr": "DA", "img": "https://imgur.com/link_ceresmon.png"},
    {"name": "Bacchusmon", "attr": "VI", "img": "https://imgur.com/link_bacchusmon.png"},
    {"name": "Apollomon", "attr": "VA", "img": "https://imgur.com/link_apollomon.png"},
    {"name": "Dianamon", "attr": "DA", "img": "https://imgur.com/link_dianamon.png"},
    {"name": "Minervamon", "attr": "VI", "img": "https://imgur.com/link_minervamon.png"},
    {"name": "Marsmon", "attr": "VA", "img": "https://imgur.com/link_marsmon.png"},
    {"name": "Vulcanusmon", "attr": "DA", "img": "https://imgur.com/link_vulcanusmon.png"},
    {"name": "Venusmon", "attr": "VA", "img": "https://imgur.com/link_venusmon.png"},
    {"name": "Mercurymon", "attr": "VI", "img": "https://imgur.com/link_mercurymon.png"},
    {"name": "Neptunemon", "attr": "VA", "img": "https://imgur.com/link_neptunemon.png"},
]

# Scale chỉ số Boss theo Tier (Tier 1: 30k HP, 300 ATK)
BOSS_STATS = {
    1: {"hp": 30000, "atk": 300},
    2: {"hp": 150000, "atk": 800},
    3: {"hp": 500000, "atk": 2000, "skill_dmg_pct": 0.50},
    4: {"hp": 1500000, "atk": 5000, "skill_dmg_pct": 0.70},
    5: {"hp": 5000000, "atk": 12000, "skill_dmg_pct": 0.90},
}



class WorldBossView(discord.ui.View):
    def __init__(self, cog, boss_state):
        super().__init__(timeout=None)
        self.cog = cog
        self.boss_state = boss_state
        self.manual_cooldowns = {} # Theo dõi CD 5s
        

    async def get_player_data(self, user_id):
        if user_id not in self.cog.player_cache:
            player_data = await self.cog.db.rpg_profiles.find_one({"user_id": user_id})
            if not player_data: return None
            
            self.cog.player_cache[user_id] = {
                "db_data": player_data,
                "turn_dmg": 0,
                "total_dmg": 0,
                "auto_attack": False,
                "auto_attack_start_time": 0, # MỚI: Bắt đầu tính giờ Auto
                "protect": False,
                "hp": player_data.get('stats', {}).get('hp', 100),
                "is_dead_notified": False # MỚI: Đánh dấu để không spam tin nhắn chết mỗi phút
            }
        return self.cog.player_cache[user_id]

    @discord.ui.button(label="Attack", style=discord.ButtonStyle.danger, custom_id="wb_attack")
    async def btn_attack(self, interaction: discord.Interaction, button: discord.ui.Button):
        now = time.time()
        if interaction.user.id in self.manual_cooldowns and now - self.manual_cooldowns[interaction.user.id] < 5:
            return await interaction.response.send_message("⏳ Đang hồi chiêu (5s)...", ephemeral=True)
            
        p_cache = await self.get_player_data(interaction.user.id)
        if not p_cache or p_cache['hp'] <= 0:
            return await interaction.response.send_message("❌ Bạn đã chết hoặc chưa tạo profile!", ephemeral=True)

        self.manual_cooldowns[interaction.user.id] = now
        
        # Lấy đầy đủ 4 tham số từ hàm mới
        dmg, is_crit, used_skill, skill_name = self.cog.calculate_damage(p_cache['db_data'], self.boss_state['attr'])
        
        p_cache['turn_dmg'] += dmg
        p_cache['total_dmg'] += dmg
        
        # Build chuỗi thông báo kết quả chi tiết
        msg = f"💥 Bạn đã tung đòn đánh gây **{dmg:,.0f}** sát thương!"
        if used_skill: 
            msg = f"✨ Kỹ năng **[{skill_name}]** kích hoạt! " + msg
        if is_crit: 
            msg = f"🔥 **BẠO KÍCH!** " + msg
            
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="Auto Attack", style=discord.ButtonStyle.primary, custom_id="wb_auto")
    async def btn_auto(self, interaction: discord.Interaction, button: discord.ui.Button):
        p_cache = await self.get_player_data(interaction.user.id)
        if not p_cache: return await interaction.response.send_message("❌ Chưa có profile!", ephemeral=True)
        if p_cache['hp'] <= 0: return await interaction.response.send_message("❌ Bạn đã tử trận, không thể bật Auto!", ephemeral=True)
        
        p_cache['auto_attack'] = not p_cache['auto_attack']
        if p_cache['auto_attack']:
            p_cache['auto_attack_start_time'] = time.time() # Lưu thời điểm bật
            status = "BẬT (Kéo dài tối đa 15 phút)"
        else:
            p_cache['auto_attack_start_time'] = 0
            status = "TẮT"
            
        await interaction.response.send_message(f"🔄 Đã {status} Auto Attack!", ephemeral=True)

    @discord.ui.button(label="Protect", style=discord.ButtonStyle.success, custom_id="wb_protect")
    async def btn_protect(self, interaction: discord.Interaction, button: discord.ui.Button):
        p_cache = await self.get_player_data(interaction.user.id)
        if not p_cache: return await interaction.response.send_message("❌ Chưa có profile!", ephemeral=True)
        
        p_cache['protect'] = True
        await interaction.response.send_message("🛡️ Bạn đã dựng khiên bảo vệ cho lượt này!", ephemeral=True)

    @discord.ui.button(label="Heal", style=discord.ButtonStyle.secondary, custom_id="wb_heal")
    async def btn_heal(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Giả lập bơm máu đơn giản
        p_cache = await self.get_player_data(interaction.user.id)
        if not p_cache: return
        max_hp = p_cache['db_data'].get('stats', {}).get('hp', 100)
        p_cache['hp'] = max_hp
        await interaction.response.send_message("💉 Bạn đã hồi đầy máu!", ephemeral=True)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, custom_id="wb_refresh")
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 1. Gọi lại hàm build_boss_embed để lấy dữ liệu sát thương/bảng xếp hạng mới nhất từ cache
        updated_embed = self.cog.build_boss_embed()
        
        # 2. Edit thẳng vào tin nhắn hiện tại chứa nút bấm này
        await interaction.response.edit_message(embed=updated_embed, view=self)




class WorldBossSystem(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = bot.db # Thích ứng với khai báo MongoDB của bạn
        self.boss_channels_col = self.db.boss_channels 
        self.rpg_profiles = db["rpg_profiles"]
        self.world_boss = db["world_boss"]

        # Global State
        self.boss_state = {
            "active": False,
            "tier": 1,
            "hp": 0,
            "max_hp": 0,
            "atk": 0,
            "name": "",
            "attr": "",
            "img": "",
            "charging_skill": False,
            "message_id": None,
            "channel_id": None
        }
        self.player_cache = {} # Lưu tạm trạng thái player trong turn
        self.turn = 0
        
        # Khởi động loop
        self.boss_loop.start()

    @app_commands.command(name="combat", description="Hiển thị UI chiến đấu với World Boss hiện tại")
    async def combat(self, interaction: discord.Interaction):
        if not self.boss_state["active"]:
            return await interaction.response.send_message("❌ Hiện tại không có World Boss nào đang xuất hiện!", ephemeral=True)
            
        embed = self.build_boss_embed()
        # View vẫn lưu trạng thái của vòng lặp hiện tại
        await interaction.response.send_message(embed=embed, view=WorldBossView(self, self.boss_state))

    # Hàm tính sát thương của người chơi (Yêu cầu 7)
    def calculate_damage(self, db_data, boss_attr):
        # 1. Lấy Base Stats
        stats = db_data.get('stats', {})
        base_atk = stats.get('atk', 0)
        base_crit_rate = stats.get('crit_rate', 0)
        
        # 2. Lấy All Gear Stats (Equipment, Armor, Vice)
        gear = db_data.get('gear', {})
        weapon_atk = gear.get('weapon', {}).get('atk', 0)
        
        # Vice thường mang dòng crit rate / crit dmg
        vice_crit_rate = gear.get('vice', {}).get('crit_rate', 0)
        # Giả định crit_dmg trong DB là multiplier cộng thêm (VD: crit_dmg = 3 nghĩa là +300% sát thương bạo)
        vice_crit_dmg = gear.get('vice', {}).get('crit_dmg', 0.0) 
        
        # Armor thường không cộng ATK nhưng phòng hờ nếu thiết kế của bạn có
        armor_atk = gear.get('armor', {}).get('atk', 0)

        # 3. Lấy Active Digimon & Skill
        active_id = db_data.get('active_digimon_id')
        digimon_list = db_data.get('digimon_list', [])
        active_digi = next((d for d in digimon_list if d.get('id') == active_id), {})
        
        digi_atk = active_digi.get('atk', 0)
        digi_attr = active_digi.get('attr', 'NO')
        digi_size = active_digi.get('size', 1.0)
        
        skill = active_digi.get('skill', {})
        skill_name = skill.get('name', None)
        skill_dmg_mult = skill.get('dmg_mult', 1.0)
        skill_chance = skill.get('chance', 0.0)
        
        # ---> Bắt đầu tính toán <---
        
        # Tổng hợp ATK từ mọi nguồn
        total_atk = base_atk + weapon_atk + armor_atk + digi_atk
        
        # Hệ số Scale Size (VD size 1.218 -> tăng 1.218 lần ATK)
        total_atk *= digi_size
        
        # Khắc hệ (VA > VI > DA > VA)
        attr_mult = 1.0
        if (digi_attr == "VA" and boss_attr == "VI") or \
           (digi_attr == "VI" and boss_attr == "DA") or \
           (digi_attr == "DA" and boss_attr == "VA"):
            attr_mult = 1.3 # Khắc hệ +30%
        elif (digi_attr == "VA" and boss_attr == "DA") or \
             (digi_attr == "VI" and boss_attr == "VA") or \
             (digi_attr == "DA" and boss_attr == "VI"):
            attr_mult = 0.8 # Bị khắc -20%
            
        final_dmg = total_atk * attr_mult
        
        # Tính toán Kỹ năng (Skill Proc) - Dựa theo Requirement 12
        used_skill = False
        if skill_name and random.random() <= skill_chance:
            final_dmg *= skill_dmg_mult
            used_skill = True
        
        # Tính toán Bạo kích (Crit)
        total_crit_rate = base_crit_rate + vice_crit_rate
        # Base bạo kích là 1.5x (150%), cộng thêm hiệu ứng từ Vice
        total_crit_mult = 1.5 + vice_crit_dmg 
        
        is_crit = random.randint(1, 100) <= total_crit_rate
        if is_crit: 
            final_dmg *= total_crit_mult
        
        # Trả về 4 giá trị để in thông báo skill cho Manual Attack
        return int(final_dmg), is_crit, used_skill, skill_name

    # Hàm Spawn Boss (Yêu cầu 1, 2)
    async def spawn_boss(self, tier=1):
        if tier > 5: tier = 1 # Reset tier sau tier 5
        
        boss_data = random.choice(OLYMPOS_XII)
        stats = BOSS_STATS[tier]
        
        # Cập nhật trạng thái ngầm
        self.boss_state.update({
            "active": True, "tier": tier,
            "max_hp": stats["hp"], "hp": stats["hp"], "atk": stats["atk"],
            "name": boss_data["name"], "attr": boss_data["attr"], "img": boss_data["img"],
            "charging_skill": False
        })
        self.player_cache.clear()
        self.turn = 0
        
        print(f"[WORLD BOSS] {boss_data['name']} (Tier {tier}) đã spawn ngầm. Đang chờ người chơi dùng /combat!")
        # Không còn gửi Embed ra kênh nào nữa

    def build_boss_embed(self):
        embed = discord.Embed(
            title=f"👑 [Tier {self.boss_state['tier']}] {self.boss_state['name']} (Hệ {self.boss_state['attr']})", 
            color=discord.Color.red()
        )
        embed.set_image(url=self.boss_state["img"])
        
        # Logic thanh máu
        hp_pct = max(0.0, self.boss_state['hp'] / self.boss_state['max_hp'])
        hp_bar = int(hp_pct * 10)
        embed.add_field(
            name="Chỉ số Boss", 
            value=f"**HP:** {'🟥'*hp_bar}{'⬛'*(10-hp_bar)} ({self.boss_state['hp']:,.0f}/{self.boss_state['max_hp']:,.0f})\n**ATK:** {self.boss_state['atk']}", 
            inline=False
        )
        embed.add_field(name="⏳ Turn", value=f"Lượt thứ {self.turn} - Cập nhật mỗi phút", inline=False)
        
        # Bảng xếp hạng trực tiếp trên UI Boss
        sorted_players = sorted(self.player_cache.items(), key=lambda x: x[1]['total_dmg'], reverse=True)
        if sorted_players:
            lb_text = "\n".join([f"**#{i+1}** <@{uid}>: **{data['total_dmg']:,.0f}** DMG" for i, (uid, data) in enumerate(sorted_players[:10])])
        else:
            lb_text = "*Chưa có ai gây sát thương trong vòng lặp này.*"
            
        embed.add_field(name="🏆 Bảng Xếp Hạng (Top 10)", value=lb_text, inline=False)

        if self.boss_state['charging_skill']:
            embed.description = "⚠️ **BOSS ĐANG VẬN SỨC KỸ NĂNG AOE TỐI THƯỢNG! HÃY DÙNG PROTECT NGAY!** ⚠️"
            
        return embed

    # --- LỆNH SETUP CHANNEL (Yêu cầu 1) ---
    @app_commands.command(name="setup_boss_channel", description="Setup channel for World Boss")
    async def setup_boss_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        is_admin = interaction.permissions.administrator if interaction.guild else False
        if not (is_admin or interaction.user.id in OWNER_IDS): 
            return await interaction.followup.send("❌ Access Denied!", ephemeral=True)
            
        try:
            # Lưu thẳng vào DB config
            await self.boss_channels_col.update_one({}, {"$set": {"channel_id": channel.id, "guild_id": interaction.guild.id}}, upsert=True)
            await interaction.followup.send("✅ Đã cài đặt kênh World Boss thành công. Đang triệu hồi...", ephemeral=True)
            await self.spawn_boss(tier=1)
        except Exception as e:
            await interaction.followup.send(f"❌ Lỗi: {e}", ephemeral=True) 

    # --- VÒNG LẶP CHÍNH CƠ CHẾ TURN-BASE (Yêu cầu 9) ---
    @tasks.loop(seconds=60)
    async def boss_loop(self):
        if not self.boss_state["active"]: return
        self.turn += 1
        current_time = time.time()
        # 1. Tính toán sát thương AUTO ATTACK
        for uid, p_data in self.player_cache.items():
            if p_data["auto_attack"] and p_data["hp"] > 0:
                # 15 phút = 15 * 60 = 900 giây
                if current_time - p_data["auto_attack_start_time"] >= 900:
                    p_data["auto_attack"] = False
                    try:
                        user = self.bot.get_user(uid)
                        if user: await user.send("⏳ **HỆ THỐNG:** Chế độ Auto Attack đã tự động tắt sau khi hoạt động liên tục 15 phút.")
                    except: pass
                else:
                    dmg_per_hit, _, _, _ = self.calculate_damage(p_data["db_data"], self.boss_state['attr'])
                    auto_dmg = dmg_per_hit * 8
                    p_data["turn_dmg"] += auto_dmg
                    p_data["total_dmg"] += auto_dmg
        
        # 2. Boss nhận sát thương
        total_turn_dmg = sum(p["turn_dmg"] for p in self.player_cache.values())
        self.boss_state["hp"] -= total_turn_dmg
        
        # 3. KẾT THÚC TRẬN ĐÁNH NẾU BOSS CHẾT (Yêu cầu 10)
        if self.boss_state["hp"] <= 0:
            self.boss_state["hp"] = 0
            await self.handle_boss_death()
            return
            
        # 4. LƯỢT BOSS TẤN CÔNG (Yêu cầu 4)
        bulk_operations = []
        is_firing_skill = self.boss_state["charging_skill"]
        
        for uid, p_data in self.player_cache.items():
            if p_data["hp"] <= 0: continue
            
            dmg_taken = 0
            hit_by_skill = False
            
            # Tính toán lượng máu mất
            if is_firing_skill:
                if not p_data["protect"]:
                    pct = BOSS_STATS[self.boss_state["tier"]]["skill_dmg_pct"]
                    max_player_hp = p_data["db_data"].get("stats", {}).get("hp", 1000)
                    dmg_taken = int(max_player_hp * pct) + self.boss_state["atk"] * 3
                    hit_by_skill = True
                else:
                    dmg_taken = 0 # Đã dùng khiên cản skill
            elif not p_data["protect"]:
                player_def = p_data["db_data"].get("stats", {}).get("def", 0)
                dmg_taken = max(1, self.boss_state["atk"] - player_def)
                
            p_data["hp"] -= dmg_taken
            p_data["protect"] = False # Reset khiên mỗi lượt
            p_data["turn_dmg"] = 0
            
            # Chuẩn bị tin nhắn DM thông báo
            dm_messages = []
            
            # Thông báo sài Skill (Nếu Boss xả skill lượt này)
            if is_firing_skill:
                if p_data["hp"] > 0: # Chỉ báo ăn skill nếu còn sống (nếu chết thì ghép vào tin báo tử luôn)
                    if hit_by_skill:
                        dm_messages.append(f"💥 **{self.boss_state['name']} vừa tung Kỹ Năng AoE!** Bạn lãnh trọn đòn tấn công và mất **{dmg_taken:,.0f} HP**!")
                    else:
                        dm_messages.append(f"🛡️ **{self.boss_state['name']} vừa tung Kỹ Năng AoE!** Lớp Protect của bạn đã đỡ hoàn toàn đòn đánh!")
            
            # Thông báo Tử trận (Kèm hủy Auto)
            if p_data["hp"] <= 0:
                p_data["hp"] = 0
                p_data["auto_attack"] = False # Hủy auto attack ngay lập tức
                if not p_data.get("is_dead_notified"):
                    p_data["is_dead_notified"] = True
                    dm_messages.append(f"💀 **BẠN ĐÃ TỬ TRẬN!** Máu của bạn đã về 0 sau đòn đánh của {self.boss_state['name']}. Hệ thống Auto Attack đã tự động bị hủy.")
            
            # Gửi tin nhắn ngầm cho user
            if dm_messages:
                try:
                    user = self.bot.get_user(uid)
                    if user: await user.send("\n\n".join(dm_messages))
                except: pass
                
            # Ghi vào DB
            bulk_operations.append(UpdateOne(
                {"user_id": uid},
                {"$set": {"current_hp": max(0, p_data["hp"])}}
            ))
            
        if is_firing_skill: self.boss_state["charging_skill"] = False

        # 5. BOSS CHUẨN BỊ SKILL CHO TURN TỚI (Yêu cầu 4, 5)
        if self.boss_state["tier"] >= 3 and random.random() < 0.2 and not self.boss_state["charging_skill"]:
            self.boss_state["charging_skill"] = True
            # Nhắn tin DM cảnh báo (Yêu cầu 5)
            for uid, p_data in self.player_cache.items():
                if p_data["hp"] > 0:
                    try:
                        user = self.bot.get_user(uid)
                        if user: await user.send(f"⚠️ **CẢNH BÁO TỪ WORLD BOSS:** {self.boss_state['name']} đang chuẩn bị tung Kỹ Năng AoE Tối Thượng! Trở lại kênh và bật **Protect** ngay trước khi hết 1 phút!")
                    except: pass # Bỏ qua nếu user tắt DM

        # 6. Bulk Write lên DB (Yêu cầu 9)
        if bulk_operations:
            await self.db.rpg_profiles.bulk_write(bulk_operations)


    # --- XỬ LÝ PHẦN THƯỞNG VÀ KẾT THÚC (Yêu cầu 8, 10, 11) ---
    async def handle_boss_death(self):
        self.boss_state["active"] = False
        print(f"[WORLD BOSS] {self.boss_state['name']} đã chết! Đang phát phần thưởng...")
        # Sắp xếp xếp hạng sát thương
        sorted_players = sorted(self.player_cache.items(), key=lambda x: x[1]['total_dmg'], reverse=True)
        tier = self.boss_state["tier"]
        bulk_updates = []
        
        # Bảng xếp hạng thu gọn cho DM
        leaderboard_str = "\n".join([f"Top {i+1}: <@{uid}> - **{data['total_dmg']:,.0f}** DMG" for i, (uid, data) in enumerate(sorted_players[:10])])

        for rank, (uid, p_data) in enumerate(sorted_players):
            db_doc = p_data["db_data"]
            user = self.bot.get_user(uid)
            
            # --- Tính toán rớt đồ (Yêu cầu 8) ---
            digibit = random.randint(*[(100,200), (150,200), (200,250), (250,300), (500,500)][tier-1])
            orb = random.randint(*[(10,15), (15,20), (20,25), (26,30), (50,50)][tier-1])
            core = random.randint(*[(20,50), (30,50), (50,100), (100,150), (200,200)][tier-1])
            fruit = random.randint(*[(0,1), (0,2), (1,3), (2,4), (5,5)][tier-1])
            
            dropped_gear = None
            gear_rarity = None
            
            # Drop Mythic T4 (5%) / Origin T5 (2%)
            if tier == 4 and random.random() <= 0.05:
                dropped_gear = "Vũ khí Mythic (Test)" # Thay bằng ID/Dict thật của bạn
                gear_rarity = "Mythic"
            elif tier == 5 and random.random() <= 0.02:
                dropped_gear = "Khiên Origin (Test)" # Thay bằng ID/Dict thật của bạn
                gear_rarity = "Origin"

            # --- Cơ chế phân biệt trùng lặp (Yêu cầu 11) ---
            inventory = db_doc.get("inventory", [])
            gear_inv = db_doc.get("gears_inventory", [])
            msg_gear_drop = ""
            
            if dropped_gear:
                # Giả sử bạn check theo tên item trong gears_inventory array
                is_duplicate = any(g.get("name") == dropped_gear for g in gear_inv)
                if is_duplicate:
                    compensate_bit = 5000 if gear_rarity == "Mythic" else 15000
                    digibit += compensate_bit
                    msg_gear_drop = f"🔄 Rơi trang bị {gear_rarity} nhưng bị trùng! Tự động chuyển hóa thành **{compensate_bit} Digibit**."
                else:
                    msg_gear_drop = f"🌟 **CHÚC MỪNG! BẠN NHẬN ĐƯỢC TRANG BỊ {gear_rarity.upper()}: {dropped_gear}**"
                    # Code push đồ vào inventory (Cần khớp với structure thật của bạn)
                    # "$push": {"gears_inventory": {"name": dropped_gear, "type": "...", "rarity": gear_rarity}}

            # Push size reroll fruit vào array inventory nếu có
            update_query = {
                "$inc": {
                    "digibit": digibit,
                    "orb": orb,
                    "hatch_core": core
                }
            }
            if fruit > 0:
                # Dựa theo DB hình 1, inventory lưu size reroll fruit theo dạng string
                fruits_array = ["Size Reroll Fruit" for _ in range(fruit)]
                update_query["$push"] = {"inventory": {"$each": fruits_array}}

            bulk_updates.append(UpdateOne({"user_id": uid}, update_query))

            # --- Gửi DM cho người chơi (Yêu cầu 10) ---
            if user:
                embed_dm = discord.Embed(title=f"Chiến Báo: {self.boss_state['name']} (Tier {tier}) Đã Bị Tiêu Diệt!", color=discord.Color.gold())
                embed_dm.add_field(name="Thành tích cá nhân", value=f"🏆 Hạng: **{rank + 1}**\n⚔️ Tổng sát thương: **{p_data['total_dmg']:,.0f}**", inline=False)
                
                rewards_text = f"💰 **Digibit:** {digibit}\n🔮 **Orb:** {orb}\n🥚 **Hatch Core:** {core}\n🍎 **Size Reroll Fruit:** {fruit}"
                if msg_gear_drop: rewards_text += f"\n\n{msg_gear_drop}"
                
                embed_dm.add_field(name="🎁 Phần thưởng nhận được", value=rewards_text, inline=False)
                embed_dm.add_field(name="📊 Bảng Xếp Hạng Sát Thương (Top 10)", value=leaderboard_str, inline=False)
                
                try: await user.send(embed=embed_dm)
                except: pass

        # Thực thi bulk write phần thưởng
        if bulk_updates:
            await self.db.rpg_profiles.bulk_write(bulk_updates)

        # Chờ 5 giây và gọi boss mới (Tier tiếp theo) ngầm
        await asyncio.sleep(1)
        await self.spawn_boss(tier=tier + 1)
async def setup(bot):
    await bot.add_cog(WorldBossSystem(bot, bot.db))