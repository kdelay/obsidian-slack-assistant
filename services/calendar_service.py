import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import EventKit
import Foundation

log = logging.getLogger(__name__)

_FILTER_FILE = Path(__file__).parent.parent / "calendar_filter.json"

# EKEventStore 싱글톤
_store: EventKit.EKEventStore | None = None
_store_lock = threading.Lock()
_authorized = False


def _get_store() -> EventKit.EKEventStore | None:
    global _store, _authorized
    with _store_lock:
        if _store is not None:
            return _store if _authorized else None

        store = EventKit.EKEventStore.alloc().init()
        status = EventKit.EKEventStore.authorizationStatusForEntityType_(0)
        # 0=EKEntityTypeEvent, status: 0=notDetermined, 3=fullAccess
        if status == 3:
            _store = store
            _authorized = True
            return _store

        # 권한 요청 (처음 실행 시)
        done = threading.Event()

        def handler(granted, error):
            global _authorized
            _authorized = bool(granted)
            done.set()

        store.requestFullAccessToEventsWithCompletion_(handler)
        done.wait(timeout=10)

        if _authorized:
            _store = store
            return _store

        log.error("캘린더 접근 권한이 없어요. 시스템 설정 → 개인 정보 보호 → 캘린더에서 Python 허용 필요.")
        return None


def _load_filter() -> tuple[list[str], dict[str, str]]:
    try:
        data = json.loads(_FILTER_FILE.read_text(encoding="utf-8"))
        include = [c.strip() for c in data.get("include", []) if c.strip()]
        attendee_filter = data.get("attendee_filter", {})
        return include, attendee_filter
    except Exception:
        return [], {}


def _load_include() -> list[str]:
    return _load_filter()[0]


def save_calendar_filter(include: list[str]) -> None:
    try:
        existing = json.loads(_FILTER_FILE.read_text(encoding="utf-8"))
        attendee_filter = existing.get("attendee_filter", {})
    except Exception:
        attendee_filter = {}
    _FILTER_FILE.write_text(
        json.dumps({"include": include, "attendee_filter": attendee_filter}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@dataclass
class CalendarEvent:
    title: str
    start: datetime
    end: datetime
    calendar_name: str
    is_all_day: bool = False
    notes: str = ""
    attendees: list[str] = field(default_factory=list)

    @property
    def duration_str(self) -> str:
        if self.is_all_day:
            return "종일"
        return f"{self.start.strftime('%H:%M')} ~ {self.end.strftime('%H:%M')}"


def get_calendar_names() -> list[str]:
    store = _get_store()
    if not store:
        return []
    cals = store.calendarsForEntityType_(0)
    return [cal.title() for cal in cals]


def _ns_date(dt: datetime) -> Foundation.NSDate:
    ref = datetime(2001, 1, 1)
    secs = (dt - ref).total_seconds()
    return Foundation.NSDate.dateWithTimeIntervalSinceReferenceDate_(secs)


def _ns_to_datetime(ns_date) -> datetime:
    # NSDate → Unix timestamp → 로컬 시각
    unix_ts = ns_date.timeIntervalSinceReferenceDate() + 978307200  # 2001-01-01 기준 오프셋
    return datetime.fromtimestamp(float(unix_ts))


def _fetch_events(start_dt: datetime, end_dt: datetime) -> list[CalendarEvent]:
    store = _get_store()
    if not store:
        return []

    include, attendee_filter = _load_filter()

    # 포함 캘린더 필터링
    all_cals = store.calendarsForEntityType_(0)
    if include:
        cals = [c for c in all_cals if c.title() in include]
    else:
        cals = list(all_cals)

    if not cals:
        return []

    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        _ns_date(start_dt), _ns_date(end_dt), cals
    )
    raw_events = store.eventsMatchingPredicate_(predicate) or []

    seen: set[str] = set()
    events: list[CalendarEvent] = []

    for evt in raw_events:
        title = evt.title() or ""
        cal_name = evt.calendar().title() if evt.calendar() else ""
        start = _ns_to_datetime(evt.startDate())
        end = _ns_to_datetime(evt.endDate())
        is_all_day = bool(evt.isAllDay())
        notes = (evt.notes() or "").replace("\r", " ").replace("\n", " ").strip()

        # 참석자 이메일 추출 (mailto:xxx 형식)
        att_emails: list[str] = []
        att_list = evt.attendees()
        if att_list:
            for att in att_list:
                url = att.URL()
                if url:
                    url_str = str(url.absoluteString())
                    if url_str.startswith("mailto:"):
                        att_emails.append(url_str[7:])

        # 참석자 필터 (특정 캘린더에만 적용)
        if cal_name in attendee_filter:
            required_email = attendee_filter[cal_name]
            if required_email not in att_emails:
                continue

        # 동일 이벤트 중복 제거 (title + start 기준, 여러 캘린더에 같은 이벤트 중복 방지)
        key = f"{title}|{start.isoformat()}"
        if key in seen:
            continue
        seen.add(key)

        events.append(CalendarEvent(
            title=title,
            start=start,
            end=end,
            calendar_name=cal_name,
            is_all_day=is_all_day,
            notes=notes,
            attendees=att_emails,
        ))

    events.sort(key=lambda e: e.start)
    return events


def get_events(target_date: date) -> list[CalendarEvent]:
    return _fetch_events(
        datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0),
        datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59),
    )


def get_events_range(start_date: date, end_date: date) -> dict[date, list[CalendarEvent]]:
    all_events = _fetch_events(
        datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0),
        datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59),
    )
    result: dict[date, list[CalendarEvent]] = {}
    for e in all_events:
        result.setdefault(e.start.date(), []).append(e)
    return result
