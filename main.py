import asyncio
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from config import BRIEFING_HOUR, OBSIDIAN_VAULT, SLACK_APP_TOKEN, SLACK_BOT_TOKEN, SLACK_CHANNEL_ID
from handlers.briefing_handler import send_morning_briefing
from handlers.message_handler import handle_message
from services.calendar_service import get_events as _get_cal_events
from services.obsidian_service import ObsidianService as _ObsidianService
from services.routine_service import RoutineService as _RoutineService

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


_reminded: set[str] = set()  # 이미 알림 보낸 이벤트 키 (date + title)


async def check_reminders(app_instance, channel_id: str):
    """캘린더 이벤트 30분 전 리마인더."""
    now = datetime.now()
    today = now.date()
    events = _get_cal_events(today)
    for e in events:
        if e.is_all_day:
            continue
        mins_until = (e.start - now).total_seconds() / 60
        if 25 <= mins_until <= 35:
            key = f"{today}|{e.title}|{e.start.strftime('%H:%M')}"
            if key not in _reminded:
                _reminded.add(key)
                time_str = e.start.strftime("%H:%M")
                try:
                    await app_instance.client.chat_postMessage(
                        channel=channel_id,
                        text=f"🔔 *{time_str}* 일정이 30분 후 시작해요.\n> {e.title}",
                    )
                except Exception as exc:
                    log.error(f"리마인더 전송 실패: {exc}")


async def apply_daily_routines(app_instance, channel_id: str):
    """오늘 루틴 태스크를 Obsidian에 자동 추가."""
    obsidian = _ObsidianService(OBSIDIAN_VAULT)
    routine_svc = _RoutineService(OBSIDIAN_VAULT)
    today = __import__("datetime").date.today()
    existing = {t.text.lower() for t in obsidian.get_tasks(today)}
    added = []
    for r in routine_svc.get_due_today(today):
        if r["text"].lower() not in existing:
            obsidian.add_task(today, r["text"], category=r.get("category"), status="pending")
            added.append(r["text"])
    if added:
        log.info(f"루틴 태스크 {len(added)}개 추가: {added}")


# ── 스케줄러 ───────────────────────────────────────────────────
scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
scheduler.add_job(
    send_morning_briefing,
    "cron",
    hour=BRIEFING_HOUR,
    minute=0,
    args=[app, SLACK_CHANNEL_ID],
    id="morning_briefing",
    replace_existing=True,
)
scheduler.add_job(
    check_reminders,
    "interval",
    minutes=1,
    args=[app, SLACK_CHANNEL_ID],
    id="reminder_check",
    replace_existing=True,
)
scheduler.add_job(
    apply_daily_routines,
    "cron",
    hour=BRIEFING_HOUR,
    minute=1,
    args=[app, SLACK_CHANNEL_ID],
    id="daily_routines",
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
