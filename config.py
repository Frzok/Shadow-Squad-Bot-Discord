"""Настройки Shadow Squad Bot.

Секреты берутся из .env, а Discord ID оставлены в коде: эта сборка работает
только на сервере Shadow Squad.
"""

from __future__ import annotations

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


def _int_set_env(name: str) -> set[int]:
    value = os.getenv(name, "")
    try:
        return {
            int(item)
            for item in re.split(r"[\s,;]+", value.strip())
            if item
        }
    except ValueError as conversion_error:
        raise RuntimeError(
            f"{name} должен содержать Discord ID через запятую"
        ) from conversion_error


DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()

GUILD_ID = 604571954422218752
SYNC_LOG_CHANNEL_ID = 723427989521432628
STREAM_ANNOUNCEMENT_CHANNEL_ID = 604573142404562964
RAID_ANNOUNCEMENT_CHANNEL_ID = 809402292284686346
RAID_VOICE_CHANNEL_ID = 713419816857370624
RAID_ABSENCE_CHANNEL_ID = 1200807297111306280
TACTICS_CHANNEL_ID = 1485886206817599569
TACTICS_NOTIFICATION_CHANNEL_ID = 810474409755541524
LOOT_HISTORY_CHANNEL_ID = 1055007278593482822
RAID_ANALYSIS_CHANNEL_ID = 1345828084640776343
RAID_NOTICE_EMOJI = "✅"
# noinspection SpellCheckingInspection
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
    "FRIENDS": 632173311018926091,
    "GUEST": 809395293002137620,
}

GUILD_RANK_ROLE_IDS = {
    0: ROLE_IDS["RL"],
    1: ROLE_IDS["BANNER_BEARER"],
    2: ROLE_IDS["SERGEANT"],
    3: ROLE_IDS["CHRONICLER"],
}

if ROLE_IDS["FRIENDS"] in GUILD_RANK_ROLE_IDS.values():
    raise RuntimeError("Роль «Друзья» не должна управляться синхронизацией")

GUEST_ROLE_ID = ROLE_IDS["GUEST"]
TARGET_CHANNEL_IDS = {1263306154499641371}
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
TACTICS_REMINDER_DELAY_HOURS = 24
WOWAUDIT_LOOT_CACHE_SECONDS = 120
RAID_LOOT_REPORT_DELAY_MINUTES = 5
RAID_LOOT_REPORT_RETRY_MINUTES = 5
WARCRAFTLOGS_REPORT_DELAY_MINUTES = 15
WARCRAFTLOGS_REPORT_RETRY_MINUTES = 15
WARCRAFTLOGS_REPORT_MAX_AGE_HOURS = 24
HEALTH_CHECK_INTERVAL_MINUTES = 10
HEALTH_ALERT_COOLDOWN_MINUTES = 60

FRZOK_USER_ID = _int_env("FRZOK_USER_ID", 197371266007564289)
PIDOR_CHANNEL_ID = _int_env("PIDOR_CHANNEL_ID", 810474409755541524)
PIDOR_EXCLUDED_USER_IDS = _int_set_env("PIDOR_EXCLUDED_USER_IDS")
HEALTH_ALERT_CHANNEL_ID = _int_env(
    "HEALTH_ALERT_CHANNEL_ID", SYNC_LOG_CHANNEL_ID
)

# Автоматическое объявление РТ по пятницам и воскресеньям в 20:30 МСК.
REMINDER_CHANNEL_ID = RAID_ANNOUNCEMENT_CHANNEL_ID
REMINDER_ROLE_ID = ROLE_IDS["SERGEANT"]
REMINDER_USER_ID = FRZOK_USER_ID

# Blizzard Battle.net API.
BLIZZARD_CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID", "")
BLIZZARD_CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET", "")
BLIZZARD_REGION = os.getenv("BLIZZARD_REGION", "eu").lower()
BLIZZARD_LOCALE = os.getenv("BLIZZARD_LOCALE", "ru_RU")
BLIZZARD_REALM_SLUG = _blizzard_slug_env("BLIZZARD_REALM_SLUG")
BLIZZARD_GUILD_SLUG = _blizzard_slug_env("BLIZZARD_GUILD_SLUG")

# WoW Audit API для истории лута RCLootCouncil.
WOWAUDIT_API_KEY = os.getenv("WOWAUDIT_API_KEY", "").strip()

