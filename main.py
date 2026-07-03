import os
import re
import asyncio
import unicodedata

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))

# Ruolo normale / member
BLOCKED_NORMAL_ROLE_ID = 1505912122926694550

# SOLO questi ruoli possono usare @everyone / @here / tag ruoli
ALLOWED_TAG_ROLE_IDS = {
    1505906085901504522,
    1519377368354132110,
    1505905849774641243,
    1516817227901567168,
}

BAD_WORDS = [
    "pula",
    "muie",
    "bag pula",
    "fmm",
    "mortii",
    "morti",
    "mata",
    "ma-ta",
    "pizda",
    "sugi",
    "curva",
    "prost",
    "handicapat",
]

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    allowed_mentions=discord.AllowedMentions.none()
)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s@]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize_text(text))


def contains_bad_word(text: str) -> bool:
    normal = normalize_text(text)
    compact = compact_text(text)

    for word in BAD_WORDS:
        w_normal = normalize_text(word)
        w_compact = compact_text(word)

        if w_normal and w_normal in normal:
            return True

        if w_compact and w_compact in compact:
            return True

    return False


def member_has_allowed_tag_role(member: discord.Member) -> bool:
    return any(role.id in ALLOWED_TAG_ROLE_IDS for role in member.roles)


def member_has_blocked_role(member: discord.Member) -> bool:
    return any(role.id == BLOCKED_NORMAL_ROLE_ID for role in member.roles)


async def send_log(guild: discord.Guild, title: str, description: str):
    if not LOG_CHANNEL_ID:
        return

    channel = guild.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )

    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.Forbidden:
        pass


async def delete_and_warn(message: discord.Message, reason: str):
    try:
        await message.delete()
    except discord.Forbidden:
        await send_log(
            message.guild,
            "⚠️ Eroare permisiuni",
            f"Nu pot șterge mesajul în {message.channel.mention}. "
            f"Verifică permisiunea **Manage Messages**."
        )
        return
    except discord.NotFound:
        return

    try:
        await message.channel.send(
            f"{message.author.mention}, mesajul tău a fost șters.\n"
            f"Motiv: **{reason}**",
            delete_after=6,
            allowed_mentions=discord.AllowedMentions(users=True)
        )
    except discord.Forbidden:
        pass

    await send_log(
        message.guild,
        "🛡️ Mesaj blocat",
        f"Membru: **{message.author}** (`{message.author.id}`)\n"
        f"Canal: {message.channel.mention}\n"
        f"Motiv: **{reason}**\n"
        f"Mesaj: `{message.content[:800]}`"
    )


async def set_mention_permission(channel: discord.abc.GuildChannel, role: discord.Role, value: bool):
    overwrite = channel.overwrites_for(role)
    overwrite.mention_everyone = value

    await channel.set_permissions(
        role,
        overwrite=overwrite,
        reason="Setup automat permisiuni @everyone / @here / tag roluri"
    )


async def apply_permissions_to_channel(channel: discord.abc.GuildChannel):
    guild = channel.guild

    # 1. @everyone NON può usare @everyone / @here / tag ruoli
    await set_mention_permission(channel, guild.default_role, False)

    # 2. Il ruolo normale NON può usare @everyone / @here / tag ruoli
    blocked_role = guild.get_role(BLOCKED_NORMAL_ROLE_ID)
    if blocked_role:
        await set_mention_permission(channel, blocked_role, False)

    # 3. Tutti i ruoli NON autorizzati vengono bloccati
    for role in guild.roles:
        if role.is_default():
            continue

        if role.id in ALLOWED_TAG_ROLE_IDS:
            continue

        if role.managed:
            continue

        try:
            await set_mention_permission(channel, role, False)
            await asyncio.sleep(0.15)
        except discord.Forbidden:
            pass
        except Exception:
            pass

    # 4. Solo i ruoli autorizzati possono usare @everyone / @here / tag ruoli
    for role_id in ALLOWED_TAG_ROLE_IDS:
        role = guild.get_role(role_id)
        if role:
            await set_mention_permission(channel, role, True)
            await asyncio.sleep(0.15)


