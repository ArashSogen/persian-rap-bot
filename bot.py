#!/usr/bin/env python3
"""
Persian Old School Rap Bot — Telegram Bot for curating Persian rap songs.

Downloads songs from SoundCloud/YouTube via yt-dlp, sends to admin for approval,
and publishes approved songs to a Telegram channel on a daily schedule.

Designed for Railway deployment with Flask health check.
"""

import json
import logging
import os
import random
import subprocess
import sys
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, jsonify
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ── Configuration ──────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
DAILY_TIME = os.environ.get("DAILY_TIME", "12:00")

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DOWNLOADS_DIR = BASE_DIR / "downloads"
SONGS_FILE = BASE_DIR / "songs.json"

CONFIG_FILE = DATA_DIR / "config.json"
HISTORY_FILE = DATA_DIR / "history.json"
PENDING_FILE = DATA_DIR / "pending.json"

DATA_DIR.mkdir(exist_ok=True)
DOWNLOADS_DIR.mkdir(exist_ok=True)

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Data helpers ───────────────────────────────────────────────────────────────


def load_json(path, default=None):
    """Load JSON from file, returning default on error."""
    if default is None:
        default = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    """Save JSON to file atomically."""
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def load_songs():
    """Load song database from songs.json."""
    return load_json(SONGS_FILE, [])


def load_config():
    """Load persistent config (channel, daily_time)."""
    cfg = load_json(CONFIG_FILE)
    if "channel_id" not in cfg:
        cfg["channel_id"] = CHANNEL_ID
    if "daily_time" not in cfg:
        cfg["daily_time"] = DAILY_TIME
    return cfg


def save_config(cfg):
    save_json(CONFIG_FILE, cfg)


def load_history():
    """Load uploaded/rejected history."""
    return load_json(HISTORY_FILE, {"uploaded": [], "rejected": []})


def save_history(history):
    save_json(HISTORY_FILE, history)


def load_pending():
    """Load songs pending admin approval."""
    return load_json(PENDING_FILE, {"songs": []})


def save_pending(pending):
    save_json(PENDING_FILE, pending)


# ── Song selection ─────────────────────────────────────────────────────────────


def get_available_songs(count=2):
    """Pick `count` random songs not yet uploaded or rejected."""
    songs = load_songs()
    history = load_history()
    uploaded_ids = set(history.get("uploaded", []))
    rejected_ids = set(history.get("rejected", []))

    available = [
        s
        for s in songs
        if s["url"] not in uploaded_ids and s["url"] not in rejected_ids
    ]

    if not available:
        return []

    return random.sample(available, min(count, len(available)))


# ── Download helpers ───────────────────────────────────────────────────────────


def sanitize_filename(text):
    """Remove characters unsuitable for filenames."""
    return "".join(c if c.isalnum() or c in " _-." else "_" for c in text)


