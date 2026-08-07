"""Apply the approved readable plain-text layout to the three guide channels."""

from __future__ import annotations

import argparse
import os
import sys

from configure_channel_permissions import DiscordAPI, GUILD_ID, load_dotenv


START_CHANNEL = "809368762812989440"
ARCHON_CHANNEL = "1486988199766265957"
WOWUTILS_CHANNEL = "1533466182793953320"

START_MAIN = "1533444983057551572"
START_STATIC = "1533447090561351723"
START_RAIDS = "1533447092104593411"
START_RESPONSIBILITY = "1533447093648232479"

ARCHON_INSTALL = "1533455453206614038"
ARCHON_LOG = "1533455456067129670"
ARCHON_VIDEO = "1533455457442861268"
ARCHON_VIDEO_SCREENSHOTS = "1533457761566982205"
ARCHON_CLOUD_SLOT = "1533457765043802166"
ARCHON_OLD_CLOUD = "1535242789917294653"
ARCHON_CLOUD_SCREENSHOTS = "1535243657282850847"

WOWUTILS_GUIDE = "1533466190465208354"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def jump(channel_id: str, message_id: str) -> str:
    return f"https://discord.com/channels/{GUILD_ID}/{channel_id}/{message_id}"


START_TEXTS = {
    START_MAIN: (
        "# ⚔️ SHADOW SQUAD\n\n"
        "> **Правила гильдии и Discord-сервера**\n"
        "> Вступая к нам, вы подтверждаете согласие с правилами ниже.\n\n"
        "## 🛡️ ОБЩЕНИЕ\n"
        "• Без обмана, оскорблений и провокаций.\n"
        "• Политика, религия и спорт — только в личных сообщениях.\n"
        "• Общение — <#810474409755541524>, мемы — <#1215605471709368402>.\n"
        "• Не мешайте голосовым мероприятиям и не заходите в закрытые комнаты без приглашения.\n\n"
        "## 🎖️ ЗВАНИЯ\n"
        "📜 **Летописец** — участник гильдии.\n"
        "⚔️ **Сержант** — участник основного статика.\n"
        "Роли синхронизируются с игровыми званиями автоматически.\n\n"
        "## 📥 ВСТУПЛЕНИЕ\n"
        "Напишите <@197371266007564289> и укажите ник персонажа, состоящего в гильдии.\n\n"
        "## 🗓️ РАСПИСАНИЕ\n"
        "**Пт + Вс · 21:00–00:00 МСК** — основной статик\n"
        "**Сб · 21:00–00:00 МСК** — необязательный рейд на твинках"
    ),
    START_STATIC: (
        "# 🏹 ОСНОВНОЙ СТАТИК\n\n"
        "## ✅ ОБЯЗАТЕЛЬНО\n"
        "`01` Активность и аттенданс **99%**. Исключение — реальные ЧС.\n\n"
        "`02` На освоении последнего босса личные планы без ЧС означают перевод на бенч.\n\n"
        "`03` До РТ изучаем тактики, настраиваем аддоны и смотрим разборы / VoD по своему классу.\n\n"
        "`04` Поддерживаем актуальные экипировку, чары и камни.\n\n"
        "`05` Во время пула слушаем РЛ и офицеров.\n\n"
        "`06` Друзья и родственники могут участвовать в субботних рейдах.\n\n"
        "## ⚠️ ВАЖНО: ОПОЗДАНИЯ И ОТСУТСТВИЯ\n"
        "Сообщайте заранее в <#1200807297111306280>. Опоздание без предупреждения снижает "
        "приоритет на лут. РЛ может заменить игрока из-за ошибок, низкого DPS/HPS или особенностей босса."
    ),
    START_RAIDS: (
        "# 🎁 РЕЙДЫ И ЛУТ\n\n"
        "## ✅ ОБЯЗАТЕЛЬНО ПЕРЕД РТ\n"
        "• Установить и настроить **Archon App** для записи VoD.\n"
        "• Инструкция по установке, записи и облачной загрузке: <#1486988199766265957>.\n"
        "• Обязательные аддоны: `BigWigs` • `Method Raid Tools` • `M33kAuras` • `RCLootCouncil`.\n\n"
        "## 🎁 RCLOOTCOUNCIL\n"
        "В стандартном окне розыгрыша всегда нажимаем **отказ**.\n\n"
        "🟢 **BiS** — незаменимый предмет; обязательно оставьте заметку.\n"
        "🟡 **Ап / Каталь** — предмет для катализатора или улучшение уровня.\n"
        "🔵 **Оффспек / Ключи / Трансмог** — соответствующие вторичные цели.\n\n"
        "## ℹ️ ДОПОЛНИТЕЛЬНО\n"
        "• Первый маунт — `/roll`, следующие — по решению РЛ.\n"
        "• Если БоЕ не нужен, его можно продать; **20% стоимости** вносится в банк гильдии.\n"
        "• Ошибки и злоупотребления при выборе кнопок снижают доверие и приоритет.\n\n"
        "## ⚠️ ВАЖНО\n"
        "`DBM` используется на свой риск. Если из-за его настройки происходят ошибки, игрок отправляется "
        "на бенч до устранения проблемы. Базовый рейдовый аддон гильдии — `BigWigs`."
    ),
    START_RESPONSIBILITY: (
        "# ⚠️ ОТВЕТСТВЕННОСТЬ\n\n"
        "## ⚠️ ВАЖНО: УХОД ИЗ СТАТИКА ИЛИ ГИЛЬДИИ\n"
        "Предупреждение менее чем за **2 часа до РТ** либо после начала рейдовой недели и до сброса КД "
        "расценивается как саботаж. Исключение — реальные ЧС; решение принимает РЛ.\n\n"
        "## ⛔ ПОСЛЕДСТВИЯ\n"
        "Уход без предупреждения, исчезновение, удаление персонажа или переход в другой состав влечёт "
        "исключение и постоянный бан на Discord-сервере без возможности возвращения.\n\n"
        "**Понижение и исключение**\n"
        "• Прекращение участия в основном статике: <@&604574109485105194> → <@&665163320776720414>.\n"
        "• Оффлайн более **14 дней** без предупреждения — исключение из гильдии.\n\n"
        "> Нарушение правил может привести к ограничению доступа, понижению, исключению или бану."
    ),
}

