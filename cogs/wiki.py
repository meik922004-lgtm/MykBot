import discord
from discord.ext import commands
import aiohttp

class WikiCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Đường dẫn API của DMW Wiki
        self.wiki_api_url = "https://digitalmastersworld.wiki.gg/api.php"

    @commands.command(name="wiki")
    async def wiki_search(self, ctx, *, query: str):
        # Thiết lập các tham số truy vấn gửi lên MediaWiki API
        # Thiết lập các tham số truy vấn gửi lên MediaWiki API
        params = {
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "exintro": "true",      # Sửa từ True thành "true"
            "explaintext": "true",  # Sửa từ True thành "true"
            "titles": query,
            "redirects": 1          # Cái này là số nguyên (int) nên giữ nguyên, không sao cả
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(self.wiki_api_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    pages = data.get("query", {}).get("pages", {})
                    
                    # Lấy ID của trang đầu tiên tìm được
                    page_id = next(iter(pages))
                    page_data = pages[page_id]
                    
                    if page_id != "-1":
                        title = page_data.get("title")
                        extract = page_data.get("extract", "Không có tóm tắt cho trang này.")
                        # Tạo link chuẩn đến bài viết (thay khoảng trắng bằng dấu gạch dưới)
                        page_url = f"https://digitalmastersworld.wiki.gg/wiki/{title.replace(' ', '_')}"
                        
                        # Tạo khung hiển thị (Embed) trên Discord
                        embed = discord.Embed(title=title, description=extract[:1000], color=discord.Color.blue())
                        embed.add_field(name="Xem chi tiết tại:", value=page_url)
                        await ctx.send(embed=embed)
                    else:
                        await ctx.send(f"❌ Không tìm thấy thông tin cho '{query}' trên DMW Wiki.")
                else:
                    await ctx.send("❌ Không thể kết nối tới máy chủ Wiki lúc này.")

# Hàm setup để Discord.py nhận diện và nạp Cog này vào bot chính
async def setup(bot):
    await bot.add_cog(WikiCog(bot))