from __future__ import annotations

import asyncio
import logging
import random
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from blizzard import BlizzardAPIError, BlizzardClient, GuildCharacter
from storage import StateStore


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("shadow-squad-bot")

MSK = timezone(timedelta(hours=3), "MSK")
UTC = timezone.utc

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
store = StateStore(config.STATE_DB_PATH)
blizzard = BlizzardClient(
    config.BLIZZARD_CLIENT_ID,
    config.BLIZZARD_CLIENT_SECRET,
    config.BLIZZARD_REGION,
    config.BLIZZARD_LOCALE,
    config.BLIZZARD_REALM_SLUG,
    config.BLIZZARD_GUILD_SLUG,
)
startup_complete = False
role_sync_lock = asyncio.Lock()
roster_fetch_lock = asyncio.Lock()
character_profile_semaphore = asyncio.Semaphore(4)
pidor_lock = asyncio.Lock()
attendance_lock = asyncio.Lock()
last_roster_request_monotonic = 0.0
specialization_role_cache: dict[int, str] = {}
suppressed_role_events: dict[tuple[int, int, str], float] = {}
PROCESS_STARTED_AT = datetime.now(MSK)

ATTENDANCE_STATUS_LABELS = {
    "present": "Присутствовал",
    "late": "Опоздал",
    "reserve": "Резерв",
    "excused": "Предупреждённый пропуск",
    "absent": "Отсутствовал",
    "pending": "Ожидает проверки",
}


def utc_timestamp() -> float:
    return datetime.now(UTC).timestamp()


def current_stats_period() -> str:
    """Метка последней среды 05:00 МСК."""
    now = datetime.now(MSK)
    days_since_wednesday = (now.weekday() - 2) % 7
    boundary = (now - timedelta(days=days_since_wednesday)).replace(
        hour=5, minute=0, second=0, microsecond=0
    )
    if boundary > now:
        boundary -= timedelta(days=7)
    return boundary.isoformat()


def normalize_character_name(value: str) -> str:
    return value.strip().casefold()


def parse_state_int(key: str) -> int:
    try:
        return int(store.get_state(key) or "0")
    except ValueError:
        return 0


def format_msk_timestamp(value: str | None) -> str:
    if not value:
        return "нет"
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(MSK).strftime("%d.%m.%Y %H:%M:%S МСК")
    except ValueError:
        return value


def next_role_sync_time(now: datetime | None = None) -> datetime:
    current = now or datetime.now(MSK)
    for hour in (8, 13, 19):
        candidate = current.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate > current:
            return candidate
    return (current + timedelta(days=1)).replace(
        hour=8, minute=0, second=0, microsecond=0
    )


def next_weekly_reset_time(now: datetime | None = None) -> datetime:
    current = now or datetime.now(MSK)
    days_ahead = (2 - current.weekday()) % 7
    candidate = (current + timedelta(days=days_ahead)).replace(
        hour=5, minute=0, second=0, microsecond=0
    )
    if candidate <= current:
        candidate += timedelta(days=7)
    return candidate


def parse_raid_date(value: str) -> datetime:
    for format_string in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(value.strip(), format_string)
            return parsed.replace(tzinfo=MSK)
        except ValueError:
            continue
    raise ValueError("Используйте дату в формате ДД.ММ.ГГГГ")


def next_main_raid_date(now: datetime | None = None) -> datetime:
    current = now or datetime.now(MSK)
    if current.weekday() in (4, 6):
        return current.replace(hour=0, minute=0, second=0, microsecond=0)
    for days_ahead in range(1, 8):
        candidate = current + timedelta(days=days_ahead)
        if candidate.weekday() in (4, 6):
            return candidate.replace(hour=0, minute=0, second=0, microsecond=0)
    raise RuntimeError("Не удалось определить ближайшее РТ")


def raid_date_from_notice(content: str) -> datetime:
    match = re.search(
        r"(?<!\d)(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?!\d)",
        content,
    )
    if not match:
        return next_main_raid_date()
    day, month, year_text = match.groups()
    now = datetime.now(MSK)
    year = int(year_text) if year_text else now.year
    if year < 100:
        year += 2000
    try:
        result = datetime(year, int(month), int(day), tzinfo=MSK)
    except ValueError as error:
        raise ValueError("В сообщении указана некорректная дата") from error
    if not year_text and result.date() < now.date() - timedelta(days=1):
        result = result.replace(year=year + 1)
    if result.weekday() not in (4, 6):
        raise ValueError("Указанная дата не является пятницей или воскресеньем")
    return result


async def save_notice_message(
    message: discord.Message,
    member_id: int,
    raid_date: datetime,
    reason: str,
) -> None:
    await message.add_reaction(config.RAID_NOTICE_EMOJI)
    store.save_raid_notice(
        message.id,
        message.channel.id,
        raid_date.date().isoformat(),
        member_id,
        config.RAID_NOTICE_EMOJI,
        reason.strip() or "Предупреждение без текста",
        utc_timestamp(),
    )
    session = store.raid_session_by_date(raid_date.date().isoformat())
    if session and session["status"] in ("draft", "confirmed"):
        record = next(
            (
                item
                for item in store.attendance_records(int(session["id"]))
                if item["member_id"] == member_id
            ),
            None,
        )
        if record and record["status"] not in ("present", "late", "reserve"):
            store.set_attendance_status(
                int(session["id"]),
                member_id,
                "excused",
                reason.strip() or "Предупреждение без текста",
                source="absence",
            )


def recalculate_after_notice_removal(raid_date: str, member_id: int) -> None:
    session = store.raid_session_by_date(raid_date)
    if not session or session["status"] not in ("draft", "confirmed"):
        return
    record = next(
        (
            item
            for item in store.attendance_records(int(session["id"]))
            if item["member_id"] == member_id
        ),
        None,
    )
    if not record or record["status"] != "excused" or record["source"] != "absence":
        return
    planned_start, planned_end = raid_window(raid_date)
    minimum_seconds = (
        (planned_end - planned_start).total_seconds()
        * config.RAID_MIN_ATTENDANCE_PERCENT
        / 100
    )
    if record["present_seconds"] >= minimum_seconds:
        late_boundary = (
            planned_start + timedelta(minutes=config.RAID_LATE_AFTER_MINUTES)
        ).timestamp()
        status = (
            "late"
            if record["first_join_at"] and record["first_join_at"] > late_boundary
            else "present"
        )
    else:
        status = "absent"
    store.set_attendance_status(
        int(session["id"]),
        member_id,
        status,
        "Предупреждение отозвано удалением реакции",
        source="automatic",
    )


def revoke_raid_notice(message_id: int) -> None:
    notice = store.remove_raid_notice(message_id)
    if notice:
        recalculate_after_notice_removal(
            notice["raid_date"], int(notice["member_id"])
        )


async def reconcile_raid_notice_reactions() -> None:
    cutoff = (datetime.now(MSK).date() - timedelta(days=1)).isoformat()
    for notice in store.all_raid_notices():
        if notice["raid_date"] < cutoff:
            continue
        channel = bot.get_channel(int(notice["channel_id"]))
        if channel is None or not hasattr(channel, "fetch_message"):
            continue
        try:
            message = await channel.fetch_message(int(notice["message_id"]))
        except discord.NotFound:
            revoke_raid_notice(int(notice["message_id"]))
            continue
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Не удалось проверить реакцию предупреждения")
            continue
        reaction_exists = any(
            str(reaction.emoji) == notice["emoji"] and reaction.me
            for reaction in message.reactions
        )
        if not reaction_exists:
            revoke_raid_notice(int(notice["message_id"]))


