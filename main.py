import os
import re
import unicodedata

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))

# Ruolo normale che NON può taggare ruoli / here / everyone
BLOCKED_NORMAL_ROLE_ID = 1505912122926694550

# Ruoli autorizzati a usare @everyone / @here / tag ruoli
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


def has_role(member: discord.Member, role_id: int) -> bool:
    return any(role.id == role_id for role in member.roles)


def can_use_tags(member: discord.Member) -> bool:
    # Se vuoi che anche Administrator possa usarli sempre, lascia questa parte.
    if member.guild_permissions.administrator:
        return True

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

    authorized = can_use_tags(member)

    # 1. Blocca @everyone / @here per tutti, tranne ruoli autorizzati
    if has_everyone_or_here and not authorized:
        await delete_and_warn(
            message,
            "Nu ai voie să folosești @everyone sau @here."
        )
        return

    # 2. Il ruolo normale 1505912122926694550 non può taggare ruoli
    if has_role(member, BLOCKED_NORMAL_ROLE_ID) and has_role_mentions and not authorized:
        await delete_and_warn(
            message,
            "Nu ai voie să dai tag la roluri."
        )
        return

    # 3. Blocca parole volgari
    if contains_bad_word(content):
        await delete_and_warn(
            message,
            "Limbaj vulgar / cuvinte interzise."
        )
        return

    await bot.process_commands(message)


bot.run(TOKEN)
