from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
