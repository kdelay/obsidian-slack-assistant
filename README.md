# Personal Slack Assistant

A personal assistant bot that manages your [Obsidian](https://obsidian.md/) tasks via natural language Slack DMs — with a daily morning briefing every day at 7 AM.

> macOS only · Powered by Claude AI + macOS Calendar (EventKit)

**🇰🇷 [한국어 README](README.ko.md)**

**Morning Briefing**

![briefing](docs/briefing.png)

**Obsidian Task Format**

![obsidian](docs/obsidian.png)

**Natural Language Chat**

![demo](docs/demo.png)

---

## What it does

| Say this | Action |
|----------|--------|
| `What's on today?` | Today's tasks + calendar events |
| `What's tomorrow look like?` | Tomorrow's tasks + calendar events |
| `Show me this week` | Weekly overview |
| `Submit report by tomorrow` | Add task with due date |
| `Team meeting at 2pm` | Add scheduled event |
| `Add refactoring to backlog` | Add to backlog |
| `Finished the API work` | Mark task complete (fuzzy match) |
| `Done with API, meeting was cancelled` | Log multiple tasks at once |
| `Summarize what I did today` | AI-generated summary |
| `Calendar filter: personal, work` | Choose which calendars to show |

**Daily 7 AM briefing** — today's tasks + upcoming deadlines (7 days) + backlog, sent as a Slack DM thread.

**In-progress tasks carry over automatically** — any `[/]` task from yesterday is copied to today's note during the morning briefing.

---

## Requirements

- macOS
- [Obsidian](https://obsidian.md/)
- [Anthropic API Key](https://console.anthropic.com/)
- A Slack workspace

---

## Setup

### Step 1 — Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Enter an app name and select your workspace
3. **Socket Mode** (left menu) → Enable → Generate token → Copy `xapp-...`
4. **OAuth & Permissions** → **Bot Token Scopes** → Add these 4 scopes:
   `chat:write` · `im:history` · `im:read` · `im:write`
5. **Install to Workspace** → **Allow** → Copy `xoxb-...`
6. **Event Subscriptions** → Enable → **Subscribe to bot events** → Add `message.im` → Save

### Step 2 — Install

**Open Terminal**: `Cmd + Space` → type "Terminal" → Enter

Run these commands one by one:

```bash
git clone https://github.com/kdelay/obsidian-slack-assistant
cd obsidian-slack-assistant
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Step 3 — Configure

```bash
cp .env.example .env
open .env
```

Fill in the values:

| Key | Description |
|-----|-------------|
| `SLACK_BOT_TOKEN` | `xoxb-...` from Step 1-5 |
| `SLACK_APP_TOKEN` | `xapp-...` from Step 1-3 |
| `ANTHROPIC_API_KEY` | From [console.anthropic.com](https://console.anthropic.com/) |
| `OBSIDIAN_VAULT` | Absolute path to your Obsidian vault (e.g. `/Users/yourname/Documents/Obsidian`) |
| `SLACK_CHANNEL_ID` | Leave blank for now — fill in after Step 4 |

### Step 4 — Run & get Channel ID

```bash
python main.py
```

Send the bot any DM message. Then find your channel ID in the Slack URL:
```
https://app.slack.com/client/TXXXXXXXX/D012AB3CD4E
                                        ↑ this is your SLACK_CHANNEL_ID
```

Add it to `.env` and restart the bot.

### Step 5 — Connect your calendar (optional)

**Google Calendar**
> macOS System Settings → Internet Accounts → Add Account → Google → enable Calendar

**Grant calendar access**
> macOS Calendar app → Settings → Accounts → select Google account → Delegation → check the boxes

Then in Slack:
```
calendar list              ← see all connected calendars
calendar filter: work      ← pick which calendars to show
```

### Step 6 — Auto-start on boot (optional)

Create `~/Library/LaunchAgents/com.yourname.personal-assistant.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.yourname.personal-assistant</string>
    <key>ProgramArguments</key>
    <array>
        <string>/absolute/path/.venv/bin/python</string>
        <string>/absolute/path/personal-assistant/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/absolute/path/personal-assistant</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key>
    <string>/tmp/personal-assistant.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/personal-assistant-error.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.yourname.personal-assistant.plist
```

---

## Obsidian file format

The bot reads and writes `Todo/YYYY년/M월.md` in your vault automatically.

```markdown
## 03.24 (Tue)
### Work
- [ ] Code review                         ← pending
- [/] API development                     ← in progress (auto-carries to tomorrow)
- [x] Bug fix 📅 2026-03-24              ← done + due date
- [-] Meeting                             ← cancelled
```

Backlog items are stored in `Todo/Backlog.md`.

---

## Tech stack

- [Slack Bolt](https://github.com/slackapi/bolt-python) — Socket Mode, no server needed
- [Anthropic Claude](https://anthropic.com/) — natural language intent parsing
- [EventKit](https://developer.apple.com/documentation/eventkit) via pyobjc — native macOS calendar access
- [APScheduler](https://apscheduler.readthedocs.io/) — daily briefing scheduler

---

## License

MIT
