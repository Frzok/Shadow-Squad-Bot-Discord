"""Create the read-only WowUtils guide channel and publish its instructions."""

from __future__ import annotations

import argparse
import os
import sys

from configure_channel_permissions import DiscordAPI, GUILD_ID, ROLE_IDS, load_dotenv


STATIC_CATEGORY_ID = "1009730361850339328"
ARCHON_CHANNEL_ID = "1486988199766265957"
CHANNEL_NAME = "🧭настройка-wowutils"
CHANNEL_TOPIC = (
    "Подключение к WowUtils / Viserio Cooldowns, привязка персонажа "
    "и работа с рейдовыми Setup."
)
GUIDE_MARKER = "shadow-squad-wowutils-guide-v1"
GUIDE_MESSAGE_ID = "1533466190465208354"
WOWUTILS_INVITE_URL = (
    "https://wowutils.com/viserio-cooldowns/groups/join?"
    "token=331170bb0f942958ed8322f34def15d1&utm_source=invite&utm_medium=app_share"
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
EMBED_LINKS = 1 << 14
ATTACH_FILES = 1 << 15
READ_MESSAGE_HISTORY = 1 << 16
CREATE_PUBLIC_THREADS = 1 << 35
CREATE_PRIVATE_THREADS = 1 << 36
SEND_MESSAGES_IN_THREADS = 1 << 38

WRITE_BITS = (
    SEND_MESSAGES
    | CREATE_PUBLIC_THREADS
    | CREATE_PRIVATE_THREADS
    | SEND_MESSAGES_IN_THREADS
)
PUBLISH_BITS = (
    VIEW_CHANNEL
    | SEND_MESSAGES
    | EMBED_LINKS
    | ATTACH_FILES
    | READ_MESSAGE_HISTORY
    | SEND_MESSAGES_IN_THREADS
)


def guide_embeds() -> list[dict[str, object]]:
    return [
        {
            "title": "🧭 WowUtils / Viserio Cooldowns — как подключиться",
            "description": (
                "WowUtils мы используем для рейдовых Setup, хиловских "
                "кулдаунов и личных назначений.\n\n"
                "**Привязку нужно сделать один раз:**\n"
                f"1. [Откройте приглашение в группу Shadow Squad]({WOWUTILS_INVITE_URL}).\n"
                "2. Войдите через **Battle.net**.\n"
                "3. Откройте `My Group → Shadow Squad → Состав`.\n"
                "4. Найдите своего персонажа и в меню `…` выберите **Claim as mine**.\n"
                "5. В **Set Up Characters** отметьте персонажей как `Main`, `Alt` или `Off`."
            ),
            "color": 0x6C5CE7,
        },
        {
            "title": "👤 Что важно знать",
            "description": (
                "• **Персонаж** и **игрок WowUtils** — это разные вещи. Надпись "
                "`Linked player` появится только после входа и привязки.\n"
                "• **Не создавайте себе дубль**, если персонаж уже есть в составе.\n"
                "• Если нет вашего персонажа, напишите РЛ: возможно, ещё не завершилась "
                "синхронизация гильдии.\n"
                "• После привязки не нужно создавать себя заново для каждого рейда — РЛ "
                "просто добавляет вас в нужный Setup."
            ),
            "color": 0x00B894,
            "footer": {"text": GUIDE_MARKER},
        },
    ]


def guide_content() -> str:
    from reformat_guide_channels import WOWUTILS_TEXT

    return WOWUTILS_TEXT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("DISCORD_BOT_TOKEN is missing", file=sys.stderr)
        return 2

    api = DiscordAPI(token, args.apply)
    channels = api.channels()
    archon = next((c for c in channels if str(c["id"]) == ARCHON_CHANNEL_ID), None)
    if archon is None or str(archon.get("parent_id")) != STATIC_CATEGORY_ID:
        raise RuntimeError("Archon channel is missing or no longer in the Static category")

    matches = [c for c in channels if str(c.get("name")) == CHANNEL_NAME]
    if len(matches) > 1:
        raise RuntimeError(f"Found multiple channels named {CHANNEL_NAME}")

    channel = matches[0] if matches else None
    if channel is None:
        print(f"{'CREATE' if args.apply else 'WOULD CREATE'} #{CHANNEL_NAME}")
        if not args.apply:
            print("WOULD PUBLISH and pin the WowUtils guide")
            return 0

        guild_role_names = ("РЛ", "Знаменосец", "Сержант")
        overwrites = [
            {
                "id": GUILD_ID,
                "type": 0,
                "allow": "0",
                "deny": str(VIEW_CHANNEL | WRITE_BITS),
            },
            *[
                {
                    "id": ROLE_IDS[role_name],
                    "type": 0,
                    "allow": str(
                        PUBLISH_BITS
                        if role_name in ("РЛ", "Знаменосец")
                        else VIEW_CHANNEL | READ_MESSAGE_HISTORY
                    ),
                    "deny": "0",
                }
                for role_name in guild_role_names
            ],
        ]
        created = api.request(
            "POST",
            f"/guilds/{GUILD_ID}/channels",
            {
                "name": CHANNEL_NAME,
                "type": 0,
                "parent_id": STATIC_CATEGORY_ID,
                "position": int(archon.get("position", 0)) + 1,
                "topic": CHANNEL_TOPIC,
                "permission_overwrites": overwrites,
            },
        )
        if not isinstance(created, dict):
            raise RuntimeError("Discord did not return the created channel")
        channel = created

    channel_id = str(channel["id"])
    if not args.apply:
        print(f"FOUND #{CHANNEL_NAME} ({channel_id})")
        print("WOULD PUBLISH the guide if it is missing")
        return 0

    api.set_overwrite(
        channel_id,
        GUILD_ID,
        0,
        0,
        VIEW_CHANNEL | WRITE_BITS,
    )
    for role_name in ("РЛ", "Знаменосец", "Сержант"):
        allow = (
            PUBLISH_BITS
            if role_name in ("РЛ", "Знаменосец")
            else VIEW_CHANNEL | READ_MESSAGE_HISTORY
        )
        api.set_overwrite(channel_id, ROLE_IDS[role_name], 0, allow, 0)
    api.set_overwrite(channel_id, ROLE_IDS["Летописец"], 0, 0, VIEW_CHANNEL)

    existing = api.request("GET", f"/channels/{channel_id}/messages?limit=50")
    guide_message = by_id = next(
        (
            message
            for message in existing
            if isinstance(message, dict) and (
                str(message.get("id")) == GUIDE_MESSAGE_ID
                or str(message.get("content") or "").startswith(
                    "# 🧭 WowUtils / Viserio Cooldowns — как подключиться"
                )
                or any(
                    str(embed.get("footer", {}).get("text", "")) == GUIDE_MARKER
                    for embed in message.get("embeds", [])
                    if isinstance(embed, dict)
                )
            )
        ),
        None,
    ) if isinstance(existing, list) else None
    if isinstance(guide_message, dict):
        api.request(
            "PATCH",
            f"/channels/{channel_id}/messages/{guide_message['id']}",
            {
                "content": guide_content(),
                "embeds": [],
                "flags": 4,
                "allowed_mentions": {"parse": []},
            },
        )
        print(f"Updated the guide in #{CHANNEL_NAME} ({channel_id})")
        return 0

    message = api.request(
        "POST",
        f"/channels/{channel_id}/messages",
        {
            "content": guide_content(),
            "embeds": [],
            "flags": 4,
            "allowed_mentions": {"parse": []},
        },
    )
    if not isinstance(message, dict):
        raise RuntimeError("Discord did not return the guide message")
    api.request("PUT", f"/channels/{channel_id}/pins/{message['id']}")
    print(f"Created #{CHANNEL_NAME} ({channel_id}), published and pinned the guide")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
