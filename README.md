# 🤖 Personal Slack Assistant

Slack DM으로 자연어를 보내면 Obsidian 할 일 파일을 관리하고, 매일 아침 브리핑을 보내주는 개인 비서 봇입니다.

> macOS 전용 (EventKit을 통한 Apple Calendar / Google Calendar 연동)

**Slack 브리핑**

![briefing](docs/briefing.png)

**Obsidian 저장 형태**

![obsidian](docs/obsidian.png)

**Slack 자연어 대화**

![demo](docs/demo.png)

---

## 주요 기능

### 매일 오전 브리핑 (7:00 AM)
- **메인 메시지**: 오늘 할 일 + 캘린더 일정 (카테고리별 인라인 포맷)
- **스레드 1**: 7일 이내 마감 태스크
- **스레드 2**: 백로그 목록
- 전날 진행 중이던 태스크 자동 이월 (`[/]` → 다음 날로 복사)

### 자연어 태스크 관리
| 발화 예시 | 동작 |
|-----------|------|
| `오늘 할 일 뭐야?` | 오늘 태스크 + 일정 조회 |
| `내일까지 보고서 제출해야 해` | 마감일 태스크 추가 |
| `13시 30분에 팀 미팅 있어` | 시간 일정 추가 |
| `나중에 리팩토링 해야해` | 백로그 추가 |
| `백엔드 API 개발 완료했어` | 퍼지 매칭으로 완료 처리 |
| `이번 주 일정 알려줘` | 주간 일정 조회 |
| `오늘 한 일 정리해줘` | Claude AI로 요약 |
| `오늘 API 개발 완료했고, 회의는 취소됐어` | 여러 태스크 한꺼번에 기록 |

### 캘린더 연동 (macOS EventKit)
- macOS Calendar에 등록된 **모든 캘린더** 접근 (Google, iCloud 등)
- 포함할 캘린더를 Slack에서 동적으로 설정 (재시작 불필요)
- 특정 캘린더는 **참석자 필터** 적용 가능 (예: 팀 캘린더에서 내가 참석한 일정만)
- Google Meet 보일러플레이트 자동 제거

```
캘린더 목록                        → 연결된 캘린더 확인
캘린더 설정: 운동, 공부, 회사      → 포함할 캘린더 지정
캘린더 설정 확인                   → 현재 필터 확인
```

---

## 요구사항

