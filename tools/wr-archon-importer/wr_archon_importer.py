from __future__ import annotations

import base64
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError as exc:  # pragma: no cover - depends on the local Python build
    raise SystemExit("В установленном Python отсутствует Tkinter.") from exc


APP_TITLE = "WR Cloud → Archon"
WCR_API = "https://api.warcraftrecorder.com/api"
AUTO_MATCH_DELTA_MS = 30_000
REVIEW_MATCH_DELTA_MS = 120_000
USER_AGENT = "WR-Archon-Importer/0.1"


class ImporterError(RuntimeError):
    pass


@dataclass
class ArchonEntry:
    folder: Path
    metadata: dict[str, Any]


@dataclass
class Match:
    video: dict[str, Any]
    archon: ArchonEntry | None
    score: float
    delta_ms: int | None
    confidence: str
    reason: str


def json_load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} не содержит JSON-объект")
    return value


def atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=4)
        handle.write("\n")
    os.replace(temporary, path)


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return re.sub(r"\s+", " ", text)


def character_name(value: Any) -> str:
    # WoW character names cannot contain a hyphen; WCR often stores Name-Realm.
    return normalize_text(value).split("-", 1)[0]


def safe_filename(value: Any, fallback: str = "WR recording") -> str:
    text = str(value or fallback).strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"\s+", " ", text).rstrip(" .")
    if not text:
        text = fallback
    return text[:150].rstrip(" .")


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def wr_start_ms(video: dict[str, Any]) -> int | None:
    value = int_or_none(video.get("start"))
    if value is None:
        return None
    # Old exports may contain seconds rather than milliseconds.
    return value * 1000 if value < 100_000_000_000 else value


def wr_duration_seconds(video: dict[str, Any]) -> float | None:
    return float_or_none(video.get("duration"))


