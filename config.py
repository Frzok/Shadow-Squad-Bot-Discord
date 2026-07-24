"""Настройки бота.

Секреты и параметры Blizzard читаются из .env. Discord ID этого сервера
зафиксированы здесь намеренно: это предотвращает случайный запуск на другом
сервере с неверными ролями.
"""

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _int_env(name: str, default: int = 0) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def _blizzard_slug_env(name: str) -> str:
    value = os.getenv(name, "").strip().casefold()
    return re.sub(r"[\s_]+", "-", value)


DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()

GUILD_ID = 604571954422218752
SYNC_LOG_CHANNEL_ID = 723427989521432628
RAID_ANNOUNCEMENT_CHANNEL_ID = 809402292284686346
RAID_VOICE_CHANNEL_ID = 713419816857370624
RAID_ABSENCE_CHANNEL_ID = 1200807297111306280
RAID_NOTICE_EMOJI = "✅"
ROSTER_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1NEyoAcgQEa2BUyNZGwpoO1FRGgpjhHPSauEPqe1BZIw/"
    "edit?gid=241918221#gid=241918221"
)

ROLE_IDS = {
    "RL": 604574054938181643,
    "BANNER_BEARER": 604581483071537154,
    "SERGEANT": 604574109485105194,
    "CHRONICLER": 665163320776720414,
    "HILA_NA_KRUTILAH": 987332716460650520,
    "RECRUIT": 1263818118539776052,
    "FRIENDS": 632173311018926091,
    "GUEST": 809395293002137620,
}

GUILD_RANK_ROLE_IDS = {
    0: ROLE_IDS["RL"],
    1: ROLE_IDS["BANNER_BEARER"],
    2: ROLE_IDS["SERGEANT"],
    3: ROLE_IDS["CHRONICLER"],
    4: ROLE_IDS["RECRUIT"],
}

if ROLE_IDS["FRIENDS"] in GUILD_RANK_ROLE_IDS.values():
    raise RuntimeError("Роль «Друзья» не должна управляться синхронизацией")

GUEST_ROLE_ID = ROLE_IDS["GUEST"]
TARGET_CHANNEL_IDS = {1273720411045232721, 1263306154499641371}
MAX_CHANNELS_PER_USER = 1
MAX_USERS_PER_TEMP_CHANNEL = 10
GUEST_ROLE_DURATION_DAYS = 7
EMPTY_CHANNEL_DURATION_SECONDS = 300
GUILD_ROLE_REMOVAL_GRACE_HOURS = 48
BLIZZARD_MIN_REQUEST_INTERVAL_SECONDS = 30
BLIZZARD_ROSTER_CACHE_SECONDS = 300
BLIZZARD_SPECIALIZATION_CACHE_SECONDS = 900
BLIZZARD_API_FAILURE_ALERT_THRESHOLD = 3
RAID_LATE_AFTER_MINUTES = 15
RAID_MIN_ATTENDANCE_PERCENT = 60
BACKUP_RETENTION_DAYS = 30

# Старые напоминания остаются доступными, но не запускаются без этих .env.
REMINDER_CHANNEL_ID = _int_env("REMINDER_CHANNEL_ID")
REMINDER_ROLE_ID = _int_env("REMINDER_ROLE_ID")
REMINDER_USER_ID = _int_env("REMINDER_USER_ID")
FRZOK_USER_ID = _int_env("FRZOK_USER_ID", 197371266007564289)
PIDOR_CHANNEL_ID = _int_env("PIDOR_CHANNEL_ID", 810474409755541524)

# Blizzard Battle.net API.
BLIZZARD_CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID", "")
BLIZZARD_CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET", "")
BLIZZARD_REGION = os.getenv("BLIZZARD_REGION", "eu").lower()
BLIZZARD_LOCALE = os.getenv("BLIZZARD_LOCALE", "ru_RU")
BLIZZARD_REALM_SLUG = _blizzard_slug_env("BLIZZARD_REALM_SLUG")
BLIZZARD_GUILD_SLUG = _blizzard_slug_env("BLIZZARD_GUILD_SLUG")

# Необязательная карта вида {"Discord ID": ["Персонаж", "Альт"]}.
# Она имеет приоритет над сопоставлением по Discord-нику.
try:
    DISCORD_CHARACTER_LINKS = {
        int(discord_id): list(names)
        for discord_id, names in json.loads(
            os.getenv("DISCORD_CHARACTER_LINKS", "{}")
        ).items()
    }
except (ValueError, TypeError, json.JSONDecodeError) as error:
    raise RuntimeError("Некорректный JSON в DISCORD_CHARACTER_LINKS") from error

_configured_character_owners: dict[str, int] = {}
for _discord_id, _character_names in DISCORD_CHARACTER_LINKS.items():
    for _character_name in _character_names:
        _normalized_name = _character_name.strip().casefold()
        _existing_owner = _configured_character_owners.get(_normalized_name)
        if _existing_owner is not None and _existing_owner != _discord_id:
            raise RuntimeError(
                f"Персонаж {_character_name} повторно указан в "
                "DISCORD_CHARACTER_LINKS"
            )
        _configured_character_owners[_normalized_name] = _discord_id

PROJECT_DIR = Path(__file__).resolve().parent
_state_path = Path(os.getenv("STATE_DB_PATH", "bot_state.sqlite3"))
STATE_DB_PATH = str(
    _state_path if _state_path.is_absolute() else PROJECT_DIR / _state_path
)
BACKUP_DIR = str(PROJECT_DIR / "backups")

MESSAGES = {
    "WELCOME_MESSAGE": (
        "Добро пожаловать! Тебе присвоена роль «Сержант». "
        "Пожалуйста, проверь необходимые аддоны, WeakAuras и тактики до рейда."
    ),
    "NO_CANDIDATES": "Не нашёл подходящих кандидатов для выбора.",
    "PIDORS_OF_THE_WEEK": "Итак, статистика этой недели:\n",
    "NO_PIDORS": "На этой неделе ещё никто не был выбран.",
}
