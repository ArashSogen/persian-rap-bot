#!/usr/bin/env python3
"""
Persian Old School Rap Bot
Daily picks 2 songs from old Persian rappers, sends to admin for approval, then uploads to channel.
"""

import os
import sys
import json
import asyncio
import logging
import random
import re
import shutil
from datetime import time as dtime, datetime, timedelta
from pathlib import Path
from typing import Optional

import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Audio
from telegram.ext import (
    Application,
    ChatMemberHandler,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ── Config ──────────────────────────────────────────────────────────────────
BOT_TOKEN = "8841645025:AAHqG1wkyGSMecVdBPkUWXQnw-qDAuybJJE"
ADMIN_ID = 849557691  # Your Telegram user ID

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DOWNLOADS_DIR = BASE_DIR / "downloads"
CONFIG_FILE = DATA_DIR / "config.json"
SONGS_FILE = BASE_DIR / "songs.json"
HISTORY_FILE = DATA_DIR / "history.json"
PENDING_FILE = DATA_DIR / "pending.json"

DATA_DIR.mkdir(exist_ok=True)
DOWNLOADS_DIR.mkdir(exist_ok=True)

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE_DIR / "bot.log"),
    ],
)
logger = logging.getLogger(__name__)

# ── File Helpers ────────────────────────────────────────────────────────────

def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default or {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_config():
    return load_json(CONFIG_FILE, {})

def save_config(cfg):
    save_json(CONFIG_FILE, cfg)

def load_songs():
    return load_json(SONGS_FILE, [])

def load_history():
    return load_json(HISTORY_FILE, {"uploaded": [], "rejected": [], "last_upload": None})

def save_history(h):
    save_json(HISTORY_FILE, h)

def load_pending():
    return load_json(PENDING_FILE, {"songs": []})

def save_pending(p):
    save_json(PENDING_FILE, p)

# ── Song Selection ──────────────────────────────────────────────────────────

def pick_songs(count=2):
    """Pick `count` random songs that haven't been uploaded yet.
    Only picks SoundCloud songs (skips any remaining YouTube entries)."""
    songs = load_songs()
    history = load_history()
    uploaded_ids = set(history.get("uploaded", []))
    rejected_ids = set(history.get("rejected", []))

    # Only use SoundCloud songs
    available = [s for s in songs
                 if s["url"] not in uploaded_ids
                 and s["url"] not in rejected_ids
                 and s.get("source") != "youtube"]

    if len(available) < count:
        logger.warning(f"Only {len(available)} songs available, need {count}")
        # If we're running low, reset the rejected pool
        if len(available) < count and len(rejected_ids) > 0:
            logger.info("Resetting rejected pool to replenish available songs")
            available = [s for s in songs if s["url"] not in uploaded_ids]
            history["rejected"] = []
            save_history(history)

    if len(available) < count:
        # If we truly have fewer songs than needed, just return what we have
        random.shuffle(available)
        return available[:count]

    return random.sample(available, min(count, len(available)))

def mark_uploaded(song):
    history = load_history()
    url = song["url"]
    if url not in history["uploaded"]:
        history["uploaded"].append(url)
    history["last_upload"] = datetime.now().isoformat()
    save_history(history)

def mark_rejected(song):
    history = load_history()
    url = song["url"]
    if url not in history["rejected"]:
        history["rejected"].append(url)
    save_history(history)

# ── SoundCloud Download ──────────────────────────────────────

async def download_song(url, output_template=None):
    """
    Download a track from SoundCloud as audio (best quality mp3).
    Returns the path to the downloaded file or None on failure.
    Runs in executor to avoid blocking.
    """
    if output_template is None:
        output_template = str(DOWNLOADS_DIR / "%(title)s.%(ext)s")

    def _download():
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            # SoundCloud-specific: prefer ogv streams (higher quality)
            "extractor_args": {"soundcloud": {"formats": ["egostream", "hls"]}},
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                base = ydl.prepare_filename(info)
                mp3_path = Path(base).with_suffix(".mp3")
                if mp3_path.exists():
                    return str(mp3_path), info
                for f in DOWNLOADS_DIR.glob("*.mp3"):
                    return str(f), info
                return None, info
        except Exception as e:
            logger.error(f"Download failed for {url}: {e}")
            return None, None

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _download)
    return result

