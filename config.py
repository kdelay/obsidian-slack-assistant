import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

SLACK_BOT_TOKEN: str = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN: str = os.environ["SLACK_APP_TOKEN"]
SLACK_USER_ID: str = os.environ["SLACK_USER_ID"]
SLACK_CHANNEL_ID: str = os.environ.get("SLACK_CHANNEL_ID", "")
ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
OBSIDIAN_VAULT: str = os.environ.get("OBSIDIAN_VAULT", "/Users/lilly/Documents/Obsidian")
BRIEFING_HOUR: int = int(os.environ.get("BRIEFING_HOUR", "7"))
