import os
import discord
from discord import app_commands
from discord.ext import commands

intents = discord.Intents.default()
client = commands.Bot(command_prefix="!", intents=intents)

# قراءة التوكن من متغيرات بيئة Railway
TOKEN = os.getenv("TOKEN")

@client.event
async def on_ready():
    print(f"تم تسجيل الدخول بنجاح باسم: {client.user.name}")
    try:
        synced = await client.tree.sync()
        print(f"تمت مزامنة {len(synced)} من الأوامر.")
    except Exception as e:
        print(f"حدث خطأ أثناء المزامنة: {e}")

# كلاس الزر التفاعلي لإرسال الصورة بالخاص
class DownloadView(discord.ui.View):
    def __init__(self, image_url: str):
        super().__init__(timeout=None)
        self.image_url = image_url

    @discord.ui.button(emoji="<:support:1567912267520147518>", style=discord.ButtonStyle.secondary)
    async def download_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # محاولة إرسال الصورة في رسالة خاصة (DM) للمستخدم
            user = interaction.user
            await user.send(f"إليك الصورة التي طلبتها:\n{self.image_url}")
            
            # الرد على الضغطة بشكل مخفي ومؤكد للمستخدم
            await interaction.response.send_message("✅ تم إرسال الصورة إلى رسائلك الخاصة (الخاص)!", ephemeral=True)
        except discord.Forbidden:
            # إذا كان خاص المستخدم مقفل
            await interaction.response.send_message("❌ عذراً، لم أتمكن من إرسال الصورة لأن خاصك (DMs) مغلق!", ephemeral=True)

@client.tree.command(name="download", description="إرسال صورة مع زر لإرسالها بالخاص")
@app_commands.describe(image_url="ضع رابط الصورة هنا")
async def download_command(interaction: discord.Interaction, image_url: str):
    # إرسال الصورة الأساسية مع الزر في السيرفر
    view = DownloadView(image_url)
    await interaction.response.send_message(content=image_url, view=view)

client.run(TOKEN)
