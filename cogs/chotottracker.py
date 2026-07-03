import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
import asyncio
from datetime import datetime

# --- HÀM HỖ TRỢ PHÂN TÍCH CHUỖI GIÁ CẢ THÔNG MINH ---
def parse_price_string(text: str) -> int:
    """
    Chuyển đổi các chuỗi nhập tay như '8.5tr', '8tr5', '3.5 tỷ', '500k' thành số int VNĐ chuẩn.
    Nếu chỉ nhập số thuần < 100, hệ thống tự hiểu là Tỷ VNĐ (để tương thích phân khúc mua bán).
    """
    text = text.strip().lower().replace(" ", "").replace(",", ".")
    if not text or text == "0":
        return 0
    
    # Kiểm tra các định dạng viết tắt kết hợp (VD: 8tr5, 1ty5, 2tỷ3)
    suffixes = [
        ("tỷ", 1_000_000_000), ("ty", 1_000_000_000), 
        ("triệu", 1_000_000), ("trieu", 1_000_000), ("tr", 1_000_000)
    ]
    
    for suffix, multiplier in suffixes:
        if suffix in text:
            parts = text.split(suffix)
            main_val = float(parts[0]) if parts[0] else 0.0
            # Nếu có phần đuôi đứng sau (VD: 8tr5 -> main=8, sub=5 -> 8.5 triệu)
            if len(parts) > 1 and parts[1]:
                sub_str = parts[1]
                sub_val = float(sub_str) / (10 ** len(sub_str))
                return int((main_val + sub_val) * multiplier)
            return int(main_val * multiplier)
            
    # Nếu là số thuần túy không kèm chữ
    try:
        val = float(text)
        if val < 100:  # Nếu nhập số nhỏ dưới 100 không đơn vị -> Quy ước là Tỷ
            return int(val * 1_000_000_000)
        return int(val)
    except ValueError:
        return 0


# --- KHU VỰC ĐỊNH NGHĨA CÁC ĐỐI THOẠI NHẬP LIỆU (MODALS) ---

class PriceModal(discord.ui.Modal, title="💰 Cấu hình Bộ Lọc Giá Tiền"):
    min_p = discord.ui.TextInput(
        label="Giá tối thiểu (VD: 0, 1.5tr, 2tr5, 1 tỷ)", 
        placeholder="Nhập 0 nếu không giới hạn mức sàn...", 
        required=True
    )
    max_p = discord.ui.TextInput(
        label="Giá tối đa (VD: 8.5tr, 8tr5, 12tr, 3 tỷ)", 
        placeholder="Nhập khoảng giá trần mong muốn...", 
        required=True
    )

    def __init__(self, view):
        super().__init__()
        self.view = view
        # Hiển thị cấu hình hiện tại lên form nhập liệu
        self.min_p.default = view.cog.format_price(view.config.get("min_price", 0))
        self.max_p.default = view.cog.format_price(view.config.get("max_price", 10_000_000_000))

    async def on_submit(self, interaction: discord.Interaction):
        min_val = parse_price_string(self.min_p.value)
        max_val = parse_price_string(self.max_p.value)
        
        if max_val <= 0 or min_val > max_val:
            return await interaction.response.send_message(
                "❌ Khoảng giá nhập vào không hợp lệ (Giá tối đa phải lớn hơn giá tối thiểu). Vui lòng thử lại!", 
                ephemeral=True
            )
        
        await self.view.cog.config_col.update_one(
            {"_id": "user_filter_config"}, 
            {"$set": {"min_price": min_val, "max_price": max_val}}
        )
        await self.view.refresh_dashboard(interaction)


class TextFilterModal(discord.ui.Modal):
    inputs = discord.ui.TextInput(
        label="Danh sách (Cách nhau bởi dấu phẩy ',')", 
        style=discord.TextStyle.paragraph,
        required=False
    )

    def __init__(self, view, field_name: str, title: str, placeholder: str):
        super().__init__(title=title)
        self.view = view
        self.field_name = field_name
        self.inputs.placeholder = placeholder
        current_list = view.config.get(field_name, [])
        self.inputs.default = ", ".join(current_list)

    async def on_submit(self, interaction: discord.Interaction):
        new_list = [item.strip().lower() for item in self.inputs.value.split(",") if item.strip()]
        await self.view.cog.config_col.update_one(
            {"_id": "user_filter_config"}, 
            {"$set": {self.field_name: new_list}}
        )
        await self.view.refresh_dashboard(interaction)