ARCHON_TEXTS = {
    ARCHON_INSTALL: (
        "# 📊 ARCHON APP — УСТАНОВКА\n\n"
        "> ⚙️ **НАСТРОИТЬ ОДИН РАЗ**\n"
        "> Archon записывает VoD и загружает новые записи в общее хранилище статика.\n\n"
        "## 1 • ПОДГОТОВКА WORLD OF WARCRAFT\n"
        "В игре откройте **Настройки → Система → Сеть** и включите "
        "**Расширенное ведение журнала боя**. Combat log нужен Archon, чтобы распознавать пулы и "
        "правильно связывать их с видео. Загружать личные логи в гильдию не нужно.\n\n"
        "## 2 • ПОДКЛЮЧЕНИЕ ИГРЫ\n"
        "В Archon выберите **World of Warcraft**, укажите папку установленной игры и папку `Logs`. "
        "Обычно файл находится в `World of Warcraft/_retail_/Logs/WoWCombatLog.txt`.\n\n"
        "## 3 • ПАПКА ДЛЯ ВИДЕО\n"
        "Выберите папку записи на **локальном диске** и укажите, сколько места готовы выделить под VoD. "
        "Полный объём диска указывать не нужно.\n\n"
        "Скачать: **[официальная страница Archon](https://www.archon.gg/download)**"
    ),
    ARCHON_LOG: (
        "# 📝 COMBAT LOG ДЛЯ VoD\n\n"
        "> ⚙️ **ПРОВЕРИТЬ ОДИН РАЗ**\n"
        "> Для VoD нужен локальный combat log. Онлайн-загрузка логов не требуется.\n\n"
        "## ЕСЛИ ЗАПИСЬ ЛОГОВ УЖЕ РАБОТАЕТ\n"
        "Если в игре уже включена запись combat log и файл обновляется автоматически, "
        "**нажимать или вводить `/combatlog` не нужно**.\n\n"
        "## ЕСЛИ ЗАПИСЬ НЕ ЗАПУСТИЛАСЬ\n"
        "Используйте `/combatlog` как запасной вариант. Повторная команда выключает запись. "
        "Также запись прекращается после выхода из игры или разрыва соединения.\n\n"
        "## ОНЛАЙН-ЛОГИ — ТОЛЬКО ПО ЖЕЛАНИЮ\n"
        "• Не создавайте правило загрузки **логов**, если нужен только VoD.\n"
        "• Не запускайте **Live Log / Go**, если не хотите отправлять combat log на сайт.\n"
        "• В настройках загрузки логов **Guild → Shadow Squad не выбираем**.\n"
        "• Для личного разбора используйте только **Personal Logs**: `Public` или `Unlisted`.\n\n"
        "> ☁️ Загрузка видео настраивается отдельно в **Video → Upload**."
    ),
    ARCHON_VIDEO: (
        "# 🎥 ЗАПИСЬ И СИНХРОНИЗАЦИЯ VoD\n\n"
        "> ⚙️ **НАСТРОИТЬ ОДИН РАЗ**\n\n"
        "Откройте **Video → Record** и включите **Recording**.\n\n"
        "## РЕКОМЕНДУЕМЫЕ ПАРАМЕТРЫ\n"
        "• Папка записи — **локальный диск**.\n"
        "• Ограничение места — столько, сколько готовы выделить на диске.\n"
        "• Контент — **Endgame Raids** и нужные сложности.\n"
        "• Настройте качество, разрешение, кодировщик, сцену, звук игры и микрофон.\n"
        "• Нажмите **Test Recording** и проверьте изображение и звук.\n\n"
        "Archon связывает видео с combat log. После пула запись можно открыть вместе с таймлайном "
        "событий и Replay Map.\n\n"
        "## 🆘 ЕСЛИ ВИДЕО НЕ СОЗДАЁТСЯ\n"
        "Проверьте combat log, выключите и снова включите Recording, запустите Test Recording и "
        "попробуйте другую папку на локальном диске."
    ),
    ARCHON_CLOUD_SLOT: (
        "# ☁️ ОБЛАЧНАЯ ЗАГРУЗКА VoD\n\n"
        "> ⚙️ **НАСТРОИТЬ ОДИН РАЗ**\n"
        "> Для статика уже подключено общее облачное хранилище.\n\n"
        "## НАСТРОЙКА\n"
        "`1` Откройте **Video → Upload**.\n\n"
        "`2` В **Cloud Storage** убедитесь, что у гильдии отображается доступный общий объём. "
        "**Add Storage** нажимать не нужно. Если общего объёма нет — сообщите РЛ.\n\n"
        "`3` Нажмите **Add Upload Rule** и выставьте:\n"
        "• **Destination** — гильдейское хранилище, указанное РЛ;\n"
        "• **Visibility** — `Private`;\n"
        "• **Enable Raids** — включено;\n"
        "• **Endgame Raids** — включено;\n"
        "• **Specific Raids** — выключено;\n"
        "• сложность основного РТ — `Mythic`;\n"
        "• **Enable Mythic+** — выключено.\n\n"
        "`4` Нажмите **Save Changes**. Правило действует только для будущих записей.\n\n"
        "`5` **Upload Rate Limit** включайте только если загрузка заметно мешает игре.\n\n"
        "[Официальная инструкция Archon](https://www.archon.gg/wow/articles/help/archon-app-cloud-video-setup-guide)"
    ),
}