def sanitize_filename(name):
    """Remove characters not suitable for filenames."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()[:80]

# ── Bot Commands ────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ You're not authorized to use this bot.")
        return

    config = load_config()
    channel = config.get("channel_id") or config.get("channel_username") or "❌ Not set"
    history = load_history()
    songs = load_songs()
    uploaded_count = len(history.get("uploaded", []))
    rejected_count = len(history.get("rejected", []))

    msg = (
        "🎵 **Old School Persian Rap Bot** 🎵\n\n"
        f"📊 **Stats:**\n"
        f"• Total songs in database: {len(songs)}\n"
        f"• Uploaded so far: {uploaded_count}\n"
        f"• Rejected: {rejected_count}\n"
        f"• Remaining: {len(songs) - uploaded_count - rejected_count}\n"
        f"• Target channel: {channel}\n\n"
        "**Commands:**\n"
        "• `/setchannel <@username or -100xxx>` — Set upload channel\n"
        "• `/setdaily HH:MM` — Change daily upload time (UTC)\n"
        "• `/status` — Bot status & next upload time\n"
        "• `/skip` — Skip today's pending songs\n"
        "• `/showsongs` — Show all songs in database\n"
        "• `/addsong <url> <Artist - Title>` — Add a new song\n"
        "• `/runscheduled` — Run the daily task now (test)\n\n"
        f"⏰ **Daily upload:** 2 songs at {_get_schedule_time()}"
    )
    await update.message.reply_text(msg)

async def setchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the target channel."""
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: `/setchannel @channelusername` or `/setchannel -1001234567890`\n\n"
            "💡 The bot must be an **admin** in the channel!",
        )
        return

    channel_input = " ".join(context.args)
    config = load_config()

    # Determine if it's a username or numeric ID
    if channel_input.startswith("@") or channel_input.startswith("-100"):
        config["channel_id"] = channel_input
        config.pop("channel_username", None)
    else:
        config["channel_username"] = channel_input if channel_input.startswith("@") else f"@{channel_input}"
        config.pop("channel_id", None)

    save_config(config)
    await update.message.reply_text(f"✅ Channel set to: `{channel_input}`")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot status."""
    if update.effective_user.id != ADMIN_ID:
        return
    config = load_config()
    history = load_history()
    songs = load_songs()
    pending = load_pending()

    channel = config.get("channel_id") or config.get("channel_username") or "❌ Not set"
    uploaded_count = len(history.get("uploaded", []))
    rejected_count = len(history.get("rejected", []))
    last_upload = history.get("last_upload", "N/A")

    msg = (
        "📊 **Bot Status**\n\n"
        f"**Channel:** {channel}\n"
        f"**Total songs:** {len(songs)}\n"
        f"**Uploaded:** {uploaded_count}\n"
        f"**Rejected:** {rejected_count}\n"
        f"**Remaining:** {len(songs) - uploaded_count - rejected_count}\n"
        f"**Last upload:** {last_upload}\n"
        f"**Pending approval:** {len(pending.get('songs', []))} songs\n"
        f"**Next daily run:** {_get_schedule_time()}\n"
    )
    await update.message.reply_text(msg)

async def showsongs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all songs in the database."""
    if update.effective_user.id != ADMIN_ID:
        return
    songs = load_songs()
    history = load_history()
    uploaded = set(history.get("uploaded", []))
    rejected = set(history.get("rejected", []))

    msg_parts = [f"🎵 **All Songs ({len(songs)} total)**\n"]
    for i, s in enumerate(songs, 1):
        status_icon = "✅" if s["url"] in uploaded else "❌" if s["url"] in rejected else "⬜"
        msg_parts.append(f"{status_icon} {i}. **{s['artist']}** — {s['title']}")

    full_msg = "\n".join(msg_parts)

    # Telegram has a 4096 char limit, split if needed
    if len(full_msg) > 4000:
        for chunk in [full_msg[i:i+4000] for i in range(0, len(full_msg), 4000)]:
            await update.message.reply_text(chunk)
    else:
        await update.message.reply_text(full_msg)

