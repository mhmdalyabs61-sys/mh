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

@client.tree.command(name="download", description="إرسال صورة مع زر تحميل مخصص")
@app_commands.describe(image_url="ضع رابط الصورة هنا")
async def download_command(interaction: discord.Interaction, image_url: str):
    # إنشاء زر الرابط بالإيموجي المخصص وبدون أي نص
    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.link,
        url=image_url,
        emoji="<:support:1567912267520147518>"
    ))
    
    # إرسال الصورة والزر بالشكل المطلوب تماماً
    await interaction.response.send_message(content=image_url, view=view)

client.run(TOKEN)
