"""Convert selected Discord guide embeds into full-width plain messages."""

from __future__ import annotations

import argparse
import os
import sys

from configure_channel_permissions import DiscordAPI, load_dotenv


TARGETS = {
    "809368762812989440": {
        "1533444983057551572": "⚔️ SHADOW SQUAD",
        "1533447090561351723": "🏹 ОСНОВНОЙ СТАТИК",
        "1533447092104593411": "🎁 РЕЙДЫ И ЛУТ",
        "1533447093648232479": "⚠️ ОТВЕТСТВЕННОСТЬ",
    },
    "1486988199766265957": {
        "1533455453206614038": "📊 ARCHON APP — УСТАНОВКА",
        "1533455456067129670": "📝 COMBAT LOG ДЛЯ VoD",
        "1533455457442861268": "🎥 ЗАПИСЬ И СИНХРОНИЗАЦИЯ VoD",
        "1533457765043802166": "☁️ ОБЛАЧНАЯ ЗАГРУЗКА VoD",
        "1535248311655862363": "✅ ПРОВЕРКА ПЕРЕД РТ",
    },
    "1533466182793953320": {
        "1533466190465208354": "🧭 WOWUTILS / VISERIO COOLDOWNS",
    },
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def plain_content(embeds: list[dict[str, object]]) -> str:
    sections: list[str] = []
    for embed in embeds:
        title = str(embed.get("title") or "").strip()
        description = str(embed.get("description") or "").strip()
        section = f"# {title}"
        if description:
            section += f"\n\n{description}"
        sections.append(section)
    return "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(sections)


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

    converted = 0
    already_plain = 0
    for channel_id, messages in TARGETS.items():
        for message_id, expected_title in messages.items():
            message = api.request("GET", f"/channels/{channel_id}/messages/{message_id}")
            if not isinstance(message, dict):
                raise RuntimeError(f"Discord returned invalid message {message_id}")
            embeds = message.get("embeds", [])
            content = str(message.get("content") or "")
            flags = int(message.get("flags") or 0)
            if content:
                if not content.startswith(f"# {expected_title}"):
                    raise RuntimeError(f"Unexpected plain message {message_id}")
                if flags & 4:
                    already_plain += 1
                    continue
                print(
                    f"{'SUPPRESS PREVIEW' if args.apply else 'WOULD SUPPRESS PREVIEW'} "
                    f"{expected_title}"
                )
                if args.apply:
                    api.request(
                        "PATCH",
                        f"/channels/{channel_id}/messages/{message_id}",
                        {"flags": flags | 4},
                    )
                converted += 1
                continue
            first_title = str(embeds[0].get("title") or "")
            if first_title != expected_title:
                raise RuntimeError(
                    f"Unexpected title for {message_id}: {first_title!r}"
                )
            new_content = plain_content(embeds)
            if len(new_content) > 2000:
                raise RuntimeError(
                    f"Plain message {message_id} exceeds Discord limit: {len(new_content)}"
                )
            print(
                f"{'CONVERT' if args.apply else 'WOULD CONVERT'} "
                f"{expected_title} ({len(new_content)} chars)"
            )
            if args.apply:
                api.request(
                    "PATCH",
                    f"/channels/{channel_id}/messages/{message_id}",
                    {"content": new_content, "embeds": [], "flags": flags | 4},
                )
            converted += 1

    print(
        f"{'Converted' if args.apply else 'Planned'}: "
        f"converted={converted}, already_plain={already_plain}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
