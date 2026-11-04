from flask import Flask
from threading import Thread

import asyncio
import datetime
import logging
import os
import time
from collections import deque, defaultdict

import discord
from discord import app_commands
from discord.ext import commands

TOKEN = os.getenv('TOKEN')
if not TOKEN:
    raise RuntimeError("TOKEN secret is not set.")

# ── Logging setup ──────────────────────────────────────────────────────────────
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

class _Colours:
    RESET   = "\033[0m";  GREY    = "\033[90m"
    GREEN   = "\033[92m"; YELLOW  = "\033[93m"
    RED     = "\033[91m"; CYAN    = "\033[96m"
    MAGENTA = "\033[95m"; BOLD    = "\033[1m"

_LEVEL_COLOURS = {"DEBUG": _Colours.GREY, "INFO": _Colours.CYAN,
                  "WARNING": _Colours.YELLOW, "ERROR": _Colours.RED, "CRITICAL": _Colours.MAGENTA}

class _ColouredFormatter(logging.Formatter):
    def format(self, record):
        colour = _LEVEL_COLOURS.get(record.levelname, _Colours.RESET)
        record.levelname = f"{colour}{_Colours.BOLD}[{record.levelname}]{_Colours.RESET}"
        base = super().format(record)
        ts, rest = base.split(" ", 1)
        return f"{_Colours.GREY}{ts}{_Colours.RESET} {rest}"

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_ColouredFormatter(fmt="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
_file_handler = logging.FileHandler(os.path.join(LOG_DIR, "guard.log"), encoding="utf-8")
_file_handler.setFormatter(logging.Formatter(fmt="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
logging.root.setLevel(logging.INFO)
logging.root.handlers = [_console_handler, _file_handler]
logger = logging.getLogger("MasterGuard")

MAX_LOG_ENTRIES = 100
action_log: deque[dict] = deque(maxlen=MAX_LOG_ENTRIES)

def _embed_colour(result: str) -> discord.Colour:
    if result.startswith("✅"): return discord.Colour.green()
    if result.startswith("❌"): return discord.Colour.red()
    if result.startswith("⚠️"): return discord.Colour.yellow()
    return discord.Colour.blurple()

_ACTION_ICONS = {
    "BAN":"🔨","KICK":"👢","KICK_BOT":"🤖","TIMEOUT":"🔇",
    "DELETE_MSG":"🗑️","DELETE_CHANNEL":"🚫","RESTORE_CHANNEL":"♻️","RENAME_CHANNEL":"✏️",
    "DELETE_CATEGORY":"🚫","RESTORE_CATEGORY":"♻️","DELETE_ROLE":"🚫","RESTORE_ROLE":"♻️",
    "DELETE_WEBHOOK":"🕸️","RESTORE_GUILD":"🏠","WHITELIST":"📋","ADD_RESPONSE":"💬",
    "TOGGLE":"⚙️","RAID_DETECTED":"🚨",
}

async def _send_log_embed(channel_id: int, entry: dict):
    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel): return
    icon = _ACTION_ICONS.get(entry["action"], "📌")
    embed = discord.Embed(title=f"{icon} {entry['action']}", colour=_embed_colour(entry["result"]), timestamp=entry["time"])
    embed.add_field(name="الهدف",   value=entry["target"] or "—", inline=True)
    embed.add_field(name="النتيجة", value=entry["result"],        inline=True)
    embed.add_field(name="السيرفر", value=entry["guild"],         inline=True)
    if entry["extra"]: embed.add_field(name="تفاصيل", value=entry["extra"], inline=False)
    embed.set_footer(text="MasterGuard")
    try: await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException): pass

def log_action(action, target, guild_name, result, extra="", guild_id=None):
    now = datetime.datetime.now(datetime.timezone.utc)
    entry = {"time": now, "action": action, "target": target, "guild": guild_name, "result": result, "extra": extra}
    action_log.appendleft(entry)
    logger.info("[%s] %s | target=%s | result=%s%s", guild_name, action, target, result, f" | {extra}" if extra else "")
    if guild_id is not None:
        ch_id = bot.log_channels.get(guild_id)
        if ch_id: asyncio.get_event_loop().create_task(_send_log_embed(ch_id, entry))

LOG_CHANNEL_NAME = "security-log"
_guild_snapshots: dict[int, dict] = {}

def _channel_info(ch):
    owrs = {}
    for target, ow in ch.overwrites.items():
        allow, deny = ow.pair()
        owrs[target.id] = {"type": "role" if isinstance(target, discord.Role) else "member",
                           "allow": allow.value, "deny": deny.value}
    base = {"name": ch.name, "type": ch.type, "position": ch.position, "category_id": ch.category_id, "overwrites": owrs}
    if isinstance(ch, discord.TextChannel):   base.update(topic=ch.topic, nsfw=ch.nsfw, slowmode_delay=ch.slowmode_delay)
    elif isinstance(ch, discord.VoiceChannel): base.update(bitrate=ch.bitrate, user_limit=ch.user_limit)
    return base

def _role_info(role):
    return {"name": role.name, "permissions": role.permissions.value, "color": role.color.value,
            "hoist": role.hoist, "mentionable": role.mentionable, "position": role.position}

async def _take_snapshot(guild: discord.Guild):
    try: icon_bytes = await guild.icon.read() if guild.icon else None
    except Exception: icon_bytes = None
    _guild_snapshots[guild.id] = {
        "name": guild.name, "icon": icon_bytes,
        "channels": {ch.id: _channel_info(ch) for ch in guild.channels},
        "roles":    {r.id: _role_info(r) for r in guild.roles if not r.is_default()},
    }

def _build_overwrites(guild, owrs):
    result = {}
    for tid_str, data in owrs.items():
        tid = int(tid_str)
        ow = discord.PermissionOverwrite.from_pair(discord.Permissions(data["allow"]), discord.Permissions(data["deny"]))
        target = guild.get_role(tid) if data["type"] == "role" else guild.get_member(tid)
        if target: result[target] = ow
    return result

async def _ensure_log_channel(guild: discord.Guild):
    if guild.id in bot.log_channels:
        ch = guild.get_channel(bot.log_channels[guild.id])
        if ch: return ch
    existing = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
    if existing:
        bot.log_channels[guild.id] = existing.id
        return existing
    try:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True),
        }
        for role in guild.roles:
            if role.permissions.administrator: overwrites[role] = discord.PermissionOverwrite(read_messages=True)
        ch = await guild.create_text_channel(name=LOG_CHANNEL_NAME, overwrites=overwrites,
                                             topic="سجل إجراءات MasterGuard — Security log",
                                             reason="MasterGuard: auto-created security log channel")
        bot.log_channels[guild.id] = ch.id
        return ch
    except Exception: return None