def raid_window(raid_date: str) -> tuple[datetime, datetime]:
    date_value = datetime.strptime(raid_date, "%Y-%m-%d").replace(tzinfo=MSK)
    start = date_value.replace(hour=21, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start, end


def raid_voice_member_ids(guild: discord.Guild) -> set[int]:
    channel = guild.get_channel(config.RAID_VOICE_CHANNEL_ID)
    if not isinstance(channel, discord.VoiceChannel):
        return set()
    return {member.id for member in channel.members if not member.bot}


def temporary_channel_name(member: discord.Member) -> str:
    return (member.nick or member.display_name or member.name)[:100]


def eligible_raid_members(guild: discord.Guild) -> set[discord.Member]:
    role_ids = set(config.GUILD_RANK_ROLE_IDS.values())
    return {
        member
        for role in guild.roles
        if role.id in role_ids
        for member in role.members
        if not member.bot
    }


async def start_raid_attendance(
    guild: discord.Guild,
    raid_date: str | None = None,
    started_at: float | None = None,
) -> tuple[int, bool]:
    async with attendance_lock:
        active = store.active_raid_session()
        if active:
            return int(active["id"]), False
        date_key = raid_date or datetime.now(MSK).date().isoformat()
        start_timestamp = started_at or utc_timestamp()
        session_id = store.create_raid_session(date_key, start_timestamp)
        for member in eligible_raid_members(guild):
            store.ensure_attendance_member(session_id, member.id)
        for member_id in raid_voice_member_ids(guild):
            store.attendance_enter(session_id, member_id, utc_timestamp())
        logger.info("Начат учёт посещаемости РТ %s, сессия %s", date_key, session_id)
        return session_id, True


async def finish_raid_attendance(
    guild: discord.Guild,
    ended_at: float | None = None,
) -> tuple[int | None, dict[str, int]]:
    async with attendance_lock:
        session = store.active_raid_session()
        if not session:
            return None, {}
        session_id = int(session["id"])
        end_timestamp = ended_at or utc_timestamp()
        store.attendance_heartbeat(session_id, set(), end_timestamp)
        absences = store.absences_for_date(session["raid_date"])
        planned_start, planned_end = raid_window(session["raid_date"])
        planned_seconds = (planned_end - planned_start).total_seconds()
        minimum_seconds = (
            planned_seconds * config.RAID_MIN_ATTENDANCE_PERCENT / 100
        )
        late_boundary = (
            planned_start + timedelta(minutes=config.RAID_LATE_AFTER_MINUTES)
        ).timestamp()

        counts = {key: 0 for key in ATTENDANCE_STATUS_LABELS}
        for record in store.attendance_records(session_id):
            if record["status"] != "pending":
                status = record["status"]
            elif record["present_seconds"] >= minimum_seconds:
                status = (
                    "late"
                    if record["first_join_at"]
                    and record["first_join_at"] > late_boundary
                    else "present"
                )
                store.set_attendance_status(
                    session_id,
                    record["member_id"],
                    status,
                    source="automatic",
                )
            elif record["member_id"] in absences:
                status = "excused"
                store.set_attendance_status(
                    session_id,
                    record["member_id"],
                    status,
                    absences[record["member_id"]],
                    source="absence",
                )
            else:
                status = "absent"
                note = (
                    f"В голосовом канале {int(record['present_seconds'] // 60)} мин."
                    if record["present_seconds"]
                    else ""
                )
                store.set_attendance_status(
                    session_id,
                    record["member_id"],
                    status,
                    note,
                    source="automatic",
                )
            counts[status] = counts.get(status, 0) + 1

        store.finish_raid_session(session_id, end_timestamp, status="draft")
        announcement_channel = bot.get_channel(config.RAID_ANNOUNCEMENT_CHANNEL_ID)
        if announcement_channel and hasattr(announcement_channel, "send"):
            await announcement_channel.send(
                f"📊 Черновик посещаемости РТ за {session['raid_date']} готов. "
                f"Присутствовали: {counts.get('present', 0)}, "
                f"опоздали: {counts.get('late', 0)}, "
                f"резерв: {counts.get('reserve', 0)}, "
                f"предупредили: {counts.get('excused', 0)}, "
                f"отсутствовали: {counts.get('absent', 0)}. "
                "Проверьте `/attendance_current` и подтвердите "
                "через `/attendance_confirm`."
            )
        logger.info("РТ-сессия %s переведена в черновик", session_id)
        return session_id, counts


async def reconcile_raid_attendance(guild: discord.Guild) -> None:
    now = datetime.now(MSK)
    active = store.active_raid_session()
    if active:
        _, planned_end = raid_window(active["raid_date"])
        if now >= planned_end:
            await finish_raid_attendance(guild, ended_at=planned_end.timestamp())
        else:
            store.attendance_heartbeat(
                int(active["id"]), raid_voice_member_ids(guild), utc_timestamp()
            )
        return
    if now.weekday() in (4, 6) and now.hour >= 21:
        planned_start = now.replace(hour=21, minute=0, second=0, microsecond=0)
        try:
            await start_raid_attendance(
                guild,
                raid_date=now.date().isoformat(),
                started_at=planned_start.timestamp(),
            )
        except ValueError:
            pass


@tasks.loop(minutes=1)
async def attendance_heartbeat() -> None:
    session = store.active_raid_session()
    guild = bot.get_guild(config.GUILD_ID)
    if not session or guild is None:
        return
    store.attendance_heartbeat(
        int(session["id"]), raid_voice_member_ids(guild), utc_timestamp()
    )


@tasks.loop(time=datetime.min.replace(hour=21, minute=0, tzinfo=MSK).timetz())
async def scheduled_attendance_start() -> None:
    now = datetime.now(MSK)
    guild = bot.get_guild(config.GUILD_ID)
    if guild is None or now.weekday() not in (4, 6):
        return
    try:
        await start_raid_attendance(
            guild,
            raid_date=now.date().isoformat(),
            started_at=now.replace(hour=21, minute=0, second=0, microsecond=0).timestamp(),
        )
    except ValueError:
        logger.warning("Сессия посещаемости за сегодня уже существует")


@tasks.loop(time=datetime.min.replace(hour=0, minute=0, tzinfo=MSK).timetz())
async def scheduled_attendance_end() -> None:
    now = datetime.now(MSK)
    guild = bot.get_guild(config.GUILD_ID)
    if guild is None or now.weekday() not in (0, 5):
        return
    await finish_raid_attendance(guild)


def backup_files() -> list[Path]:
    directory = Path(config.BACKUP_DIR)
    if not directory.exists():
        return []
    return sorted(
        (
            path
            for path in directory.glob("*.sqlite3")
            if path.is_file()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def create_database_backup(label: str = "daily") -> Path:
    directory = Path(config.BACKUP_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(MSK).strftime("%Y%m%d_%H%M%S")
    destination = directory / f"bot_state_{stamp}_{label}.sqlite3"
    store.backup_to(destination)
    cutoff = time.time() - config.BACKUP_RETENTION_DAYS * 86400
    for old_backup in backup_files():
        if old_backup.stat().st_mtime < cutoff:
            old_backup.unlink()
    return destination


@tasks.loop(time=datetime.min.replace(hour=4, minute=30, tzinfo=MSK).timetz())
async def scheduled_database_backup() -> None:
    try:
        backup = await asyncio.to_thread(create_database_backup, "daily")
        logger.info("Создана резервная копия %s", backup.name)
    except (OSError, sqlite3.Error):
        logger.exception("Не удалось создать ежедневную резервную копию")


def cached_guild_roster() -> tuple[list[GuildCharacter], float | None]:
    rows, fetched_at = store.load_roster()
    return (
        [
            GuildCharacter(name=name, realm_slug=realm, rank=rank)
            for name, realm, rank in rows
        ],
        fetched_at,
    )


async def fetch_guild_roster(force: bool = False) -> list[GuildCharacter]:
    """Получает состав с кэшем, лимитом частоты и учётом ошибок API."""
    global last_roster_request_monotonic

    cached, fetched_at = cached_guild_roster()
    now_epoch = utc_timestamp()
    cache_is_fresh = bool(
        cached
        and fetched_at
        and now_epoch - fetched_at <= config.BLIZZARD_ROSTER_CACHE_SECONDS
    )
    if cache_is_fresh and not force:
        return cached

    async with roster_fetch_lock:
        cached, fetched_at = cached_guild_roster()
        now_epoch = utc_timestamp()
        since_request = time.monotonic() - last_roster_request_monotonic
        cache_is_fresh = bool(
            cached
            and fetched_at
            and now_epoch - fetched_at <= config.BLIZZARD_ROSTER_CACHE_SECONDS
        )
        if (
            cache_is_fresh
            and (
                not force
                or since_request < config.BLIZZARD_MIN_REQUEST_INTERVAL_SECONDS
            )
        ):
            return cached

        last_roster_request_monotonic = time.monotonic()
        try:
            roster = await blizzard.guild_roster()
        except BlizzardAPIError as error:
            failures = parse_state_int("api_failure_count") + 1
            store.set_state("api_failure_count", str(failures))
            store.set_state("last_api_error", str(error))
            store.set_state("last_api_error_at", datetime.now(MSK).isoformat())
            threshold = config.BLIZZARD_API_FAILURE_ALERT_THRESHOLD
            if failures >= threshold and (
                failures == threshold or failures % threshold == 0
            ):
                logger.error(
                    "Blizzard API недоступен уже %s раз подряд: %s",
                    failures,
                    error,
                )
            raise

        fetched_at = utc_timestamp()
        store.save_roster(
            [
                (character.name, character.realm_slug, character.rank)
                for character in roster
            ],
            fetched_at,
        )
        store.set_state("last_roster_fetch", datetime.now(MSK).isoformat())
        store.set_state("last_roster_size", str(len(roster)))
        store.set_state("api_failure_count", "0")
        return roster


def member_character_candidates(member: discord.Member) -> set[str]:
    explicit = list(config.DISCORD_CHARACTER_LINKS.get(member.id, []))
    explicit.extend(store.linked_characters(member.id))
    if explicit:
        return {normalize_character_name(name) for name in explicit}

    candidates: set[str] = set()
    for value in (member.nick, member.global_name, member.name):
        if not value:
            continue
        candidates.add(normalize_character_name(value))
        # Поддерживает ники вроде "Персонаж | Имя" и "Персонаж-Сервер".
        parts = re.findall(r"[^\W\d_]+", value, flags=re.UNICODE)
        candidates.update(normalize_character_name(part) for part in parts)
    return candidates


def configured_link_owner(character_name: str) -> int | None:
    normalized = normalize_character_name(character_name)
    for member_id, names in config.DISCORD_CHARACTER_LINKS.items():
        if any(normalize_character_name(name) == normalized for name in names):
            return member_id
    return None


def highest_guild_character(
    member: discord.Member, roster: list[GuildCharacter]
) -> GuildCharacter | None:
    names = member_character_candidates(member)
    matches = [
        character.rank
        for character in roster
        if normalize_character_name(character.name) in names
    ]
    if not matches:
        return None
    highest_rank = min(matches)
    return next(
        character
        for character in roster
        if character.rank == highest_rank
        and normalize_character_name(character.name) in names
    )


async def character_specialization(
    character: GuildCharacter,
) -> tuple[str, str]:
    cached = store.get_character_spec(character.name, character.realm_slug)
    now = utc_timestamp()
    if (
        cached
        and now - cached[3] <= config.BLIZZARD_SPECIALIZATION_CACHE_SECONDS
    ):
        _, spec_name, role_type, _ = cached
        return spec_name, role_type

    async with character_profile_semaphore:
        cached = store.get_character_spec(character.name, character.realm_slug)
        now = utc_timestamp()
        if (
            cached
            and now - cached[3] <= config.BLIZZARD_SPECIALIZATION_CACHE_SECONDS
        ):
            _, spec_name, role_type, _ = cached
            return spec_name, role_type

        spec_id, spec_name = await blizzard.character_active_spec(
            character.name, character.realm_slug
        )
        role_type = specialization_role_cache.get(spec_id)
        if role_type is None:
            role_type = await blizzard.specialization_role(spec_id)
            specialization_role_cache[spec_id] = role_type
        store.save_character_spec(
            character.name,
            character.realm_slug,
            spec_id,
            spec_name,
            role_type,
            now,
        )
        return spec_name, role_type


async def member_healer_status(
    member: discord.Member,
    roster: list[GuildCharacter],
    report: list[str],
) -> bool | None:
    candidates = member_character_candidates(member)
    characters = [
        character
        for character in roster
        if normalize_character_name(character.name) in candidates
    ]
    had_error = False
    for character in characters:
        try:
            spec_name, role_type = await character_specialization(character)
        except BlizzardAPIError as error:
            had_error = True
            report.append(
                f"⚠️ Не удалось определить специализацию {character.name}: {error}"
            )
            continue
        report.append(
            f"🩺 {character.name}: специализация {spec_name}, роль {role_type}"
        )
        if role_type == "HEALER":
            return True
    if had_error:
        return None
    return False


async def send_sync_log(lines: list[str]) -> None:
    """Отправляет отчёт частями, не превышающими лимит Discord."""
    if not lines:
        return
    channel = bot.get_channel(config.SYNC_LOG_CHANNEL_ID)
    if channel is None or not hasattr(channel, "send"):
        logger.warning("Канал журнала синхронизации %s не найден", config.SYNC_LOG_CHANNEL_ID)
        return

    chunks: list[str] = []
    current = ""
    for original_line in lines:
        pieces = [
            original_line[index : index + 1900]
            for index in range(0, max(len(original_line), 1), 1900)
        ]
        for line in pieces:
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) > 1900:
                chunks.append(current)
                current = line
            else:
                current = candidate
    if current:
        chunks.append(current)

    for chunk in chunks:
        try:
            await channel.send(chunk)
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Не удалось отправить сообщение в журнал синхронизации")
            return


def suppress_role_event(member_id: int, role_id: int, action: str) -> None:
    suppressed_role_events[(member_id, role_id, action)] = time.monotonic() + 60


async def add_roles_automatically(
    member: discord.Member,
    roles: list[discord.Role],
    reason: str,
    character_name: str | None = None,
) -> None:
    if not roles:
        return
    for role in roles:
        suppress_role_event(member.id, role.id, "added")
    try:
        await member.add_roles(*roles, reason=reason)
    except Exception:
        for role in roles:
            suppressed_role_events.pop((member.id, role.id, "added"), None)
        raise
    for role in roles:
        store.add_role_history(
            utc_timestamp(),
            member.id,
            role.id,
            "added",
            "automatic",
            actor_id=bot.user.id if bot.user else None,
            character_name=character_name,
            reason=reason,
        )


async def remove_roles_automatically(
    member: discord.Member,
    roles: list[discord.Role],
    reason: str,
    character_name: str | None = None,
) -> None:
    if not roles:
        return
    for role in roles:
        suppress_role_event(member.id, role.id, "removed")
    try:
        await member.remove_roles(*roles, reason=reason)
    except Exception:
        for role in roles:
            suppressed_role_events.pop((member.id, role.id, "removed"), None)
        raise
    for role in roles:
        store.add_role_history(
            utc_timestamp(),
            member.id,
            role.id,
            "removed",
            "automatic",
            actor_id=bot.user.id if bot.user else None,
            character_name=character_name,
            reason=reason,
        )


async def apply_guild_rank(
    member: discord.Member,
    roster: list[GuildCharacter],
    report: list[str],
) -> tuple[bool, bool, int]:
    bot_member = member.guild.me
    if bot_member is None or member.top_role >= bot_member.top_role:
        report.append(f"⏭️ Пропущен {member.display_name} (роль выше/равна боту)")
        return False, False, 0

    managed_ids = set(config.GUILD_RANK_ROLE_IDS.values())
    current_managed_roles = [
        role for role in member.roles if role.id in managed_ids
    ]
    healer_role = member.guild.get_role(config.ROLE_IDS["HILA_NA_KRUTILAH"])
    current_healer_role = (
        healer_role if healer_role and healer_role in member.roles else None
    )
    character = highest_guild_character(member, roster)
    if character is None:
        removed = 0
        roles_to_remove = list(current_managed_roles)
        if current_healer_role:
            roles_to_remove.append(current_healer_role)
        if roles_to_remove:
            first_missing = store.get_absence(member.id)
            now = utc_timestamp()
            grace_seconds = config.GUILD_ROLE_REMOVAL_GRACE_HOURS * 3600
            if first_missing is None:
                store.set_guild_absence(member.id, now)
                report.append(
                    f"⏳ {member.display_name} не найден в гильдии. "
                    f"Запущен период ожидания {config.GUILD_ROLE_REMOVAL_GRACE_HOURS} ч."
                )
            elif now - first_missing < grace_seconds:
                remaining_hours = max(
                    1, int((grace_seconds - (now - first_missing) + 3599) // 3600)
                )
                report.append(
                    f"⏳ {member.display_name} не найден в гильдии. "
                    f"До снятия роли около {remaining_hours} ч."
                )
            else:
                reason = "Персонаж отсутствует в Blizzard после периода ожидания"
                await remove_roles_automatically(
                    member, roles_to_remove, reason=reason
                )
                for role in roles_to_remove:
                    report.append(
                        f"⚠️ Удалена роль {role.mention} у {member.display_name}: "
                        f"не найден в гильдии более "
                        f"{config.GUILD_ROLE_REMOVAL_GRACE_HOURS} ч."
                    )
                    removed += 1
        return bool(removed), False, removed

    store.clear_absence(member.id)
    report.append(
        f"🔎 {member.display_name} — "
        f"{normalize_character_name(character.name)}, rank: {character.rank}"
    )
    role_id = config.GUILD_RANK_ROLE_IDS.get(character.rank)
    if role_id is None:
        report.append(
            f"⚠️ Для ранга {character.rank} персонажа {character.name} "
            "не настроена Discord-роль"
        )
        return False, True, 0

    target_role = member.guild.get_role(role_id)
    if target_role is None:
        report.append(f"⚠️ Discord-роль для ранга {character.rank} не найдена")
        return False, True, 0
    if target_role >= bot_member.top_role:
        report.append(
            f"⏭️ Пропущен {member.display_name}: роль {target_role.name} "
            "выше/равна роли бота"
        )
        return False, True, 0

    obsolete_roles = [
        role for role in current_managed_roles if role.id != target_role.id
    ]
    reason = "Синхронизация ранга с составом Blizzard"
    changed = bool(obsolete_roles or target_role not in member.roles)
    # Сначала добавляем новую роль: при временной ошибке участник не останется
    # вообще без своей гильдейской роли.
    if target_role not in member.roles:
        await add_roles_automatically(
            member,
            [target_role],
            reason=reason,
            character_name=character.name,
        )
        report.append(
            f"✅ Добавлена роль {target_role.mention} игроку "
            f"{member.display_name} ({normalize_character_name(character.name)})"
        )
    if obsolete_roles:
        await remove_roles_automatically(
            member,
            obsolete_roles,
            reason=reason,
            character_name=character.name,
        )
        for role in obsolete_roles:
            report.append(f"❌ Удалена роль {role.mention} у {member.display_name}")

    removed_count = len(obsolete_roles)
    if healer_role is None:
        report.append("⚠️ Discord-роль «Хила на крутилах» не найдена")
    elif healer_role >= bot_member.top_role:
        report.append(
            f"⏭️ Нельзя изменить роль {healer_role.name}: она выше/равна роли бота"
        )
    elif character.rank == 2:
        healer_status = await member_healer_status(member, roster, report)
        if healer_status is True and healer_role not in member.roles:
            await add_roles_automatically(
                member,
                [healer_role],
                reason="Сержант играет в специализации лекаря",
                character_name=character.name,
            )
            report.append(
                f"✅ Добавлена роль {healer_role.mention} игроку "
                f"{member.display_name}"
            )
            changed = True
        elif healer_status is False and current_healer_role:
            await remove_roles_automatically(
                member,
                [healer_role],
                reason="У Сержанта нет активной специализации лекаря",
                character_name=character.name,
            )
            report.append(
                f"❌ Удалена роль {healer_role.mention} у {member.display_name}: "
                "активная специализация не лекарь"
            )
            changed = True
            removed_count += 1
    elif current_healer_role:
        await remove_roles_automatically(
            member,
            [healer_role],
            reason="Роль лекаря доступна только Сержантам",
            character_name=character.name,
        )
        report.append(
            f"❌ Удалена роль {healer_role.mention} у {member.display_name}: "
            "гильдейский ранг не Сержант"
        )
        changed = True
        removed_count += 1

    return changed, True, removed_count


async def synchronize_guild_roles(
    member: discord.Member | None = None,
) -> tuple[bool, int, int]:
    if not blizzard.configured:
        logger.warning("Синхронизация Blizzard отключена: заполните параметры в .env")
        return False, 0, 0
    guild = bot.get_guild(config.GUILD_ID)
    if guild is None:
        logger.error("Discord-сервер %s не найден", config.GUILD_ID)
        return False, 0, 0

    async with role_sync_lock:
        try:
            roster = await fetch_guild_roster(force=member is None)
        except BlizzardAPIError as error:
            logger.exception("Не удалось получить состав гильдии Blizzard")
            return False, 0, 0

        members = [member] if member else [item for item in guild.members if not item.bot]
        report: list[str] = []
        changed = 0
        matched = 0
        removed = 0
        for guild_member in members:
            try:
                was_changed, was_matched, removed_count = await apply_guild_rank(
                    guild_member, roster, report
                )
                changed += int(was_changed)
                matched += int(was_matched)
                removed += removed_count
            except (discord.Forbidden, discord.HTTPException) as error:
                logger.exception("Не удалось обновить роли %s", guild_member)
                report.append(
                    f"❌ Ошибка обновления ролей {guild_member.display_name}: {error}"
                )
        role_changes = [
            line
            for line in report
            if line.startswith(
                ("✅ Добавлена роль", "❌ Удалена роль", "⚠️ Удалена роль")
            )
        ]
        await send_sync_log(role_changes)
        if member is None:
            store.set_state("last_sync_success", datetime.now(MSK).isoformat())
            store.set_state("last_sync_roster_size", str(len(roster)))
        logger.info(
            "Синхронизация Blizzard завершена: состав=%s, найдено=%s, "
            "изменено участников=%s, удалено ролей=%s",
            len(roster),
            matched,
            changed,
            removed,
        )
        return True, len(roster), changed


async def reconcile_persistent_state(guild: discord.Guild) -> None:
    guest_role = guild.get_role(config.GUEST_ROLE_ID)
    tracked_guests = {member_id for member_id, _ in store.guests()}

    if guest_role:
        for member in guest_role.members:
            if member.id not in tracked_guests:
                # Для ролей, выданных до обновления, используем время входа.
                assigned = member.joined_at or datetime.now(UTC)
                store.set_guest(member.id, assigned.timestamp())

    for configured_owner, character_names in config.DISCORD_CHARACTER_LINKS.items():
        for character_name in character_names:
            database_owner = store.character_link_owner(character_name)
            if database_owner is not None and database_owner != configured_owner:
                store.remove_character_links(database_owner, character_name)
                logger.warning(
                    "Удалена конфликтующая локальная привязка %s у Discord ID %s; "
                    "привязка из .env к %s имеет приоритет",
                    character_name,
                    database_owner,
                    configured_owner,
                )

    for channel_id, _, _ in store.temp_channels():
        channel = guild.get_channel(channel_id)
        if channel is None:
            store.remove_temp_channel(channel_id)
        elif isinstance(channel, discord.VoiceChannel):
            store.set_channel_empty_since(
                channel_id, None if channel.members else utc_timestamp()
            )

    period = current_stats_period()
    if store.get_state("stats_period") != period:
        store.clear_stats()
        store.set_state("stats_period", period)


@bot.event
async def on_ready() -> None:
    global startup_complete
    logger.info("Бот запущен как %s (%s)", bot.user, bot.user.id)
    if startup_complete:
        return

    guild = bot.get_guild(config.GUILD_ID)
    if guild is None:
        logger.error("Бот не видит настроенный сервер %s", config.GUILD_ID)
        return

    await reconcile_persistent_state(guild)
    await reconcile_raid_notice_reactions()
    await reconcile_raid_attendance(guild)
    if not backup_files():
        try:
            await asyncio.to_thread(create_database_backup, "initial")
        except (OSError, sqlite3.Error):
            logger.exception("Не удалось создать первоначальную резервную копию")
    # Удаляем старые глобальные версии команд, затем регистрируем актуальный
    # набор мгновенно для единственного рабочего сервера.
    global_commands = await bot.tree.sync()
    guild_commands = await bot.tree.sync(guild=discord.Object(id=config.GUILD_ID))
    logger.info(
        "Slash-команды синхронизированы: глобальных=%s, серверных=%s",
        len(global_commands),
        len(guild_commands),
    )
    for loop in (
        check_guest_roles,
        check_empty_channels,
        check_tactics_reminders,
        send_weekly_messages,
        reset_weekly_stats,
        scheduled_role_sync,
        scheduled_pidor_of_the_day,
        attendance_heartbeat,
        scheduled_attendance_start,
        scheduled_attendance_end,
        scheduled_database_backup,
    ):
        if not loop.is_running():
            loop.start()
    startup_complete = True


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    if isinstance(error, app_commands.CommandNotFound):
        message = (
            "Эта версия slash-команды устарела. Подождите обновления списка "
            "Discord и выберите команду заново."
        )
    elif isinstance(error, app_commands.MissingPermissions):
        message = "Для этой команды недостаточно прав."
    else:
        logger.error(
            "Ошибка slash-команды",
            exc_info=(type(error), error, error.__traceback__),
        )
        message = "При выполнении команды произошла ошибка. Подробности записаны в журнал."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@bot.event
async def on_member_join(member: discord.Member) -> None:
    if member.guild.id != config.GUILD_ID:
        return
    guest_role = member.guild.get_role(config.GUEST_ROLE_ID)
    if guest_role:
        await member.add_roles(guest_role, reason="Новый участник сервера")
        store.set_guest(member.id, utc_timestamp())
        try:
            await member.send(config.MESSAGES["GUEST_WELCOME_MESSAGE"])
        except (discord.Forbidden, discord.HTTPException):
            logger.info("Не удалось отправить гостевое приветствие %s", member)
    await synchronize_guild_roles(member)


@bot.event
async def on_member_remove(member: discord.Member) -> None:
    store.remove_guest(member.id)
    store.clear_absence(member.id)


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return
    if (
        message.channel.id == config.TACTICS_CHANNEL_ID
        and message.author.id == config.FRZOK_USER_ID
    ):
        store.save_tactics_reminder(
            message.id,
            message.author.id,
            message.channel.id,
            config.TACTICS_NOTIFICATION_CHANNEL_ID,
            message.created_at.timestamp()
            + config.TACTICS_REMINDER_DELAY_HOURS * 3600,
            message.created_at.timestamp(),
        )
    if message.channel.id == config.RAID_ABSENCE_CHANNEL_ID:
        try:
            raid_date = raid_date_from_notice(message.content)
            await save_notice_message(
                message,
                message.author.id,
                raid_date,
                message.content,
            )
        except ValueError as error:
            await message.reply(f"⚠️ Предупреждение не сохранено: {error}")
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Не удалось отметить предупреждение реакцией")
            await message.reply(
                "⚠️ Не удалось сохранить предупреждение: бот не смог поставить реакцию."
            )
    await bot.process_commands(message)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message) -> None:
    notice = store.raid_notice(after.id)
    if not notice or after.author.bot:
        return
    try:
        raid_date = raid_date_from_notice(after.content)
    except ValueError:
        try:
            await after.remove_reaction(config.RAID_NOTICE_EMOJI, bot.user)
        except (discord.Forbidden, discord.HTTPException):
            pass
        revoke_raid_notice(after.id)
        return
    previous_date = notice["raid_date"]
    await save_notice_message(
        after,
        after.author.id,
        raid_date,
        after.content,
    )
    if previous_date != raid_date.date().isoformat():
        recalculate_after_notice_removal(previous_date, after.author.id)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent) -> None:
    if (
        payload.channel_id == config.RAID_ABSENCE_CHANNEL_ID
        and str(payload.emoji) == config.RAID_NOTICE_EMOJI
        and store.raid_notice(payload.message_id)
    ):
        revoke_raid_notice(payload.message_id)


@bot.event
async def on_raw_reaction_clear_emoji(
    payload: discord.RawReactionClearEmojiEvent,
) -> None:
    if (
        payload.channel_id == config.RAID_ABSENCE_CHANNEL_ID
        and str(payload.emoji) == config.RAID_NOTICE_EMOJI
    ):
        revoke_raid_notice(payload.message_id)


@bot.event
async def on_raw_reaction_clear(payload: discord.RawReactionClearEvent) -> None:
    if payload.channel_id == config.RAID_ABSENCE_CHANNEL_ID:
        revoke_raid_notice(payload.message_id)


@bot.event
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent) -> None:
    if payload.channel_id == config.RAID_ABSENCE_CHANNEL_ID:
        revoke_raid_notice(payload.message_id)
    elif payload.channel_id == config.TACTICS_CHANNEL_ID:
        store.remove_tactics_reminder(payload.message_id)


@bot.event
async def on_raw_bulk_message_delete(
    payload: discord.RawBulkMessageDeleteEvent,
) -> None:
    if payload.channel_id == config.RAID_ABSENCE_CHANNEL_ID:
        for message_id in payload.message_ids:
            revoke_raid_notice(message_id)
    elif payload.channel_id == config.TACTICS_CHANNEL_ID:
        for message_id in payload.message_ids:
            store.remove_tactics_reminder(message_id)


@tasks.loop(minutes=1)
async def check_guest_roles() -> None:
    guild = bot.get_guild(config.GUILD_ID)
    if guild is None:
        return
    guest_role = guild.get_role(config.GUEST_ROLE_ID)
    cutoff = utc_timestamp() - config.GUEST_ROLE_DURATION_DAYS * 86400

    for member_id, assigned_at in store.guests():
        if assigned_at > cutoff:
            continue
        member = guild.get_member(member_id)
        if member and guest_role and guest_role in member.roles:
            try:
                await member.remove_roles(
                    guest_role, reason="Истёк срок гостевой роли"
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Не удалось снять гостевую роль с %s", member)
                continue
        store.remove_guest(member_id)


@tasks.loop(minutes=1)
async def check_empty_channels() -> None:
    guild = bot.get_guild(config.GUILD_ID)
    if guild is None:
        return
    now = utc_timestamp()
    for channel_id, _, empty_since in store.temp_channels():
        channel = guild.get_channel(channel_id)
        if channel is None:
            store.remove_temp_channel(channel_id)
            continue
        if channel.members:
            if empty_since is not None:
                store.set_channel_empty_since(channel_id, None)
            continue
        if empty_since is None:
            store.set_channel_empty_since(channel_id, now)
        elif now - empty_since >= config.EMPTY_CHANNEL_DURATION_SECONDS:
            try:
                await channel.delete(reason="Временная комната пуста")
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Не удалось удалить комнату %s", channel)
                continue
            store.remove_temp_channel(channel_id)


@tasks.loop(minutes=1)
async def check_tactics_reminders() -> None:
    guild = bot.get_guild(config.GUILD_ID)
    if guild is None:
        return

    for reminder in store.due_tactics_reminders(utc_timestamp()):
        source = guild.get_channel(int(reminder["source_channel_id"]))
        target = guild.get_channel(int(reminder["target_channel_id"]))
        if source is None or not hasattr(source, "fetch_message"):
            logger.error(
                "Канал тактик %s не найден",
                reminder["source_channel_id"],
            )
            continue
        if target is None or not hasattr(target, "send"):
            logger.error(
                "Канал уведомлений о тактиках %s не найден",
                reminder["target_channel_id"],
            )
            continue

        try:
            source_message = await source.fetch_message(int(reminder["message_id"]))
        except discord.NotFound:
            store.remove_tactics_reminder(int(reminder["message_id"]))
            continue
        except (discord.Forbidden, discord.HTTPException):
            logger.exception(
                "Не удалось проверить сообщение с тактикой %s",
                reminder["message_id"],
            )
            continue

        author = guild.get_member(int(reminder["author_id"]))
        author_name = author.display_name if author else "Frzok"
        try:
            await target.send(
                f"<@&{config.ROLE_IDS['SERGEANT']}> "
                f"**{author_name}** опубликовала новую тактику по боссам. "
                "Пожалуйста, ознакомьтесь с ней до ближайшего РТ:\n"
                f"{source_message.jump_url}"
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.exception(
                "Не удалось отправить напоминание о тактике %s",
                reminder["message_id"],
            )
            continue
        store.remove_tactics_reminder(int(reminder["message_id"]))


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    active_session = store.active_raid_session()
    if active_session:
        session_id = int(active_session["id"])
        was_in_raid = bool(
            before.channel and before.channel.id == config.RAID_VOICE_CHANNEL_ID
        )
        is_in_raid = bool(
            after.channel and after.channel.id == config.RAID_VOICE_CHANNEL_ID
        )
        if is_in_raid and not was_in_raid and not member.bot:
            store.attendance_enter(session_id, member.id, utc_timestamp())
        elif was_in_raid and not is_in_raid:
            store.attendance_leave(session_id, member.id, utc_timestamp())

    if after.channel and after.channel.id in config.TARGET_CHANNEL_IDS:
        source = after.channel
        owned_channels: list[discord.VoiceChannel] = []
        for channel_id, owner_id, _ in store.temp_channels():
            if owner_id != member.id:
                continue
            channel = member.guild.get_channel(channel_id)
            if isinstance(channel, discord.VoiceChannel):
                owned_channels.append(channel)
            else:
                store.remove_temp_channel(channel_id)

        if owned_channels:
            existing_channel = owned_channels[0]
            if not existing_channel.members:
                try:
                    await existing_channel.edit(
                        name=temporary_channel_name(member),
                        category=source.category,
                        user_limit=config.MAX_USERS_PER_TEMP_CHANNEL,
                        reason=f"Переиспользование временной комнаты для {member}",
                    )
                except (discord.Forbidden, discord.HTTPException):
                    logger.exception(
                        "Не удалось обновить временную комнату %s",
                        existing_channel,
                    )
            store.set_channel_empty_since(existing_channel.id, None)
            try:
                await member.move_to(existing_channel)
            except (discord.Forbidden, discord.HTTPException):
                logger.exception(
                    "Не удалось переместить %s в существующую комнату",
                    member,
                )
        elif len(owned_channels) < config.MAX_CHANNELS_PER_USER:
            new_channel = await member.guild.create_voice_channel(
                temporary_channel_name(member),
                category=source.category,
                user_limit=config.MAX_USERS_PER_TEMP_CHANNEL,
                reason=f"Временная комната для {member}",
            )
            store.add_temp_channel(new_channel.id, member.id)
            try:
                await member.move_to(new_channel)
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Не удалось переместить %s", member)

    if before.channel:
        tracked = {item[0] for item in store.temp_channels()}
        if before.channel.id in tracked and not before.channel.members:
            store.set_channel_empty_since(before.channel.id, utc_timestamp())
    if after.channel:
        store.set_channel_empty_since(after.channel.id, None)


@tasks.loop(time=[
    datetime.min.replace(hour=8, minute=0, tzinfo=MSK).timetz(),
    datetime.min.replace(hour=13, minute=0, tzinfo=MSK).timetz(),
    datetime.min.replace(hour=19, minute=0, tzinfo=MSK).timetz(),
])
async def scheduled_role_sync() -> None:
    await synchronize_guild_roles()


@tasks.loop(time=datetime.min.replace(hour=5, minute=0, tzinfo=MSK).timetz())
async def reset_weekly_stats() -> None:
    if datetime.now(MSK).weekday() != 2:
        return
    store.clear_stats()
    store.set_state("stats_period", current_stats_period())
    logger.info("Недельная статистика сброшена")


@tasks.loop(minutes=1)
async def send_weekly_messages() -> None:
    if not all(
        (
            config.REMINDER_CHANNEL_ID,
            config.REMINDER_ROLE_ID,
            config.REMINDER_USER_ID,
        )
    ):
        return
    now = datetime.now(MSK)
    if now.weekday() not in (4, 6) or (now.hour, now.minute) != (20, 30):
        return
    reminder_key = now.date().isoformat()
    if store.get_state("last_reminder_date") == reminder_key:
        return
    channel = bot.get_channel(config.REMINDER_CHANNEL_ID)
    if channel:
        await channel.send(
            f"<@&{config.REMINDER_ROLE_ID}> РТ Старт Сбор + в ПМ "
            f"<@{config.REMINDER_USER_ID}>"
        )
        store.set_state("last_reminder_date", reminder_key)


def select_pidor_for_today(
    guild: discord.Guild,
) -> tuple[discord.Member | None, bool]:
    today = datetime.now(MSK).date().isoformat()
    saved_date = store.get_state("pidor_date")
    saved_member_id = store.get_state("pidor_member_id")
    if saved_date == today and saved_member_id:
        try:
            selected = guild.get_member(int(saved_member_id))
        except ValueError:
            selected = None
        if selected:
            return selected, False

    eligible_role_ids = {
        config.ROLE_IDS["SERGEANT"],
        config.ROLE_IDS["HILA_NA_KRUTILAH"],
        config.ROLE_IDS["RL"],
    }
    eligible = list(
        {
            member
            for role in guild.roles
            if role.id in eligible_role_ids
            for member in role.members
            if not member.bot
        }
    )
    if not eligible:
        return None, False

    selected = random.choice(eligible)
    store.set_state("pidor_date", today)
    store.set_state("pidor_member_id", str(selected.id))
    store.increment_stat(selected.id)
    return selected, True


async def animate_pidor_message(message, selected: discord.Member) -> None:
    await asyncio.sleep(5)
    await message.edit(content="А могли бы на работе делом заниматься...")
    await asyncio.sleep(5)
    await message.edit(content="Проверяю данные...")
    await asyncio.sleep(5)
    await message.edit(content=f"ВЖУХ И ТЫ ПИДОР: {selected.mention}")


@tasks.loop(time=datetime.min.replace(hour=20, minute=30, tzinfo=MSK).timetz())
async def scheduled_pidor_of_the_day() -> None:
    guild = bot.get_guild(config.GUILD_ID)
    if guild is None:
        return
    channel_id = config.PIDOR_CHANNEL_ID or parse_state_int("pidor_channel_id")
    if not channel_id:
        logger.warning(
            "Автоматический pidor_of_the_day пропущен: сначала запустите "
            "команду вручную или задайте PIDOR_CHANNEL_ID"
        )
        return
    channel = bot.get_channel(channel_id)
    if channel is None or not hasattr(channel, "send"):
        logger.error("Канал pidor_of_the_day %s не найден", channel_id)
        return

    async with pidor_lock:
        selected, is_new = select_pidor_for_today(guild)
        if selected is None:
            logger.warning("Нет кандидатов для автоматического pidor_of_the_day")
            return
        if not is_new:
            return
        message = await channel.send("Что тут у нас?")
        await animate_pidor_message(message, selected)


@bot.tree.command(name="pidor_of_the_day", description="Выбрать участника дня")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
async def pidor_of_the_day(interaction: discord.Interaction) -> None:
    if interaction.channel_id:
        store.set_state("pidor_channel_id", str(interaction.channel_id))
    async with pidor_lock:
        selected, is_new = select_pidor_for_today(interaction.guild)
        if selected is None:
            await interaction.response.send_message(config.MESSAGES["NO_CANDIDATES"])
            return
        if not is_new:
            await interaction.response.send_message(
                f"ВЖУХ И ТЫ ПИДОР: {selected.mention}"
            )
            return
        await interaction.response.send_message("Что тут у нас?")
        message = await interaction.original_response()
        await animate_pidor_message(message, selected)


@bot.tree.command(name="pidors_of_the_week", description="Статистика за неделю")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
async def pidors_of_the_week(interaction: discord.Interaction) -> None:
    stats = store.stats()
    if not stats:
        await interaction.response.send_message(config.MESSAGES["NO_PIDORS"])
        return
    lines = [config.MESSAGES["PIDORS_OF_THE_WEEK"]]
    for user_id, count in stats.items():
        member = interaction.guild.get_member(user_id)
        label = member.display_name if member else f"Участник {user_id}"
        lines.append(f"{label}: {count} раз(а)")
    await interaction.response.send_message("\n".join(lines))


async def send_ephemeral_chunks(
    interaction: discord.Interaction, lines: list[str]
) -> None:
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > 1900:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    if not chunks:
        chunks = ["Нет данных."]
    for chunk in chunks:
        await interaction.followup.send(chunk, ephemeral=True)


@bot.tree.command(name="absence", description="Предупредить об отсутствии на РТ")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.describe(
    raid_date="Дата РТ в формате ДД.ММ.ГГГГ",
    reason="Причина отсутствия",
)
async def absence(
    interaction: discord.Interaction,
    raid_date: str,
    reason: str,
) -> None:
    try:
        parsed = parse_raid_date(raid_date)
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return
    if parsed.weekday() not in (4, 6):
        await interaction.response.send_message(
            "Основные РТ проходят только по пятницам и воскресеньям.",
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True)
    channel = bot.get_channel(config.RAID_ABSENCE_CHANNEL_ID)
    if channel is None or not hasattr(channel, "send"):
        await interaction.followup.send(
            "Канал предупреждений не найден.", ephemeral=True
        )
        return
    published = await channel.send(
        f"📅 {interaction.user.mention} предупредил об отсутствии или опоздании "
        f"на РТ {parsed.strftime('%d.%m.%Y')}.\nПричина: {reason.strip()}"
    )
    try:
        await save_notice_message(
            published,
            interaction.user.id,
            parsed,
            reason,
        )
    except (discord.Forbidden, discord.HTTPException):
        logger.exception("Не удалось поставить реакцию под предупреждением")
        await interaction.followup.send(
            "Сообщение опубликовано, но предупреждение не сохранено: "
            "бот не смог поставить реакцию.",
            ephemeral=True,
        )
        return
    await interaction.followup.send(
        f"Предупреждение на {parsed.strftime('%d.%m.%Y')} опубликовано и сохранено.",
        ephemeral=True,
    )


@bot.tree.command(name="attendance_start", description="Начать учёт посещаемости РТ")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.describe(raid_date="Необязательно: дата в формате ДД.ММ.ГГГГ")
async def attendance_start(
    interaction: discord.Interaction,
    raid_date: str | None = None,
) -> None:
    if raid_date:
        try:
            parsed = parse_raid_date(raid_date)
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        date_key = parsed.date().isoformat()
        start_at = parsed.replace(hour=21, minute=0).timestamp()
    else:
        date_key = datetime.now(MSK).date().isoformat()
        start_at = utc_timestamp()
    try:
        session_id, created = await start_raid_attendance(
            interaction.guild, date_key, start_at
        )
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return
    await interaction.response.send_message(
        (
            f"Учёт посещаемости начат, сессия #{session_id}."
            if created
            else f"Уже активна сессия #{session_id}."
        ),
        ephemeral=True,
    )


@bot.tree.command(name="attendance_end", description="Завершить учёт посещаемости РТ")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_roles=True)
async def attendance_end(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    session_id, counts = await finish_raid_attendance(interaction.guild)
    if session_id is None:
        await interaction.followup.send("Активной РТ-сессии нет.", ephemeral=True)
        return
    await interaction.followup.send(
        f"Сессия #{session_id} завершена и ожидает проверки. "
        f"Автоматически обработано записей: {sum(counts.values())}.",
        ephemeral=True,
    )


@bot.tree.command(name="attendance_current", description="Показать текущий черновик РТ")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_roles=True)
async def attendance_current(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    session = store.active_raid_session() or store.latest_raid_session()
    if not session:
        await interaction.followup.send("РТ-сессий пока нет.", ephemeral=True)
        return
    if session["status"] == "active":
        store.attendance_heartbeat(
            int(session["id"]),
            raid_voice_member_ids(interaction.guild),
            utc_timestamp(),
        )
    lines = [
        f"📊 Сессия #{session['id']} за {session['raid_date']} "
        f"— статус: {session['status']}"
    ]
    for record in store.attendance_records(int(session["id"])):
        member = interaction.guild.get_member(record["member_id"])
        label = member.display_name if member else str(record["member_id"])
        status = ATTENDANCE_STATUS_LABELS.get(record["status"], record["status"])
        minutes = int(record["present_seconds"] // 60)
        note = f" — {record['note']}" if record["note"] else ""
        lines.append(f"{label}: {status}, {minutes} мин.{note}")
    await send_ephemeral_chunks(interaction, lines)


@bot.tree.command(name="attendance_mark", description="Исправить статус участника РТ")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.choices(
    status=[
        app_commands.Choice(name="Присутствовал", value="present"),
        app_commands.Choice(name="Опоздал", value="late"),
        app_commands.Choice(name="Резерв", value="reserve"),
        app_commands.Choice(name="Предупреждённый пропуск", value="excused"),
        app_commands.Choice(name="Отсутствовал", value="absent"),
    ]
)
async def attendance_mark(
    interaction: discord.Interaction,
    member: discord.Member,
    status: app_commands.Choice[str],
    note: str = "",
) -> None:
    session = store.latest_raid_session()
    if not session or session["status"] not in ("active", "draft"):
        await interaction.response.send_message(
            "Нет активной сессии или черновика для исправления.", ephemeral=True
        )
        return
    store.set_attendance_status(
        int(session["id"]),
        member.id,
        status.value,
        note.strip(),
        source="manual",
    )
    await interaction.response.send_message(
        f"{member.mention}: установлен статус "
        f"«{ATTENDANCE_STATUS_LABELS[status.value]}».",
        ephemeral=True,
    )


@bot.tree.command(name="attendance_confirm", description="Подтвердить черновик РТ")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_roles=True)
async def attendance_confirm(interaction: discord.Interaction) -> None:
    session = store.latest_raid_session()
    if not session or session["status"] != "draft":
        await interaction.response.send_message(
            "Нет черновика, ожидающего подтверждения.", ephemeral=True
        )
        return
    store.confirm_raid_session(int(session["id"]))
    await interaction.response.send_message(
        f"Посещаемость сессии #{session['id']} подтверждена.",
        ephemeral=True,
    )


def validate_month(month: str | None) -> str:
    value = month or datetime.now(MSK).strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise ValueError("Месяц должен быть в формате ГГГГ-ММ")
    return value


def attendance_summary(
    rows, guild: discord.Guild, member_id: int | None = None
) -> list[str]:
    grouped: dict[int, dict[str, int]] = {}
    for row in rows:
        if member_id is not None and row["member_id"] != member_id:
            continue
        stats = grouped.setdefault(
            int(row["member_id"]),
            {"credited": 0, "eligible": 0, "late": 0, "reserve": 0, "excused": 0},
        )
        status = row["status"]
        if status == "excused":
            stats["excused"] += 1
            continue
        stats["eligible"] += 1
        if status in ("present", "late", "reserve"):
            stats["credited"] += 1
        if status == "late":
            stats["late"] += 1
        if status == "reserve":
            stats["reserve"] += 1

    result: list[tuple[float, str]] = []
    for current_member_id, stats in grouped.items():
        member = guild.get_member(current_member_id)
        label = member.display_name if member else str(current_member_id)
        percent = (
            stats["credited"] / stats["eligible"] * 100
            if stats["eligible"]
            else 100.0
        )
        text = (
            f"{label}: {percent:.0f}% "
            f"({stats['credited']}/{stats['eligible']}), "
            f"опозданий: {stats['late']}, резерв: {stats['reserve']}, "
            f"предупреждений: {stats['excused']}"
        )
        result.append((percent, text))
    return [text for _, text in sorted(result, key=lambda item: (-item[0], item[1]))]


@bot.tree.command(name="attendance", description="Посещаемость за месяц")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.describe(month="Месяц в формате ГГГГ-ММ")
async def attendance(interaction: discord.Interaction, month: str | None = None) -> None:
    try:
        month_key = validate_month(month)
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    lines = [f"📅 Посещаемость за {month_key}"]
    lines.extend(attendance_summary(store.monthly_attendance(month_key), interaction.guild))
    await send_ephemeral_chunks(interaction, lines)


@bot.tree.command(name="attendance_member", description="Посещаемость участника")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.describe(member="Участник Discord", month="Месяц в формате ГГГГ-ММ")
async def attendance_member(
    interaction: discord.Interaction,
    member: discord.Member,
    month: str | None = None,
) -> None:
    try:
        month_key = validate_month(month)
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    rows = store.monthly_attendance(month_key)
    summary = attendance_summary(rows, interaction.guild, member.id)
    lines = [f"📅 {member.display_name}, {month_key}"]
    lines.extend(summary or ["Подтверждённых записей нет."])
    for row in rows:
        if row["member_id"] != member.id:
            continue
        label = ATTENDANCE_STATUS_LABELS.get(row["status"], row["status"])
        note = f" — {row['note']}" if row["note"] else ""
        lines.append(f"{row['raid_date']}: {label}{note}")
    await send_ephemeral_chunks(interaction, lines)


@bot.tree.command(name="link", description="Связать участника с персонажами WoW")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.describe(
    member="Участник Discord",
    characters="Имена персонажей через запятую",
)
async def link_characters(
    interaction: discord.Interaction,
    member: discord.Member,
    characters: str,
) -> None:
    names_by_key = {
        normalize_character_name(name): name.strip()
        for name in characters.split(",")
        if name.strip()
    }
    names = list(names_by_key.values())
    if not names:
        await interaction.response.send_message(
            "Укажите хотя бы одного персонажа.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        roster = await fetch_guild_roster()
    except BlizzardAPIError:
        await interaction.followup.send(
            "Не удалось проверить персонажей: Blizzard API недоступен.",
            ephemeral=True,
        )
        return

    roster_names = {
        normalize_character_name(character.name): character.name
        for character in roster
    }
    missing = [name for name in names if normalize_character_name(name) not in roster_names]
    if missing:
        await interaction.followup.send(
            "Эти персонажи не найдены в гильдии: " + ", ".join(missing),
            ephemeral=True,
        )
        return

    canonical_names = [roster_names[normalize_character_name(name)] for name in names]
    conflicts: list[str] = []
    for name in canonical_names:
        owner_id = configured_link_owner(name)
        if owner_id is None:
            owner_id = store.character_link_owner(name)
        if owner_id is not None and owner_id != member.id:
            owner = interaction.guild.get_member(owner_id)
            owner_label = owner.mention if owner else str(owner_id)
            conflicts.append(f"{name} → {owner_label}")
    if conflicts:
        await interaction.followup.send(
            "Персонажи уже привязаны к другим участникам:\n"
            + "\n".join(conflicts),
            ephemeral=True,
        )
        return

    try:
        store.replace_character_links(member.id, canonical_names)
    except ValueError as error:
        await interaction.followup.send(str(error), ephemeral=True)
        return
    store.clear_absence(member.id)
    await synchronize_guild_roles(member)
    await interaction.followup.send(
        f"Сохранил персонажей для {member.mention}: {', '.join(canonical_names)}",
        ephemeral=True,
    )


@bot.tree.command(name="links", description="Показать привязки персонажей")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.describe(member="Необязательно: показать только одного участника")
async def links(
    interaction: discord.Interaction,
    member: discord.Member | None = None,
) -> None:
    await interaction.response.defer(ephemeral=True)
    grouped: dict[int, set[str]] = {}
    for member_id, names in config.DISCORD_CHARACTER_LINKS.items():
        grouped.setdefault(member_id, set()).update(names)
    for member_id, character_name in store.all_character_links():
        grouped.setdefault(member_id, set()).add(character_name)

    if member:
        grouped = (
            {member.id: grouped[member.id]}
            if member.id in grouped
            else {}
        )
    if not grouped:
        await interaction.followup.send("Привязок не найдено.", ephemeral=True)
        return

    lines = ["📎 Привязки персонажей:"]
    for member_id, names in sorted(grouped.items()):
        guild_member = interaction.guild.get_member(member_id)
        label = guild_member.mention if guild_member else f"ID {member_id}"
        lines.append(f"{label}: {', '.join(sorted(names, key=str.casefold))}")

    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > 1900:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    for chunk in chunks:
        await interaction.followup.send(chunk, ephemeral=True)


@bot.tree.command(name="unlink", description="Удалить привязку персонажа")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.describe(
    member="Участник Discord",
    character="Имя персонажа; оставьте пустым для удаления всех привязок",
)
async def unlink(
    interaction: discord.Interaction,
    member: discord.Member,
    character: str | None = None,
) -> None:
    character = character.strip() if character else None
    configured_names = config.DISCORD_CHARACTER_LINKS.get(member.id, [])
    if character and any(
        normalize_character_name(name) == normalize_character_name(character)
        for name in configured_names
    ):
        await interaction.response.send_message(
            "Эта привязка задана через DISCORD_CHARACTER_LINKS в .env. "
            "Удалите её из .env и перезапустите бота.",
            ephemeral=True,
        )
        return
    removed = store.remove_character_links(member.id, character)
    store.clear_absence(member.id)
    if removed:
        message = (
            f"Удалена привязка {character} у {member.mention}."
            if character
            else f"Удалены все локальные привязки у {member.mention}."
        )
    else:
        message = "Подходящая локальная привязка не найдена."
    if not character and configured_names:
        message += " Привязки из .env сохранены."
    await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(name="sync_status", description="Состояние синхронизации Blizzard")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_roles=True)
async def sync_status(interaction: discord.Interaction) -> None:
    last_error = store.get_state("last_api_error") or "нет"
    last_error_at = format_msk_timestamp(store.get_state("last_api_error_at"))
    next_sync = next_role_sync_time().strftime("%d.%m.%Y %H:%M:%S МСК")
    await interaction.response.send_message(
        "\n".join(
            (
                "🔄 Состояние синхронизации",
                "Последняя успешная: "
                + format_msk_timestamp(store.get_state("last_sync_success")),
                f"Следующая плановая: {next_sync}",
                "Размер последнего состава: "
                + str(parse_state_int("last_roster_size")),
                f"Ошибок подряд: {parse_state_int('api_failure_count')}",
                f"Последняя ошибка ({last_error_at}): {last_error}",
            )
        ),
        ephemeral=True,
    )


@bot.tree.command(name="sync", description="Вручную обновить роли из Blizzard")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_roles=True)
async def sync_roles(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    success, roster_size, changed = await synchronize_guild_roles()
    if not success:
        await interaction.followup.send(
            "Не удалось обновить роли. Проверьте настройки Blizzard API и журнал бота.",
            ephemeral=True,
        )
        return
    await interaction.followup.send(
        f"Роли обновлены. Персонажей в составе: {roster_size}, "
        f"участников Discord изменено: {changed}.",
        ephemeral=True,
    )


@bot.tree.command(
    name="sync_member",
    description="Обновить Blizzard-роль одного участника",
)
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.describe(member="Участник Discord")
async def sync_member(
    interaction: discord.Interaction,
    member: discord.Member,
) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    success, roster_size, changed = await synchronize_guild_roles(member)
    if not success:
        await interaction.followup.send(
            "Не удалось обновить роль: Blizzard API недоступен.",
            ephemeral=True,
        )
        return
    await interaction.followup.send(
        f"Проверен {member.mention}. Состав: {roster_size}, "
        f"роль изменена: {'да' if changed else 'нет'}.",
        ephemeral=True,
    )


def frzok_mention(guild: discord.Guild) -> str | None:
    if config.FRZOK_USER_ID:
        return f"<@{config.FRZOK_USER_ID}>"
    expected_names = {"frzok", "fearzok"}
    for member in guild.members:
        names = (member.name, member.global_name, member.display_name)
        for name in names:
            if not name:
                continue
            normalized = normalize_character_name(name)
            first_part = re.split(r"[\s|()_-]+", normalized, maxsplit=1)[0]
            if normalized in expected_names or first_part in expected_names:
                return member.mention
    return None


async def publish_raid_announcement(
    interaction: discord.Interaction,
    content: str,
) -> None:
    channel = bot.get_channel(config.RAID_ANNOUNCEMENT_CHANNEL_ID)
    if channel is None or not hasattr(channel, "send"):
        await interaction.followup.send(
            "Канал для объявления сбора не найден.", ephemeral=True
        )
        return
    await channel.send(content)
    await interaction.followup.send(
        f"Объявление опубликовано в {channel.mention}.", ephemeral=True
    )


@bot.tree.command(name="heroic", description="Объявить сбор в героик")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_roles=True)
async def heroic(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    mention = frzok_mention(interaction.guild)
    if mention is None:
        await interaction.followup.send(
            "Не удалось найти пользователя frzok. Укажите FRZOK_USER_ID в .env.",
            ephemeral=True,
        )
        return
    content = (
        f"**<@&{config.ROLE_IDS['SERGEANT']}>** "
        f"**<@&{config.ROLE_IDS['CHRONICLER']}>** "
        f"**<@&{config.ROLE_IDS['RECRUIT']}>** "
        "Героик Старт Сбор. Для инвайта в рейд необходимо поставить + "
        f"в ПМ в игре **{mention}**"
    )
    await publish_raid_announcement(interaction, content)


@bot.tree.command(name="rt_start", description="Объявить начало сбора на РТ")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_roles=True)
async def rt_start(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    mention = frzok_mention(interaction.guild)
    if mention is None:
        await interaction.followup.send(
            "Не удалось найти пользователя frzok. Укажите FRZOK_USER_ID в .env.",
            ephemeral=True,
        )
        return
    content = (
        f"**<@&{config.ROLE_IDS['SERGEANT']}>** "
        "РТ старт сбор! Для инвайта в рейд необходимо поставить + "
        f"в ПМ в игре **{mention}**"
    )
    await publish_raid_announcement(interaction, content)


@bot.tree.command(name="roster", description="Показать таблицу состава")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
async def roster_link(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(config.ROSTER_URL, ephemeral=True)


@bot.tree.command(name="bot_status", description="Административное состояние бота")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_roles=True)
async def bot_status(interaction: discord.Interaction) -> None:
    counts = store.counts()
    uptime = datetime.now(MSK) - PROCESS_STARTED_AT
    uptime_seconds = int(uptime.total_seconds())
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    next_sync = next_role_sync_time().strftime("%d.%m.%Y %H:%M МСК")
    next_reset = next_weekly_reset_time().strftime("%d.%m.%Y %H:%M МСК")
    loops_running = sum(
        loop.is_running()
        for loop in (
            check_guest_roles,
            check_empty_channels,
            check_tactics_reminders,
            send_weekly_messages,
            reset_weekly_stats,
            scheduled_role_sync,
            scheduled_pidor_of_the_day,
            attendance_heartbeat,
            scheduled_attendance_start,
            scheduled_attendance_end,
            scheduled_database_backup,
        )
    )
    await interaction.response.send_message(
        "\n".join(
            (
                "🩺 Состояние бота",
                f"База данных: {'✅ исправна' if store.is_healthy() else '❌ ошибка'}",
                f"Blizzard API: {'✅ настроен' if blizzard.configured else '❌ не настроен'}",
                f"Ошибок API подряд: {parse_state_int('api_failure_count')}",
                f"Последний состав: {counts['roster']} персонажей",
                f"Кэш специализаций: {counts['spec_cache']} персонажей",
                f"Привязки: {counts['links']}",
                f"Ожидают снятия роли: {counts['absences']}",
                f"Гостевые таймеры: {counts['guests']}",
                f"Временные комнаты: {counts['temp_channels']}",
                f"РТ-сессии/записи: {counts['raid_sessions']}/{counts['attendance']}",
                f"Активные предупреждения РТ: {counts['raid_notices']}",
                f"История ролей: {counts['role_history']} записей",
                f"Резервные копии: {len(backup_files())}",
                f"Ожидающие напоминания о тактиках: "
                f"{counts['tactics_reminders']}",
                f"Запущенные фоновые задачи: {loops_running}/11",
                f"Следующая синхронизация: {next_sync}",
                "Автовыбор участника дня: ежедневно в 20:30 МСК",
                "Учёт РТ: Пт/Вс, 21:00–00:00 МСК",
                f"Сброс статистики: {next_reset}",
                f"Время работы процесса: {hours} ч. {minutes} мин.",
                f"Задержка Discord: {round(bot.latency * 1000)} мс",
            )
        ),
        ephemeral=True,
    )


@bot.tree.command(name="backup_status", description="Состояние резервных копий")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
async def backup_status(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    files = backup_files()
    now = datetime.now(MSK)
    next_backup = now.replace(hour=4, minute=30, second=0, microsecond=0)
    if next_backup <= now:
        next_backup += timedelta(days=1)
    if not files:
        await interaction.followup.send(
            f"Резервных копий нет. Следующая попытка: "
            f"{next_backup.strftime('%d.%m.%Y %H:%M МСК')}.",
            ephemeral=True,
        )
        return
    latest = files[0]
    modified = datetime.fromtimestamp(latest.stat().st_mtime, UTC).astimezone(MSK)
    healthy = await asyncio.to_thread(StateStore.validate_database, latest)
    lines = [
        "💾 Резервные копии",
        f"Последняя: `{latest.name}`",
        f"Создана: {modified.strftime('%d.%m.%Y %H:%M:%S МСК')}",
        f"Размер: {latest.stat().st_size / 1024:.1f} КБ",
        f"Проверка: {'✅ исправна' if healthy else '❌ повреждена'}",
        f"Всего сохранено: {len(files)}",
        f"Хранение: {config.BACKUP_RETENTION_DAYS} дней",
        f"Следующая: {next_backup.strftime('%d.%m.%Y %H:%M МСК')}",
        "Последние файлы:",
        *[f"`{path.name}`" for path in files[:5]],
    ]
    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bot.tree.command(name="backup_restore", description="Восстановить базу из копии")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    filename="Имя файла из /backup_status",
    confirmation="Введите ВОССТАНОВИТЬ",
)
async def backup_restore(
    interaction: discord.Interaction,
    filename: str,
    confirmation: str,
) -> None:
    if confirmation != "ВОССТАНОВИТЬ":
        await interaction.response.send_message(
            "Восстановление отменено: неверное подтверждение.", ephemeral=True
        )
        return
    directory = Path(config.BACKUP_DIR).resolve()
    candidate = (directory / filename).resolve()
    if (
        candidate.parent != directory
        or candidate.suffix != ".sqlite3"
        or not candidate.is_file()
    ):
        await interaction.response.send_message(
            "Указанный файл резервной копии не найден.", ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    healthy = await asyncio.to_thread(StateStore.validate_database, candidate)
    if not healthy:
        await interaction.followup.send(
            "Восстановление отменено: резервная копия повреждена.",
            ephemeral=True,
        )
        return
    try:
        safety_backup = await asyncio.to_thread(
            create_database_backup, "before_restore"
        )
        await asyncio.to_thread(store.restore_from, candidate)
        await reconcile_persistent_state(interaction.guild)
        await reconcile_raid_attendance(interaction.guild)
    except (OSError, sqlite3.Error) as error:
        logger.exception("Ошибка восстановления базы")
        await interaction.followup.send(
            f"Не удалось восстановить базу: {error}", ephemeral=True
        )
        return
    await interaction.followup.send(
        f"База восстановлена из `{candidate.name}`. Перед восстановлением "
        f"создана страховочная копия `{safety_backup.name}`.",
        ephemeral=True,
    )


async def find_manual_role_actor(member: discord.Member) -> int | None:
    try:
        async for entry in member.guild.audit_logs(
            limit=6,
            action=discord.AuditLogAction.member_role_update,
        ):
            target = entry.target
            if getattr(target, "id", None) != member.id:
                continue
            age = datetime.now(UTC) - entry.created_at
            if age.total_seconds() <= 20:
                return entry.user.id if entry.user else None
    except (discord.Forbidden, discord.HTTPException):
        return None
    return None


@bot.tree.command(name="role_history", description="История ролей участника")
@app_commands.guilds(discord.Object(id=config.GUILD_ID))
@app_commands.checks.has_permissions(manage_roles=True)
async def role_history(
    interaction: discord.Interaction,
    member: discord.Member,
) -> None:
    await interaction.response.defer(ephemeral=True)
    rows = store.member_role_history(member.id)
    if not rows:
        await interaction.followup.send(
            f"Истории ролей для {member.mention} пока нет.", ephemeral=True
        )
        return
    lines = [f"📜 История ролей {member.display_name}:"]
    for row in rows:
        occurred = datetime.fromtimestamp(row["occurred_at"], UTC).astimezone(MSK)
        role = interaction.guild.get_role(row["role_id"])
        role_label = role.mention if role else f"роль {row['role_id']}"
        action = "добавлена" if row["action"] == "added" else "удалена"
        source = "автоматически" if row["source"] == "automatic" else "вручную"
        actor = f", автор <@{row['actor_id']}>" if row["actor_id"] else ""
        character = (
            f", персонаж {row['character_name']}" if row["character_name"] else ""
        )
        reason = f" — {row['reason']}" if row["reason"] else ""
        lines.append(
            f"{occurred.strftime('%d.%m.%Y %H:%M')} — {role_label} "
            f"{action}, {source}{actor}{character}{reason}"
        )
    await send_ephemeral_chunks(interaction, lines)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member) -> None:
    tracked_role_ids = {
        *config.GUILD_RANK_ROLE_IDS.values(),
        config.ROLE_IDS["HILA_NA_KRUTILAH"],
        config.ROLE_IDS["FRIENDS"],
    }
    before_ids = {role.id for role in before.roles}
    after_ids = {role.id for role in after.roles}
    role_changes = [
        *[(role_id, "added") for role_id in after_ids - before_ids],
        *[(role_id, "removed") for role_id in before_ids - after_ids],
    ]
    manual_changes: list[tuple[int, str]] = []
    now_monotonic = time.monotonic()
    for role_id, action in role_changes:
        if role_id not in tracked_role_ids:
            continue
        key = (after.id, role_id, action)
        suppressed_until = suppressed_role_events.pop(key, None)
        if suppressed_until and suppressed_until >= now_monotonic:
            continue
        manual_changes.append((role_id, action))
    if manual_changes:
        await asyncio.sleep(1)
        actor_id = await find_manual_role_actor(after)
        for role_id, action in manual_changes:
            store.add_role_history(
                utc_timestamp(),
                after.id,
                role_id,
                action,
                "manual",
                actor_id=actor_id,
                reason="Ручное изменение Discord-роли",
            )

    sergeant = after.guild.get_role(config.ROLE_IDS["SERGEANT"])
    if sergeant and sergeant in after.roles and sergeant not in before.roles:
        try:
            await after.send(config.MESSAGES["WELCOME_MESSAGE"])
        except (discord.Forbidden, discord.HTTPException):
            logger.info("Не удалось отправить личное сообщение %s", after)


async def main() -> None:
    if not config.DISCORD_BOT_TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN не задан в .env")
    try:
        await bot.start(config.DISCORD_BOT_TOKEN)
    except discord.LoginFailure as error:
        raise RuntimeError(
            "Discord отклонил DISCORD_BOT_TOKEN. Нужен токен из раздела "
            "Developer Portal → Bot, без префикса «Bot »."
        ) from error
    finally:
        if not bot.is_closed():
            await bot.close()
        store.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
