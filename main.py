import os
import discord
import asyncio
from discord.ext import commands
from flask import Flask
from threading import Thread
import discord
from discord.ext import commands
from discord import app_commands
import json, os, asyncio
from datetime import timedelta, datetime
from typing import Union, Optional, List, Dict

# ══════════════════════════════════════════════════════════════
#                   ضع التوكن هنا ↓
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════

DATA_FILE = 'bot_data.json'
processing_events = set()

def load_data():
    default = {
        'whitelisted': [], 'log_channels': {}, 'jail_setup': {}, 
        'auto_responses': {}, 'jailed_members': {},
        'protection': {
            'channel_del': True, 'channel_update': True,
            'role_del': True, 'role_create': True,
            'webhook': True, 'bot_add': True
        }
    }
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for k, v in default.items():
                    if k not in data: data[k] = v
                return data
        except: pass
    return default

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

bot_data = load_data()
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

# --- أنظمة الراديو (UI Components) ---

class WaveModal(discord.ui.Modal, title='إنشاء/دخول موجة'):
    wave_id = discord.ui.TextInput(label='رقم الموجة', placeholder='مثال: 71.17', min_length=1, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        wave_name = f"موجة-{self.wave_id.value}"
        guild = interaction.guild
        MAIN_RADIO_ID = 1521294954243162254
        
        if not interaction.user.voice or interaction.user.voice.channel.id != MAIN_RADIO_ID:
            return await interaction.response.send_message("❌ يجب أن تكون داخل روم الراديو الرئيسي للدخول!", ephemeral=True)

        channel = discord.utils.get(guild.voice_channels, name=wave_name)
        if not channel:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=False),
                interaction.user: discord.PermissionOverwrite(connect=True, view_channel=True)
            }
            channel = await guild.create_voice_channel(name=wave_name, overwrites=overwrites, category=interaction.user.voice.channel.category)
            await interaction.response.send_message(f"✅ تم إنشاء موجتك: {channel.mention}", ephemeral=True)
        else:
            await channel.set_permissions(interaction.user, connect=True, view_channel=True)
            await interaction.response.send_message(f"✅ تم توصيلك بموجة {self.wave_id.value}", ephemeral=True)
        await interaction.user.move_to(channel)

class RadioView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="+", style=discord.ButtonStyle.primary, custom_id="radio_btn")
    async def join_wave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WaveModal())

# --- تهيئة البوت (Setup Hook) ---

@bot.event
async def setup_hook():
    bot.add_view(RadioView()) 
    await bot.tree.sync()
    print("✅ تم تفعيل نظام الراديو ومزامنة الأوامر!")

# --- الدوال المساعدة (Helpers) ---

async def check_hierarchy(interaction: discord.Interaction) -> bool:
    if interaction.user.id == interaction.guild.owner_id: return True
    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        await interaction.response.send_message("❌ **عذراً!** يجب أن تملك صلاحية الإدارة لاستخدام هذا الأمر.", ephemeral=True)
        return False
    try:
        if interaction.user.top_role.position > interaction.guild.me.top_role.position: return True
        await interaction.response.send_message("❌ **عذراً!** يجب أن تكون رتبتك أعلى من رتبة البوت.", ephemeral=True)
        return False
    except: return True

async def ensure_log_channel(guild: discord.Guild):
    gid = str(guild.id)
    log_id = bot_data['log_channels'].get(gid)
    if log_id:
        channel = guild.get_channel(int(log_id))
        if channel: return channel
    channel = discord.utils.get(guild.text_channels, name="protection-logs")
    if not channel:
        try:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }
            channel = await guild.create_text_channel("protection-logs", overwrites=overwrites)
        except: return None
    bot_data['log_channels'][gid] = channel.id
    save_data(bot_data)
    return channel

async def send_log(guild: discord.Guild, message: str):
    channel = await ensure_log_channel(guild)
    if channel:
        try: await channel.send(f"`[{datetime.now().strftime('%H:%M:%S')}]` {message}")
        except: pass