# ── Bot class ──────────────────────────────────────────────────────────────────
class MasterGuardBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
        self.whitelist: set[int] = set()
        self.auto_responses: dict[str, str] = {}
        self.msg_cache: dict[int, list[float]] = {}
        self.log_channels: dict[int, int] = {}
        self.settings = {"spam": True, "channels": True, "roles": True,
                         "webhooks": True, "guild_update": True, "bots": True}

    async def setup_hook(self):
        await self.tree.sync()
        logger.info("نظام الحماية يعمل الآن بكامل طاقته.")

    async def on_ready(self):
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        await asyncio.gather(*[asyncio.gather(_ensure_log_channel(g), _take_snapshot(g)) for g in self.guilds])

    async def on_guild_join(self, guild):
        logger.info("Joined guild: %s (ID: %s)", guild.name, guild.id)
        await asyncio.gather(_ensure_log_channel(guild), _take_snapshot(guild))

bot = MasterGuardBot()

def _can_moderate(guild, member): return guild.me.top_role > member.top_role
def _guild_name(guild): return guild.name if guild else "DM"

async def _try_ban(guild, user, reason, guild_name):
    name = str(getattr(user, "name", user.id))
    try:
        await guild.ban(user, reason=reason, delete_message_days=0)
        log_action("BAN", name, guild_name, "✅ تم الباند", reason, guild_id=guild.id)
    except Exception as e:
        log_action("BAN", name, guild_name, f"❌ خطأ: {e}", reason, guild_id=guild.id)