def download_song(song):
    """Download audio from SoundCloud/YouTube using yt-dlp.

    Returns path to downloaded MP3 or None on failure.
    """
    artist = song.get("artist", "unknown")
    title = song.get("title", "unknown")
    url = song.get("url", "")

    safe_name = sanitize_filename(f"{artist}_{title}")
    outtmpl = str(DOWNLOADS_DIR / f"{safe_name}.%(ext)s")

    try:
        subprocess.run(
            [
                "yt-dlp",
                "-x",  # extract audio
                "--audio-format", "mp3",
                "--audio-quality", "192",
                "-o", outtmpl,
                "--no-playlist",
                "--embed-thumbnail",
                "--add-metadata",
                "--no-warnings",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error("yt-dlp failed for %s: %s", url, e.stderr[:500])
        return None
    except FileNotFoundError:
        logger.error("yt-dlp not installed!")
        return None

    # Find the downloaded file
    for f in DOWNLOADS_DIR.iterdir():
        if f.stem == safe_name and f.suffix in (".mp3", ".m4a", ".webm", ".opus"):
            return str(f)

    logger.warning("Downloaded file not found for %s", safe_name)
    return None


def cleanup_download(file_path):
    """Remove a downloaded file."""
    if file_path and Path(file_path).exists():
        Path(file_path).unlink(missing_ok=True)


# ── Telegram Bot handlers ──────────────────────────────────────────────────────


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message with stats."""
    songs = load_songs()
    history = load_history()
    uploaded = len(history.get("uploaded", []))
    rejected = len(history.get("rejected", []))
    remaining = len(songs) - uploaded - rejected

    text = (
        "🎵 *Persian Old School Rap Bot* 🎵\n\n"
        "I curate and post classic Persian rap songs to your channel.\n\n"
        f"📊 *Stats:*\n"
        f"• Total songs in database: {len(songs)}\n"
        f"• Uploaded: {uploaded}\n"
        f"• Rejected/Skipped: {rejected}\n"
        f"• Remaining: {remaining}\n\n"
        "*Commands:*\n"
        "/setchannel @channel - Set target channel\n"
        "/setdaily HH:MM - Set daily upload time (UTC)\n"
        "/status - Bot health & pending info\n"
        "/addsong <url> <Artist - Title> - Add a song\n"
        "/showsongs - List all songs\n"
        "/skip - Clear pending songs\n"
        "/runscheduled - Trigger daily task now"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def set_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the target Telegram channel for uploads."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Only the admin can use this command.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /setchannel @channelusername or -100xxxxxxxxxx"
        )
        return

    channel = context.args[0]
    cfg = load_config()
    cfg["channel_id"] = channel
    save_config(cfg)

    await update.message.reply_text(f"✅ Channel set to: {channel}")


async def set_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change the daily upload schedule time (UTC)."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Only the admin can use this command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /setdaily HH:MM (UTC)")
        return

    time_str = context.args[0]
    try:
        datetime.strptime(time_str, "%H:%M")
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid format. Use HH:MM (e.g., 12:00)"
        )
        return

    cfg = load_config()
    cfg["daily_time"] = time_str
    save_config(cfg)

    # Reschedule the daily job
    schedule_daily_job(context.application, time_str)

    await update.message.reply_text(f"✅ Daily upload time set to: {time_str} UTC")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot status and pending info."""
    cfg = load_config()
    pending = load_pending()
    songs = load_songs()
    history = load_history()

    uploaded = len(history.get("uploaded", []))
    rejected = len(history.get("rejected", []))
    remaining = len(songs) - uploaded - rejected

    text = (
        "📡 *Bot Status*\n\n"
        f"• Channel: {cfg.get('channel_id', 'Not set')}\n"
        f"• Daily time: {cfg.get('daily_time', '12:00')} UTC\n"
        f"• Pending approval: {len(pending.get('songs', []))}\n"
        f"• Songs uploaded: {uploaded}\n"
        f"• Songs rejected: {rejected}\n"
        f"• Songs remaining: {remaining}\n"
        f"• Total in DB: {len(songs)}\n"
    )

    # Show next scheduled run
    for job in context.application.job_queue.jobs():
        if job.name == "daily_upload":
            next_run = job.next_t
            if next_run:
                text += f"• Next run: {next_run.strftime('%Y-%m-%d %H:%M UTC')}\n"
            break

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all pending songs."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Only the admin can use this command.")
        return

    pending = load_pending()
    for item in pending.get("songs", []):
        cleanup_download(item.get("file_path"))
    save_pending({"songs": []})

    await update.message.reply_text("🗑️ All pending songs cleared.")


async def show_songs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all songs with their status."""
    songs = load_songs()
    history = load_history()
    uploaded_ids = set(history.get("uploaded", []))
    rejected_ids = set(history.get("rejected", []))

    if not songs:
        await update.message.reply_text("📭 No songs in database.")
        return

    lines = ["*Song Database:*\n"]
    for i, s in enumerate(songs, 1):
        status_emoji = "✅" if s["url"] in uploaded_ids else (
            "❌" if s["url"] in rejected_ids else "⏳"
        )
        lines.append(
            f"{i}. {status_emoji} {s['artist']} — {s['title']}"
        )

    # Split into chunks if needed (Telegram 4096 char limit)
    text = "\n".join(lines)
    if len(text) <= 4096:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    else:
        for i in range(0, len(text), 4000):
            await update.message.reply_text(
                text[i : i + 4000], parse_mode=ParseMode.MARKDOWN
            )


async def add_song(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a new song to the database."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Only the admin can use this command.")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /addsong <url> <Artist - Title>\n"
            "Example: /addsong https://soundcloud.com/... Hichkas - Ekhtelaf"
        )
        return

    url = context.args[0]
    # The rest is "Artist - Title"
    title_text = " ".join(context.args[1:])
    if " - " not in title_text:
        await update.message.reply_text(
            "Please use format: `Artist - Title`\n"
            "Example: /addsong <url> Hichkas - Ekhtelaf"
        )
        return

    artist, title = title_text.split(" - ", 1)

    songs = load_songs()
    # Check for duplicates
    if any(s["url"] == url for s in songs):
        await update.message.reply_text("⚠️ This song URL is already in the database.")
        return

    new_song = {
        "artist": artist.strip(),
        "title": title.strip(),
        "url": url,
        "source": "soundcloud" if "soundcloud.com" in url else "youtube",
    }
    songs.append(new_song)
    save_json(SONGS_FILE, songs)

    await update.message.reply_text(
        f"✅ Added: *{artist}* — *{title}*\n"
        f"Source: {new_song['source']}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def run_scheduled(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger the daily upload task."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Only the admin can use this command.")
        return

    await update.message.reply_text("🔄 Running scheduled upload now...")
    await daily_upload(context.application)


# ── Daily upload job ────────────────────────────────────────────────────────────


async def daily_upload(app: Application):
    """Main daily job: pick songs, download, send to admin for approval."""
    cfg = load_config()
    channel_id = cfg.get("channel_id", "")

    if not channel_id:
        logger.warning("Daily upload: No channel configured.")
        return

    songs = get_available_songs(2)
    if not songs:
        logger.info("Daily upload: No new songs available.")
        # Notify admin
        try:
            await app.bot.send_message(
                ADMIN_ID,
                "📭 No new songs available to upload. All songs have been used.",
            )
        except Exception:
            pass
        return

    pending = load_pending()
    pending_songs = pending.get("songs", [])

    for song in songs:
        # Download the song
        file_path = download_song(song)
        if not file_path:
            logger.error("Failed to download: %s — %s", song["artist"], song["title"])
            try:
                await app.bot.send_message(
                    ADMIN_ID,
                    f"❌ Failed to download: *{song['artist']}* — *{song['title']}*\n"
                    f"URL: {song['url']}",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            continue

        title_display = f"{song['artist']} — {song['title']}"
        pending_songs.append(
            {
                "song": song,
                "file_path": file_path,
                "title_display": title_display,
            }
        )

    save_pending({"songs": pending_songs})

    # Send each pending song to admin for approval
    for item in pending_songs:
        await send_for_approval(app, item)


async def send_for_approval(app: Application, item: dict):
    """Send a downloaded song to admin with Approve/Reject buttons."""
    song = item["song"]
    file_path = item["file_path"]
    title_display = item["title_display"]

    # Build callback data (must be under 64 bytes)
    safe_id = song["url"].replace("https://", "").replace("/", "_")[:30]
    approve_data = f"approve_{safe_id}"
    reject_data = f"reject_{safe_id}"

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=approve_data),
            InlineKeyboardButton("❌ Reject", callback_data=reject_data),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    caption = (
        f"🎵 *New song for approval*\n\n"
        f"*{title_display}*\n"
        f"Source: {song.get('url', 'N/A')}"
    )

    try:
        with open(file_path, "rb") as audio:
            await app.bot.send_audio(
                chat_id=ADMIN_ID,
                audio=audio,
                title=song["title"],
                performer=song["artist"],
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup,
            )
    except Exception as e:
        logger.error("Failed to send audio for approval: %s", e)


async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Approve/Reject button callbacks."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if user_id != ADMIN_ID:
        await query.edit_message_caption(
            caption="⛔ Only the admin can approve or reject songs."
        )
        return

    data = query.data
    action = data.split("_", 1)[0]
    # Reconstruct safe_id from the rest
    safe_id = data[len(action) + 1 :]

    # Find the matching pending song
    pending = load_pending()
    matched_item = None
    for item in pending.get("songs", []):
        song_url = item["song"]["url"]
        item_safe_id = song_url.replace("https://", "").replace("/", "_")[:30]
        if item_safe_id == safe_id:
            matched_item = item
            break

    if not matched_item:
        await query.edit_message_caption(
            caption="⚠️ This song is no longer in the pending list."
        )
        return

    song = matched_item["song"]
    history = load_history()

    if action == "approve":
        # Upload to channel
        cfg = load_config()
        channel_id = cfg.get("channel_id", "")
        if not channel_id:
            await query.edit_message_caption(
                caption="❌ No channel configured. Use /setchannel first."
            )
            return

        file_path = matched_item.get("file_path", "")
        caption = f"🎵 *{song['artist']}* — *{song['title']}*"

        try:
            with open(file_path, "rb") as audio:
                msg = await context.bot.send_audio(
                    chat_id=channel_id,
                    audio=audio,
                    title=song["title"],
                    performer=song["artist"],
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN,
                )
            history.setdefault("uploaded", []).append(song["url"])
            save_history(history)

            # Remove from pending
            pending["songs"] = [
                i for i in pending["songs"]
                if i["song"]["url"] != song["url"]
            ]
            save_pending(pending)

            # Clean up file
            cleanup_download(file_path)

            await query.edit_message_caption(
                caption=f"✅ *Approved and uploaded!*\n{song['artist']} — {song['title']}\n\n"
                        f"View in channel: {channel_id}",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error("Failed to upload to channel: %s", e)
            await query.edit_message_caption(
                caption=f"❌ Failed to upload to channel: {e}"
            )

    elif action == "reject":
        history.setdefault("rejected", []).append(song["url"])
        save_history(history)

        # Remove from pending
        pending["songs"] = [
            i for i in pending["songs"]
            if i["song"]["url"] != song["url"]
        ]
        save_pending(pending)

        # Clean up file
        cleanup_download(matched_item.get("file_path", ""))

        await query.edit_message_caption(
            caption=f"❌ *Rejected:* {song['artist']} — {song['title']}",
            parse_mode=ParseMode.MARKDOWN,
        )


# ── Scheduling ─────────────────────────────────────────────────────────────────


def schedule_daily_job(app: Application, time_str: str):
    """Schedule or reschedule the daily upload job."""
    job_queue = app.job_queue
    if not job_queue:
        return

    # Remove existing daily job
    for job in job_queue.jobs():
        if job.name == "daily_upload":
            job.schedule_removal()

    try:
        hour, minute = map(int, time_str.split(":"))
    except (ValueError, AttributeError):
        hour, minute = 12, 0

    job_queue.run_daily(
        daily_upload,
        time=time(hour=hour, minute=minute),
        name="daily_upload",
    )
    logger.info("Daily upload scheduled at %s UTC", time_str)


# ── Flask health check ─────────────────────────────────────────────────────────


app = Flask(__name__)


@app.route("/")
@app.route("/health")
def health():
    """Railway health check endpoint."""
    songs = load_songs()
    history = load_history()
    return jsonify(
        {
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat(),
            "songs_total": len(songs),
            "uploaded": len(history.get("uploaded", [])),
            "rejected": len(history.get("rejected", [])),
        }
    )


# ── Main ───────────────────────────────────────────────────────────────────────


def main():
    """Start the bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable not set!")
        sys.exit(1)

    if not ADMIN_ID:
        logger.error("ADMIN_ID environment variable not set!")
        sys.exit(1)

    # Create the Application
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(lambda app: schedule_daily_job(app, DAILY_TIME))
        .build()
    )

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setchannel", set_channel))
    application.add_handler(CommandHandler("setdaily", set_daily))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("skip", skip))
    application.add_handler(CommandHandler("showsongs", show_songs))
    application.add_handler(CommandHandler("addsong", add_song))
    application.add_handler(CommandHandler("runscheduled", run_scheduled))

    # Register callback handler for Approve/Reject buttons
    application.add_handler(
        CallbackQueryHandler(handle_approval, pattern="^(approve_|reject_)")
    )

    # Run the bot (starts polling in a thread, Flask runs separately)
    # We use run_polling in a separate thread via the Flask app
    from threading import Thread

    def run_bot():
        application.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

    bot_thread = Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("Bot started polling.")

    # Run Flask for Railway health checks
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