async def addsong(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a new song to the database."""
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/addsong <soundcloud_url> <artist - title>`\n"
            "Example: `/addsong https://soundcloud.com/artist/track Moltafet - Track Name`"
        )
        return

    url = context.args[0]
    # The rest is artist - title
    name_parts = " ".join(context.args[1:])

    if not url.startswith("http"):
        await update.message.reply_text("❌ First argument must be a URL")
        return

    if "youtube.com" in url or "youtu.be" in url:
        await update.message.reply_text("❌ YouTube URLs are not supported. Use a SoundCloud link instead.")
        return

    if "soundcloud.com" not in url:
        await update.message.reply_text("❌ Only SoundCloud URLs are supported.")
        return

    if " - " in name_parts:
        artist, title = name_parts.split(" - ", 1)
    else:
        await update.message.reply_text("❌ Use format: `Artist - Song Title`")
        return

    songs = load_songs()
    # Check for duplicate URL
    if any(s["url"] == url for s in songs):
        await update.message.reply_text("⚠️ This song is already in the database!")
        return

    songs.append({"artist": artist.strip(), "title": title.strip(), "url": url, "source": "soundcloud"})
    save_json(SONGS_FILE, songs)

    await update.message.reply_text(f"✅ Added: **{artist}** — **{title}**\\n({len(songs)} songs total)")

async def skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip all pending songs and clear the approval queue."""
    if update.effective_user.id != ADMIN_ID:
        return
    pending = load_pending()
    songs = pending.get("songs", [])
    if not songs:
        await update.message.reply_text("No pending songs to skip.")
        return

    # Mark them as rejected so they won't be picked again immediately
    for entry in songs:
        song = entry.get("song", {})
        if song:
            mark_rejected(song)
        # Clean up downloaded file
        fpath = entry.get("file_path")
        if fpath and Path(fpath).exists():
            Path(fpath).unlink(missing_ok=True)

    save_pending({"songs": []})
    await update.message.reply_text(f"⏭ Skipped {len(songs)} pending songs.")

async def runscheduled(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger the daily task for testing."""
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("🔄 Running daily task now...")
    await daily_task(context)

async def setdaily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the daily schedule time."""
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: `/setdaily HH:MM` (UTC time, e.g. `/setdaily 12:00`)")
        return
    try:
        time_str = " ".join(context.args)
        hour, minute = map(int, time_str.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        config = load_config()
        config["schedule_hour"] = hour
        config["schedule_minute"] = minute
        save_config(config)

        # Reschedule the job
        job_queue = context.job_queue
        # Remove old daily jobs
        for job in job_queue.jobs():
            if job.name == "daily_song_task":
                job.schedule_removal()

        job_queue.run_daily(daily_task, time=dtime(hour=hour, minute=minute), name="daily_song_task")

        await update.message.reply_text(f"✅ Daily task rescheduled to `{hour:02d}:{minute:02d}` UTC")
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Invalid format. Use: `/setdaily HH:MM` (e.g. `/setdaily 12:00`)")

async def notify_startup(context: ContextTypes.DEFAULT_TYPE):
    """Send startup notification to admin."""
    config = load_config()
    channel = config.get("channel_id") or config.get("channel_username") or "❌ Not set"
    history = load_history()
    songs = load_songs()
    uploaded_count = len(history.get("uploaded", []))
    rejected_count = len(history.get("rejected", []))
    hour = config.get("schedule_hour", 10)
    minute = config.get("schedule_minute", 0)

    msg = (
        "🎵 **Persian Rap Bot is Online!** 🎵\n\n"
        f"**Channel:** {channel}\n"
        f"**Songs in DB:** {len(songs)}\n"
        f"**Uploaded:** {uploaded_count} | **Rejected:** {rejected_count}\n"
        f"**Daily upload:** {hour:02d}:{minute:02d} UTC (2 songs/day)\n\n"
        "Use commands:\n"
        "• `/setdaily HH:MM` — Change upload time\n"
        "• `/setchannel @channel` — Set channel\n"
        "• `/showsongs` — List all songs\n"
        "• `/addsong <url> <Artist - Title>` — Add songs"
    )
    try:
        await context.bot.send_message(ADMIN_ID, msg)
    except Exception as e:
        logger.error(f"Startup notification failed: {e}")

# ── Forwarded Message Handler ────────────────────────────────────────────

async def handle_forwarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """When admin forwards a message from the channel, extract the channel ID."""
    if update.effective_user.id != ADMIN_ID:
        return

    msg = update.message
    if not msg or not msg.forward_from_chat:
        return

    fwd_chat = msg.forward_from_chat
    if fwd_chat.type != "channel":
        await msg.reply_text("❌ That's not a channel! Forward a message from the target channel.")
        return

    chat_id = fwd_chat.id
    chat_title = fwd_chat.title or "Unknown Channel"

    config = load_config()
    config["channel_id"] = str(chat_id)
    config["channel_name"] = chat_title
    save_config(config)

    logger.info(f"Channel set via forward: {chat_title} (ID: {chat_id})")

    await msg.reply_text(
        f"✅ **Channel configured!**\n\n"
        f"**Name:** {chat_title}\n"
        f"**ID:** `{chat_id}`\n\n"
        f"Ready to upload songs! Use `/runscheduled` to test.",
    )

def _get_schedule_time():
    """Get the configured schedule time as a string."""
    config = load_config()
    hour = config.get("schedule_hour", 10)
    minute = config.get("schedule_minute", 0)
    return f"{hour:02d}:{minute:02d} UTC"

# ── Main Daily Task ─────────────────────────────────────────────────────────

async def daily_task(context: ContextTypes.DEFAULT_TYPE):
    """
    Main daily task:
    1. Pick 2 random songs
    2. Download them
    3. Send to admin for approval
    """
    logger.info("=== Starting daily song selection ===")
    config = load_config()
    channel = config.get("channel_id") or config.get("channel_username")
    if not channel:
        logger.error("No channel configured! Use /setchannel")
        # Try to notify admin
        try:
            await context.bot.send_message(
                ADMIN_ID,
                "⚠️ **Daily Task Failed**\nNo target channel set!\nUse `/setchannel` to configure it.",
            )
        except Exception:
            pass
        return

    # Check if there are still pending songs
    pending = load_pending()
    if pending.get("songs"):
        logger.warning("There are still pending songs from a previous run. Skipping today.")
        try:
            await context.bot.send_message(
                ADMIN_ID,
                "⚠️ There are still songs pending approval from a previous run.\n"
                "Approve or reject them first, or use `/skip` to clear.",
            )
        except Exception:
            pass
        return

    # Pick 2 songs
    selected = pick_songs(2)
    if not selected:
        logger.warning("No songs available to pick!")
        try:
            await context.bot.send_message(
                ADMIN_ID,
                "🎵 **No songs left!**\n"
                "All songs in the database have been uploaded or rejected.\n"
                "Add more songs with `/addsong <url> <Artist - Title>`",
            )
        except Exception:
            pass
        return

    logger.info(f"Selected {len(selected)} songs: {[s['title'] for s in selected]}")

    # Notify admin that we're starting
    await context.bot.send_message(
        ADMIN_ID,
        f"🎵 **Daily Song Selection**\n\n"
        f"Selected **{len(selected)} songs** for today.\n"
        f"Downloading now... ⏳",
    )

    # Download each song
    pending_entries = []
    for i, song in enumerate(selected):
        try:
            sanitized_title = sanitize_filename(f"{song['artist']} - {song['title']}")
            output_template = str(DOWNLOADS_DIR / f"{sanitized_title}_%(id)s.%(ext)s")

            await context.bot.send_message(
                ADMIN_ID,
                f"⏬ **Downloading ({i+1}/{len(selected)}):**\n"
                f"**{song['artist']}** — **{song['title']}**",
            )

            result = await download_song(song["url"], output_template)
            if not result or not result[0]:
                logger.error(f"Failed to download: {song['url']}")
                await context.bot.send_message(
                    ADMIN_ID,
                    f"❌ Failed to download: **{song['artist']}** — **{song['title']}**\n"
                    f"<code>{song['url']}</code>\nSkipping this song.",
                )
                mark_rejected(song)
                continue

            file_path, info = result
            logger.info(f"Downloaded: {file_path}")

            pending_entries.append({
                "song": song,
                "file_path": file_path,
                "title_display": f"{song['artist']} — {song['title']}",
            })

        except Exception as e:
            logger.error(f"Error processing {song['url']}: {e}")
            await context.bot.send_message(
                ADMIN_ID,
                f"❌ Error: **{song['artist']}** — **{song['title']}**\n<code>{str(e)[:200]}</code>",
            )
            mark_rejected(song)
            continue

    if not pending_entries:
        await context.bot.send_message(
            ADMIN_ID,
            "❌ All downloads failed for today. Check the logs.",
        )
        return

    # Save pending state
    save_pending({"songs": pending_entries})

    # Send each song to admin for approval
    for entry in pending_entries:
        await send_for_approval(context, entry)

async def send_for_approval(context: ContextTypes.DEFAULT_TYPE, entry):
    """Send a song to admin for approval with inline buttons."""
    song = entry["song"]
    file_path = entry["file_path"]
    title_display = entry["title_display"]
    file_size = Path(file_path).stat().st_size

    # Generate unique action IDs
    safe_url = song["url"].replace("https://", "").replace("/", "_")[:30]
    approve_data = f"approve_{safe_url}"
    reject_data = f"reject_{safe_url}"

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=approve_data),
            InlineKeyboardButton("❌ Reject", callback_data=reject_data),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    caption = (
        f"🎵 **New Song for Approval**\n\n"
        f"**Artist:** {song['artist']}\n"
        f"**Title:** {song['title']}\n"
        f"**Size:** {file_size / 1024 / 1024:.1f} MB\n"
        f"**Source:** [YouTube]({song['url']})\n\n"
        f"_Approve to upload to channel, or reject to skip._"
    )

    try:
        with open(file_path, "rb") as f:
            await context.bot.send_audio(
                chat_id=ADMIN_ID,
                audio=f,
                caption=caption,
                parse_mode="Markdown",
                reply_markup=reply_markup,
                title=song["title"],
                performer=song["artist"],
            )
        logger.info(f"Sent {title_display} to admin for approval")
    except Exception as e:
        logger.error(f"Failed to send audio to admin: {e}")
        # Fall back to just sending a link
        await context.bot.send_message(
            ADMIN_ID,
            f"⚠️ Couldn't send audio file (too large?)\n"
            f"**{title_display}**\n"
            f"Source: {song['url']}\n\n"
            f"Use inline buttons to approve/reject anyway:",
            reply_markup=reply_markup,
        )

# ── Callback Handler (Approval/Rejection) ───────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses (approve/reject)."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    if user.id != ADMIN_ID:
        await query.answer("⛔ You're not authorized!", show_alert=True)
        return

    data = query.data
    pending = load_pending()
    songs_pending = pending.get("songs", [])

    if not songs_pending:
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n_⚠️ This song is no longer pending._",
            parse_mode="Markdown",
        )
        return

    # Find which song this callback corresponds to
    action, url_suffix = data.split("_", 1)
    matching_entry = None
    for entry in songs_pending:
        song_url = entry["song"]["url"].replace("https://", "").replace("/", "_")[:30]
        # Compare the URL suffix
        if url_suffix in song_url or song_url in url_suffix:
            matching_entry = entry
            break

    if not matching_entry:
        await query.answer("Song not found in pending list.", show_alert=True)
        return

    song = matching_entry["song"]
    file_path = matching_entry.get("file_path")

    if action == "approve":
        await handle_approve(query, context, matching_entry, pending, songs_pending)
    elif action == "reject":
        await handle_reject(query, context, matching_entry, pending, songs_pending)

# ── Chat Member Handler (detect when added to channel) ─────────────────────

async def chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detect when the bot is added to a channel."""
    chat_member = update.my_chat_member
    chat = chat_member.chat

    # Check if bot was added to a channel
    if chat.type in ("channel", "supergroup"):
        new_status = chat_member.new_chat_member.status
        if new_status in ("administrator", "member"):
            config = load_config()
            # Save the channel ID
            if chat.type == "channel":
                chat_id = chat.id
                chat_title = chat.title or "Unknown Channel"
                config["channel_id"] = str(chat_id)
                config["channel_name"] = chat_title
                save_config(config)

                logger.info(f"Bot added to channel: {chat_title} (ID: {chat_id})")

                # Notify admin
                await context.bot.send_message(
                    ADMIN_ID,
                    f"✅ **Bot added to channel!**\n\n"
                    f"**Channel:** {chat_title}\n"
                    f"**ID:** `{chat_id}`\n\n"
                    f"Channel has been auto-configured. Use `/runscheduled` to test the daily task.",
                )

async def handle_approve(query, context, entry, pending, songs_pending):
    """Upload approved song to channel."""
    song = entry["song"]
    file_path = entry.get("file_path")
    title_display = entry["title_display"]

    config = load_config()
    channel = config.get("channel_id") or config.get("channel_username")

    if not channel:
        await query.edit_message_caption(
            caption=f"⚠️ No channel configured! Use /setchannel first.\n\n**{song['artist']}** — **{song['title']}**",
            parse_mode="Markdown",
        )
        return

    await query.edit_message_caption(
        caption=f"⬆️ **Uploading...**\n\n**{song['artist']}** — **{song['title']}**",
        parse_mode="Markdown",
    )

    try:
        channel_identifier = channel
        # Determine if it's a numeric ID or username
        if channel.startswith("@"):
            pass  # It's a username
        elif channel.startswith("-100"):
            # It's a numeric ID as string
            channel_identifier = int(channel)
        elif channel.isdigit() or (channel.startswith("-") and channel[1:].isdigit()):
            channel_identifier = int(channel)
        else:
            channel_identifier = channel

        if file_path and Path(file_path).exists():
            with open(file_path, "rb") as f:
                sent = await context.bot.send_audio(
                    chat_id=channel_identifier,
                    audio=f,
                    title=song["title"],
                    performer=song["artist"],
                    caption=f"🎵 {song['artist']} — {song['title']}\n#persianrap #oldschool",
                )

            logger.info(f"Uploaded {title_display} to channel {channel}")

            await query.edit_message_caption(
                caption=f"✅ **Uploaded!**\n\n**{song['artist']}** — **{song['title']}**\n\nSent to channel ✅",
                parse_mode="Markdown",
            )

            # Mark as uploaded
            mark_uploaded(song)

            # Clean up temp file
            Path(file_path).unlink(missing_ok=True)

        else:
            # File doesn't exist, try to re-download or just inform
            await query.edit_message_caption(
                caption=f"⚠️ File not found on disk. The song was already approved via link.\n**{title_display}**\n\nMarking as uploaded anyway.",
                parse_mode="Markdown",
            )
            mark_uploaded(song)

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        await query.edit_message_caption(
            caption=f"❌ **Upload failed!**\n\n**{song['artist']}** — **{song['title']}**\nError: <code>{str(e)[:200]}</code>\n\nTry again or use /setchannel to check the channel.",
            parse_mode="Markdown",
        )

    # Remove from pending
    _remove_from_pending(pending, songs_pending, entry)

async def handle_reject(query, context, entry, pending, songs_pending):
    """Reject a song."""
    song = entry["song"]
    file_path = entry.get("file_path")
    title_display = entry["title_display"]

    mark_rejected(song)

    # Clean up file
    if file_path and Path(file_path).exists():
        Path(file_path).unlink(missing_ok=True)

    await query.edit_message_caption(
        caption=f"❌ **Rejected**\n\n**{song['artist']}** — **{song['title']}**\n\n_Won't be picked again._",
        parse_mode="Markdown",
    )

    logger.info(f"Rejected: {title_display}")

    # Remove from pending
    _remove_from_pending(pending, songs_pending, entry)

def _remove_from_pending(pending, songs_pending, entry):
    """Remove an entry from pending list and save."""
    if entry in songs_pending:
        songs_pending.remove(entry)
    pending["songs"] = songs_pending
    save_pending(pending)

    # If all pending songs are handled, notify
    if not songs_pending:
        try:
            # We can't use async here directly, but this is called from async context
            pass
        except Exception:
            pass

# ── Error Handler ───────────────────────────────────────────────────────────

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors."""
    logger.error(f"Update {update} caused error {context.error}")

# ── Main ────────────────────────────────────────────────────────────────────

def main():
    """Start the bot."""
    # Create application
    app = Application.builder().token(BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setchannel", setchannel))
    app.add_handler(CommandHandler("setdaily", setdaily))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("skip", skip))
    app.add_handler(CommandHandler("showsongs", showsongs))
    app.add_handler(CommandHandler("addsong", addsong))
    app.add_handler(CommandHandler("runscheduled", runscheduled))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(ChatMemberHandler(chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))

    # Handle forwarded messages from channels (to auto-detect channel ID)
    app.add_handler(MessageHandler(filters.FORWARDED & filters.User(ADMIN_ID), handle_forwarded))

    # Error handler
    app.add_error_handler(error_handler)

    # Schedule daily job
    config = load_config()
    hour = config.get("schedule_hour", 10)
    minute = config.get("schedule_minute", 0)

    job_queue = app.job_queue
    job_queue.run_daily(daily_task, time=dtime(hour=hour, minute=minute), name="daily_song_task")

    logger.info(f"Bot started. Daily task scheduled at {hour:02d}:{minute:02d} UTC")
    logger.info(f"Admin ID: {ADMIN_ID}")

    # Send startup notification (after bot is ready)
    # Use a one-time job that fires in 3 seconds
    job_queue.run_once(notify_startup, when=3, name="startup_notif")

    # Resend any pending songs from previous run
    pending = load_pending()
    if pending.get("songs"):
        logger.info(f"Found {len(pending['songs'])} pending songs from previous run. Re-sending for approval.")
        job_queue.run_once(
            lambda ctx: asyncio.gather(*[send_for_approval(ctx, e) for e in pending["songs"]]),
            when=5,
            name="resend_pending",
        )

    # Run the bot (polling)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