ARCHON_CHECKLIST_TEXT = (
    "# ✅ ПРОВЕРКА ПЕРЕД РТ\n\n"
    "> 🔁 **ПЕРЕД КАЖДЫМ РТ**\n\n"
    "`1` Запустите **Archon App** до входа в рейд.\n\n"
    "`2` Убедитесь, что запись combat log работает. Если она включается автоматически, "
    "команда `/combatlog` не нужна.\n\n"
    "`3` Откройте **Video → Record** и проверьте, что **Recording** включён.\n\n"
    "`4` В **Video → Upload** проверьте сохранённый Upload Rule для гильдейского хранилища.\n\n"
    "`5` После первого пула откройте **Video → Play** и убедитесь, что запись появилась.\n\n"
    "> **Минимум для участия в РТ:** Archon запущен, combat log записывается, Recording работает, "
    "Upload Rule сохранён."
)

WOWUTILS_TEXT = (
    "# 🧭 WOWUTILS / VISERIO COOLDOWNS\n\n"
    "> ⚙️ **НАСТРОИТЬ ОДИН РАЗ**\n"
    "> WowUtils используется для рейдовых Setup, хиловских кулдаунов и личных назначений.\n\n"
    "## ✅ БЫСТРЫЙ ПУТЬ\n"
    "`1` [Откройте приглашение в группу Shadow Squad]"
    "(https://wowutils.com/viserio-cooldowns/groups/join?token=331170bb0f942958ed8322f34def15d1&utm_source=invite&utm_medium=app_share).\n\n"
    "`2` Войдите через **Battle.net**.\n\n"
    "`3` Откройте `My Group → Shadow Squad → Состав`.\n\n"
    "`4` Найдите своего персонажа и выберите `… → Claim as mine`.\n\n"
    "`5` В **Set Up Characters** отметьте персонажей как `Main`, `Alt` или `Off`.\n\n"
    "## ⚠️ ВАЖНО\n"
    "• Не создавайте дубль, если персонаж уже есть в составе.\n"
    "• `Linked player` появится только после входа и привязки.\n"
    "• Если персонажа нет, сообщите РЛ.\n"
    "• После привязки не нужно создавать себя заново для каждого рейда — РЛ добавляет игрока в Setup."
)


