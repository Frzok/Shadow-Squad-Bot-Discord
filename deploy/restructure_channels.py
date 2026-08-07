"""Apply the approved compact channel/category structure to Shadow Squad."""

from __future__ import annotations

import argparse
import os
import sys
import time

from configure_channel_permissions import DiscordAPI, load_dotenv


CATEGORY_NAMES = {
    "606955509941141526": ("📢📢📢INFO📢📢📢", "📢 ИНФОРМАЦИЯ"),
    "657179512538398730": ("👑👑👑OFFTOP👑👑👑", "💬 ГИЛЬДИЯ"),
    "1009730361850339328": ("Статик", "⚔️ СТАТИК"),
    "604571954422218754": ("🔔🔔🔔Voice🔔🔔🔔", "🔊 ГОЛОСОВЫЕ"),
    "606952372010221581": ("🤖🤖🤖BOTS🤖🤖🤖", "🤖 СЛУЖЕБНЫЕ"),
}

OLD_TACTICS_CATEGORY_ID = "1003921698833313872"
OLD_TACTICS_CATEGORY_NAME = "🌌🌌🌌тактики-галактики🌌🌌🌌"

INFO = "606955509941141526"
GUILD = "657179512538398730"
STATIC = "1009730361850339328"
VOICE = "604571954422218754"
SERVICE = "606952372010221581"

CHANNEL_PARENTS = {
    # Information.
    "809368762812989440": INFO,   # rules
    "809402292284686346": INFO,   # announcements
    "604573179138015281": INFO,   # news
    # Guild communication.
    "810474409755541524": GUILD,  # flood
    "1215605471709368402": GUILD, # memes
    # Current raid/static resources.
    "1200807297111306280": STATIC, # absences
    "1055007278593482822": STATIC, # weekly loot chest
    "659757581044023310": STATIC, # Raider.IO progress feed
    "1279440882679939133": STATIC, # healer discussion
    "1345828084640776343": STATIC, # current raid discussion
    "1485886206817599569": STATIC, # midnight forum
    "1486988199766265957": STATIC, # archon
    "1533466182793953320": STATIC, # wowutils
    "1487853265482813533": STATIC, # weak auras
    # Voice channels.
    "1263306154499641371": VOICE,  # key
    "713419816857370624": VOICE,   # raid
    "1270002159651655690": VOICE,  # officers
    "604579786538483712": VOICE,   # AFK
    "1388829320369410059": VOICE,  # recruiting voice
    # Bot and project channels.
    "809434235739963392": SERVICE, # invite tracking
    "604573142404562964": SERVICE, # streams feed
    "604578557733371905": STATIC, # Warcraft Logs report links
    "723427989521432628": SERVICE, # bot console
    "1530215989499662478": SERVICE,# current bot channel
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="apply changes; default is a dry run"
    )
    args = parser.parse_args()
    load_dotenv()
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("DISCORD_BOT_TOKEN is missing", file=sys.stderr)
        return 2

    api = DiscordAPI(token, args.apply)
    channels = {str(channel["id"]): channel for channel in api.channels()}
    errors: list[str] = []
    for category_id, (old_name, _) in CATEGORY_NAMES.items():
        channel = channels.get(category_id)
        if channel is None or int(channel["type"]) != 4:
            errors.append(f"category missing: {category_id} {old_name}")
        elif str(channel["name"]) not in {old_name, CATEGORY_NAMES[category_id][1]}:
            errors.append(f"category renamed unexpectedly: {category_id} #{channel['name']}")
    tactics = channels.get(OLD_TACTICS_CATEGORY_ID)
    if tactics is None or str(tactics["name"]) != OLD_TACTICS_CATEGORY_NAME:
        errors.append("old tactics category is missing or renamed")
    for channel_id in CHANNEL_PARENTS:
        if channel_id not in channels:
            errors.append(f"channel missing: {channel_id}")
    if errors:
        print("Safety validation failed; no changes were made:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    changes: list[tuple[str, str, str]] = []
    for category_id, (_, new_name) in CATEGORY_NAMES.items():
        if str(channels[category_id]["name"]) != new_name:
            changes.append((category_id, "name", new_name))
    for channel_id, parent_id in CHANNEL_PARENTS.items():
        if str(channels[channel_id].get("parent_id")) != parent_id:
            changes.append((channel_id, "parent_id", parent_id))

    action = "APPLY" if args.apply else "WOULD APPLY"
    for channel_id, field, value in changes:
        label = channels[channel_id]["name"]
        target = CATEGORY_NAMES[value][1] if field == "parent_id" else value
        print(f"{action} #{label}: {field} -> {target}")

    if args.apply:
        for channel_id, field, value in changes:
            api.request("PATCH", f"/channels/{channel_id}", {field: value})
            time.sleep(0.2)
        refreshed = api.channels()
        if any(
            str(channel.get("parent_id")) == OLD_TACTICS_CATEGORY_ID
            for channel in refreshed
        ):
            raise RuntimeError("old tactics category is not empty after channel moves")
        api.request("DELETE", f"/channels/{OLD_TACTICS_CATEGORY_ID}")
        print(f"DELETE empty category #{OLD_TACTICS_CATEGORY_NAME}")
    else:
        print(f"WOULD DELETE empty category #{OLD_TACTICS_CATEGORY_NAME}")

    print(f"{'Applied' if args.apply else 'Planned'} changes: {len(changes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
