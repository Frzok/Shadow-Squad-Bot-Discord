"""Постоянное SQLite-хранилище состояния бота."""

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
