from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from guild_navigation import (
    discord_link_targets,
    extract_timeline_version,
    find_navigation_entries,
    is_timeline_archive,
)
from raid_vacation import parse_user_date, vacation_from_state
from runtime_settings import parse_setting_value
from storage import StateStore
from warcraftlogs import WarcraftLogsClient


class EventStorageTests(unittest.TestCase):
    def test_event_and_warcraftlogs_queue_survive_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            store = StateStore(str(database))
            event_id = store.create_event(
                10,
                20,
                "key",
                "Ключи",
                "Сегодня 20:00",
                "Берём хилов",
                5,
                100.0,
            )
            store.set_event_message(event_id, 30)
            store.set_event_participant(event_id, 40, "going", 101.0)
            store.enqueue_warcraftlogs_report(1, 200.0)
            store.close()

            reopened = StateStore(str(database))
            try:
                event = reopened.event(event_id)
                self.assertIsNotNone(event)
                self.assertEqual(event["message_id"], 30)
                participants = reopened.event_participants(event_id)
                self.assertEqual(len(participants), 1)
                self.assertEqual(participants[0]["status"], "going")
            finally:
                reopened.close()

    def test_member_can_cancel_saved_absence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            store = StateStore(str(database))
            try:
                store.save_raid_notice(
                    message_id=100,
                    channel_id=200,
                    raid_date="2026-07-26",
                    member_id=300,
                    emoji="✅",
                    reason="[Опоздание до 21:30] Работа",
                    created_at=1.0,
                )
                removed = store.cancel_member_absence(
                    "2026-07-26", 300
                )
                self.assertEqual(len(removed), 1)
                self.assertEqual(removed[0]["message_id"], 100)
                self.assertNotIn(
                    300, store.absences_for_date("2026-07-26")
                )
                self.assertIsNone(store.raid_notice(100))
            finally:
                store.close()

    def test_state_can_be_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            store = StateStore(str(database))
            try:
                store.set_state("raid_vacation_start", "2026-08-01")
                store.delete_state("raid_vacation_start")
                self.assertIsNone(store.get_state("raid_vacation_start"))
            finally:
                store.close()

    def test_raid_schedule_exception_survives_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            store = StateStore(str(database))
            store.set_raid_schedule_exception(
                "2026-08-14",
                "moved",
                "2026-08-15",
                "Сбор гильдии",
                123,
                1.0,
            )
            store.close()
            reopened = StateStore(str(database))
            try:
                moved = reopened.raid_move_to_date("2026-08-15")
                self.assertIsNotNone(moved)
                self.assertEqual(moved["raid_date"], "2026-08-14")
                self.assertEqual(moved["reason"], "Сбор гильдии")
                self.assertTrue(
                    reopened.remove_raid_schedule_exception("2026-08-14")
                )
                self.assertIsNone(
                    reopened.raid_schedule_exception("2026-08-14")
                )
            finally:
                reopened.close()

    def test_sergeant_checklist_survives_reopen_and_closes_previous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            store = StateStore(str(database))
            first_id = store.create_sergeant_checklist(100, 1.0)
            store.set_sergeant_checklist_message(first_id, 200, 2.0)
            store.set_sergeant_checklist_mask(first_id, 5, 3.0)
            second_id = store.create_sergeant_checklist(100, 4.0)
            store.set_sergeant_checklist_message(second_id, 201, 5.0)
            store.close()

            reopened = StateStore(str(database))
            try:
                first = reopened.sergeant_checklist(first_id)
                second = reopened.sergeant_checklist(second_id)
                self.assertEqual(first["status"], "closed")
                self.assertEqual(first["completed_mask"], 5)
                self.assertEqual(second["status"], "active")
                self.assertEqual(second["message_id"], 201)
                self.assertEqual(
                    [row["id"] for row in reopened.active_sergeant_checklists()],
                    [second_id],
                )
            finally:
                reopened.close()

    def test_frequent_late_members_uses_recent_confirmed_raids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(str(Path(directory) / "state.sqlite3"))
            try:
                for number, raid_date in enumerate(
                    ("2026-08-02", "2026-08-07", "2026-08-09"), start=1
                ):
                    session_id = store.create_raid_session(raid_date, float(number))
                    store.set_attendance_status(session_id, 100, "late")
                    store.set_attendance_status(session_id, 200, "present")
                    store.finish_raid_session(session_id, float(number + 1), "draft")
                    store.confirm_raid_session(session_id)
                rows = store.frequent_late_members(3, 3)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["member_id"], 100)
                self.assertEqual(rows[0]["lates"], 3)
            finally:
                store.close()

    def test_absence_follows_moved_raid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(str(Path(directory) / "state.sqlite3"))
            try:
                store.save_raid_notice(
                    message_id=10,
                    channel_id=20,
                    raid_date="2026-08-14",
                    member_id=30,
                    emoji="✅",
                    reason="Отпуск",
                    created_at=1.0,
                )
                store.move_raid_notices("2026-08-14", "2026-08-15")
                self.assertEqual(store.absences_for_date("2026-08-14"), {})
                self.assertEqual(
                    store.absences_for_date("2026-08-15"), {30: "Отпуск"}
                )
                self.assertEqual(
                    store.raid_notice(10)["raid_date"], "2026-08-15"
                )
            finally:
                store.close()

    def test_tactics_acknowledgements_and_feedback_are_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(str(Path(directory) / "state.sqlite3"))
            try:
                store.save_tactics_ack_message(10, 11, 12, 1.0)
                store.acknowledge_tactics(10, 100, 2.0)
                self.assertEqual(store.tactics_acknowledged_members(10), {100})

                session_id = store.create_raid_session("2026-08-14", 1.0)
                store.save_feedback_message(session_id, 20, 21, 2.0)
                store.save_raid_feedback(
                    session_id, 100, 4, 3, 5, "Нормальный РТ", 3.0
                )
                store.save_raid_feedback(
                    session_id, 100, 5, 4, 5, "Стало лучше", 4.0
                )
                summary = store.raid_feedback_summary(session_id)
                self.assertEqual(summary["responses"], 1)
                self.assertEqual(summary["organization"], 5.0)
                self.assertEqual(
                    store.raid_feedback_comments(session_id), ["Стало лучше"]
                )
                store.close_feedback_message(session_id)
                self.assertEqual(store.open_feedback_messages(), [])
            finally:
                store.close()