async def _try_kick(member, reason, guild_name):
    try:
        await member.kick(reason=reason)
        log_action("KICK", str(member), guild_name, "✅ تم الكيك", reason, guild_id=member.guild.id)
    except Exception: pass

# ── الاسترجاع الشامل الفوري (سريع ولا يعلق) ──────────────────────────────────
async def _restore_missing_channels(guild: discord.Guild):
    snap = _guild_snapshots.get(guild.id, {})
    snap_channels = snap.get("channels", {})
    current_channel_ids = {ch.id for ch in guild.channels}
    
    for ch_id, ch_data in snap_channels.items():
        if ch_id not in current_channel_ids:
            try:
                owrs = _build_overwrites(guild, ch_data.get("overwrites", {}))
                category = guild.get_channel(ch_data["category_id"]) if ch_data["category_id"] else None
                
                if ch_data["type"] == discord.ChannelType.text:
                    new_ch = await guild.create_text_channel(
                        name=ch_data["name"], category=category, overwrites=owrs,
                        topic=ch_data.get("topic"), slowmode_delay=ch_data.get("slowmode_delay", 0),
                        reason="MasterGuard: Fast State Sync Restoration"
                    )
                    if ch_data["name"] == LOG_CHANNEL_NAME: bot.log_channels[guild.id] = new_ch.id
                elif ch_data["type"] == discord.ChannelType.voice:
                    await guild.create_voice_channel(
                        name=ch_data["name"], category=category, overwrites=owrs,
                        bitrate=ch_data.get("bitrate", 64000), user_limit=ch_data.get("user_limit", 0),
                        reason="MasterGuard: Fast State Sync Restoration"
                    )
                elif ch_data["type"] == discord.ChannelType.category:
                    await guild.create_category(
                        name=ch_data["name"], overwrites=owrs,
                        reason="MasterGuard: Fast State Sync Restoration"
                    )
                log_action("RESTORE_CHANNEL", ch_data["name"], guild.name, "✅ استُعيدت بنجاح", "استرجاع فوري", guild_id=guild.id)
            except Exception:
                pass

# ── الأحداث الأساسية ──────────────────────────────────────────────────────────
@bot.event
async def on_message(message: discord.Message):
    if message.author.id == bot.user.id: return
    guild_name = _guild_name(message.guild)
    gid = message.guild.id if message.guild else None
    if message.author.bot and bot.settings["spam"]:
        if message.author.id in bot.whitelist: return
        try: await message.delete()
        except Exception: pass
        log_action("DELETE_MSG", str(message.author), guild_name, "✅ حُذفت", f"بوت سبام", guild_id=gid)
        member = message.guild.get_member(message.author.id) if message.guild else None
        if member and message.guild:
            if _can_moderate(message.guild, member): await _try_ban(message.guild, member, "بوت سبام", guild_name)
            else: await _try_kick(member, "بوت سبام", guild_name)
        return
    if message.author.id in bot.whitelist:
        await bot.process_commands(message); return
    if bot.settings["spam"]:
        uid = message.author.id; curr = time.time()
        bot.msg_cache.setdefault(uid, [])
        bot.msg_cache[uid] = [t for t in bot.msg_cache[uid] if curr - t < 3]
        bot.msg_cache[uid].append(curr)
        if len(bot.msg_cache[uid]) > 5:
            try:
                await message.author.timeout(discord.timedelta(minutes=10), reason="سبام")
                await message.channel.send(f"{message.author.mention} تم كتمك بسبب السبام!")
                log_action("TIMEOUT", str(message.author), guild_name, "✅ كتم 10 دقائق", "سبام", guild_id=gid)
            except Exception: pass
    if message.content in bot.auto_responses: await message.channel.send(bot.auto_responses[message.content])
    await bot.process_commands(message)

