import logging
from datetime import date, timedelta

import re

from config import OBSIDIAN_VAULT, SLACK_CHANNEL_ID

_URL_RE = re.compile(r"https?://\S+")


_GCAL_SEP_RE = re.compile(r"[-:~]{5,}")
_GCAL_BOILERPLATE_RE = re.compile(
    r"(Google Meet|전화번호로 전화|참여 방법|Join with Google|video call|meet\.google\.com|\+\d[\d\s\-()]{6,})",
    re.IGNORECASE,
)

def _fmt_notes(notes: str) -> str:
    if not notes:
        return ""
    text = _URL_RE.sub("", notes)
    text = _GCAL_SEP_RE.sub("", text)
    clean_lines = [
        ln for ln in text.splitlines()
        if ln.strip() and not _GCAL_BOILERPLATE_RE.search(ln)
    ]
    text = " ".join(clean_lines).strip()
    if not text:
        return ""
    return f"  ({text[:60]})" if len(text) <= 60 else f"  ({text[:57]}...)"
from services.calendar_service import get_events
from services.obsidian_service import ObsidianService

log = logging.getLogger(__name__)
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

_obsidian = ObsidianService(OBSIDIAN_VAULT)


def _build_main_message(today: date, tasks: list, cal_events: list) -> str:
    from difflib import SequenceMatcher
    pending = sum(1 for t in tasks if not t.is_complete)
    header = (
        f"*{today.month}/{today.day} ({WEEKDAYS[today.weekday()]}) 오늘의 브리핑*\n"
        f"할 일 {len(tasks)}개 · 미완료 {pending}개 · 일정 {len(cal_events)}개"
    )
    sections = [header]

    # 캘린더 (태스크와 중복 제거)
    task_texts = [t.text for t in tasks]
    unique_events = [
        e for e in cal_events
        if not any(SequenceMatcher(None, e.title.lower(), tt.lower()).ratio() >= 0.7 for tt in task_texts)
    ]
    for e in unique_events:
            time_part = f"`{e.duration_str}`  " if not e.is_all_day else "`종일`  "
            sections.append(f"• {time_part}{e.title}{_fmt_notes(e.notes)}")

    # 태스크 카테고리별 그룹핑
    if tasks:
        by_cat: dict[str, list] = {}
        for t in tasks:
            by_cat.setdefault(t.category or "기타", []).append(t)
        for cat, cat_tasks in by_cat.items():
            parts = []
            for t in cat_tasks:
                text = t.text
                if text.lower().startswith(cat.lower()):
                    text = text[len(cat):].lstrip()
                if t.scheduled_time:
                    text = f"`{t.scheduled_time}`  {text}"
                if t.due_date:
                    text += f"  ~{t.due_date.strftime('%m/%d')}~{'  ⚠️' if t.is_urgent else ''}"
                if t.is_complete or t.status == "cancelled":
                    parts.append(f"~{text}~")
                elif t.status == "in_progress":
                    parts.append(f"▸ {text}")
                else:
                    parts.append(text)
            sections.append(f"\n_{cat}_")
            for part in parts:
                sections.append(f"• {part}")
    else:
        sections.append("\n_오늘 등록된 할 일이 없어요._")

    return "\n".join(sections)


def _build_upcoming_message(upcoming: list) -> str:
    if not upcoming:
        return "📆 *다가오는 일정*\n향후 7일 이내 마감인 태스크가 없어요. 여유롭네요! 🎉"
    lines = ["📆 *다가오는 일정 (7일 이내)*\n"]
    for t in upcoming:
        urgency = "⚠️ " if t.is_urgent else ""
        cat = f"[{t.category}] " if t.category else ""
        day_label = WEEKDAYS[t.due_date.weekday()]
        lines.append(f"• `{t.due_date.strftime('%m/%d')} ({day_label})` {urgency}{cat}{t.text}")
    return "\n".join(lines)


def _build_backlog_message(backlog: dict) -> str:
    total = sum(len(v) for v in backlog.values())
    if total == 0:
        return "📌 *백로그*\n백로그가 비어있어요!"

    lines = [f"📌 *백로그* ({total}개)\n"]
    for cat, tasks in backlog.items():
        for t in tasks:
            cat_label = f"[{cat}] " if cat != "기타" else ""
            lines.append(f"• {cat_label}{t.text}")
    return "\n".join(lines)


async def send_morning_briefing(app, user_id: str = SLACK_CHANNEL_ID):
    today = date.today()
    log.info(f"브리핑 전송 시작: {today}")

    try:
        # 1. 어제 진행중 태스크 이월
        yesterday = today - timedelta(days=1)
        carried = _obsidian.carry_over_inprogress(yesterday, today)
        if carried:
            log.info(f"이월된 태스크 {len(carried)}개: {carried}")

        # 2. ⚠️ 임박 태그 갱신
        _obsidian.update_urgency_tags()

        # 2. 데이터 수집
        tasks = _obsidian.get_tasks(today)
        upcoming = _obsidian.get_upcoming_tasks(days=7)
        backlog = _obsidian.get_backlog()
        cal_events = get_events(today)

        # 3. 메인 메시지
        main_text = _build_main_message(today, tasks, cal_events)
        result = await app.client.chat_postMessage(channel=user_id, text=main_text)
        thread_ts = result["ts"]

        # 4. 스레드 1: 다가오는 일정
        await app.client.chat_postMessage(
            channel=user_id,
            thread_ts=thread_ts,
            text=_build_upcoming_message(upcoming),
        )

        # 5. 스레드 2: 백로그
        await app.client.chat_postMessage(
            channel=user_id,
            thread_ts=thread_ts,
            text=_build_backlog_message(backlog),
        )

        log.info("브리핑 전송 완료")
    except Exception as e:
        log.error(f"브리핑 전송 실패: {e}", exc_info=True)