def find_by_prefix(messages: list[dict[str, object]], prefix: str) -> dict[str, object] | None:
    return next(
        (message for message in messages if str(message.get("content") or "").startswith(prefix)),
        None,
    )


def validate_length(label: str, content: str) -> None:
    if len(content) > 2000:
        raise RuntimeError(f"{label} exceeds Discord limit: {len(content)}")


def edit(api: DiscordAPI, channel_id: str, message_id: str, content: str) -> None:
    validate_length(message_id, content)
    api.request(
        "PATCH",
        f"/channels/{channel_id}/messages/{message_id}",
        {"content": content, "embeds": [], "flags": 4},
    )


def create(api: DiscordAPI, channel_id: str, content: str) -> dict[str, object]:
    validate_length(channel_id, content)
    message = api.request(
        "POST",
        f"/channels/{channel_id}/messages",
        {"content": content, "embeds": [], "flags": 4, "allowed_mentions": {"parse": []}},
    )
    if not isinstance(message, dict):
        raise RuntimeError("Discord did not return the created message")
    return message


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

    for label, content in {**START_TEXTS, **ARCHON_TEXTS, WOWUTILS_GUIDE: WOWUTILS_TEXT}.items():
        validate_length(label, content)
    validate_length("archon-checklist", ARCHON_CHECKLIST_TEXT)

    if not args.apply:
        print("WOULD reformat Start Here, Archon and WowUtils")
        print("WOULD reorder Archon cloud setup before the final checklist")
        print("WOULD create and pin navigation messages")
        return 0

    for message_id, content in START_TEXTS.items():
        edit(api, START_CHANNEL, message_id, content)

    start_messages = api.request("GET", f"/channels/{START_CHANNEL}/messages?limit=50")
    if not isinstance(start_messages, list):
        raise RuntimeError("Invalid Start Here messages")
    start_index = find_by_prefix(start_messages, "# 📌 НАЧАТЬ ЗДЕСЬ")
    start_index_text = (
        "# 📌 НАЧАТЬ ЗДЕСЬ\n\n"
        "> Короткая навигация по обязательным правилам Shadow Squad.\n\n"
        f"`1` [Главное и расписание]({jump(START_CHANNEL, START_MAIN)})\n"
        f"`2` [Требования основного статика]({jump(START_CHANNEL, START_STATIC)})\n"
        f"`3` [Рейды, лут, аддоны и Archon]({jump(START_CHANNEL, START_RAIDS)})\n"
        f"`4` [Ответственность и последствия]({jump(START_CHANNEL, START_RESPONSIBILITY)})\n\n"
        "**Обновлено:** 7 августа 2026"
    )
    if start_index:
        start_index_id = str(start_index["id"])
        edit(api, START_CHANNEL, start_index_id, start_index_text)
    else:
        start_index_id = str(create(api, START_CHANNEL, start_index_text)["id"])
    api.request("PUT", f"/channels/{START_CHANNEL}/pins/{start_index_id}")
    if START_MAIN != start_index_id:
        api.request("DELETE", f"/channels/{START_CHANNEL}/pins/{START_MAIN}")

    for message_id, content in ARCHON_TEXTS.items():
        edit(api, ARCHON_CHANNEL, message_id, content)
    edit(
        api,
        ARCHON_CHANNEL,
        ARCHON_VIDEO_SCREENSHOTS,
        "📸 **СКРИНШОТЫ НАСТРОЙКИ ЗАПИСИ VoD**\n"
        "`1` Папка на локальном диске, лимит места, Recording и выбор рейдов.\n"
        "`2` Разрешение, FPS, кодировщик, качество и источник захвата.\n"
        "`3` Test Recording — обязательно проверьте изображение и звук.",
    )
    edit(
        api,
        ARCHON_CHANNEL,
        ARCHON_CLOUD_SCREENSHOTS,
        "📸 **СКРИНШОТЫ НАСТРОЙКИ CLOUD VIDEO**\n"
        "`1` Откройте Video → Upload, проверьте общий объём гильдии и нажмите Add Upload Rule.\n"
        "`2` Выберите гильдейское хранилище, Private, рейды, Endgame Raids и Mythic; "
        "Mythic+ оставьте выключенным. Затем нажмите Save Changes.",
    )

    archon_messages = api.request("GET", f"/channels/{ARCHON_CHANNEL}/messages?limit=50")
    if not isinstance(archon_messages, list):
        raise RuntimeError("Invalid Archon messages")
    checklist = find_by_prefix(archon_messages, "# ✅ ПРОВЕРКА ПЕРЕД РТ")
    if checklist:
        checklist_id = str(checklist["id"])
        edit(api, ARCHON_CHANNEL, checklist_id, ARCHON_CHECKLIST_TEXT)
    else:
        checklist_id = str(create(api, ARCHON_CHANNEL, ARCHON_CHECKLIST_TEXT)["id"])

    archon_index_text = (
        "# 📌 ARCHON APP — БЫСТРАЯ НАВИГАЦИЯ\n\n"
        "> **Минимум для участия в РТ:** Archon запущен, combat log записывается, "
        "Recording работает, Upload Rule сохранён.\n\n"
        "## ⚙️ НАСТРОИТЬ ОДИН РАЗ\n"
        f"`1` [Установка Archon App]({jump(ARCHON_CHANNEL, ARCHON_INSTALL)})\n"
        f"`2` [Настройка combat log]({jump(ARCHON_CHANNEL, ARCHON_LOG)})\n"
        f"`3` [Запись VoD]({jump(ARCHON_CHANNEL, ARCHON_VIDEO)})\n"
        f"`4` [Облачная загрузка VoD]({jump(ARCHON_CHANNEL, ARCHON_CLOUD_SLOT)})\n\n"
        "## 🔁 ПЕРЕД КАЖДЫМ РТ\n"
        f"`5` [Короткая проверка]({jump(ARCHON_CHANNEL, checklist_id)})\n\n"
        "**Обновлено:** 7 августа 2026"
    )
    archon_messages = api.request("GET", f"/channels/{ARCHON_CHANNEL}/messages?limit=50")
    archon_index = find_by_prefix(archon_messages, "# 📌 ARCHON APP — БЫСТРАЯ НАВИГАЦИЯ")
    if archon_index:
        archon_index_id = str(archon_index["id"])
        edit(api, ARCHON_CHANNEL, archon_index_id, archon_index_text)
    else:
        archon_index_id = str(create(api, ARCHON_CHANNEL, archon_index_text)["id"])
    api.request("PUT", f"/channels/{ARCHON_CHANNEL}/pins/{archon_index_id}")
    if ARCHON_INSTALL != archon_index_id:
        api.request("DELETE", f"/channels/{ARCHON_CHANNEL}/pins/{ARCHON_INSTALL}")

    old_cloud = api.request("GET", f"/channels/{ARCHON_CHANNEL}/messages/{ARCHON_OLD_CLOUD}")
    if isinstance(old_cloud, dict) and str(old_cloud.get("content") or "").startswith("# ☁️"):
        api.request("DELETE", f"/channels/{ARCHON_CHANNEL}/messages/{ARCHON_OLD_CLOUD}")

    edit(api, WOWUTILS_CHANNEL, WOWUTILS_GUIDE, WOWUTILS_TEXT)
    api.request("PUT", f"/channels/{WOWUTILS_CHANNEL}/pins/{WOWUTILS_GUIDE}")

    print(f"Start index: {start_index_id}")
    print(f"Archon checklist: {checklist_id}")
    print(f"Archon index: {archon_index_id}")
    print("Reformatted all three guide channels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