async def disable_public_role_mentions(guild: discord.Guild):
    """
    Mette i ruoli come non mentionable.
    Così i membri normali non possono pingare ruoli anche se il ruolo era impostato come mentionable.
    """
    me = guild.me
    if not me:
        return 0, 0

    changed = 0
    skipped = 0

    for role in guild.roles:
        if role.is_default():
            continue

        if role.managed:
            continue

        # Il bot non può modificare ruoli sopra o uguali al suo ruolo
        if role >= me.top_role:
            skipped += 1
            continue

        if role.mentionable:
            try:
                await role.edit(
                    mentionable=False,
                    reason="Setup automat: blocco tag ruoli pentru membri normali"
                )
                changed += 1
                await asyncio.sleep(0.2)
            except discord.Forbidden:
                skipped += 1
            except Exception:
                skipped += 1

    return changed, skipped


@bot.command(name="setup_mentions", aliases=["fixmentions", "setup_tag"])
@commands.has_guild_permissions(administrator=True)
async def setup_mentions(ctx: commands.Context):
    await ctx.reply(
        "⏳ Aplic permisiunile pe toate canalele. Așteaptă puțin...",
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none()
    )

    guild = ctx.guild
    success = 0
    failed = 0

    # Prima cosa: disattiva mentionable sui ruoli
    changed_roles, skipped_roles = await disable_public_role_mentions(guild)

    # Poi applica i permessi su tutti i canali / categorie
    for channel in guild.channels:
        try:
            await apply_permissions_to_channel(channel)
            success += 1
            await asyncio.sleep(0.3)
        except discord.Forbidden:
            failed += 1
        except Exception:
            failed += 1

    await ctx.send(
        f"✅ Gata.\n\n"
        f"Canale configurate: **{success}**\n"
        f"Canale cu eroare: **{failed}**\n"
        f"Roluri făcute non-mentionable: **{changed_roles}**\n"
        f"Roluri sărite: **{skipped_roles}**\n\n"
        f"Acum doar rolurile autorizate pot folosi `@everyone`, `@here` și tag la roluri.",
        allowed_mentions=discord.AllowedMentions.none()
    )


@setup_mentions.error
async def setup_mentions_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply(
            "❌ Nu ai permisiunea necesară. Doar Administrator poate folosi această comandă.",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none()
        )


@bot.event
async def on_guild_channel_create(channel):
    # Applica automaticamente i permessi anche ai canali nuovi
    try:
        await apply_permissions_to_channel(channel)
    except Exception:
        pass


@bot.event
async def on_ready():
    print(f"Bot protecție online ca {bot.user} | Servere: {len(bot.guilds)}")


@bot.event
async def on_message(message: discord.Message):
    if not message.guild:
        return

    if message.author.bot:
        return

    if not isinstance(message.author, discord.Member):
        return

    member = message.author
    content = message.content or ""
    lower_content = content.lower()

    has_everyone_or_here = (
        message.mention_everyone
        or "@everyone" in lower_content
        or "@here" in lower_content
    )

    has_role_mentions = len(message.role_mentions) > 0
    allowed = member_has_allowed_tag_role(member)

    # Sicurezza extra: cancella comunque se qualcuno riesce a scrivere il tag
    if has_everyone_or_here and not allowed:
        await delete_and_warn(
            message,
            "Nu ai voie să folosești @everyone sau @here."
        )
        return

    if has_role_mentions and not allowed:
        await delete_and_warn(
            message,
            "Nu ai voie să dai tag la roluri."
        )
        return

    if contains_bad_word(content):
        await delete_and_warn(
            message,
            "Limbaj vulgar / cuvinte interzise."
        )
        return

    await bot.process_commands(message)


bot.run(TOKEN)
