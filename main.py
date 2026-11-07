import os
import io
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageOps, ImageDraw
import aiohttp

intents = discord.Intents.default()
client = commands.Bot(command_prefix="!", intents=intents)
TOKEN = os.getenv("TOKEN")

@client.event
async def on_ready():
    print(f"تم تسجيل الدخول بنجاح باسم: {client.user.name}")
    try:
        synced = await client.tree.sync()
        print(f"تمت مزامنة {len(synced)} من الأوامر.")
    except Exception as e:
        print(f"حدث خطأ أثناء المزامنة: {e}")

# دالة لدمج البنر والبروفايل بالشكل المطلوب تماماً
async def create_banner_profile_image(banner_url: str, avatar_url: str) -> discord.File:
    async with aiohttp.ClientSession() as session:
        async with session.get(banner_url) as resp:
            banner_bytes = await resp.read()
        async with session.get(avatar_url) as resp:
            avatar_bytes = await resp.read()

    banner = Image.open(io.BytesIO(banner_bytes)).convert("RGBA")
    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")

    banner = banner.resize((960, 320), Image.Resampling.LANCZOS)

    avatar_size = 220
    avatar = avatar.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)

    mask = Image.new("L", (avatar_size, avatar_size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
    
    circular_avatar = Image.new("RGBA", (avatar_size, avatar_size), (0, 0, 0, 0))
    circular_avatar.paste(avatar, (0, 0), mask=mask)

    border_width = 8
    bordered_avatar_size = avatar_size + (border_width * 2)
    bordered_avatar = Image.new("RGBA", (bordered_avatar_size, bordered_avatar_size), (0, 0, 0, 0))
    draw_border = ImageDraw.Draw(bordered_avatar)
    draw_border.ellipse((0, 0, bordered_avatar_size, bordered_avatar_size), fill=(40, 42, 48, 255))
    bordered_avatar.paste(circular_avatar, (border_width, border_width), mask=circular_avatar)

    final_width = 1000
    final_height = 420
    final_image = Image.new("RGBA", (final_width, final_height), (20, 21, 24, 255))

    banner_x = (final_width - banner.width) // 2
    banner_y = 40
    final_image.paste(banner, (banner_x, banner_y))

    avatar_x = banner_x - 30
    avatar_y = banner_y + banner.height - (bordered_avatar.height // 2) - 10
    final_image.paste(bordered_avatar, (avatar_x, avatar_y), mask=bordered_avatar)

    buffer = io.BytesIO()
    final_image.convert("RGB").save(buffer, format="JPEG", quality=95)
    buffer.seek(0)

    return discord.File(buffer, filename="profile_preview.jpg")

# كلاس الزر لإرسال الصورتين كملفات حقيقية بالخاص
class DownloadView(discord.ui.View):
    def __init__(self, banner_bytes: bytes, avatar_bytes: bytes):
        super().__init__(timeout=None)
        self.banner_bytes = banner_bytes
        self.avatar_bytes = avatar_bytes

    @discord.ui.button(emoji="<:support:1567912267520147518>", style=discord.ButtonStyle.secondary, custom_id="send_raw_files_btn")
    async def download_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            user = interaction.user
            banner_file = discord.File(io.BytesIO(self.banner_bytes), filename="banner.png")
            avatar_file = discord.File(io.BytesIO(self.avatar_bytes), filename="avatar.png")
            
            # إرسال الصورتين في الخاص مباشرة بدون أي كلام
            await user.send(files=[banner_file, avatar_file])
            await interaction.response.send_message("✅ تم إرسال الصور إلى خاصك كملفات!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ عذراً، خاصك (DMs) مغلق!", ephemeral=True)

@client.tree.command(name="setprofile", description="دمج وإرسال طقم البنر والبروفايل إلى روم محدد")
@app_commands.describe(
    banner_url="رابط صورة البنر",
    avatar_url="رابط صورة البروفايل",
    channel="الروم الذي تريد إرسال النتيجة إليه"
)
async def setprofile_command(interaction: discord.Interaction, banner_url: str, avatar_url: str, channel: discord.TextChannel):
    # الرد بشكل مخفي (Ephemeral) لصاحب الأمر فقط لكي لا يظهر الشغل للعامة في مكان كتابة الأمر
    await interaction.response.defer(thinking=True, ephemeral=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(banner_url) as resp:
                banner_bytes = await resp.read()
            async with session.get(avatar_url) as resp:
                avatar_bytes = await resp.read()

        image_file = await create_banner_profile_image(banner_url, avatar_url)
        view = DownloadView(banner_bytes, avatar_bytes)

        # إرسال الصورة المدمجة مع الزر في الروم الذي حددته أنت
        await channel.send(file=image_file, view=view)

        # تأكيد العملية لك أنت فقط بشكل سرّي
        await interaction.followup.send(f"✅ تم إرسال الصورة بنجاح إلى الروم: {channel.mention}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ حدث خطأ أثناء المعالجة: {e}", ephemeral=True)

if not TOKEN:
    print("خطأ: لم يتم العثور على متغير البيئة TOKEN!")
else:
    client.run(TOKEN)
