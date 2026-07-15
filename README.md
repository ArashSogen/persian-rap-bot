# 🎵 Persian Old School Rap Bot / ربات رپ فارسی قدیمی

A Telegram bot that curates and posts classic Persian rap songs to a Telegram channel automatically. Built with `python-telegram-bot` v20+, APScheduler, yt-dlp, and Flask. Ready to deploy on **Railway**.

ربات تلگرام برای مدیریت و انتشار خودکار آهنگ‌های رپ فارسی قدیمی در کانال تلگرام. ساخته شده با `python-telegram-bot` v20+، APScheduler، yt-dlp و Flask. آماده استقرار در **Railway**.

---

## Features / قابلیت‌ها

- **Daily scheduling** — picks 2 random songs each day and sends them to admin for approval / زمان‌بندی روزانه — ۲ آهنگ تصادفی انتخاب و برای تأیید به ادمین ارسال می‌کند
- **Admin approval flow** — inline Approve/Reject buttons / جریان تأیید ادمین — دکمه‌های تأیید/رد درون‌خطی
- **SoundCloud & YouTube download** — via yt-dlp / دانلود از ساندکلود و یوتیوب با yt-dlp
- **Channel publishing** — approved songs auto-posted to channel / انتشار خودکار آهنگ‌های تأیید شده در کانال
- **Duplicate tracking** — avoids re-uploading / جلوگیری از انتشار تکراری
- **Railway-ready** — health check endpoint on port 8080 / آماده استقرار در Railway با endpoint سلامت روی پورت 8080

---

## Commands / دستورات

| Command | Description / توضیحات |
|---------|----------------------|
| `/start` | Welcome + stats / خوش‌آمدگویی و آمار |
| `/setchannel @channel` | Set target channel / تنظیم کانال مقصد |
| `/setdaily HH:MM` | Set daily upload time (UTC) / تنظیم زمان انتشار روزانه (UTC) |
| `/status` | Bot health & pending count / وضعیت ربات و تعداد در انتظار |
| `/showsongs` | List all songs / نمایش همه آهنگ‌ها |
| `/addsong <url> <Artist - Title>` | Add a new song / اضافه کردن آهنگ جدید |
| `/skip` | Clear pending songs / پاک کردن آهنگ‌های در انتظار |
| `/runscheduled` | Manually trigger daily task / اجرای دستی وظیفه روزانه |

---

## Quick Deploy (Railway) / استقرار سریع در Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/your-template-url?referralCode=your-ref)

### Manual steps / مراحل دستی:

1. **Fork or clone** this repo / این مخزن را fork یا clone کنید
2. **Create a Railway project** from the repo / یک پروژه Railway از مخزن بسازید
3. **Set environment variables** in Railway dashboard / متغیرهای محیطی را در داشبورد Railway تنظیم کنید:

   ```
   BOT_TOKEN=your_bot_token_from_@BotFather
   ADMIN_ID=your_telegram_user_id
   CHANNEL_ID=@your_channel (optional, can be set via /setchannel)
   DAILY_TIME=12:00 (optional, default 12:00 UTC)
   ```

4. **Deploy!** Railway auto-detects `railway.json` / Railway به طور خودکار railway.json را تشخیص می‌دهد

### Get your ADMIN_ID / دریافت ADMIN_ID:

Send a message to [@userinfobot](https://t.me/userinfobot) on Telegram to get your user ID.

---

## Local Development / توسعه محلی

```bash
# Clone / کلون کنید
git clone https://github.com/payrogamer1-del/persian-rap-bot.git
cd persian-rap-bot

# Install dependencies / نصب وابستگی‌ها
pip install -r requirements.txt

# Install ffmpeg (required for audio processing)
# Ubuntu/Debian: sudo apt install ffmpeg
# macOS: brew install ffmpeg

# Set environment variables / تنظیم متغیرهای محیطی
export BOT_TOKEN=your_bot_token
export ADMIN_ID=your_user_id
export CHANNEL_ID=@your_channel

# Run / اجرا
python bot.py
```

---

## Project Structure / ساختار پروژه

```
persian-rap-bot/
├── bot.py              # Main bot application / برنامه اصلی ربات
├── songs.json          # Song database / پایگاه داده آهنگ‌ها
├── requirements.txt    # Python dependencies / وابستگی‌های پایتون
├── Dockerfile          # Docker image for deployment / داکرفایل برای استقرار
├── railway.json        # Railway deployment config / تنظیمات استقرار Railway
├── Procfile            # Process type declaration / اعلام نوع فرآیند
├── .env.example        # Environment variables template / نمونه متغیرهای محیطی
└── README.md           # This file / این فایل
```

## Runtime directories (auto-created) / دایرکتوری‌های زمان اجرا (خودکار ساخته می‌شوند)

```
data/
├── config.json     # Channel & schedule config / تنظیمات کانال و زمان‌بندی
├── history.json    # Uploaded/rejected tracking / تاریخچه آپلود/رد شده
└── pending.json    # Songs awaiting approval / آهنگ‌های در انتظار تأیید
downloads/          # Temp MP3 files / فایل‌های موقت MP3
```

---

## Requirements / نیازمندی‌ها

- Python 3.11+
- ffmpeg (for audio processing / برای پردازش صدا)
- Telegram Bot Token from [@BotFather](https://t.me/BotFather)

---

## License / مجوز

MIT
