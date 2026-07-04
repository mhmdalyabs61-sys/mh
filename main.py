import os
import discord
import asyncio
from discord.ext import commands
from flask import Flask
from threading import Thread

# 1. إعداد المتغيرات والأمان
# سيقوم الكود بسحب التوكن من إعدادات الاستضافة (Render/CodeSandbox)
TOKEN = os.environ.get('TOKEN')

if not TOKEN:
    print("❌ خطأ: لم يتم العثور على التوكن في إعدادات النظام!")
    exit()

# 2. إعداد البوت
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

# 3. إعداد الويب الوهمي (Keep-Alive)
app = Flask('')

@app.route('/')
def home():
    return "البوت يعمل بكامل طاقته!"

def run():
    # Render يحدد البورت تلقائياً
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def run_web_server():
    t = Thread(target=run)
    t.start()

# 4. تشغيل البوت والويب
@bot.event
async def on_ready():
    print(f"✅ تم تسجيل الدخول كـ {bot.user}")
    print(f"✅ نظام الويب الوهمي نشط!")

# تشغيل السيرفر قبل البوت
run_web_server()

# تشغيل البوت
bot.run(TOKEN)
