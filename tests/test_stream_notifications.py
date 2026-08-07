from __future__ import annotations

import unittest
from types import SimpleNamespace

from stream_notifications import (
    register_active_stream,
    twitch_login,
    twitch_preview_url,
    twitch_stream_from_activities,
)


class TwitchStreamParsingTests(unittest.TestCase):
    def test_accepts_twitch_channel_urls(self) -> None:
        self.assertEqual(twitch_login("https://www.twitch.tv/Frzok"), "Frzok")
        self.assertEqual(twitch_login("https://twitch.tv/shadow_squad/"), "shadow_squad")

    def test_rejects_non_twitch_and_lookalike_urls(self) -> None:
        self.assertIsNone(twitch_login("https://youtube.com/frzok"))
        self.assertIsNone(twitch_login("https://twitch.tv.evil.example/frzok"))
        self.assertIsNone(twitch_login("http://twitch.tv/frzok"))
        self.assertIsNone(twitch_login("https://twitch.tv/directory"))

    def test_extracts_first_twitch_streaming_activity(self) -> None:
        activities = [
            SimpleNamespace(
                type=SimpleNamespace(value=0, name="playing"),
                url="",
                name="World of Warcraft",
                game=None,
            ),
            SimpleNamespace(
                type=SimpleNamespace(value=1, name="streaming"),
                url="https://www.twitch.tv/Frzok",
                name="Гильдия Shadow Squad — Рекрутинг",
                game="Frostpunk 2",
            ),
        ]
        stream = twitch_stream_from_activities(activities)
        self.assertIsNotNone(stream)
        assert stream is not None
        self.assertEqual(stream.login, "Frzok")
        self.assertEqual(stream.game, "Frostpunk 2")
        self.assertEqual(stream.signature, "https://www.twitch.tv/frzok")

    def test_preview_url_is_stable_and_cache_busted(self) -> None:
        self.assertEqual(
            twitch_preview_url("Frzok", 123),
            "https://static-cdn.jtvnw.net/previews-ttv/"
            "live_user_frzok-640x360.jpg?v=123",
        )

    def test_active_stream_is_announced_only_once(self) -> None:
        activity = SimpleNamespace(
            type=SimpleNamespace(value=1, name="streaming"),
            url="https://www.twitch.tv/Frzok",
            name="Первое название",
            game="World of Warcraft",
        )
        stream = twitch_stream_from_activities([activity])
        assert stream is not None
        active: dict[int, str] = {}
        self.assertTrue(register_active_stream(active, 42, stream))
        self.assertFalse(register_active_stream(active, 42, stream))

        # Discord may update title/game while the same broadcast continues.
        activity.name = "Новое название"
        updated = twitch_stream_from_activities([activity])
        assert updated is not None
        self.assertFalse(register_active_stream(active, 42, updated))

        active.pop(42)
        self.assertTrue(register_active_stream(active, 42, updated))


if __name__ == "__main__":
    unittest.main()
