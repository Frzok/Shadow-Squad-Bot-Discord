"""Удаление данных одного Discord-участника из рабочей SQLite и копий.

Запускать только оператору при остановленном боте. Инструмент намеренно не
создаёт резервную копию: она противоречила бы цели запроса на удаление.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def delete_where(
    connection: sqlite3.Connection,
    table: str,
    where: str,
    parameters: tuple[object, ...],
) -> int:
    if not table_exists(connection, table):
        return 0
    cursor = connection.execute(f"DELETE FROM {table} WHERE {where}", parameters)
    return max(cursor.rowcount, 0)


def purge_database(
    path: Path,
    member_id: int,
    explicit_characters: set[str],
) -> tuple[int, set[str]]:
    deleted = 0
    characters = {
        name.strip().casefold()
        for name in explicit_characters
        if name.strip()
    }

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA secure_delete=ON")

        if table_exists(connection, "character_links"):
            rows = connection.execute(
                "SELECT character_name FROM character_links WHERE member_id=?",
                (member_id,),
            ).fetchall()
            characters.update(str(row[0]).strip().casefold() for row in rows)

        member_tables = {
            "guest_roles": "member_id",
            "pidor_stats": "member_id",
            "character_links": "member_id",
            "guild_absences": "member_id",
            "attendance_records": "member_id",
            "raid_absences": "member_id",
            "raid_notice_messages": "member_id",
            "temp_channels": "owner_id",
            "tactics_reminders": "author_id",
            "guild_event_participants": "member_id",
        }
        for table, column in member_tables.items():
            deleted += delete_where(
                connection, table, f"{column}=?", (member_id,)
            )

        if table_exists(connection, "role_history"):
            deleted += delete_where(
                connection,
                "role_history",
                "member_id=? OR actor_id=?",
                (member_id, member_id),
            )

        if table_exists(connection, "guild_events"):
            event_rows = connection.execute(
                "SELECT id FROM guild_events WHERE creator_id=?",
                (member_id,),
            ).fetchall()
            for event_row in event_rows:
                deleted += delete_where(
                    connection,
                    "guild_event_participants",
                    "event_id=?",
                    (event_row[0],),
                )
            deleted += delete_where(
                connection,
                "guild_events",
                "creator_id=?",
                (member_id,),
            )

        if table_exists(connection, "bot_state"):
            deleted += delete_where(
                connection,
                "bot_state",
                "key='pidor_member_id' AND value=?",
                (str(member_id),),
            )

        for character in characters:
            if table_exists(connection, "guild_roster_cache"):
                deleted += delete_where(
                    connection,
                    "guild_roster_cache",
                    "character_name=? COLLATE NOCASE",
                    (character,),
                )
            if table_exists(connection, "character_spec_cache"):
                deleted += delete_where(
                    connection,
                    "character_spec_cache",
                    "character_name=? COLLATE NOCASE",
                    (character,),
                )

        connection.commit()
        check = connection.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError(f"{path}: SQLite quick_check failed: {check}")
        connection.execute("VACUUM")

    return deleted, characters


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Удалить данные участника из рабочей SQLite и всех копий."
    )
    parser.add_argument("--member-id", required=True, type=int)
    parser.add_argument("--character", action="append", default=[])
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(os.getenv("STATE_DB_PATH", PROJECT_DIR / "bot_state.sqlite3")),
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=PROJECT_DIR / "backups",
    )
    parser.add_argument("--confirm", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    expected = f"DELETE-{args.member_id}"
    if args.confirm != expected:
        raise SystemExit(f"Подтверждение должно быть: {expected}")

    database = args.database.resolve()
    if not database.is_file():
        raise SystemExit(f"Рабочая база не найдена: {database}")

    backup_dir = args.backup_dir.resolve()
    backup_paths = (
        sorted(backup_dir.glob("*.sqlite3")) if backup_dir.is_dir() else []
    )
    paths = [database, *[path for path in backup_paths if path.resolve() != database]]

    characters = {
        name.strip().casefold() for name in args.character if name.strip()
    }
    total_deleted = 0
    for path in paths:
        deleted, discovered = purge_database(
            path, args.member_id, characters
        )
        characters.update(discovered)
        total_deleted += deleted
        print(f"{path}: удалено строк={deleted}")

    names = ", ".join(sorted(characters)) or "нет"
    print(
        f"Готово: баз={len(paths)}, удалено строк={total_deleted}, "
        f"персонажи={names}"
    )


if __name__ == "__main__":
    main()
