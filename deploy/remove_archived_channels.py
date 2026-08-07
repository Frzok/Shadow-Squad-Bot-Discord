"""Remove the explicitly approved legacy Discord channels.

The command is a dry run by default. Pass ``--apply`` to delete the validated
channels. A channel is skipped if either its ID or its current name does not
match this manifest.
"""

from __future__ import annotations

import argparse
import sys
import time

from configure_channel_permissions import DiscordAPI, load_dotenv


ARCHIVED_CHANNELS = {
    # Old raid tiers, seasons, and retrospective channels.
    "1003921898134057072": "🧛замок-нафрия",
    "1003922526382080020": "⛓святилище-господства",
    "1003922589720264734": "⚙гробница-предвечных",
    "1026871238703976569": "🐲хранилище-воплощений",
    "1048731948018843728": "dragonflight",
    "1065589295420813342": "где-сложный-босс-вот-сложный-босс",
    "1102500357885661224": "оглядываясь-назад",
    "1102635966524559481": "🦮абберий",
    "1204112307047899156": "amirdrasil",
    "1231165316831379496": "🕓4-йсезон",
    "1263310185531965531": "🔥the-war-within",
    "1329394727241646101": "🤖liberation-of-undermine",
    "1342850232525914213": "оглядываясь-назад-нд",
    "1343503282777358429": "🪖всякое-по-tww",
    "1386284323740848208": "🕳️manaforge-omega",
    "1386598841658249297": "оглядываясь-назад-шахта",
    "1401943675210301511": "оглядываясь-назад-твв",
    # Old game channels.
    "1197991654641115236": "🐩lethal-company",
    "1308451001312870430": "destiny-2",
    "1336330853902712943": "goose-goose-duck",
    "1336330884910940262": "deep-rock-galactic",
    "1336330940330541097": "lethal-company",
    # Superseded absence channel.
    "1044167366004703232": "🐷опоздуны",
    # Old officer channels.
    "657180220180398091": "офицерский-чат",
    "659133247896158248": "записная-книжка-труер",
    "1052318559398801549": "офицерская-капралы",
    # Clearly abandoned OFFTOP channels.
    "635107790142177301": "🐀шкаф-с-бельём",
    "810478921191129138": "🦄wa-macro",
    "934063302512873503": "рекрутинг",
    "976242370481885304": "🙀крутилочная",
    "976743816751099904": "💌copy-paste",
    "987335196804276275": "🙌френдс-4ревер",
    "1002895770363625522": "мастерская",
    "1073610841586413628": "🪙бухгалтерия",
    "1079729136681103390": "дафия-хуяфия",
    "1091779428360663090": "курочка",
    "1107016308505182328": "🪙бухие-ключи",
    "1111994220320923798": "✍авторизация",
    "1212857783419150366": "🍑ебальня",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="delete channels; default is a dry run"
    )
    args = parser.parse_args()

    load_dotenv()
    import os

    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("DISCORD_BOT_TOKEN is missing", file=sys.stderr)
        return 2

    api = DiscordAPI(token, args.apply)
    channels = {str(channel["id"]): channel for channel in api.channels()}
    mismatches: list[str] = []
    candidates: list[tuple[str, str]] = []
    for channel_id, expected_name in ARCHIVED_CHANNELS.items():
        channel = channels.get(channel_id)
        if channel is None:
            mismatches.append(f"missing: {channel_id} #{expected_name}")
            continue
        actual_name = str(channel["name"])
        if actual_name != expected_name:
            mismatches.append(
                f"renamed: {channel_id} expected #{expected_name}, got #{actual_name}"
            )
            continue
        candidates.append((channel_id, expected_name))

    if mismatches:
        print("Safety validation failed; no channels were deleted:", file=sys.stderr)
        for mismatch in mismatches:
            print(f"- {mismatch}", file=sys.stderr)
        return 1

    action = "DELETE" if args.apply else "WOULD DELETE"
    for channel_id, name in candidates:
        print(f"{action} {channel_id} #{name}")

    if args.apply:
        for channel_id, _ in candidates:
            api.request("DELETE", f"/channels/{channel_id}")
            time.sleep(0.2)

    print(f"{'Deleted' if args.apply else 'Planned deletions'}: {len(candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
