"""Preview and, after confirmation, bulk-remove stale WowUtils roster members."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deploy.configure_channel_permissions import load_dotenv

load_dotenv()

from blizzard import BlizzardClient, GuildCharacter


GROUP_ID = "67d466a3930df6653e745d22"
API_BASE = "https://api.wowutils.com/v1"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


@dataclass(frozen=True)
class Candidate:
    member_id: str
    display_name: str
    character_names: tuple[str, ...]
    claimed: bool


def normalize(value: object) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def wowutils_request(
    api_key: str,
    method: str,
    path: str,
) -> tuple[object | None, dict[str, str]]:
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "ShadowSquadBot/roster-cleanup",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            payload = json.loads(body.decode("utf-8")) if body else None
            return payload, {key.lower(): value for key, value in response.headers.items()}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"WowUtils API returned HTTP {error.code} for {method} {path}: {detail}"
        ) from error


async def current_guild_roster() -> list[GuildCharacter]:
    client = BlizzardClient(
        os.getenv("BLIZZARD_CLIENT_ID", ""),
        os.getenv("BLIZZARD_CLIENT_SECRET", ""),
        os.getenv("BLIZZARD_REGION", "eu").lower(),
        os.getenv("BLIZZARD_LOCALE", "ru_RU"),
        os.getenv("BLIZZARD_REALM_SLUG", "").strip().lower(),
        os.getenv("BLIZZARD_GUILD_SLUG", "").strip().lower(),
    )
    return await client.guild_roster()


def classify(
    members: list[dict[str, object]],
    guild_roster: list[GuildCharacter],
) -> tuple[list[Candidate], list[str], int]:
    exact_guild = {
        (normalize(character.name), normalize(character.realm_slug))
        for character in guild_roster
    }
    names_in_guild = {normalize(character.name) for character in guild_roster}
    candidates: list[Candidate] = []
    manual_review: list[str] = []
    matched_count = 0

    for member in members:
        member_id = str(member.get("memberId") or "")
        display_name = str(member.get("displayName") or member_id or "Без имени")
        characters = member.get("characters")
        if not isinstance(characters, list) or not characters:
            manual_review.append(f"{display_name} — нет привязанных персонажей")
            continue

        pairs: list[tuple[str, str]] = []
        readable_names: list[str] = []
        for character in characters:
            if not isinstance(character, dict):
                continue
            name = str(character.get("name") or "")
            realm = str(character.get("realm") or "")
            if name:
                readable_names.append(f"{name}-{realm}" if realm else name)
                pairs.append((normalize(name), normalize(realm)))

        if any(pair in exact_guild for pair in pairs):
            matched_count += 1
            continue
        if any(name in names_in_guild for name, _ in pairs):
            manual_review.append(
                f"{display_name} — имя есть в гильдии, но игровой мир отличается: "
                f"{', '.join(readable_names)}"
            )
            continue
        candidates.append(
            Candidate(
                member_id=member_id,
                display_name=display_name,
                character_names=tuple(readable_names),
                claimed=bool(member.get("claimed")),
            )
        )

    return candidates, manual_review, matched_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--member-id",
        action="append",
        default=[],
        help="confirmed candidate ID to delete; repeat for multiple members",
    )
    parser.add_argument(
        "--allowed-rank",
        action="append",
        type=int,
        default=[],
        help="guild rank allowed in WowUtils; repeat for multiple ranks",
    )
    args = parser.parse_args()

    api_key = os.getenv("WOWUTILS_API_KEY", "").strip()
    if not api_key:
        print("WOWUTILS_API_KEY is missing", file=sys.stderr)
        return 2

    payload, headers = wowutils_request(api_key, "GET", f"/groups/{GROUP_ID}/roster")
    if not isinstance(payload, dict) or not isinstance(payload.get("members"), list):
        raise RuntimeError("WowUtils returned an invalid roster payload")
    members = [item for item in payload["members"] if isinstance(item, dict)]
    guild_roster = asyncio.run(current_guild_roster())
    allowed_ranks = set(args.allowed_rank)
    eligible_roster = (
        [character for character in guild_roster if character.rank in allowed_ranks]
        if allowed_ranks
        else guild_roster
    )
    candidates, manual_review, matched_count = classify(members, eligible_roster)

    print(f"Игровой состав: {len(guild_roster)} персонажей")
    if allowed_ranks:
        print(
            "Разрешённые игровые ранги: "
            + ", ".join(str(rank) for rank in sorted(allowed_ranks))
            + f" ({len(eligible_roster)} персонажей)"
        )
    print(f"WowUtils: {len(members)} участников")
    print(f"Оставить автоматически: {matched_count}")
    print(f"Кандидаты на удаление: {len(candidates)}")
    for candidate in candidates:
        characters = ", ".join(candidate.character_names) or "нет персонажей"
        claimed = "; аккаунт привязан" if candidate.claimed else ""
        print(f"- {candidate.display_name}: {characters}{claimed} [{candidate.member_id}]")

    if manual_review:
        print(f"Требуют ручной проверки: {len(manual_review)}")
        for item in manual_review:
            print(f"- {item}")

    remaining = headers.get("x-ratelimit-remaining")
    if remaining:
        print(f"Остаток API-лимита после сверки: {remaining}")

    if not args.apply:
        print("Предварительный просмотр: ничего не удалено.")
        return 0

    requested = set(args.member_id)
    candidate_ids = {candidate.member_id for candidate in candidates}
    if not requested:
        raise RuntimeError("For --apply, pass at least one confirmed --member-id")
    unexpected = requested - candidate_ids
    if unexpected:
        raise RuntimeError(
            "Refusing to delete IDs that are no longer candidates: "
            + ", ".join(sorted(unexpected))
        )

    by_id = {candidate.member_id: candidate for candidate in candidates}
    for member_id in sorted(requested):
        wowutils_request(
            api_key,
            "DELETE",
            f"/groups/{GROUP_ID}/roster/members/{member_id}",
        )
        print(f"Удалён: {by_id[member_id].display_name} [{member_id}]")
    print(f"Удалено участников: {len(requested)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
