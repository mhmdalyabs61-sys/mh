import os
import discord
from discord import app_commands
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True

client = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.getenv("TOKEN")

# كلاس الزر لإرسال الصورتين في الخاص عند الضغط
class BannerProfileView(discord.ui.View):
    def __init__(self, banner_url: str, avatar_url: str):
        super().__init__(timeout=None)
        self.banner_url = banner_url
        self.avatar_url = avatar_url

    @discord.ui.button(emoji="<:support:1567912267520147518>", style=discord.ButtonStyle.secondary, custom_id="send_both_images_btn")
    async def download_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            user = interaction.user
            # إرسال الصورتين منفصلتين للخاص
            await user.send(
                f"📥 **إليك صور البنر والملف الشخصي التي طلبتها:**\n\n"
                f"**1. صورة البنر:**\n{self.banner_url}\n\n"
                f"**2. صورة الملف الشخصي (البروفايل):**\n{self.avatar_url}"
            )
            await interaction.response.send_message("✅ تم إرسال صور البنر والبروفايل إلى رسائلك الخاصة (الخاص)!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ عذراً، لم أتمكن من إرسال الصور لأن خاصك (DMs) مغلق!", ephemeral=True)

@client.event
async def on_ready():
    print(f"تم تسجيل الدخول بنجاح باسم: {client.user.name}")
    try:
        synced = await client.tree.sync()
        print(f"تمت مزامنة {len(synced)} من الأوامر.")
    except Exception as e:
        print(f"حدث خطأ أثناء المزامنة: {e}")

@client.tree.command(name="setprofile", description="إرسال بنر وصورة بروفايل مع زر تحميل للخاص")
@app_commands.describe(banner_url="رابط صورة البنر", avatar_url="رابط صورة البروفايل (الدائرية)")
async def setprofile_command(interaction: discord.Interaction, banner_url: str, avatar_url: str):
    # إرسال البنر والبروفايل في الشات العام مع زر الإيموجي المخصص
    view = BannerProfileView(banner_url, avatar_url)
    
    embed = discord.Embed(title="✨ طقم البنر والبروفايل", color=discord.Color.dark_theme())
    embed.set_image(url=banner_url)
    embed.set_thumbnail(url=avatar_url)
    embed.set_footer(text="اضغط على الزر أدناه لتحميل الصور في الخاص")

    await interaction.response.send_message(embed=embed, view=view)

if not TOKEN:
    print("خطأ: لم يتم العثور على متغير البيئة TOKEN في Railway!")
else:
    client.run(TOKEN)
