"""Add Shadow Squad cloud-video setup to the existing Archon Discord guide."""

from __future__ import annotations

import argparse
import os
import sys

from configure_channel_permissions import DiscordAPI, load_dotenv


CHANNEL_ID = "1486988199766265957"
INSTALL_MESSAGE_ID = "1533455453206614038"
LOG_MESSAGE_ID = "1533455456067129670"
VIDEO_MESSAGE_ID = "1533455457442861268"
CHECKLIST_MESSAGE_ID = "1533457765043802166"
CLOUD_MARKER = "shadow-squad-archon-cloud-v1"
CLOUD_MESSAGE_ID = "1535242789917294653"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


INSTALL_EMBED = {
    "title": "📊  ARCHON APP — УСТАНОВКА",
    "description": (
        "> Основная задача Archon для участников **Shadow Squad** — запись VoD "
        "с возможностью загрузки в гильдейское облако.\n"
        "> Скачать: **[официальная страница Archon](https://www.archon.gg/download)**\n\n"
        "**1  •  Подготовка World of Warcraft**\n"
        "В игре откройте **Настройки → Система → Сеть** и включите "
        "**Расширенное ведение журнала боя**. Локальный combat log нужен Archon, "
        "чтобы распознавать пулы и правильно сохранять видео. Загружать его на сайт необязательно.\n\n"
        "**2  •  Подключение игры**\n"
        "В Archon выберите **World of Warcraft**, укажите папку установленной игры и папку `Logs`. "
        "Обычно файл находится в `World of Warcraft/_retail_/Logs/WoWCombatLog.txt`.\n\n"
        "**3  •  Папка для видео**\n"
        "Выберите отдельную папку на локальном диске и укажите, сколько места вы готовы выделить под VoD. "
        "Полный объём диска указывать не нужно. Не используйте OneDrive, Google Drive или Dropbox — "
        "облачная синхронизация таких папок может блокировать запись."
    ),
    "color": 0xD6AAF3,
    "footer": {"text": "1 / 5  •  Установка"},
}

LOG_EMBED = {
    "title": "📝  ЛОКАЛЬНЫЙ COMBAT LOG ДЛЯ VoD",
    "description": (
        "**Для работы VoD нужен локальный combat log — онлайн-загрузка логов не нужна.**\n\n"
        "**Как включать журнал боя**\n"
        "• Надёжный вариант: перед РТ введите в игре `/combatlog`.\n"
        "• Удобный вариант: установите игровой Auto Logging Addon из Archon — он может сам включать "
        "combat log при входе в рейд или подземелье и предупреждать о конфликтах.\n"
        "• После выхода из игры, разрыва соединения или повторной команды `/combatlog` журнал выключается.\n\n"
        "**Онлайн-логи — только по желанию игрока**\n"
        "• Не создавайте правило загрузки **логов**, если нужен только VoD.\n"
        "• Не запускайте **Live Log / Go**, если не хотите отправлять combat log на сайт.\n"
        "• В настройках загрузки логов **Guild → Shadow Squad не выбираем**.\n"
        "• Если хотите личный онлайн-разбор, используйте только **Personal Logs**: `Public` для рейтингов "
        "либо `Unlisted` для доступа по ссылке.\n\n"
        "> ☁️ Облачное видео настраивается отдельно в **Video → Upload** и не требует загрузки "
        "combat log в гильдию.\n\n"
        "[Справка о combat logging](https://www.archon.gg/wow/articles/help/archon-app-help-and-faq)  •  "
        "[Auto Logging — дополнительная функция](https://www.archon.gg/classic-fresh/articles/news/archon-app-auto-logging)"
    ),
    "color": 0x5865F2,
    "footer": {"text": "2 / 5  •  Локальный журнал боя"},
}

VIDEO_EMBED = {
    "title": "🎥  ЗАПИСЬ И СИНХРОНИЗАЦИЯ VoD",
    "description": (
        "Откройте вкладку **Record** и включите **Recording**.\n\n"
        "**Рекомендуемые параметры**\n"
        "• Папка записи — локальный диск, не OneDrive / Google Drive / Dropbox\n"
        "• Ограничение места — по объёму вашего диска\n"
        "• Контент — **Endgame Raids** и нужные сложности\n"
        "• Настройте качество, разрешение, кодировщик, сцену, звук игры и микрофон\n"
        "• Нажмите **Test Recording** и проверьте картинку и звук\n\n"
        "Archon связывает видео с боевым логом. После пула можно открыть запись вместе с таймлайном "
        "событий и Replay Map и увидеть, что происходило на экране и вокруг персонажа.\n\n"
        "Если видео не создаётся: проверьте боевой лог, выключите и снова включите Recording, "
        "запустите тест и попробуйте другую локальную папку.\n\n"
        "Ниже приложены скриншоты всех основных настроек записи."
    ),
    "color": 0x57F287,
    "footer": {"text": "3 / 5  •  Видео"},
}

CHECKLIST_EMBED = {
    "title": "✅  ПЕРЕД НАЧАЛОМ РТ",
    "description": (
        "`1` Запустите Archon до входа в рейд.\n\n"
        "`2` Включите локальный combat log командой `/combatlog` или через Auto Logging Addon.\n\n"
        "`3` Откройте **Видео → Record** и убедитесь, что переключатель **Recording** включён.\n\n"
        "`4` В **Видео → Upload** проверьте правило загрузки в гильдейское хранилище.\n\n"
        "`5` После первого пула откройте **Видео → Play** и проверьте, что запись появилась. "
        "Онлайн-отчёт для этого не требуется.\n\n"
        "`6` Облачная загрузка применяется только к новым записям. Старые локальные VoD "
        "автоматически не загрузятся.\n\n"
        "> Главное: combat log включён, Recording работает, а правило загрузки видео сохранено."
    ),
    "color": 0xEB459E,
    "footer": {"text": "4 / 5  •  Проверка перед РТ"},
}

