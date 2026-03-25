import re
from datetime import date, timedelta
from difflib import SequenceMatcher

from config import ANTHROPIC_API_KEY, OBSIDIAN_VAULT
from services.calendar_service import get_events, get_events_range, get_calendar_names, save_calendar_filter, CalendarEvent
from services.routine_service import RoutineService
from services.claude_service import parse_intent, summarize_tasks, generate_weekly_report, generate_monthly_summary
from services.obsidian_service import ObsidianService

_obsidian = ObsidianService(OBSIDIAN_VAULT)
_routine = RoutineService(OBSIDIAN_VAULT)

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

_history: dict[str, list] = {}
_MAX_HISTORY = 8  # 최대 4회 교환 (user+assistant 쌍)


_URL_RE = re.compile(r"https?://\S+")


_GCAL_SEP_RE = re.compile(r"[-:~]{5,}")
_GCAL_BOILERPLATE_RE = re.compile(
    r"(Google Meet|전화번호로 전화|참여 방법|Join with Google|video call|meet\.google\.com|\+\d[\d\s\-()]{6,})",
    re.IGNORECASE,
)

def _fmt_notes(notes: str) -> str:
    """메모에서 URL·구글 구분선·boilerplate 제거 후 (메모) 형태로 포맷."""
    if not notes:
        return ""
    text = _URL_RE.sub("", notes)
    text = _GCAL_SEP_RE.sub("", text)
    # 구글 미트 boilerplate 포함된 줄 제거
    clean_lines = [
        ln for ln in text.splitlines()
        if ln.strip() and not _GCAL_BOILERPLATE_RE.search(ln)
    ]
    text = " ".join(clean_lines).strip()
    if not text:
        return ""
    return f"  ({text[:60]})" if len(text) <= 60 else f"  ({text[:57]}...)"


def _is_duplicate(event_title: str, task_texts: list[str], threshold: float = 0.7) -> bool:
    t = event_title.lower()
    return any(SequenceMatcher(None, t, tt.lower()).ratio() >= threshold for tt in task_texts)


def _fmt_day(tasks: list, cal_events: list[CalendarEvent]) -> str:
    """하루의 캘린더 + 태스크를 카테고리별로 포맷. 중복 제거 포함."""
    lines = []
    task_texts = [t.text for t in tasks]

    # 캘린더 (태스크와 중복되지 않는 것만)
    unique_events = [e for e in cal_events if not _is_duplicate(e.title, task_texts)]
    for e in unique_events:
            time_part = f"`{e.duration_str}`  " if not e.is_all_day else "`종일`  "
            lines.append(f"• {time_part}{e.title}{_fmt_notes(e.notes)}")

    # 태스크를 카테고리별로 그룹핑
    by_cat: dict[str, list] = {}
    for t in tasks:
        cat = t.category or "기타"
        by_cat.setdefault(cat, []).append(t)

    for cat, cat_tasks in by_cat.items():
        parts = []
        for t in cat_tasks:
            text = t.text
            # 카테고리명 접두어 제거
            if text.lower().startswith(cat.lower()):
                text = text[len(cat):].lstrip()
            if t.scheduled_time:
                text = f"`{t.scheduled_time}`  {text}"
            if t.due_date:
                urgency = " ⚠️" if t.is_urgent else ""
                text += f"  `{t.due_date.strftime('%m/%d')}`{urgency}"
            if t.is_complete or t.status == "cancelled":
                parts.append(f"~{text}~")
            elif t.status == "in_progress":
                parts.append(f"▸ {text}")
            else:
                parts.append(text)
        lines.append(f"_{cat}_")
        for part in parts:
            lines.append(f"• {part}")

    return "\n".join(lines) if lines else "_(없음)_"


