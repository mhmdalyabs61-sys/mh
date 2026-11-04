import discord
from discord.ext import commands
from discord import app_commands
import json, os, asyncio
from datetime import timedelta, datetime
from typing import Union, Optional, List, Dict
from flask import Flask
from threading import Thread

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

DATA_FILE = 'bot_data.json'

def load_data():
    default = {
        'whitelisted': [], 'log_channels': {}, 'jail_setup': {}, 
        'auto_responses': {}, 'jailed_members': {},
        'protection': {
            'channel_del': True, 'channel_update': True,
            'role_del': True, 'role_create': True,
            'webhook': True, 'bot_add': True,
            'channel_create': True
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

app = Flask('')

@app.route('/')
def home():
    return "I am alive!"

def run():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()

keep_alive()

local_cache = {
    'channels': {},  
    'roles': {},     
    'categories': {} 
}

# --- نظام قفل منع التكرار والطابور المجمع ---
processed_channels = set()
channel_queue = asyncio.Queue()
is_processing_queue = False

def update_guild_cache(guild):
    for cat in guild.categories:
        local_cache['categories'][cat.id] = {
            'name': cat.name, 'position': cat.position, 'overwrites': cat.overwrites
        }
    for ch in guild.channels:
        if isinstance(ch, discord.CategoryChannel): continue
        local_cache['channels'][ch.id] = {
            'name': ch.name,
            'type': str(ch.type),
            'category_id': ch.category_id,
            'position': ch.position,
            'overwrites': ch.overwrites,
            'topic': getattr(ch, 'topic', None),
            'nsfw': getattr(ch, 'nsfw', False),
            'bitrate': getattr(ch, 'bitrate', 64000),
            'user_limit': getattr(ch, 'user_limit', 0)
        }
    for r in guild.roles:
        if r.is_default() or r.managed: continue
        local_cache['roles'][r.id] = {
            'name': r.name, 'permissions': r.permissions,
            'color': r.color, 'hoist': r.hoist,
            'mentionable': r.mentionable, 'position': r.position
        }

async def safe_execute(coro):
    while True:
        try:
            return await coro
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = float(e.response.headers.get('Retry-After', 1))
                await asyncio.sleep(retry_after + 0.1)
            else:
                break
        except Exception:
            break

async def process_channel_queue(guild):
    global is_processing_queue
    if is_processing_queue: return
    is_processing_queue = True
    
    await asyncio.sleep(0.5) # نافذة تجميع الطلبات لمنع التكرار وضغط اللمتد
    
    while not channel_queue.empty():
        item = await channel_queue.get()
        channel_id = item['id']
        channel = item['channel']
        user = item['user']
        
        if channel_id in processed_channels:
            channel_queue.task_done()
            continue
            
        processed_channels.add(channel_id)
        
        try:
            data = local_cache['channels'].get(channel_id)
            if isinstance(channel, discord.CategoryChannel):
                cat_data = local_cache['categories'].get(channel_id, {'name': channel.name, 'position': channel.position, 'overwrites': channel.overwrites})
                new_cat = await safe_execute(guild.create_category(name=cat_data['name'], position=cat_data['position'], overwrites=cat_data['overwrites']))
                if new_cat: local_cache['categories'][new_cat.id] = cat_data
            elif isinstance(channel, discord.VoiceChannel):
                cat = guild.get_channel(data['category_id']) if data and data.get('category_id') else None
                await safe_execute(guild.create_voice_channel(name=channel.name, category=cat, position=data.get('position', 0) if data else 0, overwrites=channel.overwrites))
            else:
                cat = guild.get_channel(data['category_id']) if data and data.get('category_id') else None
                await safe_execute(guild.create_text_channel(name=channel.name, category=cat, position=data.get('position', 0) if data else 0, overwrites=channel.overwrites, topic=getattr(channel, 'topic', None), nsfw=getattr(channel, 'nsfw', False)))
        except Exception as e:
            print(f"Queue Restore Error: {e}")
            
        channel_queue.task_done()
        
    is_processing_queue = False

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

async def handle_protection_log(guild, user, action_name, target):
    channel = await ensure_log_channel(guild)
    if channel:
        embed = discord.Embed(title="🛡️ Anti-Nuke Queue Shield", color=discord.Color.red(), timestamp=discord.utils.utcnow())
        embed.add_field(name="👤 الفاعل", value=f"{user.mention} (`{user.id}`)", inline=True)
        embed.add_field(name="⚡ الإجراء", value=f"`{action_name}`", inline=True)
        embed.add_field(name="🎯 الهدف", value=f"**{target}**", inline=False)
        try: await channel.send(embed=embed)
        except: pass

    if user.id != bot.user.id and user.id not in bot_data.get('whitelisted', []):
        await safe_execute(guild.ban(user, reason=f"Anti-Nuke: {action_name}"))

# --- واجهات الراديو ---
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
            channel = await safe_execute(guild.create_voice_channel(name=wave_name, overwrites=overwrites, category=interaction.user.voice.channel.category))
            await interaction.response.send_message(f"✅ تم إنشاء موجتك: {channel.mention}", ephemeral=True)
        else:
            await safe_execute(channel.set_permissions(interaction.user, connect=True, view_channel=True))
            await interaction.response.send_message(f"✅ تم توصيلك بموجة {self.wave_id.value}", ephemeral=True)
        await interaction.user.move_to(channel)

class RadioView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="+", style=discord.ButtonStyle.primary, custom_id="radio_btn")
    async def join_wave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WaveModal())

