import discord
from discord import app_commands
from discord.ext import commands

# إعداد الصلاحيات الأساسية للبوت
intents = discord.Intents.default()
client = commands.Bot(command_prefix="!", intents=intents)

# ضع توكن البوت هنا مباشرة داخل المتغير
TOKEN = "YOUR_BOT_TOKEN_HERE"

@client.event
async def on_ready():
    print(f"تم تسجيل الدخول بنجاح باسم: {client.user.name}")
    try:
        # مزامنة أمر السلاش تلقائياً
        synced = await client.tree.sync()
        print(f"تمت مزامنة {len(synced)} من الأوامر.")
    except Exception as e:
        print(f"حدث خطأ أثناء المزامنة: {e}")

# تعريف أمر السلاش (/download)
@client.tree.command(name="download", description="إرسال صورة مع زر تحميل مباشر")
@app_commands.describe(image_url="ضع رابط الصورة هنا")
async def download_command(interaction: discord.Interaction, image_url: str):
    
    # إنشاء الـ Embed الخاص بعرض الصورة
    embed = discord.Embed(color=discord.Color.blurple())
    embed.set_image(url=image_url)
    
    # إنشاء زر التحميل (Link Button) يوجه المستخدم للرابط مباشرة
    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="تحميل", 
        style=discord.ButtonStyle.link, 
        url=image_url, 
        emoji="📥"
    ))
    
    # إرسال الرسالة للمستخدم في الشات
    await interaction.response.send_message(embed=embed, view=view)

# تشغيل البوت باستخدام متغير التوكن
client.run(TOKEN)