- **macOS** (EventKit 사용)
- **Python 3.11+**
- [Obsidian](https://obsidian.md/) 볼트
- [Slack App](https://api.slack.com/apps) (Socket Mode)
- [Anthropic API Key](https://console.anthropic.com/)

---

## 설치

### 1. Slack App 생성

1. [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → From scratch
2. **Socket Mode** 활성화 → App-Level Token 발급 (`connections:write` scope)
3. **OAuth & Permissions** → Bot Token Scopes 추가:
   - `im:history`, `im:read`, `im:write`, `chat:write`
4. **Event Subscriptions** → Subscribe to bot events: `message.im`
5. 워크스페이스에 앱 설치 → Bot Token 복사
6. 본인 Slack 프로필 → **Copy member ID** (User ID)

### 2. 프로젝트 설정

```bash
git clone https://github.com/your-username/personal-slack-assistant
cd personal-slack-assistant

python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. 환경변수 설정

```bash
cp .env.example .env
# .env 파일을 열어 각 값 입력
```

### 4. 캘린더 연동

이 봇은 macOS의 **Calendar 앱**에 등록된 모든 캘린더를 읽습니다.
iCloud / Google / Exchange 등 Calendar 앱에서 보이는 캘린더라면 모두 연동됩니다.

#### iCloud 캘린더
Apple ID로 macOS에 로그인되어 있으면 자동으로 연동됩니다.

#### Google 캘린더 연동

1. **시스템 설정** → **인터넷 계정** → **계정 추가** → **Google**
2. Google 계정으로 로그인
3. **캘린더** 토글 활성화
4. macOS **캘린더 앱**을 열어 Google 캘린더가 보이는지 확인

#### macOS Calendar 접근 권한 허용

봇이 캘린더를 읽으려면 Python 실행 파일에 권한을 부여해야 합니다.

```bash
# venv Python 경로 확인
which python  # 예: /path/to/.venv/bin/python3.x
```

**시스템 설정 → 개인 정보 및 보안 → 캘린더** → `+` 버튼으로 위 경로의 Python 바이너리 추가

> 봇을 처음 실행하면 macOS가 자동으로 권한 요청 팝업을 띄우기도 합니다.

#### 연결된 캘린더 확인

봇 실행 후 Slack에서 확인:
```
캘린더 목록
```

#### 특정 캘린더만 표시

```
캘린더 설정: 개인, 회사, 운동
```

`calendar_filter.json`에 저장되며 재시작 없이 즉시 반영됩니다.

#### 팀 캘린더 참석자 필터 (선택)

팀 공유 캘린더에서 **내가 참석자로 등록된 일정만** 보고 싶을 때:

`calendar_filter.json`을 직접 수정하거나, 초기 설정 시 아래와 같이 구성합니다:

```json
{
  "include": ["개인", "팀 캘린더"],
  "attendee_filter": {
    "팀 캘린더": "my-email@company.com"
  }
}
```

### 5. SLACK_CHANNEL_ID 확인

브리핑 DM을 전송하려면 봇과의 DM 채널 ID(`D`로 시작)가 필요합니다.

1. `SLACK_CHANNEL_ID` 없이 봇을 먼저 실행
2. 봇에게 DM 한 번 전송
3. 로그에서 채널 ID 확인:
```bash
grep "DM 수신" logs/bot.log
# 예: DM 수신 from=U012AB3CD4E: 안녕 → 이때 event.channel 값이 D...
```

또는 더 간단하게 — Slack에서 봇과의 DM 채널을 열고 URL에서 확인:
```
https://app.slack.com/client/TXXXXXXXX/D012AB3CD4E
                                        ^^^^^^^^^^^^ 이 부분이 SLACK_CHANNEL_ID
```

4. `.env`에 추가:
```
SLACK_CHANNEL_ID=D012AB3CD4E
```

### 6. 실행

```bash
python main.py
```

#### 부팅 시 자동 시작 (launchd)

```bash
# LaunchAgent plist 예시 (~/Library/LaunchAgents/com.yourname.personal-assistant.plist)
cat > ~/Library/LaunchAgents/com.yourname.personal-assistant.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.yourname.personal-assistant</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/.venv/bin/python</string>
        <string>/path/to/personal-assistant/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/personal-assistant</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/personal-assistant.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/personal-assistant-error.log</string>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.yourname.personal-assistant.plist
```

---

## Obsidian 파일 포맷

봇은 Obsidian 볼트의 `Todo/YYYY년/M월.md` 파일을 읽고 씁니다.

```markdown
## 03.23 (월)
### 개발
- [x] API 개발 완료 📅 2026-03-25    ← 완료 + 마감일
- [/] 리팩토링                        ← 진행 중 (다음 날 자동 이월)
- [-] 정기회의                        ← 취소
- [ ] 코드 리뷰                       ← 대기

## Backlog (Todo/Backlog.md)
### 개인
- [ ] 블로그 글 작성
```

**캘린더 필터 설정** (`calendar_filter.json`, gitignore됨):

```json
{
  "include": ["캘린더명1", "캘린더명2"],
  "attendee_filter": {
    "팀 캘린더명": "my-email@company.com"
  }
}
```

---

## 프로젝트 구조

```
personal-assistant/
├── main.py                    # Slack Socket Mode + APScheduler
├── config.py                  # 환경변수 로드
├── handlers/
│   ├── message_handler.py     # DM 이벤트 → Claude → Obsidian → 응답
│   └── briefing_handler.py    # 오전 브리핑 생성/전송
├── services/
│   ├── claude_service.py      # Claude API 의도 파악
│   ├── calendar_service.py    # macOS EventKit 캘린더 연동
│   └── obsidian_service.py    # Obsidian 파일 읽기/쓰기
├── models/
│   └── task.py                # Task 데이터 클래스
├── .env.example
└── pyproject.toml
```

---

## 기술 스택

- **[Slack Bolt](https://github.com/slackapi/bolt-python)** — Socket Mode로 ngrok 없이 로컬 실행
- **[Anthropic Claude](https://anthropic.com/)** — 자연어 의도 파악 (claude-sonnet)
- **[EventKit](https://developer.apple.com/documentation/eventkit) via pyobjc** — macOS 네이티브 캘린더 API
- **[APScheduler](https://apscheduler.readthedocs.io/)** — 매일 오전 브리핑 스케줄링
- **Obsidian** 마크다운 파일 직접 파싱/수정

---

## License

MIT
