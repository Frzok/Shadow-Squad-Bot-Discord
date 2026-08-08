"""SQLite-база таймеров, привязок и рейдовой статистики."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class StateStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS guest_roles (
                    member_id INTEGER PRIMARY KEY,
                    assigned_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS temp_channels (
                    channel_id INTEGER PRIMARY KEY,
                    owner_id INTEGER NOT NULL,
                    empty_since REAL
                );
                CREATE TABLE IF NOT EXISTS pidor_stats (
                    member_id INTEGER PRIMARY KEY,
                    selections INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS character_links (
                    member_id INTEGER NOT NULL,
                    character_name TEXT NOT NULL COLLATE NOCASE,
                    PRIMARY KEY (member_id, character_name)
                );
                CREATE TABLE IF NOT EXISTS guild_absences (
                    member_id INTEGER PRIMARY KEY,
                    first_missing_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS guild_roster_cache (
                    character_name TEXT NOT NULL COLLATE NOCASE,
                    realm_slug TEXT NOT NULL,
                    guild_rank INTEGER NOT NULL,
                    fetched_at REAL NOT NULL,
                    PRIMARY KEY (character_name, realm_slug)
                );
                CREATE TABLE IF NOT EXISTS character_spec_cache (
                    character_name TEXT NOT NULL COLLATE NOCASE,
                    realm_slug TEXT NOT NULL,
                    spec_id INTEGER NOT NULL,
                    spec_name TEXT NOT NULL,
                    role_type TEXT NOT NULL,
                    checked_at REAL NOT NULL,
                    PRIMARY KEY (character_name, realm_slug)
                );
                CREATE TABLE IF NOT EXISTS raid_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    raid_date TEXT NOT NULL UNIQUE,
                    started_at REAL NOT NULL,
                    ended_at REAL,
                    status TEXT NOT NULL DEFAULT 'active'
                );
                CREATE TABLE IF NOT EXISTS attendance_records (
                    session_id INTEGER NOT NULL,
                    member_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    present_seconds REAL NOT NULL DEFAULT 0,
                    first_join_at REAL,
                    joined_at REAL,
                    note TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'automatic',
                    PRIMARY KEY (session_id, member_id),
                    FOREIGN KEY (session_id) REFERENCES raid_sessions(id)
                );
                CREATE TABLE IF NOT EXISTS raid_absences (
                    raid_date TEXT NOT NULL,
                    member_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (raid_date, member_id)
                );
                CREATE TABLE IF NOT EXISTS raid_notice_messages (
                    message_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    raid_date TEXT NOT NULL,
                    member_id INTEGER NOT NULL,
                    emoji TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS role_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at REAL NOT NULL,
                    member_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    source TEXT NOT NULL,
                    actor_id INTEGER,
                    character_name TEXT,
                    reason TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS tactics_reminders (
                    message_id INTEGER PRIMARY KEY,
                    author_id INTEGER NOT NULL,
                    source_channel_id INTEGER NOT NULL,
                    target_channel_id INTEGER NOT NULL,
                    due_at REAL NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS wowaudit_loot_seen (
                    loot_id INTEGER PRIMARY KEY,
                    seen_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS raid_loot_reports (
                    session_id INTEGER PRIMARY KEY,
                    due_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    sent_at REAL,
                    FOREIGN KEY (session_id) REFERENCES raid_sessions(id)
                );
                CREATE TABLE IF NOT EXISTS warcraftlogs_reports (
                    session_id INTEGER PRIMARY KEY,
                    due_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    report_code TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    sent_at REAL,
                    FOREIGN KEY (session_id) REFERENCES raid_sessions(id)
                );
                CREATE TABLE IF NOT EXISTS guild_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER,
                    channel_id INTEGER NOT NULL,
                    creator_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    scheduled_for TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    max_participants INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open'
                );
                CREATE TABLE IF NOT EXISTS guild_event_participants (
                    event_id INTEGER NOT NULL,
                    member_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (event_id, member_id),
                    FOREIGN KEY (event_id) REFERENCES guild_events(id)
                );
                CREATE TABLE IF NOT EXISTS raid_schedule_exceptions (
                    raid_date TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    replacement_date TEXT,
                    reason TEXT NOT NULL DEFAULT '',
                    created_by INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    CHECK (action IN ('cancelled', 'moved'))
                );
                CREATE TABLE IF NOT EXISTS tactics_acknowledgements (
                    source_message_id INTEGER NOT NULL,
                    member_id INTEGER NOT NULL,
                    acknowledged_at REAL NOT NULL,
                    PRIMARY KEY (source_message_id, member_id)
                );
                CREATE TABLE IF NOT EXISTS tactics_ack_messages (
                    source_message_id INTEGER PRIMARY KEY,
                    acknowledgement_message_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS raid_feedback_messages (
                    session_id INTEGER PRIMARY KEY,
                    message_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    FOREIGN KEY (session_id) REFERENCES raid_sessions(id)
                );
                CREATE TABLE IF NOT EXISTS raid_feedback (
                    session_id INTEGER NOT NULL,
                    member_id INTEGER NOT NULL,
                    organization INTEGER NOT NULL,
                    pace INTEGER NOT NULL,
                    atmosphere INTEGER NOT NULL,
                    comment TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    PRIMARY KEY (session_id, member_id),
                    FOREIGN KEY (session_id) REFERENCES raid_sessions(id)
                );
                CREATE TABLE IF NOT EXISTS sergeant_checklists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    member_id INTEGER NOT NULL,
                    message_id INTEGER UNIQUE,
                    completed_mask INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                );
                """
            )
            # Старые версии разрешали привязать одного персонажа нескольким
            # людям. При обновлении сохраняется самая ранняя привязка.
            self._connection.execute(
                """
                DELETE FROM character_links
                WHERE rowid NOT IN (
                    SELECT MIN(rowid)
                    FROM character_links
                    GROUP BY character_name COLLATE NOCASE
                )
                """
            )
            self._connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                uq_character_link_name
                ON character_links(character_name COLLATE NOCASE)
                """
            )

    def set_guest(self, member_id: int, assigned_at: float) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO guest_roles(member_id, assigned_at) VALUES (?, ?)
                ON CONFLICT(member_id) DO UPDATE SET assigned_at=excluded.assigned_at
                """,
                (member_id, assigned_at),
            )

    def guests(self) -> list[tuple[int, float]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT member_id, assigned_at FROM guest_roles"
            ).fetchall()
        return [(row["member_id"], row["assigned_at"]) for row in rows]

    def remove_guest(self, member_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM guest_roles WHERE member_id=?", (member_id,)
            )

    def add_temp_channel(self, channel_id: int, owner_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO temp_channels VALUES (?, ?, NULL)",
                (channel_id, owner_id),
            )

    def temp_channels(self) -> list[tuple[int, int, float | None]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT channel_id, owner_id, empty_since FROM temp_channels"
            ).fetchall()
        return [
            (row["channel_id"], row["owner_id"], row["empty_since"]) for row in rows
        ]

    def owner_channel_count(self, owner_id: int) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS amount FROM temp_channels WHERE owner_id=?",
                (owner_id,),
            ).fetchone()
        return int(row["amount"])

    def set_channel_empty_since(
        self, channel_id: int, empty_since: float | None
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE temp_channels SET empty_since=? WHERE channel_id=?",
                (empty_since, channel_id),
            )

    def remove_temp_channel(self, channel_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM temp_channels WHERE channel_id=?", (channel_id,)
            )

    def stats(self) -> dict[int, int]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT member_id, selections FROM pidor_stats"
            ).fetchall()
        return {row["member_id"]: row["selections"] for row in rows}

    def increment_stat(self, member_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO pidor_stats(member_id, selections) VALUES (?, 1)
                ON CONFLICT(member_id)
                DO UPDATE SET selections=selections + 1
                """,
                (member_id,),
            )

    def clear_stats(self) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM pidor_stats")

    def create_sergeant_checklist(self, member_id: int, created_at: float) -> int:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE sergeant_checklists
                SET status='closed', updated_at=?
                WHERE member_id=? AND status='active'
                """,
                (created_at, member_id),
            )
            cursor = self._connection.execute(
                """
                INSERT INTO sergeant_checklists(
                    member_id, created_at, updated_at
                ) VALUES (?, ?, ?)
                """,
                (member_id, created_at, created_at),
            )
            return int(cursor.lastrowid)

    def set_sergeant_checklist_message(
        self, checklist_id: int, message_id: int, updated_at: float
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE sergeant_checklists
                SET message_id=?, updated_at=?
                WHERE id=?
                """,
                (message_id, updated_at, checklist_id),
            )

    def sergeant_checklist(self, checklist_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                "SELECT * FROM sergeant_checklists WHERE id=?",
                (checklist_id,),
            ).fetchone()

    def active_sergeant_checklists(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT * FROM sergeant_checklists
                WHERE status='active' AND message_id IS NOT NULL
                ORDER BY id
                """
            ).fetchall()

    def set_sergeant_checklist_mask(
        self, checklist_id: int, completed_mask: int, updated_at: float
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE sergeant_checklists
                SET completed_mask=?, updated_at=?
                WHERE id=? AND status='active'
                """,
                (completed_mask, updated_at, checklist_id),
            )

    def close_sergeant_checklist(self, checklist_id: int, updated_at: float) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE sergeant_checklists
                SET status='closed', updated_at=?
                WHERE id=?
                """,
                (updated_at, checklist_id),
            )

    def get_state(self, key: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM bot_state WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO bot_state(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )

    def delete_state(self, key: str) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM bot_state WHERE key=?", (key,))

    def linked_characters(self, member_id: int) -> list[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT character_name FROM character_links WHERE member_id=?",
                (member_id,),
            ).fetchall()
        return [row["character_name"] for row in rows]

    def all_character_links(self) -> list[tuple[int, str]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT member_id, character_name
                FROM character_links
                ORDER BY member_id, character_name
                """
            ).fetchall()
        return [(row["member_id"], row["character_name"]) for row in rows]

    def character_link_owner(self, character_name: str) -> int | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT member_id FROM character_links
                WHERE character_name = ? COLLATE NOCASE
                """,
                (character_name,),
            ).fetchone()
        return row["member_id"] if row else None

    def replace_character_links(self, member_id: int, names: list[str]) -> None:
        unique_names_by_key = {
            name.strip().casefold(): name.strip() for name in names if name.strip()
        }
        unique_names = list(unique_names_by_key.values())
        with self._lock, self._connection:
            for name in unique_names:
                row = self._connection.execute(
                    """
                    SELECT member_id FROM character_links
                    WHERE character_name = ? COLLATE NOCASE AND member_id != ?
                    """,
                    (name, member_id),
                ).fetchone()
                if row:
                    raise ValueError(
                        f"Персонаж {name} уже привязан к участнику {row['member_id']}"
                    )
            self._connection.execute(
                "DELETE FROM character_links WHERE member_id=?", (member_id,)
            )
            self._connection.executemany(
                "INSERT INTO character_links VALUES (?, ?)",
                [(member_id, name) for name in unique_names],
            )

    def remove_character_links(
        self, member_id: int, character_name: str | None = None
    ) -> int:
        with self._lock, self._connection:
            if character_name is None:
                cursor = self._connection.execute(
                    "DELETE FROM character_links WHERE member_id=?", (member_id,)
                )
            else:
                cursor = self._connection.execute(
                    """
                    DELETE FROM character_links
                    WHERE member_id=? AND character_name=? COLLATE NOCASE
                    """,
                    (member_id, character_name),
                )
        return cursor.rowcount

    def get_absence(self, member_id: int) -> float | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT first_missing_at FROM guild_absences WHERE member_id=?",
                (member_id,),
            ).fetchone()
        return row["first_missing_at"] if row else None

    def set_guild_absence(self, member_id: int, first_missing_at: float) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO guild_absences(member_id, first_missing_at)
                VALUES (?, ?)
                ON CONFLICT(member_id) DO NOTHING
                """,
                (member_id, first_missing_at),
            )

    def clear_absence(self, member_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM guild_absences WHERE member_id=?", (member_id,)
            )

    def guild_absences(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT member_id, first_missing_at
                FROM guild_absences
                ORDER BY first_missing_at, member_id
                """
            ).fetchall()

    def save_roster(
        self, characters: list[tuple[str, str, int]], fetched_at: float
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM guild_roster_cache")
            self._connection.executemany(
                """
                INSERT INTO guild_roster_cache(
                    character_name, realm_slug, guild_rank, fetched_at
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (name, realm_slug, guild_rank, fetched_at)
                    for name, realm_slug, guild_rank in characters
                ],
            )

    def load_roster(self) -> tuple[list[tuple[str, str, int]], float | None]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT character_name, realm_slug, guild_rank, fetched_at
                FROM guild_roster_cache
                """
            ).fetchall()
        if not rows:
            return [], None
        return (
            [
                (row["character_name"], row["realm_slug"], row["guild_rank"])
                for row in rows
            ],
            rows[0]["fetched_at"],
        )

    def get_character_spec(
        self, character_name: str, realm_slug: str
    ) -> tuple[int, str, str, float] | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT spec_id, spec_name, role_type, checked_at
                FROM character_spec_cache
                WHERE character_name=? COLLATE NOCASE AND realm_slug=?
                """,
                (character_name, realm_slug),
            ).fetchone()
        if not row:
            return None
        return (
            row["spec_id"],
            row["spec_name"],
            row["role_type"],
            row["checked_at"],
        )

    def save_character_spec(
        self,
        character_name: str,
        realm_slug: str,
        spec_id: int,
        spec_name: str,
        role_type: str,
        checked_at: float,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO character_spec_cache(
                    character_name, realm_slug, spec_id, spec_name,
                    role_type, checked_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(character_name, realm_slug) DO UPDATE SET
                    spec_id=excluded.spec_id,
                    spec_name=excluded.spec_name,
                    role_type=excluded.role_type,
                    checked_at=excluded.checked_at
                """,
                (
                    character_name,
                    realm_slug,
                    spec_id,
                    spec_name,
                    role_type,
                    checked_at,
                ),
            )

    def create_raid_session(self, raid_date: str, started_at: float) -> int:
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT id, status FROM raid_sessions WHERE raid_date=?",
                (raid_date,),
            ).fetchone()
            if existing:
                if existing["status"] == "active":
                    return int(existing["id"])
                raise ValueError(f"Сессия за {raid_date} уже существует")
            cursor = self._connection.execute(
                """
                INSERT INTO raid_sessions(raid_date, started_at, status)
                VALUES (?, ?, 'active')
                """,
                (raid_date, started_at),
            )
        return int(cursor.lastrowid)

    def active_raid_session(self) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                """
                SELECT id, raid_date, started_at, ended_at, status
                FROM raid_sessions WHERE status='active'
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()

    def raid_session(self, session_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                """
                SELECT id, raid_date, started_at, ended_at, status
                FROM raid_sessions WHERE id=?
                """,
                (session_id,),
            ).fetchone()

    def raid_session_by_date(self, raid_date: str) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                """
                SELECT id, raid_date, started_at, ended_at, status
                FROM raid_sessions WHERE raid_date=?
                """,
                (raid_date,),
            ).fetchone()

    def latest_raid_session(self) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                """
                SELECT id, raid_date, started_at, ended_at, status
                FROM raid_sessions ORDER BY id DESC LIMIT 1
                """
            ).fetchone()

    def set_raid_schedule_exception(
        self,
        raid_date: str,
        action: str,
        replacement_date: str | None,
        reason: str,
        created_by: int,
        created_at: float,
    ) -> None:
        if action not in ("cancelled", "moved"):
            raise ValueError("Некорректное действие календаря РТ")
        if action == "moved" and not replacement_date:
            raise ValueError("Для переноса нужна новая дата")
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO raid_schedule_exceptions(
                    raid_date, action, replacement_date, reason,
                    created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(raid_date) DO UPDATE SET
                    action=excluded.action,
                    replacement_date=excluded.replacement_date,
                    reason=excluded.reason,
                    created_by=excluded.created_by,
                    created_at=excluded.created_at
                """,
                (
                    raid_date,
                    action,
                    replacement_date,
                    reason,
                    created_by,
                    created_at,
                ),
            )

    def raid_schedule_exception(self, raid_date: str) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                """
                SELECT raid_date, action, replacement_date, reason,
                       created_by, created_at
                FROM raid_schedule_exceptions WHERE raid_date=?
                """,
                (raid_date,),
            ).fetchone()

    def raid_move_to_date(self, replacement_date: str) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                """
                SELECT raid_date, action, replacement_date, reason,
                       created_by, created_at
                FROM raid_schedule_exceptions
                WHERE action='moved' AND replacement_date=?
                ORDER BY created_at DESC LIMIT 1
                """,
                (replacement_date,),
            ).fetchone()

    def raid_schedule_exceptions(
        self, start_date: str, end_date: str
    ) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT raid_date, action, replacement_date, reason,
                       created_by, created_at
                FROM raid_schedule_exceptions
                WHERE raid_date BETWEEN ? AND ?
                   OR replacement_date BETWEEN ? AND ?
                ORDER BY raid_date
                """,
                (start_date, end_date, start_date, end_date),
            ).fetchall()

    def remove_raid_schedule_exception(self, raid_date: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM raid_schedule_exceptions WHERE raid_date=?",
                (raid_date,),
            )
        return bool(cursor.rowcount)

    def move_raid_notices(self, old_date: str, new_date: str) -> None:
        if old_date == new_date:
            return
        with self._lock, self._connection:
            rows = self._connection.execute(
                """
                SELECT member_id, reason, created_at FROM raid_absences
                WHERE raid_date=?
                """,
                (old_date,),
            ).fetchall()
            for row in rows:
                self._connection.execute(
                    """
                    INSERT INTO raid_absences(
                        raid_date, member_id, reason, created_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(raid_date, member_id) DO UPDATE SET
                        reason=excluded.reason,
                        created_at=excluded.created_at
                    """,
                    (
                        new_date,
                        row["member_id"],
                        row["reason"],
                        row["created_at"],
                    ),
                )
            self._connection.execute(
                "DELETE FROM raid_absences WHERE raid_date=?", (old_date,)
            )
            self._connection.execute(
                """
                UPDATE raid_notice_messages SET raid_date=?
                WHERE raid_date=?
                """,
                (new_date, old_date),
            )

    def ensure_attendance_member(self, session_id: int, member_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO attendance_records(session_id, member_id)
                VALUES (?, ?)
                ON CONFLICT(session_id, member_id) DO NOTHING
                """,
                (session_id, member_id),
            )

    def attendance_enter(
        self, session_id: int, member_id: int, entered_at: float
    ) -> None:
        self.ensure_attendance_member(session_id, member_id)
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE attendance_records
                SET joined_at=COALESCE(joined_at, ?),
                    first_join_at=COALESCE(first_join_at, ?)
                WHERE session_id=? AND member_id=?
                """,
                (entered_at, entered_at, session_id, member_id),
            )

    def attendance_leave(
        self,
        session_id: int,
        member_id: int,
        left_at: float,
        max_interval: float | None = None,
    ) -> None:
        with self._lock, self._connection:
            row = self._connection.execute(
                """
                SELECT joined_at FROM attendance_records
                WHERE session_id=? AND member_id=?
                """,
                (session_id, member_id),
            ).fetchone()
            if not row or row["joined_at"] is None:
                return
            elapsed = max(0.0, left_at - row["joined_at"])
            if max_interval is not None:
                elapsed = min(elapsed, max_interval)
            self._connection.execute(
                """
                UPDATE attendance_records
                SET present_seconds=present_seconds + ?, joined_at=NULL
                WHERE session_id=? AND member_id=?
                """,
                (elapsed, session_id, member_id),
            )

    def attendance_heartbeat(
        self,
        session_id: int,
        active_member_ids: set[int],
        checked_at: float,
        max_interval: float = 90,
    ) -> None:
        with self._lock:
            joined_rows = self._connection.execute(
                """
                SELECT member_id FROM attendance_records
                WHERE session_id=? AND joined_at IS NOT NULL
                """,
                (session_id,),
            ).fetchall()
        joined_ids = {int(row["member_id"]) for row in joined_rows}
        for member_id in joined_ids:
            self.attendance_leave(
                session_id, member_id, checked_at, max_interval=max_interval
            )
        for member_id in active_member_ids:
            self.attendance_enter(session_id, member_id, checked_at)

    def attendance_records(self, session_id: int) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT session_id, member_id, status, present_seconds,
                       first_join_at, joined_at, note, source
                FROM attendance_records
                WHERE session_id=?
                ORDER BY member_id
                """,
                (session_id,),
            ).fetchall()

    def set_attendance_status(
        self,
        session_id: int,
        member_id: int,
        status: str,
        note: str = "",
        source: str = "manual",
    ) -> None:
        self.ensure_attendance_member(session_id, member_id)
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE attendance_records
                SET status=?, note=?, source=?
                WHERE session_id=? AND member_id=?
                """,
                (status, note, source, session_id, member_id),
            )

    def finish_raid_session(
        self, session_id: int, ended_at: float, status: str = "draft"
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE raid_sessions SET ended_at=?, status=?
                WHERE id=?
                """,
                (ended_at, status, session_id),
            )

    def confirm_raid_session(self, session_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE raid_sessions SET status='confirmed' WHERE id=?",
                (session_id,),
            )

    def enqueue_raid_loot_report(self, session_id: int, due_at: float) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO raid_loot_reports(session_id, due_at)
                VALUES (?, ?)
                ON CONFLICT(session_id) DO NOTHING
                """,
                (session_id, due_at),
            )

    def due_raid_loot_reports(self, now: float) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT
                    rlr.session_id,
                    rlr.due_at,
                    rlr.attempts,
                    rs.raid_date,
                    rs.started_at,
                    rs.ended_at
                FROM raid_loot_reports rlr
                JOIN raid_sessions rs ON rs.id=rlr.session_id
                WHERE rlr.status='pending' AND rlr.due_at<=?
                ORDER BY rlr.due_at, rlr.session_id
                """,
                (now,),
            ).fetchall()

    def fail_raid_loot_report(
        self,
        session_id: int,
        error: str,
        retry_at: float,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE raid_loot_reports
                SET attempts=attempts + 1, last_error=?, due_at=?
                WHERE session_id=? AND status='pending'
                """,
                (error, retry_at, session_id),
            )

    def complete_raid_loot_report(
        self,
        session_id: int,
        sent_at: float,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE raid_loot_reports
                SET status='sent', sent_at=?, last_error=''
                WHERE session_id=?
                """,
                (sent_at, session_id),
            )

    def enqueue_warcraftlogs_report(
        self, session_id: int, due_at: float
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO warcraftlogs_reports(session_id, due_at)
                VALUES (?, ?)
                ON CONFLICT(session_id) DO NOTHING
                """,
                (session_id, due_at),
            )

    def due_warcraftlogs_reports(self, now: float) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT
                    wlr.session_id,
                    wlr.due_at,
                    wlr.attempts,
                    rs.raid_date,
                    rs.started_at,
                    rs.ended_at
                FROM warcraftlogs_reports wlr
                JOIN raid_sessions rs ON rs.id=wlr.session_id
                WHERE wlr.status='pending' AND wlr.due_at<=?
                ORDER BY wlr.due_at, wlr.session_id
                """,
                (now,),
            ).fetchall()

    def fail_warcraftlogs_report(
        self,
        session_id: int,
        error: str,
        retry_at: float,
        abandon: bool = False,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE warcraftlogs_reports
                SET attempts=attempts + 1, last_error=?, due_at=?,
                    status=CASE WHEN ? THEN 'failed' ELSE 'pending' END
                WHERE session_id=? AND status='pending'
                """,
                (error[:1000], retry_at, int(abandon), session_id),
            )

    def complete_warcraftlogs_report(
        self, session_id: int, report_code: str, sent_at: float
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE warcraftlogs_reports
                SET status='sent', report_code=?, sent_at=?, last_error=''
                WHERE session_id=?
                """,
                (report_code, sent_at, session_id),
            )

    def create_event(
        self,
        channel_id: int,
        creator_id: int,
        event_type: str,
        title: str,
        scheduled_for: str,
        description: str,
        max_participants: int,
        created_at: float,
    ) -> int:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO guild_events(
                    channel_id, creator_id, event_type, title,
                    scheduled_for, description, max_participants, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    channel_id,
                    creator_id,
                    event_type,
                    title,
                    scheduled_for,
                    description,
                    max_participants,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def set_event_message(self, event_id: int, message_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE guild_events SET message_id=? WHERE id=?",
                (message_id, event_id),
            )

    def event(self, event_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                """
                SELECT id, message_id, channel_id, creator_id, event_type,
                       title, scheduled_for, description, max_participants,
                       created_at, status
                FROM guild_events WHERE id=?
                """,
                (event_id,),
            ).fetchone()

    def open_events(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT id, message_id, channel_id, creator_id, event_type,
                       title, scheduled_for, description, max_participants,
                       created_at, status
                FROM guild_events
                WHERE status='open' AND message_id IS NOT NULL
                ORDER BY id
                """
            ).fetchall()

    def set_event_participant(
        self,
        event_id: int,
        member_id: int,
        status: str,
        updated_at: float,
    ) -> None:
        with self._lock, self._connection:
            if status == "removed":
                self._connection.execute(
                    """
                    DELETE FROM guild_event_participants
                    WHERE event_id=? AND member_id=?
                    """,
                    (event_id, member_id),
                )
                return
            self._connection.execute(
                """
                INSERT INTO guild_event_participants(
                    event_id, member_id, status, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(event_id, member_id) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (event_id, member_id, status, updated_at),
            )

    def event_participants(self, event_id: int) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT member_id, status, updated_at
                FROM guild_event_participants
                WHERE event_id=?
                ORDER BY
                    CASE status WHEN 'going' THEN 0 ELSE 1 END,
                    updated_at,
                    member_id
                """,
                (event_id,),
            ).fetchall()

    def close_event(self, event_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE guild_events SET status='closed' WHERE id=?",
                (event_id,),
            )

    def set_absence(
        self, raid_date: str, member_id: int, reason: str, created_at: float
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO raid_absences(raid_date, member_id, reason, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(raid_date, member_id) DO UPDATE SET
                    reason=excluded.reason,
                    created_at=excluded.created_at
                """,
                (raid_date, member_id, reason, created_at),
            )

    def absences_for_date(self, raid_date: str) -> dict[int, str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT member_id, reason FROM raid_absences WHERE raid_date=?",
                (raid_date,),
            ).fetchall()
        return {int(row["member_id"]): row["reason"] for row in rows}

    def cancel_member_absence(
        self, raid_date: str, member_id: int
    ) -> list[sqlite3.Row]:
        with self._lock, self._connection:
            rows = self._connection.execute(
                """
                SELECT message_id, channel_id, raid_date, member_id,
                       emoji, reason, created_at
                FROM raid_notice_messages
                WHERE raid_date=? AND member_id=?
                """,
                (raid_date, member_id),
            ).fetchall()
            self._connection.execute(
                """
                DELETE FROM raid_notice_messages
                WHERE raid_date=? AND member_id=?
                """,
                (raid_date, member_id),
            )
            self._connection.execute(
                """
                DELETE FROM raid_absences
                WHERE raid_date=? AND member_id=?
                """,
                (raid_date, member_id),
            )
        return rows

    def save_raid_notice(
        self,
        message_id: int,
        channel_id: int,
        raid_date: str,
        member_id: int,
        emoji: str,
        reason: str,
        created_at: float,
    ) -> None:
        with self._lock, self._connection:
            previous = self._connection.execute(
                """
                SELECT raid_date, member_id FROM raid_notice_messages
                WHERE message_id=?
                """,
                (message_id,),
            ).fetchone()
            self._connection.execute(
                """
                INSERT INTO raid_notice_messages(
                    message_id, channel_id, raid_date, member_id,
                    emoji, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    raid_date=excluded.raid_date,
                    member_id=excluded.member_id,
                    emoji=excluded.emoji,
                    reason=excluded.reason
                """,
                (
                    message_id,
                    channel_id,
                    raid_date,
                    member_id,
                    emoji,
                    reason,
                    created_at,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO raid_absences(raid_date, member_id, reason, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(raid_date, member_id) DO UPDATE SET
                    reason=excluded.reason,
                    created_at=excluded.created_at
                """,
                (raid_date, member_id, reason, created_at),
            )
            if previous and (
                previous["raid_date"] != raid_date
                or previous["member_id"] != member_id
            ):
                remaining = self._connection.execute(
                    """
                    SELECT COUNT(*) AS amount FROM raid_notice_messages
                    WHERE raid_date=? AND member_id=?
                    """,
                    (previous["raid_date"], previous["member_id"]),
                ).fetchone()
                if not remaining["amount"]:
                    self._connection.execute(
                        """
                        DELETE FROM raid_absences
                        WHERE raid_date=? AND member_id=?
                        """,
                        (previous["raid_date"], previous["member_id"]),
                    )

    def raid_notice(self, message_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                """
                SELECT message_id, channel_id, raid_date, member_id,
                       emoji, reason, created_at
                FROM raid_notice_messages WHERE message_id=?
                """,
                (message_id,),
            ).fetchone()

    def all_raid_notices(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT message_id, channel_id, raid_date, member_id,
                       emoji, reason, created_at
                FROM raid_notice_messages
                ORDER BY created_at DESC
                """
            ).fetchall()

    def remove_raid_notice(self, message_id: int) -> sqlite3.Row | None:
        with self._lock, self._connection:
            row = self._connection.execute(
                """
                SELECT message_id, channel_id, raid_date, member_id,
                       emoji, reason, created_at
                FROM raid_notice_messages WHERE message_id=?
                """,
                (message_id,),
            ).fetchone()
            if not row:
                return None
            self._connection.execute(
                "DELETE FROM raid_notice_messages WHERE message_id=?",
                (message_id,),
            )
            remaining = self._connection.execute(
                """
                SELECT COUNT(*) AS amount FROM raid_notice_messages
                WHERE raid_date=? AND member_id=?
                """,
                (row["raid_date"], row["member_id"]),
            ).fetchone()
            if not remaining["amount"]:
                self._connection.execute(
                    """
                    DELETE FROM raid_absences
                    WHERE raid_date=? AND member_id=?
                    """,
                    (row["raid_date"], row["member_id"]),
                )
            else:
                latest = self._connection.execute(
                    """
                    SELECT reason, created_at FROM raid_notice_messages
                    WHERE raid_date=? AND member_id=?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (row["raid_date"], row["member_id"]),
                ).fetchone()
                self._connection.execute(
                    """
                    UPDATE raid_absences SET reason=?, created_at=?
                    WHERE raid_date=? AND member_id=?
                    """,
                    (
                        latest["reason"],
                        latest["created_at"],
                        row["raid_date"],
                        row["member_id"],
                    ),
                )
        return row

    def monthly_attendance(self, month: str) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT ar.member_id, ar.status, ar.present_seconds,
                       rs.raid_date, ar.note
                FROM attendance_records ar
                JOIN raid_sessions rs ON rs.id=ar.session_id
                WHERE rs.status='confirmed' AND rs.raid_date LIKE ?
                ORDER BY rs.raid_date, ar.member_id
                """,
                (f"{month}%",),
            ).fetchall()

    def member_attendance(
        self, member_id: int, limit: int = 12
    ) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT ar.member_id, ar.status, ar.present_seconds,
                       rs.raid_date, ar.note
                FROM attendance_records ar
                JOIN raid_sessions rs ON rs.id=ar.session_id
                WHERE rs.status='confirmed' AND ar.member_id=?
                ORDER BY rs.raid_date DESC LIMIT ?
                """,
                (member_id, limit),
            ).fetchall()

    def frequent_late_members(
        self, minimum_lates: int, recent_raids: int
    ) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                WITH recent AS (
                    SELECT id, raid_date FROM raid_sessions
                    WHERE status='confirmed'
                    ORDER BY raid_date DESC LIMIT ?
                )
                SELECT ar.member_id,
                       SUM(CASE WHEN ar.status='late' THEN 1 ELSE 0 END) AS lates,
                       COUNT(*) AS raids,
                       MAX(recent.raid_date) AS latest_raid_date
                FROM attendance_records ar
                JOIN recent ON recent.id=ar.session_id
                GROUP BY ar.member_id
                HAVING lates >= ?
                ORDER BY lates DESC, ar.member_id
                """,
                (recent_raids, minimum_lates),
            ).fetchall()

    def weekly_raid_sessions(
        self, start_date: str, end_date: str
    ) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT rs.id, rs.raid_date, rs.started_at, rs.ended_at,
                       rs.status, wlr.report_code
                FROM raid_sessions rs
                LEFT JOIN warcraftlogs_reports wlr ON wlr.session_id=rs.id
                WHERE rs.status='confirmed'
                  AND rs.raid_date BETWEEN ? AND ?
                ORDER BY rs.raid_date
                """,
                (start_date, end_date),
            ).fetchall()

    def attendance_between(
        self, start_date: str, end_date: str
    ) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT ar.member_id, ar.status, ar.present_seconds,
                       rs.raid_date, ar.note
                FROM attendance_records ar
                JOIN raid_sessions rs ON rs.id=ar.session_id
                WHERE rs.status='confirmed'
                  AND rs.raid_date BETWEEN ? AND ?
                ORDER BY rs.raid_date, ar.member_id
                """,
                (start_date, end_date),
            ).fetchall()

    def save_tactics_ack_message(
        self,
        source_message_id: int,
        acknowledgement_message_id: int,
        channel_id: int,
        created_at: float,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO tactics_ack_messages(
                    source_message_id, acknowledgement_message_id,
                    channel_id, created_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(source_message_id) DO UPDATE SET
                    acknowledgement_message_id=excluded.acknowledgement_message_id,
                    channel_id=excluded.channel_id,
                    created_at=excluded.created_at
                """,
                (
                    source_message_id,
                    acknowledgement_message_id,
                    channel_id,
                    created_at,
                ),
            )

    def tactics_ack_message(self, source_message_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                """
                SELECT source_message_id, acknowledgement_message_id,
                       channel_id, created_at
                FROM tactics_ack_messages WHERE source_message_id=?
                """,
                (source_message_id,),
            ).fetchone()

    def all_tactics_ack_messages(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT source_message_id, acknowledgement_message_id,
                       channel_id, created_at
                FROM tactics_ack_messages ORDER BY created_at DESC
                """
            ).fetchall()

    def acknowledge_tactics(
        self, source_message_id: int, member_id: int, acknowledged_at: float
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO tactics_acknowledgements(
                    source_message_id, member_id, acknowledged_at
                ) VALUES (?, ?, ?)
                ON CONFLICT(source_message_id, member_id) DO UPDATE SET
                    acknowledged_at=excluded.acknowledged_at
                """,
                (source_message_id, member_id, acknowledged_at),
            )

    def tactics_acknowledged_members(self, source_message_id: int) -> set[int]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT member_id FROM tactics_acknowledgements
                WHERE source_message_id=?
                """,
                (source_message_id,),
            ).fetchall()
        return {int(row["member_id"]) for row in rows}

    def remove_tactics_ack_tracker(self, source_message_id: int) -> sqlite3.Row | None:
        with self._lock, self._connection:
            row = self.tactics_ack_message(source_message_id)
            self._connection.execute(
                "DELETE FROM tactics_acknowledgements WHERE source_message_id=?",
                (source_message_id,),
            )
            self._connection.execute(
                "DELETE FROM tactics_ack_messages WHERE source_message_id=?",
                (source_message_id,),
            )
        return row

    def save_feedback_message(
        self,
        session_id: int,
        message_id: int,
        channel_id: int,
        created_at: float,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO raid_feedback_messages(
                    session_id, message_id, channel_id, created_at, status
                ) VALUES (?, ?, ?, ?, 'open')
                ON CONFLICT(session_id) DO UPDATE SET
                    message_id=excluded.message_id,
                    channel_id=excluded.channel_id,
                    created_at=excluded.created_at,
                    status='open'
                """,
                (session_id, message_id, channel_id, created_at),
            )

    def feedback_message(self, session_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                """
                SELECT session_id, message_id, channel_id, created_at, status
                FROM raid_feedback_messages WHERE session_id=?
                """,
                (session_id,),
            ).fetchone()

    def open_feedback_messages(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT session_id, message_id, channel_id, created_at, status
                FROM raid_feedback_messages WHERE status='open'
                ORDER BY created_at
                """
            ).fetchall()

    def finished_sessions_missing_feedback(
        self, ended_after: float
    ) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT rs.id, rs.raid_date, rs.ended_at
                FROM raid_sessions rs
                LEFT JOIN raid_feedback_messages rfm ON rfm.session_id=rs.id
                WHERE rs.status IN ('draft', 'confirmed')
                  AND rs.ended_at>=?
                  AND rfm.session_id IS NULL
                ORDER BY rs.ended_at DESC LIMIT 1
                """,
                (ended_after,),
            ).fetchall()

    def save_raid_feedback(
        self,
        session_id: int,
        member_id: int,
        organization: int,
        pace: int,
        atmosphere: int,
        comment: str,
        created_at: float,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO raid_feedback(
                    session_id, member_id, organization, pace,
                    atmosphere, comment, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, member_id) DO UPDATE SET
                    organization=excluded.organization,
                    pace=excluded.pace,
                    atmosphere=excluded.atmosphere,
                    comment=excluded.comment,
                    created_at=excluded.created_at
                """,
                (
                    session_id,
                    member_id,
                    organization,
                    pace,
                    atmosphere,
                    comment,
                    created_at,
                ),
            )

    def raid_feedback_summary(self, session_id: int) -> sqlite3.Row:
        with self._lock:
            return self._connection.execute(
                """
                SELECT COUNT(*) AS responses,
                       AVG(organization) AS organization,
                       AVG(pace) AS pace,
                       AVG(atmosphere) AS atmosphere
                FROM raid_feedback WHERE session_id=?
                """,
                (session_id,),
            ).fetchone()

    def raid_feedback_comments(self, session_id: int) -> list[str]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT comment FROM raid_feedback
                WHERE session_id=? AND comment<>''
                ORDER BY created_at
                """,
                (session_id,),
            ).fetchall()
        return [str(row["comment"]) for row in rows]

    def close_feedback_message(self, session_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE raid_feedback_messages SET status='closed'
                WHERE session_id=?
                """,
                (session_id,),
            )

    def add_role_history(
        self,
        occurred_at: float,
        member_id: int,
        role_id: int,
        action: str,
        source: str,
        actor_id: int | None = None,
        character_name: str | None = None,
        reason: str = "",
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO role_history(
                    occurred_at, member_id, role_id, action, source,
                    actor_id, character_name, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    occurred_at,
                    member_id,
                    role_id,
                    action,
                    source,
                    actor_id,
                    character_name,
                    reason,
                ),
            )

    def member_role_history(
        self, member_id: int, limit: int = 30
    ) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT occurred_at, role_id, action, source, actor_id,
                       character_name, reason
                FROM role_history
                WHERE member_id=?
                ORDER BY occurred_at DESC
                LIMIT ?
                """,
                (member_id, limit),
            ).fetchall()

    def save_tactics_reminder(
        self,
        message_id: int,
        author_id: int,
        source_channel_id: int,
        target_channel_id: int,
        due_at: float,
        created_at: float,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO tactics_reminders(
                    message_id, author_id, source_channel_id,
                    target_channel_id, due_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    author_id=excluded.author_id,
                    source_channel_id=excluded.source_channel_id,
                    target_channel_id=excluded.target_channel_id,
                    due_at=excluded.due_at
                """,
                (
                    message_id,
                    author_id,
                    source_channel_id,
                    target_channel_id,
                    due_at,
                    created_at,
                ),
            )

    def due_tactics_reminders(self, now: float) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT message_id, author_id, source_channel_id,
                       target_channel_id, due_at, created_at
                FROM tactics_reminders
                WHERE due_at <= ?
                ORDER BY due_at, message_id
                """,
                (now,),
            ).fetchall()

    def remove_tactics_reminder(self, message_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM tactics_reminders WHERE message_id=?",
                (message_id,),
            )

    def wowaudit_seen_loot_ids(self) -> set[int]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT loot_id FROM wowaudit_loot_seen"
            ).fetchall()
        return {int(row["loot_id"]) for row in rows}

    def mark_wowaudit_loot_seen(
        self, loot_ids: list[int], seen_at: float
    ) -> None:
        if not loot_ids:
            return
        with self._lock, self._connection:
            self._connection.executemany(
                """
                INSERT INTO wowaudit_loot_seen(loot_id, seen_at)
                VALUES (?, ?)
                ON CONFLICT(loot_id) DO NOTHING
                """,
                [(loot_id, seen_at) for loot_id in loot_ids],
            )

    def backup_to(self, destination: str | Path) -> None:
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(destination_path)
        try:
            with self._lock:
                self._connection.backup(target)
            row = target.execute("PRAGMA quick_check").fetchone()
            if not row or row[0] != "ok":
                raise sqlite3.DatabaseError("Проверка резервной копии не пройдена")
        finally:
            target.close()

    @staticmethod
    def validate_database(path: str | Path) -> bool:
        try:
            connection = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
            try:
                row = connection.execute("PRAGMA quick_check").fetchone()
                return bool(row and row[0] == "ok")
            finally:
                connection.close()
        except sqlite3.Error:
            return False

    def restore_from(self, source_path: str | Path) -> None:
        source = sqlite3.connect(f"file:{Path(source_path)}?mode=ro", uri=True)
        try:
            row = source.execute("PRAGMA quick_check").fetchone()
            if not row or row[0] != "ok":
                raise sqlite3.DatabaseError("Резервная копия повреждена")
            with self._lock:
                source.backup(self._connection)
        finally:
            source.close()
        self._create_schema()

    def counts(self) -> dict[str, int]:
        tables = {
            "guests": "guest_roles",
            "temp_channels": "temp_channels",
            "stats": "pidor_stats",
            "links": "character_links",
            "absences": "guild_absences",
            "roster": "guild_roster_cache",
            "spec_cache": "character_spec_cache",
            "raid_sessions": "raid_sessions",
            "attendance": "attendance_records",
            "raid_notices": "raid_notice_messages",
            "role_history": "role_history",
            "tactics_reminders": "tactics_reminders",
            "wowaudit_loot_seen": "wowaudit_loot_seen",
            "raid_loot_reports": "raid_loot_reports",
            "warcraftlogs_reports": "warcraftlogs_reports",
            "events": "guild_events",
            "event_participants": "guild_event_participants",
            "sergeant_checklists": "sergeant_checklists",
        }
        result: dict[str, int] = {}
        with self._lock:
            for key, table in tables.items():
                row = self._connection.execute(
                    f"SELECT COUNT(*) AS amount FROM {table}"
                ).fetchone()
                result[key] = int(row["amount"])
        return result

    def is_healthy(self) -> bool:
        try:
            with self._lock:
                row = self._connection.execute("PRAGMA quick_check").fetchone()
            return bool(row and row[0] == "ok")
        except sqlite3.Error:
            return False

    def close(self) -> None:
        with self._lock:
            self._connection.close()
