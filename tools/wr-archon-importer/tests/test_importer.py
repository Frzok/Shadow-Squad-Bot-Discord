import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "wr_archon_importer.py"
SPEC = importlib.util.spec_from_file_location("wr_archon_importer", MODULE_PATH)
assert SPEC and SPEC.loader
importer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(importer)


def archon_metadata(start=1_750_000_000_000, encounter=1234):
    return {
        "id": "existing-id",
        "actorId": 7,
        "source": "disk",
        "key": "existing.mp4",
        "startTimeOffsetMs": 3100,
        "name": "Mythic Test Boss",
        "contentType": {"id": "raids", "name": "Raids"},
        "zone": {"id": 1, "name": "Test Zone"},
        "difficulty": {"id": 5, "name": "Mythic"},
        "size": {"id": 20, "name": "20-Player"},
        "encounter": {"id": encounter, "name": "Test Boss"},
        "startTime": start,
        "endTime": start + 180_000,
        "isKill": False,
        "players": [
            {
                "actorId": 7,
                "name": "Viewer",
                "serverName": "Realm",
                "fullType": "Mage-Arcane",
            },
            {
                "actorId": 8,
                "name": "Cloudplayer",
                "serverName": "Realm",
                "fullType": "Priest-Holy",
            },
        ],
        "serverFight": {"reportCode": "abc123", "fightId": 42},
        "serverFightLastUpdated": start + 200_000,
        "serverVideo": None,
        "serverVideoLastUpdated": None,
        "otherVideos": [],
        "otherVideosLastUpdated": None,
        "isFavorited": False,
    }


def wr_video(start=1_750_000_004_000, encounter=1234):
    return {
        "videoName": "Cloudplayer - Test Boss",
        "videoKey": "cloud-key.mp4",
        "signedVideoKey": "https://example.invalid/signed",
        "start": start,
        "duration": 180,
        "result": False,
        "encounterID": encounter,
        "encounterName": "Test Boss",
        "category": "Raids",
        "player": {"_name": "Cloudplayer-Realm", "_realm": "Realm"},
        "combatants": [
            {"_name": "Viewer-Realm"},
            {"_name": "Cloudplayer-Realm"},
        ],
    }


class ImporterTests(unittest.TestCase):
    def test_loads_archon_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "fight"
            folder.mkdir()
            (folder / "metadata.json").write_text(
                json.dumps(archon_metadata()), encoding="utf-8"
            )
            entries = importer.load_archon_entries(Path(directory))
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].metadata["serverFight"]["fightId"], 42)

    def test_exact_fight_is_automatic(self):
        entry = importer.ArchonEntry(Path("fight"), archon_metadata())
        match = importer.find_match(wr_video(), [entry])
        self.assertEqual(match.confidence, "auto")
        self.assertEqual(match.delta_ms, 4_000)

    def test_wrong_encounter_is_rejected(self):
        entry = importer.ArchonEntry(Path("fight"), archon_metadata(encounter=9999))
        match = importer.find_match(wr_video(encounter=1234), [entry])
        self.assertEqual(match.confidence, "none")

    def test_distant_fight_is_rejected(self):
        entry = importer.ArchonEntry(Path("fight"), archon_metadata())
        video = wr_video(start=1_750_000_500_000)
        match = importer.find_match(video, [entry])
        self.assertEqual(match.confidence, "none")

    def test_metadata_reuses_server_fight_and_changes_actor(self):
        entry = importer.ArchonEntry(Path("fight"), archon_metadata())
        video = wr_video()
        built = importer.build_archon_metadata(
            "Guild", video, entry, "cloud.mp4"
        )
        self.assertEqual(built["serverFight"]["reportCode"], "abc123")
        self.assertEqual(built["serverFight"]["fightId"], 42)
        self.assertEqual(built["actorId"], 8)
        self.assertEqual(built["key"], "cloud.mp4")
        self.assertEqual(built["startTimeOffsetMs"], 0)
        self.assertEqual(built["endTime"] - built["startTime"], 180_000)
        self.assertNotEqual(built["id"], entry.metadata["id"])

    def test_identity_is_stable(self):
        first = importer.video_identity("Guild", wr_video())
        second = importer.video_identity("Guild", wr_video())
        self.assertEqual(first, second)

    def test_safe_filename_removes_windows_characters(self):
        self.assertEqual(importer.safe_filename('a<b>c:"d"/e\\f|g?*'), "a_b_c__d__e_f_g__")


if __name__ == "__main__":
    unittest.main()