# Warcraft Logs API v2. Работает с публичными отчётами через client credentials.
WARCRAFTLOGS_CLIENT_ID = os.getenv("WARCRAFTLOGS_CLIENT_ID", "").strip()
WARCRAFTLOGS_CLIENT_SECRET = os.getenv(
    "WARCRAFTLOGS_CLIENT_SECRET", ""
).strip()
WARCRAFTLOGS_GUILD_NAME = os.getenv(
    "WARCRAFTLOGS_GUILD_NAME", "Shadow Squad"
).strip()
WARCRAFTLOGS_SERVER_SLUG = _blizzard_slug_env(
    "WARCRAFTLOGS_SERVER_SLUG"
) or BLIZZARD_REALM_SLUG
WARCRAFTLOGS_REGION = os.getenv(
    "WARCRAFTLOGS_REGION", BLIZZARD_REGION
).strip().upper()
WARCRAFTLOGS_REPORT_CHANNEL_ID = _int_env(
    "WARCRAFTLOGS_REPORT_CHANNEL_ID", RAID_ANALYSIS_CHANNEL_ID
)

# Необязательная карта вида {"Discord ID": ["Персонаж", "Альт"]}.
# Она имеет приоритет над сопоставлением по Discord-нику.
try:
    DISCORD_CHARACTER_LINKS = {
        int(discord_id): list(names)
        for discord_id, names in json.loads(
            os.getenv("DISCORD_CHARACTER_LINKS", "{}")
        ).items()
    }
except (ValueError, TypeError, json.JSONDecodeError) as links_json_error:
    raise RuntimeError(
        "Некорректный JSON в DISCORD_CHARACTER_LINKS"
    ) from links_json_error

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
    "GUEST_WELCOME_MESSAGE": (
        "# 👋 Добро пожаловать в Shadow Squad!\n\n"
        "Тебе временно выдана роль **Гости**.\n\n"
        "Если ты хочешь попасть в основной состав гильдии, напиши "
        "<@197371266007564289>.\n\n"
        "Все обращения по поводу изменения ролей, привязок персонажей "
        "или других данных также необходимо направлять "
        "<@197371266007564289>.\n\n"
        "Как Бот обрабатывает данные: "
        "[Политика конфиденциальности]"
        "(https://github.com/Frzok/Shadow-Squad-Bot-Discord/blob/main/"
        "Privacy%20Policy)."
    ),
    "WELCOME_MESSAGE": (
        "# ⚔️ Тебе присвоена роль «Сержант»!\n\n"
        "Добро пожаловать в основной состав Shadow Squad.\n\n"
        "Вступление в основной состав автоматически подтверждает, что ты "
        "ознакомился и согласен со всеми правилами гильдии. Они опубликованы "
        "в канале "
        "[👋начать-здесь]"
        "(https://discord.com/channels/604571954422218752/809368762812989440).\n\n"
        "Пожалуйста, перед рейдом проверь:\n\n"
        "• необходимые аддоны — найдёшь в "
        "[канале с аддонами]"
        "(https://discord.com/channels/604571954422218752/1485886451999703150);\n"
        "• актуальные WeakAuras;\n"
        "• тактики на боссов — можно прочитать в "
        "[канале с тактиками]"
        "(https://discord.com/channels/604571954422218752/1485886206817599569).\n\n"
        "Обязательные РТ проходят по **пятницам и воскресеньям "
        "с 21:00 до 00:00 МСК** в голосовом канале "
        "[⚔️РТ・Спец-отряд]"
        "(https://discord.com/channels/604571954422218752/713419816857370624).\n\n"
        "Если не сможешь прийти или опоздаешь, заранее напиши в "
        "[🐷отсутствия-и-опоздания]"
        "(https://discord.com/channels/604571954422218752/1200807297111306280). "
        "Когда бот поставит под сообщением ✅, предупреждение будет учтено.\n\n"
        "Если твой привязанный персонаж играет в активной специализации "
        "лекаря, бот дополнительно выдаст роль **Хила на крутилах**. "
        "Если ты получил эту роль, хиловское обсуждение проходит в канале "
        "[💚чат-хилов]"
        "(https://discord.com/channels/604571954422218752/1279440882679939133).\n\n"
        "Все обращения по поводу изменения ролей, привязок персонажей "
        "или других данных необходимо направлять <@197371266007564289>.\n\n"
        "Как Бот обрабатывает данные: "
        "[Политика конфиденциальности]"
        "(https://github.com/Frzok/Shadow-Squad-Bot-Discord/blob/main/"
        "Privacy%20Policy)."
    ),
    "NO_CANDIDATES": "Не нашёл подходящих кандидатов для выбора.",
    "PIDORS_OF_THE_WEEK": "Итак, статистика этой недели:\n",
    "NO_PIDORS": "На этой неделе ещё никто не был выбран.",
}
