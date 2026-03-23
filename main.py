import asyncio
import logging
import logging.handlers
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from config import BRIEFING_HOUR, SLACK_APP_TOKEN, SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, SLACK_USER_ID
from handlers.briefing_handler import send_morning_briefing
from handlers.message_handler import handle_message

# ── 로깅 설정 ─────────────────────────────────────────────────
log_path = Path(__file__).parent / "logs" / "bot.log"
log_path.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ── Slack App ──────────────────────────────────────────────────
app = AsyncApp(token=SLACK_BOT_TOKEN)


@app.event("message")
async def on_message(event, say):
    if event.get("channel") != SLACK_CHANNEL_ID:
        return
    if event.get("bot_id") or event.get("subtype"):
        return
    text = event.get("text", "").strip()
    if not text:
        return
    user = event.get("user", "")
    log.info(f"DM 수신 from={user}: {text[:60]}")
    await handle_message(text, say, user)


# ── 스케줄러 ───────────────────────────────────────────────────
scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
scheduler.add_job(
    send_morning_briefing,
    "cron",
    hour=BRIEFING_HOUR,
    minute=0,
    args=[app, SLACK_USER_ID],
    id="morning_briefing",
    replace_existing=True,
)


# ── 진입점 ────────────────────────────────────────────────────
async def main():
    scheduler.start()
    log.info(f"스케줄러 시작 — 매일 {BRIEFING_HOUR:02d}:00 브리핑")
    handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)
    log.info("Slack Socket Mode 연결 중...")
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