async def handle_message(text: str, say, user: str):
    today = date.today()
    prev_history = _history.get(user, [])
    intent_data = parse_intent(text, ANTHROPIC_API_KEY, history=prev_history)
    intent = intent_data.get("intent", "unknown")
    reply = intent_data.get("reply_message", "")
    response_text = ""

    _original_say = say

    async def say_and_record(msg: str):
        nonlocal response_text
        response_text = msg
        await _original_say(msg)
        history = prev_history + [
            {"role": "user", "content": text},
            {"role": "assistant", "content": msg},
        ]
        _history[user] = history[-_MAX_HISTORY:]

    say = say_and_record

    if intent == "add_task":
        task_text = intent_data.get("task_text")
        due_str = intent_data.get("due_date")
        category = intent_data.get("category")
        due_date = date.fromisoformat(due_str) if due_str else None
        added = _obsidian.add_task(today, task_text, due_date=due_date, category=category)
        await say(f"{reply}\n> {added}")

    elif intent == "add_scheduled":
        task_text = intent_data.get("task_text")
        sched_time = intent_data.get("scheduled_time")
        category = intent_data.get("category")
        due_str = intent_data.get("due_date")
        target_str = intent_data.get("target_date")
        task_date = date.fromisoformat(target_str) if target_str else today
        due_date = date.fromisoformat(due_str) if due_str else None
        added = _obsidian.add_task(task_date, task_text, due_date=due_date, category=category, scheduled_time=sched_time)
        await say(f"{reply}\n> {added}")

    elif intent == "complete_task":
        task_text = intent_data.get("task_text")
        target_str = intent_data.get("target_date")
        task_date = date.fromisoformat(target_str) if target_str else today
        ok = _obsidian.mark_complete(task_date, task_text)
        if ok:
            await say(f"완료 처리했어요. {reply}")
        else:
            await say(f"'{task_text}'와 일치하는 미완료 태스크를 찾지 못했어요.")

    elif intent == "log_day":
        log_tasks = intent_data.get("log_tasks") or []
        if not log_tasks:
            await say(reply or "기록할 태스크를 찾지 못했어요.")
            return
        lines = [f"{reply}\n"]
        status_icon = {"complete": "[x]", "in_progress": "[/]", "cancelled": "[-]", "pending": "[ ]"}
        for item in log_tasks:
            task_text = item.get("task_text", "")
            status = item.get("status", "pending")
            category = item.get("category")
            if not task_text:
                continue
            _obsidian.add_task(today, task_text, category=category, status=status)
            icon = status_icon.get(status, "[ ]")
            lines.append(f"• {icon} {task_text}")
        await say("\n".join(lines))

    elif intent == "add_backlog":
        backlog_tasks = intent_data.get("backlog_tasks")
        if backlog_tasks:
            lines = [f"{reply}\n"]
            for item in backlog_tasks:
                added = _obsidian.add_backlog(item.get("task_text", ""), item.get("category"))
                lines.append(f"• {added}")
            response_text = "\n".join(lines)
        else:
            task_text = intent_data.get("task_text")
            category = intent_data.get("category")
            added = _obsidian.add_backlog(task_text, category)
            response_text = f"백로그에 추가했어요.\n> {added}"
        await say(response_text)

    elif intent == "query_today":
        target_str = intent_data.get("target_date")
        target = date.fromisoformat(target_str) if target_str else today
        tasks = _obsidian.get_tasks(target)
        cal_events = get_events(target)
        pending = sum(1 for t in tasks if not t.is_complete)
        if target == today:
            label = "오늘"
        elif target == today + timedelta(days=1):
            label = "내일"
        else:
            label = f"{target.month}/{target.day} ({WEEKDAYS[target.weekday()]})"
        header = f"*{target.month}/{target.day} ({WEEKDAYS[target.weekday()]}) {label}*  —  할 일 {len(tasks)}개 · 미완료 {pending}개 · 일정 {len(cal_events)}개"
        body = _fmt_day(tasks, cal_events)
        await say(f"{header}\n\n{body}")

    elif intent == "query_week":
        # 일~토 기준 (일요일 시작)
        days_since_sunday = (today.weekday() + 1) % 7
        sunday = today - timedelta(days=days_since_sunday)
        monday = sunday  # 변수명 재사용 (start)
        saturday = sunday + timedelta(days=6)
        tasks_by_date = _obsidian.get_tasks_range(sunday, saturday)
        events_by_date = get_events_range(sunday, saturday)

        all_dates = sorted(set(list(tasks_by_date.keys()) + list(events_by_date.keys())))
        lines = [f"*이번 주  {sunday.month}/{sunday.day} (일) ~ {saturday.month}/{saturday.day} (토)*\n"]

        for d in all_dates:
            day_tasks = tasks_by_date.get(d, [])
            day_events = events_by_date.get(d, [])
            pending = sum(1 for t in day_tasks if not t.is_complete)
            if d == today:
                day_header = f"*── 오늘  {d.month}/{d.day} ({WEEKDAYS[d.weekday()]}) ──*"
            else:
                day_header = f"*{d.month}/{d.day} ({WEEKDAYS[d.weekday()]})*"
            if day_tasks:
                day_header += f"  {len(day_tasks)}개 · 미완료 {pending}개"
            lines.append("")
            lines.append(day_header)
            lines.append(_fmt_day(day_tasks, day_events))

        if len(lines) == 1:
            await say("이번 주 등록된 일정과 할 일이 없어요.")
        else:
            await say("\n".join(lines))

    elif intent == "query_backlog":
        backlog = _obsidian.get_backlog()
        total = sum(len(v) for v in backlog.values())
        if total == 0:
            await say("📌 *백로그*\n백로그가 비어있어요!")
        else:
            lines = [f"📌 *백로그* ({total}개)\n"]
            for cat, tasks in backlog.items():
                cat_label = f"[{cat}] " if cat != "기타" else ""
                for t in tasks:
                    lines.append(f"• {cat_label}{t.text}")
            await say("\n".join(lines))

    elif intent == "query_upcoming":
        upcoming = _obsidian.get_upcoming_tasks(days=14)
        if not upcoming:
            await say("향후 2주 이내 마감인 태스크가 없어요.")
            return
        lines = ["*다가오는 마감*\n"]
        by_cat: dict[str, list] = {}
        for t in upcoming:
            cat = t.category or "기타"
            by_cat.setdefault(cat, []).append(t)
        for cat, cat_tasks in by_cat.items():
            lines.append(f"_{cat}_")
            for t in cat_tasks:
                urgency = " ⚠️" if t.is_urgent else ""
                lines.append(f"• `{t.due_date.strftime('%m/%d')}`  {t.text}{urgency}")
        await say("\n".join(lines))

    elif intent == "summarize_today":
        tasks = _obsidian.get_tasks(today)
        completed = [t.text for t in tasks if t.is_complete]
        summary = summarize_tasks(completed, ANTHROPIC_API_KEY)
        await say(f"*오늘 한 일 요약*\n\n{summary}")

    elif intent == "query_calendar":
        target_str = intent_data.get("target_date")
        date_range = intent_data.get("date_range")

        if date_range:
            start = date.fromisoformat(date_range["start"])
            end = date.fromisoformat(date_range["end"])
            events_by_date = get_events_range(start, end)
            if not events_by_date:
                await say("해당 기간에 캘린더 일정이 없어요.")
                return
            lines = [f"*캘린더  {start.month}/{start.day} ~ {end.month}/{end.day}*\n"]
            for d in sorted(events_by_date):
                lines.append(f"*{d.month}/{d.day} ({WEEKDAYS[d.weekday()]})*")
                for e in events_by_date[d]:
                    time_part = f"`{e.duration_str}`  " if not e.is_all_day else "`종일`  "
                    lines.append(f"• {time_part}{e.title}  _{e.calendar_name}_{_fmt_notes(e.notes)}")
            await say("\n".join(lines))
        else:
            target = date.fromisoformat(target_str) if target_str else today
            events = get_events(target)
            label = "오늘" if target == today else f"{target.month}/{target.day} ({WEEKDAYS[target.weekday()]})"
            if not events:
                await say(f"{label} 캘린더에 일정이 없어요.")
            else:
                lines = [f"*캘린더  {label}*\n"]
                for e in events:
                    time_part = f"`{e.duration_str}`  " if not e.is_all_day else "`종일`  "
                    lines.append(f"• {time_part}{e.title}  _{e.calendar_name}_{_fmt_notes(e.notes)}")
                await say("\n".join(lines))

    elif intent == "list_calendars":
        names = get_calendar_names()
        if not names:
            await say("캘린더를 불러오지 못했어요.")
        else:
            lines = ["*사용 가능한 캘린더 목록*\n"]
            for n in names:
                lines.append(f"• {n}")
            lines.append("\n_포함할 캘린더를 설정하려면:_  `캘린더 설정: 운동, 공부, 중요`")
            await say("\n".join(lines))

    elif intent == "set_calendar_filter":
        cal_names = intent_data.get("calendar_names") or []
        save_calendar_filter(cal_names)
        if cal_names:
            names_str = ", ".join(cal_names)
            await say(f"캘린더 설정을 저장했어요.\n포함: *{names_str}*\n\n이후 일정 조회부터 바로 반영돼요.")
        else:
            await say("캘린더 필터를 초기화했어요. 전체 캘린더를 포함해요.")

    elif intent == "query_calendar_filter":
        from services.calendar_service import _load_include
        include = _load_include()
        if include:
            names_str = ", ".join(include)
            await say(f"현재 포함된 캘린더: *{names_str}*\n\n변경하려면 `캘린더 설정: 캘린더명1, 캘린더명2` 형태로 말씀해 주세요.\n초기화(전체 포함)는 `캘린더 설정 초기화`라고 하면 돼요.")
        else:
            await say("현재 모든 캘린더를 포함하고 있어요.\n\n특정 캘린더만 보려면 `캘린더 설정: 운동, 공부, 중요` 형태로 말씀해 주세요.\n전체 목록은 `캘린더 목록`으로 확인할 수 있어요.")

    elif intent == "cancel_task":
        task_text = intent_data.get("task_text")
        from_str = intent_data.get("from_date")
        task_date = date.fromisoformat(from_str) if from_str else today
        ok = _obsidian.mark_cancelled(task_date, task_text)
        if ok:
            await say(f"취소 처리했어요. {reply}")
        else:
            await say(f"'{task_text}'와 일치하는 태스크를 찾지 못했어요.")

    elif intent == "delete_task":
        task_text = intent_data.get("task_text")
        from_str = intent_data.get("from_date")
        task_date = date.fromisoformat(from_str) if from_str else today
        ok = _obsidian.delete_task(task_date, task_text)
        if ok:
            await say(f"삭제했어요. {reply}")
        else:
            await say(f"'{task_text}'와 일치하는 태스크를 찾지 못했어요.")

    elif intent == "postpone_task":
        task_text = intent_data.get("task_text")
        from_str = intent_data.get("from_date")
        target_str = intent_data.get("target_date")
        from_date = date.fromisoformat(from_str) if from_str else today
        to_date = date.fromisoformat(target_str) if target_str else today + timedelta(days=1)
        ok = _obsidian.move_task(from_date, task_text, to_date)
        label = f"{to_date.month}/{to_date.day} ({WEEKDAYS[to_date.weekday()]})"
        if ok:
            await say(f"{label}로 이동했어요. {reply}")
        else:
            await say(f"'{task_text}'와 일치하는 태스크를 찾지 못했어요.")

    elif intent == "move_from_backlog":
        task_text = intent_data.get("task_text")
        target_str = intent_data.get("target_date")
        target = date.fromisoformat(target_str) if target_str else today
        ok = _obsidian.move_backlog_to_date(task_text, target)
        label = "오늘" if target == today else f"{target.month}/{target.day}"
        if ok:
            await say(f"백로그에서 {label} 할 일로 옮겼어요. {reply}")
        else:
            await say(f"'{task_text}'와 일치하는 백로그 항목을 찾지 못했어요.")

    elif intent == "search_tasks":
        keyword = intent_data.get("task_text", "")
        results = _obsidian.search_tasks(keyword)
        if not results:
            await say(f"'{keyword}'와 관련된 과거 태스크를 찾지 못했어요.")
        else:
            lines = [f"*'{keyword}' 검색 결과 ({len(results)}개)*\n"]
            for t in results[:15]:
                d_label = t.task_date.strftime("%m/%d") if t.task_date else "날짜 미상"
                cat = f"_{t.category}_ " if t.category else ""
                status_icon = {"complete": "✅", "in_progress": "▸", "cancelled": "~~", "pending": "○"}.get(t.status, "○")
                lines.append(f"• `{d_label}` {status_icon} {cat}{t.text}")
            await say("\n".join(lines))

    elif intent == "weekly_report":
        days_since_sunday = (today.weekday() + 1) % 7
        sunday = today - timedelta(days=days_since_sunday)
        saturday = sunday + timedelta(days=6)
        tasks_by_date = _obsidian.get_tasks_range(sunday, saturday)
        completed = [t for tasks in tasks_by_date.values() for t in tasks if t.is_complete]
        report = generate_weekly_report(completed, ANTHROPIC_API_KEY)
        await say(f"*📋 주간 업무 보고서 초안*\n\n{report}")

    elif intent == "monthly_summary":
        target_str = intent_data.get("target_date")
        target = date.fromisoformat(target_str) if target_str else today
        completed = _obsidian.get_month_completed(target.year, target.month)
        summary = generate_monthly_summary(completed, target.year, target.month, ANTHROPIC_API_KEY)
        await say(f"*📊 {target.month}월 완료 통계* ({len(completed)}개)\n\n{summary}")

    elif intent == "add_routine":
        task_text = intent_data.get("task_text")
        frequency = intent_data.get("frequency", "daily")
        weekday = intent_data.get("weekday")
        category = intent_data.get("category")
        r = _routine.add_routine(task_text, frequency, category=category, weekday=weekday)
        await say(f"루틴 등록했어요.\n> {_routine.describe(r)}")

    elif intent == "list_routines":
        routines = _routine.list_routines()
        if not routines:
            await say("등록된 루틴이 없어요.")
        else:
            lines = [f"*루틴 목록 ({len(routines)}개)*\n"]
            for r in routines:
                lines.append(f"• {_routine.describe(r)}")
            await say("\n".join(lines))

    elif intent == "delete_routine":
        task_text = intent_data.get("task_text", "")
        ok = _routine.delete_routine(task_text)
        if ok:
            await say(f"루틴 삭제했어요. {reply}")
        else:
            await say(f"'{task_text}'와 일치하는 루틴을 찾지 못했어요.")

    else:
        await say(reply or "죄송해요, 이해하지 못했어요. 다시 말씀해 주세요.")
