import os
import io
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageOps, ImageDraw
import aiohttp

intents = discord.Intents.default()
intents.message_content = True

client = commands.Bot(command_prefix="!", intents=intents)
TOKEN = os.getenv("TOKEN")

# دالة لدمج البنر والبروفايل بنفس الشكل المطبق في صورتك تماماً
async def create_banner_profile_image(banner_url: str, avatar_url: str) -> discord.File:
    async with aiohttp.ClientSession() as session:
        async with session.get(banner_url) as resp:
            banner_bytes = await resp.read()
        async with session.get(avatar_url) as resp:
            avatar_bytes = await resp.read()

    banner = Image.open(io.BytesIO(banner_bytes)).convert("RGBA")
    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")

    # ضبط مقاسات البنر المستطيل في الأعلى
    banner = banner.resize((960, 320), Image.Resampling.LANCZOS)

    # تجهيز البروفايل الدائري المتداخل على اليسار
    avatar_size = 220
    avatar = avatar.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)

    mask = Image.new("L", (avatar_size, avatar_size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
    
    circular_avatar = Image.new("RGBA", (avatar_size, avatar_size), (0, 0, 0, 0))
    circular_avatar.paste(avatar, (0, 0), mask=mask)

    # إضافة الإطار الدائري المحيط بالبروفايل نفس الستايل
    border_width = 8
    bordered_avatar_size = avatar_size + (border_width * 2)
    bordered_avatar = Image.new("RGBA", (bordered_avatar_size, bordered_avatar_size), (0, 0, 0, 0))
    draw_border = ImageDraw.Draw(bordered_avatar)
    draw_border.ellipse((0, 0, bordered_avatar_size, bordered_avatar_size), fill=(40, 42, 48, 255))
    bordered_avatar.paste(circular_avatar, (border_width, border_width), mask=circular_avatar)

    # دمج البنر والبروفايل في لوحة واحدة متناسقة
    final_width = 1000
    final_height = 420
    final_image = Image.new("RGBA", (final_width, final_height), (20, 21, 24, 255))

    banner_x = (final_width - banner.width) // 2
    banner_y = 40
    final_image.paste(banner, (banner_x, banner_y))

    # وضع البروفايل الدائري في المكان المخصص أسفل يسار البنر
    avatar_x = banner_x - 30
    avatar_y = banner_y + banner.height - (bordered_avatar.height // 2) - 10
    final_image.paste(bordered_avatar, (avatar_x, avatar_y), mask=bordered_avatar)

    buffer = io.BytesIO()
    final_image.convert("RGB").save(buffer, format="JPEG", quality=95)
    buffer.seek(0)

    return discord.File(buffer, filename="profile_preview.jpg")

# كلاس الزر التفاعلي
class DownloadView(discord.ui.View):
    def __init__(self, banner_url: str, avatar_url: str):
        super().__init__(timeout=None)
        self.banner_url = banner_url
        self.avatar_url = avatar_url

    @discord.ui.button(emoji="<:support:1567912267520147518>", style=discord.ButtonStyle.secondary, custom_id="send_raw_images_btn")
    async def download_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            user = interaction.user
            # إرسال الصورتين المنفصلتين للخاص بدقة عالية للشكل الطبيعي
            await user.send(
                f"📥 إليك الصور الأصلية لتحميلها:\n\n"
                f"**صورة البنر العريض:**\n{self.banner_url}\n\n"
                f"**صورة البروفايل الدائرية:**\n{self.avatar_url}"
            )
            await interaction.response.send_message("✅ تم إرسال صور البنر والبروفايل إلى خاصك بنجاح!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ عذراً، خاصك (DMs) مغلق، لم أستطع إرسال الصور!", ephemeral=True)

@client.event
async def on_ready():
    print(f"تم تسجيل الدخول بنجاح باسم: {client.user.name}")
    try:
        synced = await client.tree.sync()
        print(f"تمت مزامنة {len(synced)} من الأوامر.")
    except Exception as e:
        print(f"حدث خطأ أثناء المزامنة: {e}")

@client.tree.command(name="setprofile", description="إرسال صورة مدمجة للبنر والبروفايل مع زر التحميل للخاص")
@app_commands.describe(banner_url="رابط صورة البنر", avatar_url="رابط صورة البروفايل")
async def setprofile_command(interaction: discord.Interaction, banner_url: str, avatar_url: str):
    await interaction.response.defer(thinking=True)

    try:
        image_file = await create_banner_profile_image(banner_url, avatar_url)
        view = DownloadView(banner_url, avatar_url)

        # إرسال الصورة مباشرة بدون أي إيمبد أو كلام، ومعها الزر فقط
        await interaction.followup.send(file=image_file, view=view)
    except Exception as e:
        await interaction.followup.send(f"❌ حدث خطأ أثناء معالجة الصور: {e}", ephemeral=True)

if not TOKEN:
    print("خطأ: لم يتم العثور على متغير البيئة TOKEN!")
else:
    client.run(TOKEN)
