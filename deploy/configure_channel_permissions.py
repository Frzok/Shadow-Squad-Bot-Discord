"""Synchronize the Shadow Squad Discord channel visibility policy.

The command is a dry run by default. Pass ``--apply`` to update Discord.
It only changes the View Channel and Connect permission bits and preserves all
other channel-specific permission settings.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


GUILD_ID = "604571954422218752"
EVERYONE_ID = GUILD_ID

ROLE_IDS = {
    "РЛ": "604574054938181643",
    "Знаменосец": "604581483071537154",
    "Сержант": "604574109485105194",
    "Летописец": "665163320776720414",
    "Друзья": "632173311018926091",
}

FLOOD_CHANNEL_ID = "810474409755541524"
ABSENCE_CHANNEL_ID = "1200807297111306280"
LEGACY_ABSENCE_CHANNEL_ID = "1044167366004703232"
RAID_VOICE_CHANNEL_ID = "713419816857370624"
OFFICER_VOICE_CHANNEL_ID = "1270002159651655690"
KEY_VOICE_CHANNEL_ID = "1263306154499641371"
SERVICE_CATEGORY_ID = "606952372010221581"

TEXT_CHANNEL_TYPES = {0, 5, 15, 16}
VIEW_CHANNEL = 1 << 10
CONNECT = 1 << 20

GUILD_AND_FRIEND_ROLES = frozenset(ROLE_IDS.values())
RAID_ROLES = GUILD_AND_FRIEND_ROLES
OFFICER_ROLES = frozenset(
    ROLE_IDS[name] for name in ("РЛ", "Знаменосец")
)
PRIVATE_TEXT_CHANNELS = {FLOOD_CHANNEL_ID, ABSENCE_CHANNEL_ID}
UNCHANGED_CHANNELS = {KEY_VOICE_CHANNEL_ID, LEGACY_ABSENCE_CHANNEL_ID}


def load_dotenv() -> None:
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


class DiscordAPI:
    def __init__(self, token: str, apply: bool) -> None:
        self.apply = apply
        self.headers = {
            "Authorization": f"Bot {token}",
            "User-Agent": "ShadowSquadBot/channel-permissions",
        }

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> object | None:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = dict(self.headers)
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if method != "GET":
            headers["X-Audit-Log-Reason"] = urllib.parse.quote(
                "Синхронизация прав каналов Shadow Squad"
            )
        request = urllib.request.Request(
            f"https://discord.com/api/v10{path}",
            data=data,
            headers=headers,
            method=method,
        )
        for attempt in range(6):
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    body = response.read()
                    return json.loads(body) if body else None
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")
                if error.code == 429 and attempt < 5:
                    try:
                        retry_after = float(json.loads(detail)["retry_after"])
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                        retry_after = 1.0
                    time.sleep(retry_after + 0.1)
                    continue
                raise RuntimeError(
                    f"Discord API returned {error.code} for {method} {path}: {detail}"
                ) from error
        raise RuntimeError(f"Discord rate limit did not clear for {method} {path}")

    def channels(self) -> list[dict[str, object]]:
        result = self.request("GET", f"/guilds/{GUILD_ID}/channels")
        if not isinstance(result, list):
            raise RuntimeError("Discord returned an invalid channel list")
        return result

    def set_overwrite(
        self, channel_id: str, target_id: str, overwrite_type: int, allow: int, deny: int
    ) -> None:
        if not self.apply:
            return
        self.request(
            "PUT",
            f"/channels/{channel_id}/permissions/{target_id}",
            {"type": overwrite_type, "allow": str(allow), "deny": str(deny)},
        )
        time.sleep(0.15)


def update_bits(
    allow: int,
    deny: int,
    *,
    allow_bits: int = 0,
    deny_bits: int = 0,
    clear_bits: int = 0,
    clear_deny_bits: int = 0,
) -> tuple[int, int]:
    allow &= ~clear_bits
    deny &= ~(clear_bits | clear_deny_bits)
    allow = (allow & ~deny_bits) | allow_bits
    deny = (deny & ~allow_bits) | deny_bits
    return allow, deny


def desired_overwrites(
    channel: dict[str, object], *, include_public_text: bool = False
) -> list[tuple[str, int, int, int]]:
    channel_id = str(channel["id"])
    channel_type = int(channel["type"])
    original = {
        str(item["id"]): (int(item["type"]), int(item["allow"]), int(item["deny"]))
        for item in channel.get("permission_overwrites", [])
    }
    desired = dict(original)

    def change(
        target_id: str,
        target_type: int,
        *,
        allow_bits: int = 0,
        deny_bits: int = 0,
        clear_bits: int = 0,
        clear_deny_bits: int = 0,
    ) -> None:
        _, allow, deny = desired.get(target_id, (target_type, 0, 0))
        allow, deny = update_bits(
            allow,
            deny,
            allow_bits=allow_bits,
            deny_bits=deny_bits,
            clear_bits=clear_bits,
            clear_deny_bits=clear_deny_bits,
        )
        desired[target_id] = (target_type, allow, deny)

    if (
        include_public_text
        and channel_type in TEXT_CHANNEL_TYPES
        and channel_id not in PRIVATE_TEXT_CHANNELS
        and str(channel.get("parent_id")) != SERVICE_CATEGORY_ID
    ):
        # Public text channels are visible. Remove role/member visibility denials
        # so an unrelated role cannot accidentally hide one again.
        change(EVERYONE_ID, 0, allow_bits=VIEW_CHANNEL)
        for target_id, (target_type, _, _) in tuple(desired.items()):
            if target_id != EVERYONE_ID:
                change(target_id, target_type, clear_deny_bits=VIEW_CHANNEL)

    if channel_id in PRIVATE_TEXT_CHANNELS:
        change(EVERYONE_ID, 0, deny_bits=VIEW_CHANNEL, clear_bits=VIEW_CHANNEL)
        for target_id, (target_type, _, _) in tuple(desired.items()):
            if target_id not in GUILD_AND_FRIEND_ROLES and target_id != EVERYONE_ID:
                change(target_id, target_type, clear_bits=VIEW_CHANNEL)
        for role_id in GUILD_AND_FRIEND_ROLES:
            change(role_id, 0, allow_bits=VIEW_CHANNEL, clear_bits=VIEW_CHANNEL)

    if channel_id in {RAID_VOICE_CHANNEL_ID, OFFICER_VOICE_CHANNEL_ID}:
        allowed_roles = (
            RAID_ROLES if channel_id == RAID_VOICE_CHANNEL_ID else OFFICER_ROLES
        )
        protected_bits = VIEW_CHANNEL | CONNECT
        change(
            EVERYONE_ID,
            0,
            deny_bits=protected_bits,
            clear_bits=protected_bits,
        )
        for target_id, (target_type, _, _) in tuple(desired.items()):
            if target_id not in allowed_roles and target_id != EVERYONE_ID:
                change(target_id, target_type, clear_bits=protected_bits)
        for role_id in allowed_roles:
            change(
                role_id,
                0,
                allow_bits=protected_bits,
                clear_bits=protected_bits,
            )

    return [
        (target_id, value[0], value[1], value[2])
        for target_id, value in desired.items()
        if original.get(target_id) != value
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="apply changes; default is a dry run"
    )
    parser.add_argument(
        "--include-public-text",
        action="store_true",
        help="also make every other text channel visible; this is intentionally opt-in",
    )
    args = parser.parse_args()
    load_dotenv()
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("DISCORD_BOT_TOKEN is missing", file=sys.stderr)
        return 2

    api = DiscordAPI(token, args.apply)
    channels = api.channels()
    channel_names = {str(channel["id"]): str(channel["name"]) for channel in channels}
    role_names = {role_id: name for name, role_id in ROLE_IDS.items()}
    role_names[EVERYONE_ID] = "@everyone"
    changed = 0
    for channel in channels:
        channel_id = str(channel["id"])
        if channel_id in UNCHANGED_CHANNELS:
            continue
        for target_id, target_type, allow, deny in desired_overwrites(
            channel, include_public_text=args.include_public_text
        ):
            changed += 1
            target = role_names.get(
                target_id, f"member:{target_id}" if target_type == 1 else target_id
            )
            print(
                f"{'APPLY' if args.apply else 'WOULD APPLY'} "
                f"#{channel_names[channel_id]} -> {target}: allow={allow} deny={deny}"
            )
            api.set_overwrite(channel_id, target_id, target_type, allow, deny)
    print(f"{'Applied' if args.apply else 'Planned'} overwrites: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
