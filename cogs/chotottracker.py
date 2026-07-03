import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
import asyncio
from datetime import datetime

# --- KHU VỰC ĐỊNH NGHĨA CÁC ĐỐI THOẠI NHẬP LIỆU (MODALS) ---

class PriceModal(discord.ui.Modal, title="💰 Cấu hình Bộ Lọc Giá Tiền"):
    min_p = discord.ui.TextInput(label="Giá tối thiểu (Tỷ VNĐ) - Nhập số (VD: 1.5)", placeholder="Nhập 0 nếu không giới hạn...", required=True)
    max_p = discord.ui.TextInput(label="Giá tối đa (Tỷ VNĐ) - Nhập số (VD: 5.2)", placeholder="Nhập số Tỷ mong muốn...", required=True)

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.min_p.default = str(view.config.get("min_price", 0) / 1_000_000_000)
        self.max_p.default = str(view.config.get("max_price", 100_000_000_000) / 1_000_000_000)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            min_val = int(float(self.min_p.value) * 1_000_000_000)
            max_val = int(float(self.max_p.value) * 1_000_000_000)
            if min_val < 0 or max_val <= 0 or min_val > max_val:
                raise ValueError
            
            await self.view.cog.config_col.update_one(
                {"_id": "user_filter_config"}, 
                {"$set": {"min_price": min_val, "max_price": max_val}}
            )
            await self.view.refresh_dashboard(interaction)
        except ValueError:
            await interaction.response.send_message("❌ Định dạng số không hợp lệ hoặc khoảng giá sai. Vui lòng thử lại!", ephemeral=True)


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
        # Tách chuỗi thành mảng, loại bỏ khoảng trắng và chuyển về chữ thường để khớp chính xác
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
        # Cập nhật màu sắc trạng thái Bật/Tắt trên Button
        is_active = self.config.get("is_active", True)
        self.btn_toggle.label = "Trạng thái: BẬT 🟢" if is_active else "Trạng thái: TẮT 🔴"
        self.btn_toggle.style = discord.ButtonStyle.success if is_active else discord.ButtonStyle.danger

    async def refresh_dashboard(self, interaction: discord.Interaction):
        # Đọc lại data mới từ MongoDB và vẽ lại giao diện điều khiển
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
            "Ví dụ: hẻm xe hơi, sổ hồng riêng, mặt tiền..."
        ))

    @discord.ui.button(label="🚫 Từ Khóa Loại Trừ", style=discord.ButtonStyle.secondary, custom_id="ct_btn_ex", row=2)
    async def btn_exclude(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TextFilterModal(
            self, "exclude_keywords", "🚫 Từ Khóa Cấm / Loại Trừ", 
            "Ví dụ: chung cư, căn hộ, cho thuê, cần mua... (Giúp lọc tin rác)"
        ))

    @discord.ui.button(label="🧹 Xóa Bộ Nhớ Đệm Tin Cũ", style=discord.ButtonStyle.danger, custom_id="ct_btn_clear", row=2)
    async def btn_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.seen_ads_col.delete_many({})
        await interaction.response.send_message("🧹 Đã làm sạch toàn bộ danh sách bài đăng cũ lưu trong bộ nhớ đệm!", ephemeral=True)


# --- CLASS HOẠT ĐỘNG CHÍNH CỦA COG COG ---

class ChototTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Đồng bộ chính xác với ID của bạn từ Main.py
        self.owner_id = 1283689737567211581 
        
        self.config_col = self.bot.db["chotot_config"]
        self.seen_ads_col = self.bot.db["chotot_seen_ads"]
        
        self.is_first_run = True
        self.scan_market.start()

    def cog_unload(self):
        self.scan_market.cancel()

    # Chặn quyền thực thi ở cấp độ tương tác (Slash command và Giao diện UI)
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Bạn không có quyền quản lý hệ thống quét Chợ Tốt này.", ephemeral=True)
            return False
        return True

    def format_price(self, price_vnd):
        if price_vnd >= 1_000_000_000:
            return f"{price_vnd / 1_000_000_000:.2f} Tỷ"
        elif price_vnd >= 1_000_000:
            return f"{price_vnd / 1_000_000:.0f} Triệu"
        return f"{price_vnd:,} VNĐ"

    def create_status_embed(self, guild, config):
        """Hàm dựng giao diện hiển thị thông tin cấu hình hiện tại"""
        status_text = "ĐANG CHẠY QUÉT 🟢" if config.get("is_active", True) else "ĐANG TẠM DỪNG TẮT 🔴"
        channel_id = config.get("channel_id")
        channel_mention = f"<#{channel_id}>" if channel_id else "`Chưa cấu hình`"
        
        min_p_str = self.format_price(config.get("min_price", 0))
        max_p_str = self.format_price(config.get("max_price", 100_000_000_000))
        
        areas = config.get("areas", [])
        keywords = config.get("keywords", [])
        excludes = config.get("exclude_keywords", [])

        embed = discord.Embed(
            title="🎯 BẢNG ĐIỀU KHIỂN: CHỢ TỐT REAL-ESTATE TRACKER",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="⚙️ Trạng thái hệ thống", value=f"**{status_text}**", inline=True)
        embed.add_field(name="📍 Kênh thông báo hiện tại", value=channel_mention, inline=True)
        embed.add_field(name="💰 Khoảng giá lọc", value=f"`{min_p_str}` đến `{max_p_str}`", inline=False)
        embed.add_field(name="🗺️ Khu vực theo dõi tuyển chọn", value=f"`{', '.join(areas)}`" if areas else "_Theo dõi toàn quốc (Chưa lọc)_", inline=False)
        embed.add_field(name="🔑 Từ khóa tìm kiếm bắt buộc", value=f"`{', '.join(keywords)}`" if keywords else "_Bất kỳ bài đăng nào (Chưa lọc)_", inline=False)
        embed.add_field(name="🚫 Từ khóa loại trừ (Bộ lọc nhà rác)", value=f"`{', '.join(excludes)}`" if excludes else "_Không cấu hình_", inline=False)
        embed.set_footer(text="Bấm vào các nút bên dưới để tiến hành Thêm/Xóa/Sửa bộ lọc mong muốn.")
        return embed

    @app_commands.command(name="chotot", description="Mở Menu điều khiển thông minh hệ thống quét và thông báo Nhà Đất Chợ Tốt")
    async def chotot_command(self, interaction: discord.Interaction):
        """Hàm thực thi duy nhất của Slash Command"""
        # Đọc cấu hình hoặc khởi tạo giá trị mặc định nếu là lần đầu tiên sử dụng
        config = await self.config_col.find_one({"_id": "user_filter_config"})
        if not config:
            config = {
                "_id": "user_filter_config",
                "channel_id": interaction.channel_id,
                "is_active": True,
                "min_price": 0,
                "max_price": 10_000_000_000, # 10 Tỷ mặc định
                "areas": [],
                "keywords": [],
                "exclude_keywords": ["chung cư", "căn hộ", "cho thuê"] # Bộ lọc nhà đất cơ bản thích hợp
            }
            await self.config_col.insert_one(config)
        else:
            # Tự động cập nhật kênh nhận tin về kênh vừa gõ lệnh slash command mới nhất
            await self.config_col.update_one({"_id": "user_filter_config"}, {"$set": {"channel_id": interaction.channel_id}})
            config["channel_id"] = interaction.channel_id

        embed = self.create_status_embed(interaction.guild, config)
        view = ChototDashboardView(self, config)
        await interaction.response.send_message(embed=embed, view=view)

    # --- HỆ THỐNG VÒNG LẶP QUÉT TỰ ĐỘNG CHẠY NGẦM ---
    @tasks.loop(minutes=5)
    async def scan_market(self):
        config = await self.config_col.find_one({"_id": "user_filter_config"})
        if not config or not config.get("is_active", True):
            return

        channel = self.bot.get_channel(config["channel_id"])
        if not channel:
            return

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
                    
                    # Tải trước bộ lọc dạng list
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
                        
                        # 1. Bộ lọc Giá Tiền sâu
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

                        # 2. Bộ lọc Từ Khóa Loại Trừ (NẾU dính từ khóa cấm -> LOẠI BỎ NGAY)
                        has_exclude = False
                        for ex in filter_excludes:
                            if ex in subject or ex in body:
                                has_exclude = True
                                break
                        if has_exclude:
                            await self.seen_ads_col.insert_one({"_id": ad_id, "at": datetime.utcnow()})
                            continue

                        # 3. Bộ lọc Đa Khu Vực (Nếu có cấu hình thì vị trí tin đăng phải khớp ít nhất 1 khu vực)
                        if filter_areas:
                            match_area = False
                            for area in filter_areas:
                                if area in full_location_text:
                                    match_area = True
                                    break
                            if not match_area:
                                await self.seen_ads_col.insert_one({"_id": ad_id, "at": datetime.utcnow()})
                                continue

                        # 4. Bộ lọc Từ khóa bắt buộc tìm kiếm
                        if filter_keywords:
                            match_kw = False
                            for kw in filter_keywords:
                                if kw in subject or kw in body:
                                    match_kw = True
                                    break
                            if not match_kw:
                                await self.seen_ads_col.insert_one({"_id": ad_id, "at": datetime.utcnow()})
                                continue

                        # Nếu vượt qua tất cả các chốt chặn lọc
                        new_ads_found.append(ad)

                    # Chống spam tin cũ khi bot vừa khởi chạy
                    if self.is_first_run:
                        for ad in new_ads_found:
                            await self.seen_ads_col.insert_one({"_id": ad.get("list_id"), "at": datetime.utcnow()})
                        self.is_first_run = False
                        print("[Chotot Tracker] Khởi tạo thành công hệ thống dữ liệu Slash Command.")
                        return

                    # Đẩy tin nhắn báo Embed về Discord
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
                        embed.add_field(name="💰 Giá bán", value=f"**{self.format_price(price_val)}**", inline=True)
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