@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    if not bot.settings["channels"]: return
    guild = channel.guild
    guild_name = _guild_name(guild)
    
    # 1. تشغيل الاسترجاع الشامل الفوري للرومات المفقودة دون أي انتظار
    asyncio.create_task(_restore_missing_channels(guild))

    # 2. محاولة بند واحدة فقط (بدون تكرار أو محاولات عمياء تسبب لمتد وتلخبط البوت)
    try:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
            if entry.user and entry.user.id != bot.user.id and entry.user.id not in bot.whitelist:
                member = guild.get_member(entry.user.id)
                if member and _can_moderate(guild, member):
                    await guild.ban(member, reason="Anti-Nuke: Channel Deletion", delete_message_days=0)
            break
    except Exception:
        pass

@bot.event
async def on_guild_role_delete(role: discord.Role):
    if not bot.settings["roles"]: return
    guild = role.guild
    guild_name = _guild_name(guild)
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
        if not entry.user or entry.user.id == bot.user.id or entry.user.id in bot.whitelist: return
        snap_roles = _guild_snapshots.get(guild.id, {}).get("roles", {})
        role_data = snap_roles.get(role.id, {})
        try:
            nr = await guild.create_role(
                name=role.name, permissions=role.permissions, color=role.color,
                hoist=role_data.get("hoist", role.hoist), mentionable=role_data.get("mentionable", role.mentionable),
                reason="MasterGuard: Role Restoration"
            )
            try: await nr.edit(position=role_data.get("position", role.position))
            except Exception: pass
            log_action("RESTORE_ROLE", role.name, guild_name, "✅ استُعيدت الرتبة", f"حذفها {entry.user}", guild_id=guild.id)
        except Exception:
            pass
        member = guild.get_member(entry.user.id)
        if member and _can_moderate(guild, member):
            asyncio.create_task(_try_ban(guild, member, "حذف رتبة", guild_name))
        break

@bot.event
async def on_webhooks_update(channel: discord.abc.GuildChannel):
    if not bot.settings["webhooks"]: return
    try:
        webhooks = await channel.webhooks()
        for wb in webhooks:
            await wb.delete(reason="MasterGuard: Delete webhook")
            log_action("DELETE_WEBHOOK", wb.name, channel.guild.name, "✅ حُذف", "", guild_id=channel.guild.id)
    except Exception: pass

@bot.event
async def on_guild_update(before: discord.Guild, after: discord.Guild):
    if not bot.settings["guild_update"] or (before.name == after.name and before.icon == after.icon): return
    async for entry in after.audit_logs(limit=1, action=discord.AuditLogAction.guild_update):
        if not entry.user or entry.user.id == bot.user.id or entry.user.id in bot.whitelist: return
        snap = _guild_snapshots.get(after.id, {})
        try:
            icon_bytes = snap.get("icon") or (await before.icon.read() if before.icon else None)
            await after.edit(name=snap.get("name", before.name), icon=icon_bytes)
            log_action("RESTORE_GUILD", before.name, after.name, "✅ استُعيدت البيانات", f"غيّرها {entry.user}", guild_id=after.id)
        except Exception: pass
        member = after.get_member(entry.user.id)
        if member and _can_moderate(after, member):
            asyncio.create_task(_try_ban(after, member, "تغيير بيانات السيرفر", after.name))
        break

@bot.event
async def on_member_join(member: discord.Member):
    if not member.bot or not bot.settings["bots"] or member.id == bot.user.id: return
    guild = member.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
        if entry.target and entry.target.id == member.id and entry.user and entry.user.id not in bot.whitelist:
            try: await member.kick()
            except Exception: pass
            adder = guild.get_member(entry.user.id)
            if adder and _can_moderate(guild, adder):
                asyncio.create_task(_try_ban(guild, adder, "إضافة بوت غير موثوق", guild.name))
            break