def wr_player_names(video: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    player = video.get("player")
    if isinstance(player, dict) and player.get("_name"):
        names.add(character_name(player["_name"]))
    combatants = video.get("combatants")
    if isinstance(combatants, list):
        for combatant in combatants:
            if isinstance(combatant, dict) and combatant.get("_name"):
                names.add(character_name(combatant["_name"]))
    names.discard("")
    return names


def archon_player_names(metadata: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    players = metadata.get("players")
    if isinstance(players, list):
        for player in players:
            if isinstance(player, dict) and player.get("name"):
                names.add(character_name(player["name"]))
    names.discard("")
    return names


def wr_actor_name(video: dict[str, Any]) -> str:
    player = video.get("player")
    if isinstance(player, dict):
        return str(player.get("_name") or "")
    return ""


def wr_encounter_id(video: dict[str, Any]) -> int | None:
    return int_or_none(video.get("encounterID"))


def archon_encounter_id(metadata: dict[str, Any]) -> int | None:
    encounter = metadata.get("encounter")
    if isinstance(encounter, dict):
        return int_or_none(encounter.get("id"))
    return None


def wr_activity_name(video: dict[str, Any]) -> str:
    for key in ("encounterName", "zoneName", "videoName"):
        if video.get(key):
            return str(video[key])
    return "Без названия"


def load_archon_entries(root: Path) -> list[ArchonEntry]:
    if not root.is_dir():
        raise ImporterError(f"Папка Archon не найдена: {root}")
    entries: list[ArchonEntry] = []
    for metadata_path in root.glob("*/metadata.json"):
        try:
            metadata = json_load(metadata_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        entries.append(ArchonEntry(metadata_path.parent, metadata))
    if not entries:
        raise ImporterError(
            "В выбранной папке нет метаданных Archon. "
            "Нужна папка вида …\\VOD\\warcraft-live."
        )
    return entries


def imported_ids(entries: Iterable[ArchonEntry]) -> set[str]:
    return {
        str(entry.metadata.get("id"))
        for entry in entries
        if entry.metadata.get("id")
    }


def video_identity(guild: str, video: dict[str, Any]) -> str:
    key = (
        video.get("videoKey")
        or video.get("videoName")
        or f"{video.get('uniqueHash', '')}:{video.get('start', '')}"
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"wcr://{guild}/{key}"))


def score_candidate(video: dict[str, Any], entry: ArchonEntry) -> tuple[float, int] | None:
    metadata = entry.metadata
    if not isinstance(metadata.get("serverFight"), dict):
        return None
    start = wr_start_ms(video)
    archon_start = int_or_none(metadata.get("startTime"))
    if start is None or archon_start is None:
        return None
    delta = abs(start - archon_start)
    if delta > REVIEW_MATCH_DELTA_MS:
        return None

    wr_encounter = wr_encounter_id(video)
    local_encounter = archon_encounter_id(metadata)
    if (
        wr_encounter is not None
        and local_encounter is not None
        and wr_encounter != local_encounter
    ):
        return None

    score = max(0.0, 100.0 - delta / 1_000.0)
    if wr_encounter is not None and wr_encounter == local_encounter:
        score += 120.0

    wr_names = wr_player_names(video)
    local_names = archon_player_names(metadata)
    if wr_names and local_names:
        overlap = len(wr_names & local_names) / max(1, min(len(wr_names), len(local_names)))
        score += overlap * 80.0

    if isinstance(video.get("result"), bool) and isinstance(metadata.get("isKill"), bool):
        if video["result"] == metadata["isKill"]:
            score += 20.0
        else:
            score -= 20.0

    duration = wr_duration_seconds(video)
    local_start = int_or_none(metadata.get("startTime"))
    local_end = int_or_none(metadata.get("endTime"))
    if duration is not None and local_start is not None and local_end is not None:
        local_duration = max(0.0, (local_end - local_start) / 1_000.0)
        difference = abs(duration - local_duration)
        if difference <= 10:
            score += 25.0
        elif difference <= 30:
            score += 10.0

    return score, delta


def find_match(video: dict[str, Any], entries: list[ArchonEntry]) -> Match:
    candidates: list[tuple[float, int, ArchonEntry]] = []
    for entry in entries:
        scored = score_candidate(video, entry)
        if scored is not None:
            score, delta = scored
            candidates.append((score, delta, entry))
    candidates.sort(key=lambda item: (-item[0], item[1]))

    if not candidates:
        return Match(video, None, 0, None, "none", "Подходящий бой Archon не найден")

    score, delta, entry = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    ambiguous = second is not None and abs(score - second[0]) < 15

    if delta <= AUTO_MATCH_DELTA_MS and score >= 160 and not ambiguous:
        confidence = "auto"
        reason = f"Точное совпадение, разница {delta / 1000:.1f} с"
    else:
        confidence = "review"
        reason = f"Нужна проверка, разница {delta / 1000:.1f} с"
        if ambiguous:
            reason += ", рядом есть другой похожий бой"
    return Match(video, entry, score, delta, confidence, reason)


def match_all(videos: list[dict[str, Any]], entries: list[ArchonEntry]) -> list[Match]:
    return [find_match(video, entries) for video in videos]


def actor_id_for_video(video: dict[str, Any], base: dict[str, Any]) -> int | None:
    wanted = character_name(wr_actor_name(video))
    if not wanted:
        return None
    players = base.get("players")
    if not isinstance(players, list):
        return None
    for player in players:
        if isinstance(player, dict) and character_name(player.get("name")) == wanted:
            return int_or_none(player.get("actorId"))
    return None


def build_archon_metadata(
    guild: str,
    video: dict[str, Any],
    matched: ArchonEntry,
    mp4_name: str,
) -> dict[str, Any]:
    metadata = copy.deepcopy(matched.metadata)
    start = wr_start_ms(video)
    duration = wr_duration_seconds(video)
    if start is None or duration is None:
        raise ImporterError("В метаданных WR отсутствуют start или duration")

    actor_id = actor_id_for_video(video, metadata)
    metadata["id"] = video_identity(guild, video)
    metadata["source"] = "disk"
    metadata["key"] = mp4_name
    metadata["startTimeOffsetMs"] = 0
    metadata["startTime"] = start
    metadata["endTime"] = start + round(duration * 1000)
    metadata["isKill"] = bool(video.get("result"))
    metadata["serverVideo"] = None
    metadata["serverVideoLastUpdated"] = None
    metadata["otherVideos"] = []
    metadata["otherVideosLastUpdated"] = None
    metadata["isFavorited"] = False
    if actor_id is not None:
        metadata["actorId"] = actor_id
    return metadata


class WcrClient:
    def __init__(self, username: str, password: str, guild: str) -> None:
        self.username = username
        self.password = password
        self.guild = guild

    def _headers(self) -> dict[str, str]:
        token = base64.b64encode(
            f"{self.username}:{self.password}".encode("utf-8")
        ).decode("ascii")
        return {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }

    def get_videos(self) -> list[dict[str, Any]]:
        encoded_guild = urllib.parse.quote(self.guild, safe="")
        url = f"{WCR_API}/guild/{encoded_guild}/video"
        request = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise ImporterError("WR отклонил логин или пароль") from exc
            if exc.code == 403:
                raise ImporterError("Нет доступа к указанной гильдии WR") from exc
            raise ImporterError(f"WR API вернул HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ImporterError(f"Не удалось подключиться к WR: {exc}") from exc
        if not isinstance(data, list):
            raise ImporterError("WR API вернул неожиданный ответ")
        return [item for item in data if isinstance(item, dict)]


def download_video(
    video: dict[str, Any],
    destination: Path,
    progress: Callable[[int], None] | None = None,
) -> None:
    signed_url = video.get("signedVideoKey")
    if not signed_url:
        raise ImporterError("WR не вернул временную ссылку на видео")
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(
        str(signed_url), headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            total = int_or_none(response.headers.get("Content-Length")) or 0
            received = 0
            with temporary.open("xb") as output:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    received += len(block)
                    if progress and total:
                        progress(min(100, round(received * 100 / total)))
        os.replace(temporary, destination)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def import_match(
    guild: str,
    match: Match,
    archon_root: Path,
    progress: Callable[[int], None] | None = None,
) -> Path:
    if match.archon is None:
        raise ImporterError("У записи нет сопоставленного боя")
    video = match.video
    identity = video_identity(guild, video)
    stem = safe_filename(video.get("videoName") or wr_activity_name(video))
    folder = archon_root / safe_filename(f"WR - {stem} - {identity[:8]}")
    mp4_name = f"{stem}.mp4"
    mp4_path = folder / mp4_name
    metadata_path = folder / "metadata.json"

    if folder.exists() or mp4_path.exists() or metadata_path.exists():
        raise ImporterError("Эта запись уже импортирована или её папка занята")

    folder.mkdir(parents=False, exist_ok=False)
    try:
        download_video(video, mp4_path, progress)
        metadata = build_archon_metadata(
            guild=guild,
            video=video,
            matched=match.archon,
            mp4_name=mp4_name,
        )
        atomic_json_write(metadata_path, metadata)
    except Exception:
        # Only remove the directory created by this invocation, and only when
        # it still contains no completed MP4 or metadata.
        if not mp4_path.exists() and not metadata_path.exists():
            shutil.rmtree(folder, ignore_errors=True)
        raise
    return folder


def detect_archon_root() -> Path:
    appdata = Path(os.environ.get("APPDATA", ""))
    log_path = appdata / "Archon App" / "logs" / "main.log"
    if log_path.is_file():
        try:
            text = log_path.read_text(encoding="utf-8", errors="ignore")
            matches = re.findall(r'"outputDirectoryPath":"((?:[^"\\]|\\.)+)"', text)
            if matches:
                decoded = json.loads(f'"{matches[-1]}"')
                candidate = Path(decoded) / "warcraft-live"
                if candidate.is_dir():
                    return candidate
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    common = [
        Path("D:/VOD/warcraft-live"),
        Path.home() / "Videos" / "Archon" / "warcraft-live",
    ]
    for candidate in common:
        if candidate.is_dir():
            return candidate
    return Path.home() / "Videos" / "Archon" / "warcraft-live"


def find_wcr_config() -> Path | None:
    appdata = Path(os.environ.get("APPDATA", ""))
    for folder in ("WarcraftRecorder", "Warcraft Recorder", "warcraftrecorder"):
        candidate = appdata / folder / "config-v3.json"
        if candidate.is_file():
            return candidate
    return None


def load_wcr_defaults() -> dict[str, str]:
    config_path = find_wcr_config()
    if config_path is None:
        return {}
    try:
        config = json_load(config_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return {
        "username": str(config.get("cloudAccountName") or ""),
        "password": str(config.get("cloudAccountPassword") or ""),
        "guild": str(config.get("cloudGuildName") or ""),
    }


def archon_is_running() -> bool:
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Archon App.exe"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "Archon App.exe" in result.stdout


def format_date(video: dict[str, Any]) -> str:
    start = wr_start_ms(video)
    if start is None:
        return "—"
    return datetime.fromtimestamp(start / 1000).strftime("%d.%m.%Y %H:%M:%S")


def format_duration(video: dict[str, Any]) -> str:
    duration = wr_duration_seconds(video)
    if duration is None:
        return "—"
    seconds = max(0, round(duration))
    return f"{seconds // 60}:{seconds % 60:02d}"


class ImporterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1120x680")
        self.root.minsize(900, 560)
        self.matches: list[Match] = []
        self.entries: list[ArchonEntry] = []
        self._busy = False

        defaults = load_wcr_defaults()
        self.username = tk.StringVar(value=defaults.get("username", ""))
        self.password = tk.StringVar(value=defaults.get("password", ""))
        self.guild = tk.StringVar(value=defaults.get("guild", ""))
        self.archon_path = tk.StringVar(value=str(detect_archon_root()))
        self.status = tk.StringVar(value="Готово к проверке")
        self.progress = tk.IntVar(value=0)

        self._build_ui()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)

        credentials = ttk.LabelFrame(outer, text="Доступ к Warcraft Recorder Cloud", padding=10)
        credentials.pack(fill="x")
        credentials.columnconfigure(1, weight=1)
        credentials.columnconfigure(3, weight=1)

        ttk.Label(credentials, text="Логин").grid(row=0, column=0, sticky="w")
        ttk.Entry(credentials, textvariable=self.username).grid(
            row=0, column=1, sticky="ew", padx=(8, 16)
        )
        ttk.Label(credentials, text="Пароль").grid(row=0, column=2, sticky="w")
        ttk.Entry(credentials, textvariable=self.password, show="•").grid(
            row=0, column=3, sticky="ew", padx=(8, 0)
        )
        ttk.Label(credentials, text="Гильдия WR").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Entry(credentials, textvariable=self.guild).grid(
            row=1, column=1, sticky="ew", padx=(8, 16), pady=(8, 0)
        )
        ttk.Label(credentials, text="Папка Archon").grid(
            row=1, column=2, sticky="w", pady=(8, 0)
        )
        path_frame = ttk.Frame(credentials)
        path_frame.grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        path_frame.columnconfigure(0, weight=1)
        ttk.Entry(path_frame, textvariable=self.archon_path).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(path_frame, text="Выбрать…", command=self._choose_folder).grid(
            row=0, column=1, padx=(8, 0)
        )

        actions = ttk.Frame(outer, padding=(0, 12, 0, 8))
        actions.pack(fill="x")
        self.check_button = ttk.Button(
            actions, text="1. Проверить облако", command=self._check_cloud
        )
        self.check_button.pack(side="left")
        self.import_button = ttk.Button(
            actions,
            text="2. Импортировать выбранные",
            command=self._import_selected,
            state="disabled",
        )
        self.import_button.pack(side="left", padx=(8, 0))
        ttk.Label(
            actions,
            text="Зелёные совпадения можно импортировать автоматически; жёлтые требуют проверки.",
        ).pack(side="left", padx=(16, 0))

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("date", "activity", "player", "duration", "match", "status")
        self.tree = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="extended"
        )
        headings = {
            "date": "Дата",
            "activity": "Активность",
            "player": "Точка зрения",
            "duration": "Длина",
            "match": "Привязка к логу",
            "status": "Статус",
        }
        widths = {
            "date": 145,
            "activity": 220,
            "player": 150,
            "duration": 60,
            "match": 310,
            "status": 140,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w")
        self.tree.tag_configure("auto", background="#dff3df")
        self.tree.tag_configure("review", background="#fff3cd")
        self.tree.tag_configure("none", foreground="#777777")
        scrollbar = ttk.Scrollbar(
            table_frame, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        footer = ttk.Frame(outer, padding=(0, 10, 0, 0))
        footer.pack(fill="x")
        ttk.Progressbar(
            footer, variable=self.progress, maximum=100, length=240
        ).pack(side="left")
        ttk.Label(footer, textvariable=self.status).pack(side="left", padx=(12, 0))

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(
            title="Выберите папку warcraft-live",
            initialdir=self.archon_path.get(),
        )
        if selected:
            self.archon_path.set(selected)

    def _credentials(self) -> tuple[str, str, str]:
        username = self.username.get().strip()
        password = self.password.get()
        guild = self.guild.get().strip()
        if not username or not password or not guild:
            raise ImporterError("Заполните логин, пароль и название гильдии WR")
        return username, password, guild

    def _set_busy(self, busy: bool, text: str | None = None) -> None:
        self._busy = busy
        self.check_button.configure(state="disabled" if busy else "normal")
        import_state = "disabled"
        if not busy and any(match.confidence == "auto" for match in self.matches):
            import_state = "normal"
        self.import_button.configure(state=import_state)
        if text:
            self.status.set(text)

    def _run_async(
        self,
        worker: Callable[[], Any],
        complete: Callable[[Any], None],
    ) -> None:
        def run() -> None:
            try:
                result = worker()
            except Exception as exc:
                self.root.after(0, lambda: self._show_error(exc))
            else:
                self.root.after(0, lambda: complete(result))

        threading.Thread(target=run, daemon=True).start()

    def _show_error(self, exc: Exception) -> None:
        self._set_busy(False, "Ошибка")
        messagebox.showerror(APP_TITLE, str(exc))

    def _check_cloud(self) -> None:
        if self._busy:
            return
        try:
            username, password, guild = self._credentials()
            archon_root = Path(self.archon_path.get()).expanduser()
        except ImporterError as exc:
            self._show_error(exc)
            return
        self._set_busy(True, "Читаю локальную библиотеку Archon…")
        self.progress.set(0)

        def worker() -> tuple[list[ArchonEntry], list[Match]]:
            entries = load_archon_entries(archon_root)
            videos = WcrClient(username, password, guild).get_videos()
            return entries, match_all(videos, entries)

        self._run_async(worker, self._show_matches)

    def _show_matches(self, result: tuple[list[ArchonEntry], list[Match]]) -> None:
        self.entries, self.matches = result
        existing = imported_ids(self.entries)
        for item in self.tree.get_children():
            self.tree.delete(item)
        auto_count = 0
        for index, match in enumerate(self.matches):
            identity = video_identity(self.guild.get().strip(), match.video)
            already = identity in existing
            if already:
                status = "Уже импортировано"
            elif match.confidence == "auto":
                status = "Готово"
                auto_count += 1
            elif match.confidence == "review":
                status = "Требует проверки"
            else:
                status = "Без пары"
            actor = wr_actor_name(match.video) or "—"
            values = (
                format_date(match.video),
                wr_activity_name(match.video),
                actor,
                format_duration(match.video),
                match.reason,
                status,
            )
            self.tree.insert(
                "", "end", iid=str(index), values=values, tags=(match.confidence,)
            )
        self.progress.set(100)
        self._set_busy(
            False,
            f"WR: {len(self.matches)} записей; уверенно сопоставлено новых: {auto_count}",
        )

    def _import_selected(self) -> None:
        if self._busy:
            return
        selected = list(self.tree.selection())
        if selected:
            indexes = [int(item) for item in selected]
        else:
            indexes = list(range(len(self.matches)))
        entries_existing = imported_ids(self.entries)
        selected_matches = [
            self.matches[index]
            for index in indexes
            if self.matches[index].confidence == "auto"
            and video_identity(self.guild.get().strip(), self.matches[index].video)
            not in entries_existing
        ]
        if not selected_matches:
            messagebox.showinfo(
                APP_TITLE,
                "Среди выбранных строк нет новых уверенно сопоставленных записей.",
            )
            return
        if archon_is_running():
            proceed = messagebox.askyesno(
                APP_TITLE,
                "Archon сейчас запущен. Новые файлы безопасно создать можно, "
                "но для их появления потребуется перезапуск Archon.\n\nПродолжить?",
            )
            if not proceed:
                return
        proceed = messagebox.askyesno(
            APP_TITLE,
            f"Будет загружено {len(selected_matches)} видео. "
            "Существующие файлы не изменяются.\n\nПродолжить?",
        )
        if not proceed:
            return

        guild = self.guild.get().strip()
        archon_root = Path(self.archon_path.get()).expanduser()
        self.progress.set(0)
        self._set_busy(True, "Начинаю импорт…")

        def worker() -> list[tuple[int, Path]]:
            imported: list[tuple[int, Path]] = []
            total = len(selected_matches)
            for position, match in enumerate(selected_matches, start=1):
                original_index = self.matches.index(match)

                def on_progress(value: int, pos: int = position) -> None:
                    overall = round(((pos - 1) + value / 100) * 100 / total)
                    self.root.after(0, lambda v=overall: self.progress.set(v))

                folder = import_match(guild, match, archon_root, on_progress)
                imported.append((original_index, folder))
                self.root.after(
                    0,
                    lambda i=original_index, p=position: self._mark_imported(
                        i, p, total
                    ),
                )
            return imported

        self._run_async(worker, self._import_complete)

    def _mark_imported(self, index: int, position: int, total: int) -> None:
        item = str(index)
        if self.tree.exists(item):
            values = list(self.tree.item(item, "values"))
            values[-1] = "Импортировано"
            self.tree.item(item, values=values)
        self.status.set(f"Импортировано {position} из {total}")

    def _import_complete(self, imported: list[tuple[int, Path]]) -> None:
        self.progress.set(100)
        self._set_busy(False, f"Готово: импортировано {len(imported)} видео")
        messagebox.showinfo(
            APP_TITLE,
            f"Импортировано видео: {len(imported)}.\n"
            "Перезапустите Archon, чтобы он обновил библиотеку.",
        )


def main() -> int:
    root = tk.Tk()
    try:
        root.iconname(APP_TITLE)
        ImporterApp(root)
        root.mainloop()
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
