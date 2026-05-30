import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import aiohttp
from Database import rpg_profiles_col, world_boss_col, boss_channels_col
# Tạm thời giả định bạn đã import các collection này từ Database.py
# from Database import rpg_profiles_col, world_boss_col, boss_channels_col

class RPGSystemCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="rpg_profile", description="Xem hoặc tạo hồ sơ sức mạnh của bạn")
    async def rpg_profile(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_id = interaction.user.id
        
        # 1. Tìm trong DB xem người này có profile chưa
        profile = await rpg_profiles_col.find_one({"user_id": user_id})
        
        # 2. Nếu chưa có, tự động tạo mới (Chỉ số tân thủ)
        if not profile:
            profile = {
                "user_id": user_id,
                "ign": interaction.user.display_name,
                "gold": 0,
                "stats": { "hp": 1000, "atk": 50, "def": 20, "crit_rate": 5.0 },
                "inventory": []
            }
            await rpg_profiles_col.insert_one(profile)
            msg_content = "🎉 **Congratz, your profile is ready."
        else:
            msg_content = "📊 Your charactor infomation:"

        stats = profile.get("stats", {})
        
        # 3. Render giao diện
        embed = discord.Embed(title=f"Index framework - {profile.get('ign')}", color=discord.Color.dark_red())
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="❤️ HP", value=f"{stats.get('hp')}/{stats.get('hp')}", inline=True)
        embed.add_field(name="⚔️ ATK", value=str(stats.get('atk')), inline=True)
        embed.add_field(name="🛡️ DEF", value=str(stats.get('def')), inline=True)
        embed.add_field(name="💰 Gold", value=f"{profile.get('gold')} Tera", inline=False)
        
        await interaction.followup.send(content=msg_content, embed=embed)
         #phần 2 settup
    @app_commands.command(name="setup_boss_channel", description="Thiết lập kênh làm chiến trường đánh World Boss và Chat liên server")
    @app_commands.describe(channel="Chọn kênh văn bản")
    async def setup_boss_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        
        # Chỉ Admin hoặc Bot Owner mới được setup
        is_owner = await self.bot.is_owner(interaction.user)
        if not (interaction.user.guild_permissions.administrator or is_owner):
            return await interaction.followup.send("❌ Bạn cần quyền Administrator!", ephemeral=True)

        try:
            # 1. Tìm xem kênh này đã có webhook do bot tạo chưa
            existing_webhooks = await channel.webhooks()
            webhook = next((w for w in existing_webhooks if w.user == self.bot.user), None)
            
            # 2. Nếu chưa có, tiến hành tạo mới
            if not webhook:
                webhook = await channel.create_webhook(name="DMW Cross-Server Relay")
                
            # 3. Lưu thông tin vào Database (Giả định boss_channels_col đã có)
            # await boss_channels_col.update_one(
            #     {"guild_id": interaction.guild_id},
            #     {
            #         "$set": {
            #             "channel_id": channel.id,
            #             "webhook_url": webhook.url
            #         }
            #     },
            #     upsert=True
            # )
            
            await interaction.followup.send(f"✅ Đã thiết lập chiến trường thành công tại {channel.mention}. Webhook đã được tạo sẵn sàng cho Chat liên server!", ephemeral=True)
            
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot không có quyền 'Manage Webhooks' (Quản lý Webhook) ở kênh này. Hãy cấp quyền và thử lại!", ephemeral=True)
        except Exception as e:
            print(f"Lỗi setup boss channel: {e}")
            await interaction.followup.send("❌ Có lỗi xảy ra trong quá trình thiết lập.", ephemeral=True)

            # --- PHẦN 3: LẮNG NGHE CHAT & BẮN WEBHOOK CROSS-SERVER ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 1. Chặn bot tự lấy tin nhắn của chính nó (tránh lặp vô hạn)
        if message.author.bot or not message.guild:
            return

        # 2. Kiểm tra xem kênh người dùng chat có nằm trong DB boss_channels không
        current_channel_config = await boss_channels_col.find_one({"channel_id": message.channel.id})
        if not current_channel_config:
            return 

        # 3. Lấy TẤT CẢ các kênh sự kiện khác (ngoại trừ kênh vừa chat)
        other_channels = await boss_channels_col.find({"channel_id": {"$ne": message.channel.id}}).to_list(length=None)
        if not other_channels:
            return 

        # 4. Gom tác vụ bắn Webhook lại để chạy đồng thời (Concurrency)
        tasks = []
        for config in other_channels:
            webhook_url = config.get("webhook_url")
            if webhook_url:
                # Ép tên server (tối đa 10 ký tự) + Tên người gửi để mọi người biết ai ở đâu
                sender_name = f"[{message.guild.name[:10]}] {message.author.display_name}"
                
                tasks.append(self.send_webhook_message(
                    webhook_url=webhook_url,
                    content=message.content,
                    username=sender_name,
                    avatar_url=message.author.display_avatar.url,
                    attachments=message.attachments
                ))
        
        # Thực thi tất cả các tác vụ bắn Webhook cùng lúc
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def send_webhook_message(self, webhook_url, content, username, avatar_url, attachments):
        """Hàm phụ trợ để bắn webhook sử dụng aiohttp"""
        try:
            async with aiohttp.ClientSession() as session:
                webhook = discord.Webhook.from_url(webhook_url, session=session)
                
                # Xử lý nếu người chơi gửi cả hình ảnh/ảnh chụp màn hình
                files_content = ""
                if attachments:
                    files_content = "\n" + "\n".join([att.url for att in attachments])
                
                final_content = content + files_content
                
                # Tránh lỗi gửi tin nhắn rỗng (ví dụ gửi sticker bot không đọc được)
                if final_content.strip() == "":
                    return 

                await webhook.send(
                    content=final_content,
                    username=username,
                    avatar_url=avatar_url
                )
        except Exception as e:
            print(f"Lỗi gửi relay webhook: {e}")

async def setup(bot):
    await bot.add_cog(RPGSystemCog(bot))

    @app_commands.command(name="rpg_profile", description="Xem chỉ số sức mạnh của bạn")
    async def rpg_profile(self, interaction: discord.Interaction):
        # Nơi này sau này sẽ query từ rpg_profiles_col
        # Hiện tại trả về dữ liệu mẫu để test UI
        
        embed = discord.Embed(title=f"Khung Nhìn Chỉ Số - {interaction.user.display_name}", color=discord.Color.dark_red())
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="❤️ HP", value="1000/1000", inline=True)
        embed.add_field(name="⚔️ ATK", value="50", inline=True)
        embed.add_field(name="🛡️ DEF", value="20", inline=True)
        embed.add_field(name="💰 Gold", value="0 Tera", inline=False)
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(RPGSystemCog(bot))
    