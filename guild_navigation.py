"""Поиск по разделам Discord и разбор ссылок/версий для служебных задач."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NavigationEntry:
    key: str
    title: str
    description: str
    url: str
    aliases: tuple[str, ...]


NAVIGATION_ENTRIES = (
    NavigationEntry(
        "start",
        "👋 Начать здесь",
        "Правила, расписание и карта сервера",
        "https://discord.com/channels/604571954422218752/809368762812989440",
        ("начать", "правила", "расписание", "роли", "новичок"),
    ),
    NavigationEntry(
        "tactics",
        "🌙 Форум тактик",
        "Тактики, макросы, WeakAuras и импорты по боссам",
        "https://discord.com/channels/604571954422218752/1485886206817599569",
        ("тактики", "тактика", "боссы", "босс", "макросы", "tr импорты"),
    ),
    NavigationEntry(
        "tools",
        "🧰 Рейдовые инструменты",
        "Аддоны, настройка, архивы и помощь",
        "https://discord.com/channels/604571954422218752/1535621607815385122",
        ("аддоны", "аддон", "инструменты", "настройка", "рейдовые инструменты"),
    ),
    NavigationEntry(
        "timeline",
        "⏱️ Timeline Reminder",
        "Актуальный архив и инструкция по настройке",
        "https://discord.com/channels/604571954422218752/1535621623091302422",
        ("timeline", "timeline reminder", "tr", "таймлайн", "архив timeline"),
    ),
    NavigationEntry(
        "archon",
        "☁️ Archon App",
        "Установка, запись VoD и облако гильдии",
        "https://discord.com/channels/604571954422218752/1535621644645564557",
        ("archon", "archon app", "вод", "vod", "запись рейда", "облако"),
    ),
    NavigationEntry(
        "mrt",
        "📝 Method Raid Tools",
        "Рейдовая заметка и связанные напоминания",
        "https://discord.com/channels/604571954422218752/1535621614144720926",
        ("mrt", "method raid tools", "заметка"),
    ),
    NavigationEntry(
        "nsrt",
        "🧭 NSRT",
        "Базовые рейдовые напоминания и утилиты",
        "https://discord.com/channels/604571954422218752/1535621626979160146",
        ("nsrt", "northern sky", "приватные ауры", "интерапты"),
    ),
    NavigationEntry(
        "weakauras",
        "✨ M33kAuras и WeakAuras",
        "Рабочий форк и полезные ауры",
        "https://discord.com/channels/604571954422218752/1535621629722230886",
        ("wa", "weakauras", "weak auras", "m33k", "m33kauras", "ауры"),
    ),
    NavigationEntry(
        "absence",
        "🐷 Отсутствия и опоздания",
        "Предупредить об отсутствии или опоздании на РТ",
        "https://discord.com/channels/604571954422218752/1200807297111306280",
        ("отсутствие", "опоздание", "не приду", "опоздаю", "absence"),
    ),
    NavigationEntry(
        "loot",
        "🎁 Недельный лут",
        "Полученный лут и история выдачи",
        "https://discord.com/channels/604571954422218752/1055007278593482822",
        ("лут", "недельный лут", "rc", "rclootcouncil", "вещи"),
    ),
    NavigationEntry(
        "logs",
        "📈 Warcraft Logs",
        "Логи рейдов",
        "https://discord.com/channels/604571954422218752/604578557733371905",
        ("логи", "warcraft logs", "wcl", "парсы"),
    ),
    NavigationEntry(
        "analysis",
        "🏠 Разборы РТ",
        "Записи, ошибки и работа над механиками",
        "https://discord.com/channels/604571954422218752/1345828084640776343",
        ("разбор", "разборы", "ошибки", "домик", "домик ебли"),
    ),
    NavigationEntry(
        "progress",
        "🚧 Прогресс гильдии",
        "Текущий рейдовый прогресс",
        "https://discord.com/channels/604571954422218752/659757581044023310",
        ("прогресс", "убитые боссы", "киллы"),
    ),
    NavigationEntry(
        "healers",
        "💚 Чат хилов",
        "Обсуждение лекарей основного состава",
        "https://discord.com/channels/604571954422218752/1279440882679939133",
        ("хилы", "хил", "лекари", "чат хилов"),
    ),
    NavigationEntry(
        "chat",
        "🐓 Флудильня",
        "Основной чат гильдии",
        "https://discord.com/channels/604571954422218752/810474409755541524",
        ("чат", "флуд", "флудилка", "флудильня", "общение"),
    ),
    NavigationEntry(
        "memes",
        "😆 Мемесы",
        "Мемы и смешные материалы",
        "https://discord.com/channels/604571954422218752/1215605471709368402",
        ("мемы", "мем", "мемесы"),
    ),
    NavigationEntry(
        "bot_ideas",
        "🤖 Предложения по боту",
        "Ошибки, пожелания и идеи по автоматизации",
        "https://discord.com/channels/604571954422218752/1530215989499662478",
        ("бот", "предложение", "идея", "ошибка бота", "баг"),
    ),
)

DISCORD_LINK_RE = re.compile(
    r"https://(?:www\.)?discord(?:app)?\.com/channels/"
    r"(?P<guild>\d+)/(?P<channel>\d+)(?:/(?P<message>\d+))?"
)
TIMELINE_ARCHIVE_SUFFIXES = frozenset({".zip", ".rar", ".7z"})


def normalize_search(value: str) -> str:
    normalized = value.strip().casefold().replace("ё", "е")
    return " ".join(re.sub(r"[^\w]+", " ", normalized).split())


def find_navigation_entries(query: str, limit: int = 5) -> list[NavigationEntry]:
    needle = normalize_search(query)
    if not needle:
        return []
    matches: list[tuple[int, int, NavigationEntry]] = []
    for position, entry in enumerate(NAVIGATION_ENTRIES):
        candidates = (entry.key, entry.title, *entry.aliases)
        normalized = [normalize_search(candidate) for candidate in candidates]
        if needle in normalized:
            score = 0
        elif any(candidate.startswith(needle) for candidate in normalized):
            score = 1
        elif any(needle in candidate for candidate in normalized):
            score = 2
        elif all(
            any(word in candidate for candidate in normalized)
            for word in needle.split()
        ):
            score = 3
        else:
            continue
        matches.append((score, position, entry))
    matches.sort(key=lambda item: (item[0], item[1]))
    return [entry for _, _, entry in matches[:limit]]


def discord_link_targets(content: str) -> set[tuple[int, int, int | None, str]]:
    return {
        (
            int(match.group("guild")),
            int(match.group("channel")),
            int(match.group("message")) if match.group("message") else None,
            match.group(0),
        )
        for match in DISCORD_LINK_RE.finditer(content)
    }


def is_timeline_archive(filename: str) -> bool:
    return Path(filename).suffix.casefold() in TIMELINE_ARCHIVE_SUFFIXES


def extract_timeline_version(*values: str) -> str | None:
    text = " ".join(values)
    patterns = (
        r"(?i)(?:^|\W)v(?:ersion)?[\s._-]*(\d+(?:\.\d+)*)\b",
        r"(?i)timeline\s*reminders?[\s._-]+(?:v[\s._-]*)?(\d+(?:\.\d+)*)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return f"v{match.group(1)}"
    return None
