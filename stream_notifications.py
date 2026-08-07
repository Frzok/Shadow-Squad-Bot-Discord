"""Pure helpers for Discord Twitch stream presence notifications."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, MutableMapping, Optional, Protocol
from urllib.parse import urlparse


TWITCH_HOSTS = frozenset({"twitch.tv", "www.twitch.tv", "m.twitch.tv"})
TWITCH_LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,25}$")
TWITCH_RESERVED_PATHS = frozenset(
    {"directory", "downloads", "jobs", "p", "settings", "subscriptions", "videos"}
)


class ActivityLike(Protocol):
    type: object
    url: str
    name: Optional[str]
    game: Optional[str]


@dataclass(frozen=True)
class TwitchStream:
    url: str
    login: str
    title: str
    game: str

    @property
    def signature(self) -> str:
        # A title/game change during one broadcast must not create a duplicate.
        return self.url.casefold().rstrip("/")


def twitch_login(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in TWITCH_HOSTS:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None
    login = parts[0]
    if (
        login.casefold() in TWITCH_RESERVED_PATHS
        or TWITCH_LOGIN_PATTERN.fullmatch(login) is None
    ):
        return None
    return login


def is_streaming_type(activity_type: object) -> bool:
    return (
        getattr(activity_type, "value", None) == 1
        or getattr(activity_type, "name", None) == "streaming"
    )


def twitch_stream_from_activities(
    activities: Iterable[ActivityLike],
) -> Optional[TwitchStream]:
    for activity in activities:
        if not is_streaming_type(getattr(activity, "type", None)):
            continue
        url = str(getattr(activity, "url", "") or "")
        login = twitch_login(url)
        if login is None:
            continue
        title = str(getattr(activity, "name", "") or "Стрим на Twitch").strip()
        game = str(getattr(activity, "game", "") or "Не указана").strip()
        return TwitchStream(url=url, login=login, title=title, game=game)
    return None


def twitch_preview_url(login: str, cache_key: int) -> str:
    if TWITCH_LOGIN_PATTERN.fullmatch(login) is None:
        raise ValueError("Invalid Twitch login")
    return (
        "https://static-cdn.jtvnw.net/previews-ttv/"
        f"live_user_{login.casefold()}-640x360.jpg?v={cache_key}"
    )


def register_active_stream(
    active_streams: MutableMapping[int, str],
    member_id: int,
    stream: TwitchStream,
) -> bool:
    """Register a stream and return True only when it should be announced."""
    if active_streams.get(member_id) == stream.signature:
        return False
    active_streams[member_id] = stream.signature
    return True
