# Azure A.R.O.N.A

A self-hosted Discord bot for Blue Archive fans. Tracks new student announcements from the JP Twitter/X account, monitors EN gacha banner notices, and provides in-Discord skill lookups for all students.

---

## Features

- 📣 **Auto-posts new JP student introductions** from [@Blue_ArchiveJP](https://x.com/Blue_ArchiveJP) to all configured servers
- 📢 **Weekly EN gacha banner notices** from [@EN_BlueArchive](https://x.com/EN_BlueArchive) posted every Friday
- 🎴 **Student skill lookups** — EX, Normal, Enhanced, and Sub skills with upgrade info
- 📋 **Current banner summary** — shows active banners with images on demand
- 🗄️ **SQLite persistence** — tracks seen posts to avoid duplicates across restarts
- 🔔 **Developer DM reports** — daily task summaries and error alerts sent to the bot owner

---

## Commands

| Command | Description | Access |
|---|---|---|
| `/setup` | Set the channel for bot posts | Admin |
| `/enable` | Enable posting in this server | Admin |
| `/disable` | Disable posting in this server | Admin |
| `/status` | Show current bot config for this server | Everyone |
| `/student` | Show a student's full skill kit | Everyone |
| `/ex` | Show a student's EX skill | Everyone |
| `/ns` | Show a student's Normal skill | Everyone |
| `/enhanced` | Show a student's Enhanced skill | Everyone |
| `/sub` | Show a student's Sub skill | Everyone |
| `/gachapreview` | Show upcoming EN gacha notices from DB | Everyone |
| `/currentbanner` | Show banners posted in the last 7 days | Everyone |
| `/testlatest` | Force post the latest JP student intro | Dev only |
| `/testgachapreview` | Pull fresh EN gacha notices and post | Dev only |

---

## Requirements

- Python 3.12+
- Docker + Docker Compose
- [X/Twitter API Bearer Token](https://developer.twitter.com/en/portal/dashboard) (Basic tier or above)
- Discord Bot Token from the [Discord Developer Portal](https://discord.com/developers/applications)
- `students.min.en.json` from [SchaleDB](https://github.com/aiotrc/schaledb) (MIT licensed)

---

## Setup

**1. Clone the repo:**
```bash
git clone https://github.com/heaslay/azure-arona.git
cd azure-arona
```

**2. Update student data if needed:**

Student data is included as of March 2026. If you need the latest data, download a fresh `students.min.en.json` from [SchaleDB](https://github.com/aiotrc/schaledb) and replace:
```
data/students.min.en.json
```

**3. Create your `.env` file:**
```bash
cp .env.example .env
```
Fill in all the values in `.env` (see [Environment Variables](#environment-variables) below).

**4. Update `docker-compose.yml` to match your machine:**

Update the volume path to where you cloned the repo:
```yaml
volumes:
  - /your/path/to/azure-arona:/projects/azure-arona
```

And set your timezone (full list at [Wikipedia](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)):
```yaml
environment:
  - TZ=Your/Timezone  # e.g. America/New_York, Europe/London, Asia/Tokyo
```

**5. Build and run:**
```bash
docker compose up -d --build
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `DISCORD_BOT_TOKEN` | Your Discord bot token |
| `X_BEARER_TOKEN` | X/Twitter API Bearer Token |
| `X_USER_ID` | Numeric user ID of the JP Blue Archive account |
| `X_USERNAME` | Username of the JP account (default: `Blue_ArchiveJP`) |
| `X_USER_ID2` | Numeric user ID of the EN Blue Archive account |
| `X_USERNAME2` | Username of the EN account (default: `EN_BlueArchive`) |
| `DEV_DISCORD_USER_ID` | Your Discord user ID for DM reports and dev commands |
| `DEV_GUILD_ID` | Your dev server ID for instant command sync (optional) |
| `DB_PATH` | Path to SQLite database (default: `./state.db`) |
| `FETCH_LIMIT` | Max tweets to fetch per check (default: `10`) |
| `JP_PREFIX` | JP tweet prefix to filter (default: `【生徒紹介】`) |
| `POST_HOUR_UTC` | Hour to run JP daily check in UTC (default: `3`) |
| `POST_MINUTE_UTC` | Minute to run JP daily check in UTC (default: `10`) |
| `EN_POST_HOUR_UTC` | Hour to run EN gacha check in UTC (default: `7`) |
| `EN_POST_MINUTE_UTC` | Minute to run EN gacha check in UTC (default: `20`) |
| `DM_DAILY_STATUS` | Send DM summary after each task run (default: `true`) |

---

## Project Structure

```
azure-arona/
├── app/
│   ├── bot.py          # Main bot, commands, and scheduled tasks
│   ├── db.py           # SQLite database helpers
│   ├── scraper.py      # X/Twitter API fetching and image downloading
│   └── formatters.py   # Skill text rendering helpers
├── data/
│   └── students.min.en.json  # Student data from SchaleDB
├── .env.example        # Environment variable template
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Scheduled Tasks

| Task | Schedule | Description |
|---|---|---|
| `daily_check` | Daily at `POST_HOUR_UTC:POST_MINUTE_UTC` | Checks for new JP student intro tweets |
| `gacha_notice_check` | Fridays at `EN_POST_HOUR_UTC:EN_POST_MINUTE_UTC` | Checks for new EN gacha banner notices |

---

## Acknowledgements

- Student data from [SchaleDB](https://github.com/aiotrc/schaledb) — MIT License
- Built with [discord.py](https://github.com/Rapptz/discord.py)