async def ban_user(guild, user, reason):
    if user.id == bot.user.id or user.id in bot_data['whitelisted']: return
    try: await user.send(f"🚫 **تم طردك من سيرفر {guild.name}**\n📝 **السبب:** {reason}\nرح دور لك سيرفر ثاني يا هطف.")
    except: pass
    try:
        await guild.ban(user, reason=reason)
        await send_log(guild, f"🔨 **تم تبنيد** {user.mention} | السبب: {reason}")
    except: pass

# --- أحداث الحماية القصوى (Events) ---

@bot.event
async def on_guild_channel_delete(channel):
    if not bot_data['protection'].get('channel_del', True): return
    if channel.id in processing_events: return
    processing_events.add(channel.id)
    guild = channel.guild
    await asyncio.sleep(0.5)
    async for entry in guild.audit_logs(action=discord.AuditLogAction.channel_delete, limit=1):
        if entry.user.id != bot.user.id and entry.user.id not in bot_data['whitelisted']:
            await ban_user(guild, entry.user, f"حذف قناة: {channel.name}")
            try:
                if isinstance(channel, discord.TextChannel):
                    await guild.create_text_channel(name=channel.name, category=channel.category, topic=channel.topic)
                elif isinstance(channel, discord.VoiceChannel):
                    await guild.create_voice_channel(name=channel.name, category=channel.category)
                elif isinstance(channel, discord.CategoryChannel):
                    await guild.create_category(name=channel.name)
            except: pass
            break
    await asyncio.sleep(2)
    processing_events.discard(channel.id)

@bot.event
async def on_guild_channel_update(before, after):
    if not bot_data['protection'].get('channel_update', True): return
    if before.name == after.name: return
    guild = after.guild
    async for entry in guild.audit_logs(action=discord.AuditLogAction.channel_update, limit=1):
        if entry.user.id != bot.user.id and entry.user.id not in bot_data['whitelisted']:
            await after.edit(name=before.name)
            member = guild.get_member(entry.user.id)
            if member: await member.remove_roles(*[r for r in member.roles if r != guild.default_role and not r.managed])
            await send_log(guild, f"🔄 **إرجاع اسم** القناة `{before.name}` وسحب رتب الفاعل.")
            break

@bot.event
async def on_guild_role_delete(role):
    if not bot_data['protection'].get('role_del', True): return
    guild = role.guild
    async for entry in guild.audit_logs(action=discord.AuditLogAction.role_delete, limit=1):
        if entry.user.id != bot.user.id and entry.user.id not in bot_data['whitelisted']:
            await ban_user(guild, entry.user, f"حذف رتبة: {role.name}")
            await guild.create_role(name=role.name, permissions=role.permissions, color=role.color, hoist=role.hoist, mentionable=role.mentionable)
            break

@bot.event
async def on_webhooks_update(channel):
    if not bot_data['protection'].get('webhook', True): return
    guild = channel.guild
    async for entry in guild.audit_logs(action=discord.AuditLogAction.webhook_create, limit=1):
        if entry.user.id != bot.user.id and entry.user.id not in bot_data['whitelisted']:
            await ban_user(guild, entry.user, "إنشاء ويب هوك غير مصرح")
            webhooks = await channel.webhooks()
            for wh in webhooks:
                if wh.id == entry.target.id: await wh.delete()
            break

@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel and before.channel != after.channel:
        if "موجة-" in before.channel.name and len(before.channel.members) == 0:
            try: await before.channel.delete()
            except: pass

# --- أوامر السلاش (Slash Commands) ---

@bot.tree.command(name="setup_radio", description="إرسال رسالة نظام الموجات")
async def setup_radio(interaction: discord.Interaction):
    if not await check_hierarchy(interaction): return
    LOG_CHANNEL_ID = 1521294580933328967
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel: return await interaction.response.send_message("❌ الروم غير موجود.", ephemeral=True)
    await channel.send("📻 **نظام الموجات:**\nاضغط على الزائد (+) لإنشاء أو دخول موجتك الخاصة.", view=RadioView())
    await interaction.response.send_message("✅ تم الإرسال.", ephemeral=True)

@bot.tree.command(name="protection", description="تفعيل أو تعطيل الحماية")
async def protection(interaction: discord.Interaction, feature: str, status: bool):
    if not await check_hierarchy(interaction): return
    bot_data['protection'][feature] = status
    save_data(bot_data)
    await interaction.response.send_message(f"✅ تم التحديث.", ephemeral=True)

