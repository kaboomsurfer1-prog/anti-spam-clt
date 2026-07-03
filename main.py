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

# Ruolo Member / normale
BLOCKED_NORMAL_ROLE_ID = 1505912122926694550

# SOLO questi ruoli possono usare @everyone, @here e tag ruoli
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

if not TOKEN:
    raise RuntimeError("Lipsește DISCORD_TOKEN în Railway Variables / .env")

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("!", "."),
    intents=intents,
    allowed_mentions=discord.AllowedMentions.none()
)

already_configured = set()


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


def member_can_use_tags(member: discord.Member) -> bool:
    return any(role.id in ALLOWED_TAG_ROLE_IDS for role in member.roles)


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
            f"Nu pot șterge mesajul în {message.channel.mention}.\n"
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


async def set_channel_mention_permission(
    channel: discord.abc.GuildChannel,
    role: discord.Role,
    value: bool
):
    overwrite = channel.overwrites_for(role)
    overwrite.mention_everyone = value

    await channel.set_permissions(
        role,
        overwrite=overwrite,
        reason="Setup automat: permisiuni @everyone / @here / tag roluri"
    )


async def apply_permissions_to_channel(channel: discord.abc.GuildChannel):
    guild = channel.guild

    # @everyone non può usare @everyone / @here / tag ruoli
    await set_channel_mention_permission(channel, guild.default_role, False)

    # Ruolo normale bloccato
    blocked_role = guild.get_role(BLOCKED_NORMAL_ROLE_ID)
    if blocked_role:
        await set_channel_mention_permission(channel, blocked_role, False)

    # Se qualche ruolo normale aveva già permesso speciale nel canale, lo togliamo
    for target in list(channel.overwrites.keys()):
        if not isinstance(target, discord.Role):
            continue

        if target.is_default():
            continue

        if target.id in ALLOWED_TAG_ROLE_IDS:
            continue

        if target.managed:
            continue

        try:
            await set_channel_mention_permission(channel, target, False)
            await asyncio.sleep(0.10)
        except Exception:
            pass

    # Solo questi ruoli possono usare @everyone / @here / tag ruoli
    for role_id in ALLOWED_TAG_ROLE_IDS:
        role = guild.get_role(role_id)
        if role:
            await set_channel_mention_permission(channel, role, True)
            await asyncio.sleep(0.10)


async def force_role_permissions(guild: discord.Guild):
    """
    Sistema anche i permessi dei ruoli.
    - Ruoli autorizzati: possono usare Mention Everyone.
    - Tutti gli altri: no.
    - Tutti i ruoli vengono resi non mentionable, così i membri normali non possono taggarli.
    """
    me = guild.me
    if not me:
        return 0, 0, []

    changed = 0
    skipped = 0
    admin_warning_roles = []

    for role in guild.roles:
        if role.managed:
            continue

        if role >= me.top_role and not role.is_default():
            skipped += 1
            continue

        perms = role.permissions
        should_allow = role.id in ALLOWED_TAG_ROLE_IDS

        if role.permissions.administrator and not should_allow:
            admin_warning_roles.append(role.name)

        changed_something = False

        if perms.mention_everyone != should_allow:
            perms.mention_everyone = should_allow
            changed_something = True

        try:
            if role.is_default():
                if changed_something:
                    await role.edit(
                        permissions=perms,
                        reason="Setup automat: blocco @everyone / @here"
                    )
                    changed += 1
            else:
                if changed_something or role.mentionable:
                    await role.edit(
                        permissions=perms,
                        mentionable=False,
                        reason="Setup automat: blocco tag ruoli"
                    )
                    changed += 1

            await asyncio.sleep(0.20)

        except discord.Forbidden:
            skipped += 1
        except Exception:
            skipped += 1

    return changed, skipped, admin_warning_roles


async def run_mentions_setup(guild: discord.Guild):
    print(f"Aplic automat permisiunile pentru serverul: {guild.name}")

    success = 0
    failed = 0

    changed_roles, skipped_roles, admin_warning_roles = await force_role_permissions(guild)

    for channel in guild.channels:
        try:
            await apply_permissions_to_channel(channel)
            success += 1
            await asyncio.sleep(0.25)
        except Exception as e:
            failed += 1
            print(f"Eroare canal {channel.name}: {e}")

    warning_text = ""
    if admin_warning_roles:
        warning_text = (
            "\n\n⚠️ Atenție: aceste roluri au **Administrator** și pot ocoli permisiunile:\n"
            + ", ".join(admin_warning_roles[:20])
        )

    print(
        f"Setup terminat pentru {guild.name} | "
        f"Canale configurate: {success} | "
        f"Canale eroare: {failed} | "
        f"Roluri modificate: {changed_roles} | "
        f"Roluri sărite: {skipped_roles}"
    )

    await send_log(
        guild,
        "✅ Setup mentions aplicat",
        f"Canale configurate: **{success}**\n"
        f"Canale cu eroare: **{failed}**\n"
        f"Roluri modificate: **{changed_roles}**\n"
        f"Roluri sărite: **{skipped_roles}**"
        f"{warning_text}"
    )

    return success, failed, changed_roles, skipped_roles


@bot.command(name="setup_mentions", aliases=["setup_mentinos", "fixmentions", "setup_tag"])
@commands.has_guild_permissions(administrator=True)
async def setup_mentions(ctx: commands.Context):
    await ctx.reply(
        "⏳ Aplic permisiunile pe toate canalele. Așteaptă puțin...",
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none()
    )

    success, failed, changed_roles, skipped_roles = await run_mentions_setup(ctx.guild)

    await ctx.send(
        f"✅ Gata.\n\n"
        f"Canale configurate: **{success}**\n"
        f"Canale cu eroare: **{failed}**\n"
        f"Roluri modificate: **{changed_roles}**\n"
        f"Roluri sărite: **{skipped_roles}**\n\n"
        f"Acum doar rolurile autorizate pot folosi `@everyone`, `@here` și tag la roluri.",
        allowed_mentions=discord.AllowedMentions.none()
    )


@bot.command(name="ping")
async def ping(ctx: commands.Context):
    await ctx.reply(
        "✅ Botul funcționează.",
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none()
    )


@setup_mentions.error
async def setup_mentions_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply(
            "❌ Doar Administrator poate folosi această comandă.",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none()
        )
    else:
        await ctx.reply(
            f"❌ Eroare: `{error}`",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none()
        )


@bot.event
async def on_guild_channel_create(channel):
    try:
        await apply_permissions_to_channel(channel)
        await send_log(
            channel.guild,
            "✅ Canal nou configurat",
            f"Canal: {channel.mention if hasattr(channel, 'mention') else channel.name}"
        )
    except Exception:
        pass


@bot.event
async def on_ready():
    print(f"Bot protecție online ca {bot.user} | Servere: {len(bot.guilds)}")
    print("Comenzi încărcate:", [cmd.name for cmd in bot.commands])

    for guild in bot.guilds:
        if guild.id in already_configured:
            continue

        already_configured.add(guild.id)

        try:
            await run_mentions_setup(guild)
        except Exception as e:
            print(f"Eroare setup automat pentru {guild.name}: {e}")


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

    allowed = member_can_use_tags(member)

    has_everyone_or_here = (
        message.mention_everyone
        or "@everyone" in lower_content
        or "@here" in lower_content
    )

    has_role_mentions = (
        len(message.role_mentions) > 0
        or bool(re.search(r"<@&\d+>", content))
    )

    # Sicurezza extra: se qualcuno riesce comunque a scriverlo, il messaggio viene cancellato
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