# ── أوامر السلاش كاملة ────────────────────────────────────────────────────────
@bot.tree.command(name="setlog", description="تحديد روم اللوق")
async def cmd_setlog(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.guild: return await interaction.response.send_message("يعمل داخل السيرفر فقط.", ephemeral=True)
    bot.log_channels[interaction.guild.id] = channel.id
    log_action("SETLOG", channel.name, interaction.guild.name, "✅ تم", f"بواسطة {interaction.user}", guild_id=interaction.guild.id)
    await interaction.response.send_message(f"✅ روم اللوق: {channel.mention}", ephemeral=True)

@bot.tree.command(name="whitelist", description="إضافة/حذف من القائمة البيضاء")
async def whitelist_cmd(interaction: discord.Interaction, user: discord.Member, action: bool):
    if action: bot.whitelist.add(user.id)
    else: bot.whitelist.discard(user.id)
    status = "أُضيف إلى" if action else "حُذف من"
    gid = interaction.guild.id if interaction.guild else None
    log_action("WHITELIST", str(user), interaction.guild.name if interaction.guild else "DM",
               f"{'➕' if action else '➖'} {status} القائمة البيضاء", f"بواسطة {interaction.user}", guild_id=gid)
    await interaction.response.send_message(f"{user.name} {status} القائمة البيضاء.", ephemeral=True)

@bot.tree.command(name="add_response", description="إضافة رد تلقائي")
async def add_response(interaction: discord.Interaction):
    class ResponseModal(discord.ui.Modal, title="إضافة رد تلقائي"):
        word = discord.ui.TextInput(label="الكلمة أو الجملة")
        resp = discord.ui.TextInput(label="الرد", style=discord.TextStyle.paragraph)
        async def on_submit(self, i: discord.Interaction):
            bot.auto_responses[str(self.word)] = str(self.resp)
            gid = i.guild.id if i.guild else None
            log_action("ADD_RESPONSE", str(self.word), i.guild.name if i.guild else "DM", "✅ تم الحفظ", f"بواسطة {i.user}", guild_id=gid)
            await i.response.send_message(f"تم حفظ الرد على: {self.word}", ephemeral=True)
    await interaction.response.send_modal(ResponseModal())

@bot.tree.command(name="check_protection", description="فحص حالة جميع الحمايات")
async def check_protection(interaction: discord.Interaction):
    s = bot.settings
    gid = interaction.guild.id if interaction.guild else None
    log_ch = f"<#{bot.log_channels[gid]}>" if gid and gid in bot.log_channels else "غير محدد"
    lines = [
        "**حالة الحماية الحالية:**",
        f"- الرومات والكاتقوري: {'✅ مفعلة' if s['channels'] else '❌ معطلة'}",
        f"- الرتب: {'✅ مفعلة' if s['roles'] else '❌ معطلة'}",
        f"- الويب هوك: {'✅ مفعلة' if s['webhooks'] else '❌ معطلة'}",
        f"- بيانات السيرفر: {'✅ مفعلة' if s['guild_update'] else '❌ معطلة'}",
        f"- البوتات الغير موثوقة: {'✅ مفعلة' if s['bots'] else '❌ معطلة'}",
        f"- السبام: {'✅ مفعلة' if s['spam'] else '❌ معطلة'}",
        f"- القائمة البيضاء: {len(bot.whitelist)} مستخدم",
        f"- روم اللوق: {log_ch}",
        f"- إجمالي الإجراءات: {len(action_log)}",
    ]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

@bot.tree.command(name="spam", description="تفعيل أو تعطيل حماية السبام")
async def cmd_spam(interaction: discord.Interaction, state: bool):
    bot.settings["spam"] = state; txt = "✅ مفعلة" if state else "❌ معطلة"
    gid = interaction.guild.id if interaction.guild else None
    log_action("TOGGLE","السبام", interaction.guild.name if interaction.guild else "DM", txt, f"بواسطة {interaction.user}", guild_id=gid)
    await interaction.response.send_message(f"حماية **السبام**: {txt}", ephemeral=True)

@bot.tree.command(name="channels", description="تفعيل أو تعطيل حماية الرومات والكاتقوري")
async def cmd_channels(interaction: discord.Interaction, state: bool):
    bot.settings["channels"] = state; txt = "✅ مفعلة" if state else "❌ معطلة"
    gid = interaction.guild.id if interaction.guild else None
    log_action("TOGGLE","الرومات", interaction.guild.name if interaction.guild else "DM", txt, f"بواسطة {interaction.user}", guild_id=gid)
    await interaction.response.send_message(f"حماية **الرومات والكاتقوري**: {txt}", ephemeral=True)

@bot.tree.command(name="roles", description="تفعيل أو تعطيل حماية الرتب")
async def cmd_roles(interaction: discord.Interaction, state: bool):
    bot.settings["roles"] = state; txt = "✅ مفعلة" if state else "❌ معطلة"
    gid = interaction.guild.id if interaction.guild else None
    log_action("TOGGLE","الرتب", interaction.guild.name if interaction.guild else "DM", txt, f"بواسطة {interaction.user}", guild_id=gid)
    await interaction.response.send_message(f"حماية **الرتب**: {txt}", ephemeral=True)

@bot.tree.command(name="webhooks", description="تفعيل أو تعطيل حماية الويب هوك")
async def cmd_webhooks(interaction: discord.Interaction, state: bool):
    bot.settings["webhooks"] = state; txt = "✅ مفعلة" if state else "❌ معطلة"
    gid = interaction.guild.id if interaction.guild else None
    log_action("TOGGLE","الويب هوك", interaction.guild.name if interaction.guild else "DM", txt, f"بواسطة {interaction.user}", guild_id=gid)
    await interaction.response.send_message(f"حماية **الويب هوك**: {txt}", ephemeral=True)

@bot.tree.command(name="server", description="تفعيل أو تعطيل حماية بيانات السيرفر")
async def cmd_server(interaction: discord.Interaction, state: bool):
    bot.settings["guild_update"] = state; txt = "✅ مفعلة" if state else "❌ معطلة"
    gid = interaction.guild.id if interaction.guild else None
    log_action("TOGGLE","بيانات السيرفر", interaction.guild.name if interaction.guild else "DM", txt, f"بواسطة {interaction.user}", guild_id=gid)
    await interaction.response.send_message(f"حماية **بيانات السيرفر**: {txt}", ephemeral=True)

@bot.tree.command(name="unverified_bots", description="تفعيل أو تعطيل منع إضافة البوتات الغير موثوقة")
async def cmd_unverified_bots(interaction: discord.Interaction, state: bool):
    bot.settings["bots"] = state; txt = "✅ مفعلة" if state else "❌ معطلة"
    gid = interaction.guild.id if interaction.guild else None
    log_action("TOGGLE","البوتات الغير موثوقة", interaction.guild.name if interaction.guild else "DM", txt, f"بواسطة {interaction.user}", guild_id=gid)
    await interaction.response.send_message(f"🤖 حماية **البوتات الغير موثوقة**: {txt}", ephemeral=True)

@bot.tree.command(name="logs", description="عرض آخر 10 إجراءات")
async def cmd_logs(interaction: discord.Interaction):
    if not action_log: return await interaction.response.send_message("لا توجد إجراءات بعد.", ephemeral=True)
    lines = [f"`{e['time'].strftime('%H:%M:%S')}` **{e['action']}** — {e['target']} → {e['result']}" for e in list(action_log)[:10]]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

@bot.tree.command(name="server_info", description="معلومات السيرفر الحالي")
async def cmd_server_info(interaction: discord.Interaction):
    g = interaction.guild
    if not g: return await interaction.response.send_message("يعمل داخل السيرفر فقط.", ephemeral=True)
    embed = discord.Embed(title=g.name, colour=discord.Colour.blurple())
    embed.add_field(name="الأعضاء", value=str(g.member_count), inline=True)
    embed.add_field(name="الرومات", value=str(len(g.channels)), inline=True)
    embed.add_field(name="الرتب",   value=str(len(g.roles)),   inline=True)
    embed.add_field(name="المالك",  value=str(g.owner),        inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- إبقاء البوت حياً ---
app = Flask('')
@app.route('/')
def home():
    return "MasterGuard is Online!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

if __name__ == "__main__":
    t = Thread(target=run_flask)
    t.start()
    bot.run(TOKEN)