@bot.tree.command(name="whitelist", description="القائمة البيضاء")
async def whitelist(interaction: discord.Interaction, user: discord.Member):
    if not await check_hierarchy(interaction): return
    if user.id in bot_data['whitelisted']:
        bot_data['whitelisted'].remove(user.id)
        msg = f"❌ تمت إزالة {user.name}."
    else:
        bot_data['whitelisted'].append(user.id)
        msg = f"✅ تمت إضافة {user.name}."
    save_data(bot_data)
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="ban", description="تبنيد عضو")
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str = "لا يوجد"):
    if not await check_hierarchy(interaction): return
    await ban_user(interaction.guild, user, reason)
    await interaction.response.send_message(f"🔨 تم طرد {user.name}.")

@bot.tree.command(name="timeout", description="تايم أوت")
async def timeout(interaction: discord.Interaction, user: discord.Member, seconds: int):
    if not await check_hierarchy(interaction): return
    await user.timeout(discord.utils.utcnow() + timedelta(seconds=seconds))
    await interaction.response.send_message(f"⏱️ تم عمل تايم أوت لـ {user.name}.")

@bot.tree.command(name="setup_jail", description="إعداد السجن")
async def setup_jail(interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role):
    if not await check_hierarchy(interaction): return
    bot_data['jail_setup'][str(interaction.guild.id)] = {'c': channel.id, 'r': role.id}
    save_data(bot_data)
    await interaction.response.send_message("✅ تم إعداد السجن.", ephemeral=True)

@bot.tree.command(name="jail", description="سجن عضو")
async def jail(interaction: discord.Interaction, user: discord.Member):
    if not await check_hierarchy(interaction): return
    gid = str(interaction.guild.id)
    setup = bot_data['jail_setup'].get(gid)
    if not setup: return await interaction.response.send_message("❌ السجن غير معد.", ephemeral=True)
    bot_data['jailed_members'][str(user.id)] = [r.id for r in user.roles if r != interaction.guild.default_role and not r.managed]
    await user.edit(roles=[interaction.guild.get_role(setup['r'])])
    save_data(bot_data)
    await interaction.response.send_message(f"🏛️ تم سجن {user.name}.")

@bot.tree.command(name="unjail", description="فك سجن")
async def unjail(interaction: discord.Interaction, user: discord.Member):
    if not await check_hierarchy(interaction): return
    saved_roles = bot_data['jailed_members'].pop(str(user.id), [])
    roles = [interaction.guild.get_role(rid) for rid in saved_roles if interaction.guild.get_role(rid)]
    await user.edit(roles=roles)
    save_data(bot_data)
    await interaction.response.send_message(f"🔓 تم فك سجن {user.name}.")

@bot.tree.command(name="add_response", description="إضافة رد تلقائي")
async def add_res(interaction: discord.Interaction, word: str, response: str):
    if not await check_hierarchy(interaction): return
    gid = str(interaction.guild.id)
    if gid not in bot_data['auto_responses']: bot_data['auto_responses'][gid] = {}
    bot_data['auto_responses'][gid][word] = response
    save_data(bot_data)
    await interaction.response.send_message(f"✅ تم إضافة الرد التلقائي للكلمة: {word}", ephemeral=True)

@bot.tree.command(name="set_log", description="تحديد روم اللوق")
async def set_log(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await check_hierarchy(interaction): return
    bot_data['log_channels'][str(interaction.guild.id)] = channel.id
    save_data(bot_data)
    await interaction.response.send_message(f"✅ تم التحديد.", ephemeral=True)

@bot.command()
@commands.is_owner()
async def sync(ctx):
    await bot.tree.sync()
    await ctx.send("✅ تم مزامنة الأوامر يدوياً!")

@bot.event
async def on_guild_join(guild):
    await ensure_log_channel(guild)

@bot.event
async def on_ready():
    for guild in bot.guilds: await ensure_log_channel(guild)
    print(f"✅ {bot.user} جاهز للعمل بجميع الميزات!")

bot.run(TOKEN)

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
