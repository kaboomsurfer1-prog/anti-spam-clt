import os
import re
import unicodedata

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))

# Ruolo che NON può taggare ruoli / here / everyone
BLOCK_MENTION_ROLE_ID = 1505912122926694550

# Parole volgari bloccate
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

        if w_normal in normal:
            return True

        if w_compact in compact:
            return True

    return False


def has_blocked_role(member: discord.Member) -> bool:
    return any(role.id == BLOCK_MENTION_ROLE_ID for role in member.roles)


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

    await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


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

    # 1. Chi ha il ruolo 1505912122926694550 NON può taggare ruoli / here / everyone
    if has_blocked_role(member):
        has_everyone_or_here = (
            message.mention_everyone
            or "@everyone" in content.lower()
            or "@here" in content.lower()
        )

        has_role_mentions = len(message.role_mentions) > 0

        if has_everyone_or_here or has_role_mentions:
            await delete_and_warn(
                message,
                "Nu ai voie să dai tag la roluri, @here sau @everyone."
            )
            return

    # 2. Blocca parole volgari
    if contains_bad_word(content):
        await delete_and_warn(
            message,
            "Limbaj vulgar / cuvinte interzise."
        )
        return

    await bot.process_commands(message)


bot.run(TOKEN)