# --- KHU VỰC GIAO DIỆN ĐIỀU KHIỂN CHÍNH (DASHBOARD VIEW) ---

class ChototDashboardView(discord.ui.View):
    def __init__(self, cog, config):
        super().__init__(timeout=None)
        self.cog = cog
        self.config = config
        self.update_buttons_label()

    def update_buttons_label(self):
        is_active = self.config.get("is_active", True)
        self.btn_toggle.label = "Trạng thái: BẬT 🟢" if is_active else "Trạng thái: TẮT 🔴"
        self.btn_toggle.style = discord.ButtonStyle.success if is_active else discord.ButtonStyle.danger

    async def refresh_dashboard(self, interaction: discord.Interaction):
        self.config = await self.cog.config_col.find_one({"_id": "user_filter_config"})
        self.update_buttons_label()
        embed = self.cog.create_status_embed(interaction.guild, self.config)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Trạng thái", custom_id="ct_btn_toggle", row=0)
    async def btn_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_status = self.config.get("is_active", True)
        await self.cog.config_col.update_one(
            {"_id": "user_filter_config"}, 
            {"$set": {"is_active": not current_status, "channel_id": interaction.channel_id}}
        )
        await self.refresh_dashboard(interaction)

    @discord.ui.button(label="💰 Sửa Khoảng Giá", style=discord.ButtonStyle.primary, custom_id="ct_btn_price", row=0)
    async def btn_price(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PriceModal(self))

    @discord.ui.button(label="📍 Sửa Khu Vực", style=discord.ButtonStyle.primary, custom_id="ct_btn_areas", row=1)
    async def btn_areas(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TextFilterModal(
            self, "areas", "📍 Quản lý Khu Vực Theo Dõi", 
            "Ví dụ: gò vấp, quận 12, bình thạnh..."
        ))

    @discord.ui.button(label="🔑 Sửa Từ Khóa Tìm", style=discord.ButtonStyle.primary, custom_id="ct_btn_kw", row=1)
    async def btn_keywords(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TextFilterModal(
            self, "keywords", "🔑 Quản lý Từ Khóa Bắt Buộc", 
            "Ví dụ: hẻm xe hơi, phòng trọ, full nội thất..."
        ))

    @discord.ui.button(label="🚫 Từ Khóa Loại Trừ", style=discord.ButtonStyle.secondary, custom_id="ct_btn_ex", row=2)
    async def btn_exclude(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TextFilterModal(
            self, "exclude_keywords", "🚫 Từ Khóa Cấm / Loại Trừ", 
            "Ví dụ: cần mua, cần thuê, pass đồ... (Giúp tránh tin rác người tìm phòng)"
        ))

    @discord.ui.button(label="🧹 Xóa Bộ Nhớ Đệm Tin Cũ", style=discord.ButtonStyle.danger, custom_id="ct_btn_clear", row=2)
    async def btn_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.seen_ads_col.delete_many({})
        await interaction.response.send_message("🧹 Đã làm sạch toàn bộ danh sách bài đăng cũ lưu trong bộ nhớ đệm!", ephemeral=True)


# --- CLASS HOẠT ĐỘNG CHÍNH CỦA COG ---

class ChototTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.owner_id = 1283689737567211581 
        
        self.config_col = self.bot.db["chotot_config"]
        self.seen_ads_col = self.bot.db["chotot_seen_ads"]
        
        self.is_first_run = True
        self.scan_market.start()

    def cog_unload(self):
        self.scan_market.cancel()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Bạn không có quyền quản lý hệ thống quét Chợ Tốt này.", ephemeral=True)
            return False
        return True

    def format_price(self, price_vnd):
        if price_vnd >= 1_000_000_000:
            return f"{price_vnd / 1_000_000_000:.2f} Tỷ"
        elif price_vnd >= 1_000_000:
            return f"{price_vnd / 1_000_000:.1f} Triệu"
        return f"{price_vnd:,} VNĐ"

    def create_status_embed(self, guild, config):
        status_text = "ĐANG CHẠY QUÉT 🟢" if config.get("is_active", True) else "ĐANG TẠM DỪNG TẮT 🔴"
        channel_id = config.get("channel_id")
        channel_mention = f"<#{channel_id}>" if channel_id else "`Chưa cấu hình`"
        
        min_p_str = self.format_price(config.get("min_price", 0))
        max_p_str = self.format_price(config.get("max_price", 100_000_000_000))
        
        areas = config.get("areas", [])
        keywords = config.get("keywords", [])
        excludes = config.get("exclude_keywords", [])

        embed = discord.Embed(
            title="🎯 BẢNG ĐIỀU KHIỂN: CHỢ TỐT SMART TRACKER",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="⚙️ Trạng thái hệ thống", value=f"**{status_text}**", inline=True)
        embed.add_field(name="📍 Kênh thông báo hiện tại", value=channel_mention, inline=True)
        embed.add_field(name="💰 Khoảng giá lọc", value=f"`{min_p_str}` đến `{max_p_str}`", inline=False)
        embed.add_field(name="🗺️ Khu vực theo dõi", value=f"`{', '.join(areas)}`" if areas else "_Toàn quốc (Chưa lọc)_", inline=False)
        embed.add_field(name="🔑 Từ khóa bắt buộc", value=f"`{', '.join(keywords)}`" if keywords else "_Bất kỳ bài viết nào_", inline=False)
        embed.add_field(name="🚫 Từ khóa loại trừ", value=f"`{', '.join(excludes)}`" if excludes else "_Không cấu hình_", inline=False)
        embed.set_footer(text="Bấm vào các nút bên dưới để tùy chỉnh bộ lọc theo nhu cầu.")
        return embed

    @app_commands.command(name="chotot", description="Mở Menu điều khiển thông minh hệ thống quét Nhà Đất / Phòng Trọ Chợ Tốt")
    async def chotot_command(self, interaction: discord.Interaction):
        config = await self.config_col.find_one({"_id": "user_filter_config"})
        if not config:
            config = {
                "_id": "user_filter_config",
                "channel_id": interaction.channel_id,
                "is_active": True,
                "min_price": 0,
                "max_price": 8_500_000, # Đặt mặc định 8.5 Triệu theo cấu hình yêu cầu mới của bạn
                "areas": [],
                "keywords": [],
                "exclude_keywords": ["cần mua", "cần thuê"] # Bộ lọc rác tối ưu cho người đi tìm thuê phòng
            }
            await self.config_col.insert_one(config)
        else:
            await self.config_col.update_one({"_id": "user_filter_config"}, {"$set": {"channel_id": interaction.channel_id}})
            config["channel_id"] = interaction.channel_id

        embed = self.create_status_embed(interaction.guild, config)
        view = ChototDashboardView(self, config)
        await interaction.response.send_message(embed=embed, view=view)

    @tasks.loop(minutes=5)
    async def scan_market(self):
        config = await self.config_col.find_one({"_id": "user_filter_config"})
        if not config or not config.get("is_active", True):
            return

        channel = self.bot.get_channel(config["channel_id"])
        if not channel:
            return

        # Danh mục cg=1000 (Bất động sản chung). Bạn có thể đổi sang cg=1020 nếu chỉ muốn quét chuyên phòng trọ.
        url = "https://gateway.chotot.com/v1/public/ad-listing?cg=1000&limit=50"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, timeout=15) as response:
                    if response.status != 200:
                        return
                    
                    data = await response.json()
                    ads = data.get("ads", [])
                    new_ads_found = []
                    
                    filter_areas = config.get("areas", [])
                    filter_keywords = config.get("keywords", [])
                    filter_excludes = config.get("exclude_keywords", [])
                    min_price = config.get("min_price", 0)
                    max_price = config.get("max_price", 100_000_000_000)

                    for ad in ads:
                        ad_id = ad.get("list_id")
                        if not ad_id:
                            continue
                        
                        seen = await self.seen_ads_col.find_one({"_id": ad_id})
                        if seen:
                            continue
                        
                        # 1. Kiểm tra Khoảng Giá
                        price = int(ad.get("price", 0))
                        if price == 0 or not (min_price <= price <= max_price):
                            await self.seen_ads_col.insert_one({"_id": ad_id, "at": datetime.utcnow()})
                            continue
                        
                        subject = ad.get("subject", "").lower()
                        body = ad.get("body", "").lower()
                        area_name = ad.get("area_name", "").lower()
                        ward_name = ad.get("ward_name", "").lower()
                        region_name = ad.get("region_name", "").lower()
                        full_location_text = f"{ward_name} {area_name} {region_name}"

                        # 2. Kiểm tra Từ Khóa Loại Trừ
                        has_exclude = False
                        for ex in filter_excludes:
                            if ex in subject or ex in body:
                                has_exclude = True
                                break
                        if has_exclude:
                            await self.seen_ads_col.insert_one({"_id": ad_id, "at": datetime.utcnow()})
                            continue

                        # 3. Kiểm tra Đa Khu Vực (Gò Vấp, Quận 12...)
                        if filter_areas:
                            match_area = False
                            for area in filter_areas:
                                if area in full_location_text:
                                    match_area = True
                                    break
                            if not match_area:
                                await self.seen_ads_col.insert_one({"_id": ad_id, "at": datetime.utcnow()})
                                continue

                        # 4. Kiểm tra Từ khóa bắt buộc
                        if filter_keywords:
                            match_kw = False
                            for kw in filter_keywords:
                                if kw in subject or kw in body:
                                    match_kw = True
                                    break
                            if not match_kw:
                                await self.seen_ads_col.insert_one({"_id": ad_id, "at": datetime.utcnow()})
                                continue

                        new_ads_found.append(ad)

                    if self.is_first_run:
                        for ad in new_ads_found:
                            await self.seen_ads_col.insert_one({"_id": ad.get("list_id"), "at": datetime.utcnow()})
                        self.is_first_run = False
                        print("[Chotot Tracker] Khởi tạo đồng bộ thành công dữ liệu giá thông minh.")
                        return

                    for ad in new_ads_found:
                        ad_id = ad.get("list_id")
                        title = ad.get("subject", "Không có tiêu đề")
                        price_val = int(ad.get("price", 0))
                        loc_display = f"{ad.get('ward_name', '')}, {ad.get('area_name', '')}, {ad.get('region_name', '')}".strip(", ")
                        
                        description = ad.get("body", "Không có mô tả chi tiết.")
                        if len(description) > 350:
                            description = description[:350] + "..."
                            
                        ad_url = f"https://www.nhatot.com/vi/{ad_id}.htm"
                        image_hash = ad.get("image")
                        image_url = f"https://cdn.chotot.com/{image_hash}" if image_hash else None

                        embed = discord.Embed(
                            title=title,
                            url=ad_url,
                            description=description,
                            color=discord.Color.green(),
                            timestamp=datetime.utcnow()
                        )
                        embed.add_field(name="💰 Giá bán/thuê", value=f"**{self.format_price(price_val)}**", inline=True)
                        embed.add_field(name="📍 Khu vực", value=loc_display or "Không rõ", inline=True)
                        if image_url:
                            embed.set_image(url=image_url)
                        embed.set_footer(text=f"Nhà Tốt Tracker • ID: {ad_id}")

                        await channel.send(embed=embed)
                        await self.seen_ads_col.insert_one({"_id": ad_id, "at": datetime.utcnow()})
                        await asyncio.sleep(1.5)

            except Exception as e:
                print(f"❌ Lỗi quét Chợ Tốt: {e}")

    @scan_market.before_loop
    async def before_scan_market(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(ChototTracker(bot))