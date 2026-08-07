"""Add the mandatory Archon/VOD requirement to the raid and loot rules."""

from __future__ import annotations

import argparse
import os
import sys

from configure_channel_permissions import DiscordAPI, load_dotenv


CHANNEL_ID = "809368762812989440"
MESSAGE_ID = "1533447092104593411"
ARCHON_CHANNEL_ID = "1486988199766265957"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


EMBED = {
    "title": "🎁  РЕЙДЫ И ЛУТ",
    "description": (
        "**RCLootCouncil**\n"
        "В стандартном окне розыгрыша всегда нажимаем **отказ**.\n\n"
        "🟢 **BiS** — незаменимый предмет; обязательно оставьте заметку.\n"
        "🟡 **Ап / Каталь** — предмет для катализатора или улучшение уровня.\n"
        "🔵 **Оффспек / Ключи / Трансмог** — соответствующие вторичные цели.\n\n"
        "**Дополнительно**\n"
        "• Первый маунт — `/roll`, следующие — по решению РЛ.\n"
        "• Если БоЕ не нужен, его можно продать; **20% стоимости** вносится в банк гильдии.\n"
        "• Ошибки и злоупотребления при выборе кнопок снижают доверие и приоритет.\n\n"
        "**🧰 Обязательные аддоны**\n"
        "`BigWigs`  •  `Method Raid Tools`  •  `M33kAuras`  •  `RCLootCouncil`\n\n"
        "**🎥 Archon App и VoD**\n"
        "Каждому участнику основного статика необходимо установить и настроить **Archon App** "
        "для записи VoD. Инструкция по установке, записи и облачной загрузке: "
        f"<#{ARCHON_CHANNEL_ID}>.\n\n"
        "`DBM` используется на свой риск. Если из-за настройки аддона происходят ошибки, "
        "игрок отправляется на бенч до устранения проблемы. Базовый рейдовый аддон гильдии — `BigWigs`."
    ),
    "color": 0x57F287,
    "footer": {"text": "3 / 4  •  Рейды и лут"},
}


def plain_message() -> str:
    from reformat_guide_channels import START_RAIDS, START_TEXTS

    return START_TEXTS[START_RAIDS]


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
    message = api.request("GET", f"/channels/{CHANNEL_ID}/messages/{MESSAGE_ID}")
    if not isinstance(message, dict):
        raise RuntimeError("Discord returned an invalid message")
    embeds = message.get("embeds", [])
    content = str(message.get("content") or "")
    title = embeds[0].get("title") if isinstance(embeds, list) and embeds else None
    if title != EMBED["title"] and not content.startswith("# 🎁 РЕЙДЫ И ЛУТ"):
        raise RuntimeError(f"Unexpected rules message title: {title!r}")

    print(f"{'UPDATE' if args.apply else 'WOULD UPDATE'} Archon/VOD requirement")
    if args.apply:
        api.request(
            "PATCH",
            f"/channels/{CHANNEL_ID}/messages/{MESSAGE_ID}",
            {"content": plain_message(), "embeds": [], "flags": 4},
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