class RaidVacationTests(unittest.TestCase):
    def test_period_is_inclusive(self) -> None:
        period = vacation_from_state("2026-08-01", "2026-08-10")
        self.assertIsNotNone(period)
        assert period is not None
        self.assertTrue(period.includes(parse_user_date("01.08.2026")))
        self.assertTrue(period.includes(parse_user_date("10.08.2026")))
        self.assertFalse(period.includes(parse_user_date("11.08.2026")))

    def test_invalid_period_is_not_loaded(self) -> None:
        self.assertIsNone(vacation_from_state("2026-08-10", "2026-08-01"))
        with self.assertRaises(ValueError):
            parse_user_date("31.02.2026")


class RuntimeSettingsTests(unittest.TestCase):
    def test_validates_times_numbers_and_channels(self) -> None:
        self.assertEqual(parse_setting_value("raid_start_time", "20:45"), "20:45")
        self.assertEqual(parse_setting_value("raid_attendance_percent", "75"), "75")
        self.assertEqual(
            parse_setting_value("raid_analysis_channel", "<#1345828084640776343>"),
            "1345828084640776343",
        )
        with self.assertRaises(ValueError):
            parse_setting_value("raid_late_minutes", "0")
        with self.assertRaises(ValueError):
            parse_setting_value("raid_end_time", "25:00")


class GuildNavigationTests(unittest.TestCase):
    def test_searches_by_alias_and_normalizes_russian(self) -> None:
        self.assertEqual(find_navigation_entries("опоздаю")[0].key, "absence")
        self.assertEqual(find_navigation_entries("ТАЙМЛАЙН")[0].key, "timeline")
        self.assertEqual(find_navigation_entries("домик ебли")[0].key, "analysis")

    def test_extracts_discord_targets(self) -> None:
        targets = discord_link_targets(
            "https://discord.com/channels/10/20 и "
            "https://discord.com/channels/10/30/40"
        )
        self.assertIn((10, 20, None, "https://discord.com/channels/10/20"), targets)
        self.assertIn((10, 30, 40, "https://discord.com/channels/10/30/40"), targets)

    def test_timeline_archive_and_version(self) -> None:
        self.assertTrue(is_timeline_archive("TimelineReminders-v353.rar"))
        self.assertFalse(is_timeline_archive("TimelineReminders.exe"))
        self.assertEqual(
            extract_timeline_version("", "TimelineReminders-v353.rar"),
            "v353",
        )
        self.assertEqual(extract_timeline_version("Версия v354", "addon.rar"), "v354")
        self.assertIsNone(extract_timeline_version("Новая версия", "addon.rar"))


class WarcraftLogsParsingTests(unittest.TestCase):
    def test_extracts_deaths_and_best_rankings(self) -> None:
        deaths = WarcraftLogsClient._extract_deaths(
            {
                "data": {
                    "entries": [
                        {
                            "name": "Игрок",
                            "fight": 1,
                            "timestamp": 10,
                            "deathTime": 10,
                        },
                        {
                            "name": "Другой",
                            "fight": 1,
                            "timestamp": 20,
                            "deathWindow": 20,
                        },
                        {
                            "name": "Не считается",
                            "fight": 1,
                            "timestamp": 30,
                            "killingBlow": {"name": "Босс"},
                        },
                        {
                            "name": "Игрок",
                            "fight": 2,
                            "timestamp": 10,
                            "deathTime": 10,
                        },
                        {
                            "name": "Третий",
                            "fight": 2,
                            "timestamp": 20,
                            "deathTime": 20,
                        },
                        {
                            "name": "Не считается",
                            "fight": 2,
                            "timestamp": 30,
                            "deathTime": 30,
                        },
                    ]
                }
            }
        )
        self.assertEqual(
            deaths,
            {"Игрок": 2, "Другой": 1, "Третий": 1},
        )
        death_events = WarcraftLogsClient._extract_death_events(
            {
                "data": {
                    "entries": [
                        {
                            "name": "Первый",
                            "fight": 3,
                            "timestamp": 100,
                            "deathTime": 100,
                        },
                        {
                            "name": "Второй",
                            "fight": 3,
                            "timestamp": 200,
                            "deathTime": 200,
                        },
                        {
                            "name": "После команды вайп",
                            "fight": 3,
                            "timestamp": 300,
                            "deathTime": 300,
                        },
                    ]
                }
            }
        )
        self.assertEqual(
            [(event.fight_id, event.player_name) for event in death_events],
            [(3, "Первый"), (3, "Второй")],
        )

        best = WarcraftLogsClient.best_rankings(
            {
                "data": [
                    {
                        "roles": {
                            "dps": {
                                "characters": [
                                    {"name": "Игрок", "rankPercent": 91.5},
                                    {"name": "Другой", "rankPercent": 72.0},
                                ]
                            }
                        }
                    }
                ]
            }
        )
        self.assertEqual(best[0], ("Игрок", 91.5))


if __name__ == "__main__":
    unittest.main()