@bot.event
async def setup_hook():
    bot.add_view(RadioView()) 
    await bot.tree.sync()
    print("✅ تم تفعيل النظام بنظام الطابور المجمع المانع للتكرار!")

async def check_hierarchy(interaction: discord.Interaction) -> bool:
    if interaction.user.id == interaction.guild.owner_id: return True
    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        await interaction.response.send_message("❌ **عذراً!** يجب أن تملك صلاحية الإدارة.", ephemeral=True)
        return False
    return True

# --- أحداث الحماية عبر الطابور المجمع (Queue) ---

@bot.event
async def on_guild_channel_delete(channel):
    if not bot_data['protection'].get('channel_del', True) or channel.id in processed_channels: return

    user = bot.user
    async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
        user = entry.user
        break

    if user.id == bot.user.id or user.id in bot_data.get('whitelisted', []):
        return

    await handle_protection_log(channel.guild, user, "حذف جماعي/فردي", channel.name)
    await channel_queue.put({'id': channel.id, 'channel': channel, 'user': user})
    asyncio.create_task(process_channel_queue(channel.guild))

@bot.event
async def on_guild_role_delete(role):
    if not bot_data['protection'].get('role_del', True): return

    user = bot.user
    async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
        user = entry.user
        break

    if user.id == bot.user.id or user.id in bot_data.get('whitelisted', []):
        return

    try:
        r_data = local_cache['roles'].get(role.id, {'name': role.name, 'permissions': role.permissions, 'color': role.color, 'hoist': role.hoist, 'mentionable': role.mentionable})
        new_role = await safe_execute(role.guild.create_role(name=r_data['name'], permissions=r_data['permissions'], color=r_data['color'], hoist=r_data['hoist'], mentionable=r_data['mentionable']))
        if new_role: local_cache['roles'][new_role.id] = r_data
        await handle_protection_log(role.guild, user, "حذف رتبة", role.name)
    except Exception as e:
        print(f"Role Restore Error: {e}")

@bot.event
async def on_guild_channel_create(channel):
    if not bot_data['protection'].get('channel_create', True): return
    update_guild_cache(channel.guild)

@bot.event
async def on_guild_role_create(role):
    if not bot_data['protection'].get('role_create', True): return
    update_guild_cache(role.guild)

@bot.event
async def on_webhooks_update(channel):
    if not bot_data['protection'].get('webhook', True): return
    try:
        webhooks = await channel.webhooks()
        for wh in webhooks:
            await safe_execute(wh.delete())
    except: pass

@bot.event
async def on_message(message):
    if message.author.bot: return
    gid = str(message.guild.id) if message.guild else None
    if gid and gid in bot_data.get('auto_responses', {}):
        for word, res in bot_data['auto_responses'][gid].items():
            if word in message.content:
                await message.channel.send(res)
                break
    await bot.process_commands(message)

# --- أوامر السلاش ---
@bot.tree.command(name="setup_radio", description="إرسال رسالة نظام الموجات")
async def setup_radio(interaction: discord.Interaction):
    if not await check_hierarchy(interaction): return
    channel = bot.get_channel(1521294580933328967)
    if not channel: return await interaction.response.send_message("❌ الروم غير موجود.", ephemeral=True)
    await channel.send("📻 **نظام الموجات:**\nاضغط على الزائد (+) لإنشاء أو دخول موجتك الخاصة.", view=RadioView())
    await interaction.response.send_message("✅ تم الإرسال.", ephemeral=True)

@bot.tree.command(name="whitelist", description="القائمة البيضاء")
async def whitelist_cmd(interaction: discord.Interaction, user: discord.Member):
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
    await safe_execute(interaction.guild.ban(user, reason=reason))
    await interaction.response.send_message(f"🔨 تم طرد {user.name}.")

@bot.tree.command(name="set_log", description="تحديد روم اللوق")
async def set_log(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await check_hierarchy(interaction): return
    bot_data['log_channels'][str(interaction.guild.id)] = channel.id
    save_data(bot_data)
    await interaction.response.send_message("✅ تم التحديد.", ephemeral=True)

@bot.event
async def on_ready():
    for guild in bot.guilds:
        update_guild_cache(guild)
        await ensure_log_channel(guild)
    print(f"✅ {bot.user} جاهز للعمل بنظام الطابور المجمع (Queue) لمنع التكرار!")

TOKEN = os.getenv('TOKEN')
bot.run(TOKEN)