CLOUD_EMBED = {
    "title": "☁️  ОБЛАЧНАЯ ЗАГРУЗКА VoD",
    "description": (
        "Для статика уже подключено общее облачное хранилище. "
        "Игроку нужно только настроить правило автоматической загрузки своих новых VoD.\n\n"
        "**Настройка**\n"
        "`1` Откройте в Archon раздел **Video → Upload**.\n\n"
        "`2` В блоке **Cloud Storage** убедитесь, что у гильдии отображается доступный общий объём. "
        "Нажимать **Add Storage** не нужно. Если общего объёма нет — сообщите РЛ.\n\n"
        "`3` Нажмите **Add Upload Rule** и выставьте:\n"
        "• **Destination** — гильдия с общим хранилищем\n"
        "• **Visibility** — `Private`\n"
        "• **Enable Raids** — включено\n"
        "• **Endgame Raids** — включено\n"
        "• **Specific Raids** — выключено\n"
        "• Выберите нужную сложность рейда, для основного РТ — `Mythic`\n"
        "• **Enable Mythic+** — выключено\n\n"
        "`4` Нажмите **Save Changes**. Правило действует только для **будущих записей**; уже существующие "
        "локальные VoD автоматически не переносятся.\n\n"
        "`5` Оставьте **Recording** включённым как обычно. После записи Archon сможет загрузить VoD "
        "в гильдейское хранилище, чтобы участники статика могли смотреть нужные PoV.\n\n"
        "`6` **Upload Rate Limit** включайте только при необходимости, если загрузка заметно мешает игре.\n\n"
        "> Это правило относится только к **видео**. Загружать личные combat logs в гильдию не нужно.\n\n"
        "[Официальная инструкция Archon](https://www.archon.gg/wow/articles/help/archon-app-cloud-video-setup-guide)"
    ),
    "color": 0x3498DB,
    "footer": {"text": f"5 / 5  •  Cloud Video  •  {CLOUD_MARKER}"},
}


EXPECTED_TITLES = {
    INSTALL_MESSAGE_ID: "📊  ARCHON APP — УСТАНОВКА",
    LOG_MESSAGE_ID: "📝  ЛОКАЛЬНЫЙ COMBAT LOG ДЛЯ VoD",
    VIDEO_MESSAGE_ID: "🎥  ЗАПИСЬ И СИНХРОНИЗАЦИЯ VoD",
    CHECKLIST_MESSAGE_ID: "✅  ПЕРЕД НАЧАЛОМ РТ",
}


def plain_message(embed: dict[str, object]) -> str:
    return f"# {embed['title']}\n\n{embed['description']}"


def main() -> int:
    # The consolidated formatter is now authoritative for the Archon guide.
    from reformat_guide_channels import main as reformat_main

    return reformat_main()

    # Kept below for historical context; unreachable by design.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("DISCORD_BOT_TOKEN is missing", file=sys.stderr)
        return 2

    api = DiscordAPI(token, args.apply)
    messages = api.request("GET", f"/channels/{CHANNEL_ID}/messages?limit=50")
    if not isinstance(messages, list):
        raise RuntimeError("Discord returned an invalid message list")
    by_id = {str(message.get("id")): message for message in messages}

    errors: list[str] = []
    for message_id, expected_title in EXPECTED_TITLES.items():
        message = by_id.get(message_id)
        embeds = message.get("embeds", []) if isinstance(message, dict) else []
        content = str(message.get("content") or "") if isinstance(message, dict) else ""
        actual_title = embeds[0].get("title") if embeds else None
        if actual_title != expected_title and not content.startswith(f"# {expected_title}"):
            errors.append(f"message {message_id}: expected {expected_title!r}, got {actual_title!r}")
    if errors:
        raise RuntimeError("Safety validation failed:\n" + "\n".join(errors))

    updates = {
        INSTALL_MESSAGE_ID: INSTALL_EMBED,
        LOG_MESSAGE_ID: LOG_EMBED,
        VIDEO_MESSAGE_ID: VIDEO_EMBED,
        CHECKLIST_MESSAGE_ID: CHECKLIST_EMBED,
    }
    cloud_message = by_id.get(CLOUD_MESSAGE_ID)

    if not args.apply:
        print("WOULD UPDATE four existing Archon guide embeds")
        print("WOULD UPDATE cloud guide" if cloud_message else "WOULD CREATE cloud guide")
        return 0

    for message_id, embed in updates.items():
        api.request(
            "PATCH",
            f"/channels/{CHANNEL_ID}/messages/{message_id}",
            {"content": plain_message(embed), "embeds": [], "flags": 4},
        )

    if isinstance(cloud_message, dict):
        api.request(
            "PATCH",
            f"/channels/{CHANNEL_ID}/messages/{cloud_message['id']}",
            {"content": plain_message(CLOUD_EMBED), "embeds": [], "flags": 4},
        )
        cloud_id = str(cloud_message["id"])
    else:
        created = api.request(
            "POST",
            f"/channels/{CHANNEL_ID}/messages",
            {
                "content": plain_message(CLOUD_EMBED),
                "embeds": [],
                "flags": 4,
                "allowed_mentions": {"parse": []},
            },
        )
        if not isinstance(created, dict):
            raise RuntimeError("Discord did not return the cloud guide message")
        cloud_id = str(created["id"])

    print(f"Updated Archon guide; cloud message: {cloud_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
