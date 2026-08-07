"""Refine the approved Shadow Squad channel layout and special permissions."""

from __future__ import annotations

import argparse
import os
import sys
import time

from configure_channel_permissions import (
    DiscordAPI,
    GUILD_AND_FRIEND_ROLES,
    GUILD_ID,
    ROLE_IDS,
    VIEW_CHANNEL,
    load_dotenv,
    update_bits,
)


INFO = "606955509941141526"
GUILD = "657179512538398730"
STATIC = "1009730361850339328"
VOICE = "604571954422218754"
SERVICE = "606952372010221581"
EVERYONE = GUILD_ID

CHEST = "1055007278593482822"
HEALER_CHAT = "1279440882679939133"
ANALYSIS_CHANNEL = "1345828084640776343"
STREAMS = "604573142404562964"
LOGS = "604578557733371905"
PROGRESS = "659757581044023310"
INVITE = "809434235739963392"
PUBLISHER = "197371266007564289"
HEALER_ROLE = "987332716460650520"
MIDNIGHT = "1485886206817599569"
PUBLIC_RESOURCES = {
    "1486988199766265957", # archon
    "1487853265482813533", # weak auras
}
WOWUTILS = "1533466182793953320"
OLD_BOT_CHANNEL = "1274682053958438974"
OLD_BOT_CHANNEL_NAME = "💀ss_bot"

RENAMES = {
    "809368762812989440": ("📌правила-и-роли", "👋начать-здесь"),
    "809402292284686346": ("📯обьявления", "📯объявления"),
    "713419816857370624": ('🎉"Спец" отряд', "⚔️РТ・Спец-отряд"),
    "1270002159651655690": (
        "🤪Душевнобольная",
        "🤪Душевнобольная・офицеры",
    ),
    "1388829320369410059": ("🗿Рекрутинг", "🎙️Собеседование"),
    "1263306154499641371": ("🔑Ключ", "🔑Создать комнату・Ключ"),
    "1530215989499662478": ("☠️ss-bot", "💬бот-и-предложения"),
    "1200807297111306280": ("🐷опоздуны", "🐷отсутствия-и-опоздания"),
    CHEST: ("🎁сундук", "🎁недельный-лут"),
    PROGRESS: ("🚧progress", "🚧прогресс-гильдии"),
    HEALER_CHAT: ("🙀крутилочная", "💚чат-хилов"),
    ANALYSIS_CHANNEL: ("🏠домик-ебли", "🏠домик-ебли・разборы"),
    MIDNIGHT: ("midnight", "🌙midnight・тактики"),
    "1486988199766265957": ("📽️archon-app", "📊настройка-archon"),
    INVITE: ("🍆invite", "🔗invite-log"),
    LOGS: ("📈логи", "📈warcraft-logs"),
}

TOPICS = {
    "1200807297111306280": (
        "Предупреждения об отсутствии и опозданиях на РТ. "
        "Используйте /absence или напишите причину и время."
    ),
    CHEST: "Недельный лут участников гильдии и автоматическая история добычи.",
    PROGRESS: (
        "Автоматическая лента Raider.IO: убийства боссов, прогресс и место гильдии."
    ),
    HEALER_CHAT: "Закрытый чат хилов, РЛ и Знаменосца.",
    ANALYSIS_CHANNEL: (
        "Разборы РТ и важные материалы от Frzok. Канал только для чтения."
    ),
    MIDNIGHT: (
        "Тактики и обсуждение актуального рейда Midnight. "
        "Доступ: РЛ, Знаменосец и Сержант."
    ),
    "1486988199766265957": "Настройка Archon и связанные рекомендации.",
    "1533466182793953320": (
        "Подключение к WowUtils / Viserio Cooldowns, привязка персонажа "
        "и работа с рейдовыми Setup."
    ),
    "1487853265482813533": (
        "Рабочие WeakAuras: делитесь проверенными и актуальными версиями."
    ),
    INVITE: "Технический журнал приглашений на сервер.",
    LOGS: "Автоматические ссылки на отчёты Warcraft Logs после РТ.",
    STREAMS: (
        "Уведомления Shadow Squad о Twitch-стримах участников гильдии."
    ),
}

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

EXPECTED_NAMES = {
    CHEST: "🎁сундук",
    HEALER_CHAT: "🙀крутилочная",
    ANALYSIS_CHANNEL: "🏠домик-ебли",
    STREAMS: "📺стримы",
    LOGS: "📈логи",
    PROGRESS: "🚧progress",
    INVITE: "🍆invite",
}

PARENTS = {
    CHEST: STATIC,
    PROGRESS: STATIC,
    STREAMS: SERVICE,
    LOGS: STATIC,
    INVITE: SERVICE,
}

CATEGORY_ORDER = [INFO, GUILD, STATIC, VOICE, SERVICE]
CHANNEL_ORDER = {
    INFO: [
        "809368762812989440",
        "809402292284686346",
        "604573179138015281",
    ],
    GUILD: [
        "810474409755541524",  # flood
        "1215605471709368402", # memes
    ],
    STATIC: [
        "1200807297111306280", # absences
        CHEST,
        PROGRESS,
        LOGS,
        HEALER_CHAT,
        ANALYSIS_CHANNEL,
        "1485886206817599569", # midnight
        "1486988199766265957", # archon
        "1533466182793953320", # wowutils
        "1487853265482813533", # weak auras
    ],
    VOICE: [
        "1263306154499641371", # key
        "713419816857370624",  # raid
        "1270002159651655690", # officers
        "1388829320369410059", # recruiting
        "604579786538483712",  # AFK
    ],
    SERVICE: [
        STREAMS,
        INVITE,
        "723427989521432628",  # bot console
        "1530215989499662478", # current bot
    ],
}


def overwrite_map(channel: dict[str, object]) -> dict[str, tuple[int, int, int]]:
    return {
        str(item["id"]): (int(item["type"]), int(item["allow"]), int(item["deny"]))
        for item in channel.get("permission_overwrites", [])
    }


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
    channels = {str(channel["id"]): channel for channel in api.channels()}

    errors = [
        f"missing or renamed: {channel_id} #{name}"
        for channel_id, name in EXPECTED_NAMES.items()
        if channel_id not in channels
        or str(channels[channel_id]["name"])
        not in ({name} | set(RENAMES.get(channel_id, ())))
    ]
    required = set(CATEGORY_ORDER)
    required.update(channel_id for ids in CHANNEL_ORDER.values() for channel_id in ids)
    errors.extend(f"missing layout channel: {channel_id}" for channel_id in required if channel_id not in channels)
    for channel_id, (old_name, new_name) in RENAMES.items():
        if channel_id not in channels:
            errors.append(f"rename channel missing: {channel_id}")
        elif str(channels[channel_id]["name"]) not in {old_name, new_name}:
            errors.append(f"rename channel changed unexpectedly: {channel_id}")
    if (
        OLD_BOT_CHANNEL in channels
        and str(channels[OLD_BOT_CHANNEL]["name"]) != OLD_BOT_CHANNEL_NAME
    ):
        errors.append(f"old bot channel changed unexpectedly: {OLD_BOT_CHANNEL}")
    if errors:
        print("Safety validation failed; no changes were made:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1

    renames = [
        (channel_id, new_name)
        for channel_id, (_, new_name) in RENAMES.items()
        if str(channels[channel_id]["name"]) != new_name
    ]
    for channel_id, new_name in renames:
        print(
            f"{'APPLY' if args.apply else 'WOULD APPLY'} rename "
            f"#{channels[channel_id]['name']} -> #{new_name}"
        )
        if args.apply:
            api.request("PATCH", f"/channels/{channel_id}", {"name": new_name})
            time.sleep(0.2)

    topic_updates = [
        (channel_id, topic)
        for channel_id, topic in TOPICS.items()
        if str(channels[channel_id].get("topic") or "") != topic
    ]
    for channel_id, topic in topic_updates:
        print(
            f"{'APPLY' if args.apply else 'WOULD APPLY'} topic "
            f"#{channels[channel_id]['name']}"
        )
        if args.apply:
            api.request("PATCH", f"/channels/{channel_id}", {"topic": topic})
            time.sleep(0.2)

    moves = [
        (channel_id, parent_id)
        for channel_id, parent_id in PARENTS.items()
        if str(channels[channel_id].get("parent_id")) != parent_id
    ]
    for channel_id, parent_id in moves:
        print(f"{'APPLY' if args.apply else 'WOULD APPLY'} move #{channels[channel_id]['name']}")
        if args.apply:
            api.request("PATCH", f"/channels/{channel_id}", {"parent_id": parent_id})
            time.sleep(0.2)

    permission_updates: list[tuple[str, str, int, int, int]] = []

    def set_bits(
        channel_id: str,
        target_id: str,
        target_type: int,
        *,
        allow_bits: int = 0,
        deny_bits: int = 0,
        clear_bits: int = 0,
        clear_deny_bits: int = 0,
    ) -> None:
        current = overwrite_map(channels[channel_id])
        _, allow, deny = current.get(target_id, (target_type, 0, 0))
        new_allow, new_deny = update_bits(
            allow,
            deny,
            allow_bits=allow_bits,
            deny_bits=deny_bits,
            clear_bits=clear_bits,
            clear_deny_bits=clear_deny_bits,
        )
        if (allow, deny) != (new_allow, new_deny):
            permission_updates.append(
                (channel_id, target_id, target_type, new_allow, new_deny)
            )

    # Healer chat: healer role plus the two officer ranks.
    set_bits(HEALER_CHAT, EVERYONE, 0, deny_bits=VIEW_CHANNEL, clear_bits=VIEW_CHANNEL)
    for role_id in (HEALER_ROLE, ROLE_IDS["РЛ"], ROLE_IDS["Знаменосец"]):
        set_bits(
            HEALER_CHAT,
            role_id,
            0,
            allow_bits=PUBLISH_BITS,
            clear_deny_bits=PUBLISH_BITS,
        )

    # Static analysis is readable by guild/friends and writable only by Frzok.
    readonly_bits = VIEW_CHANNEL | READ_MESSAGE_HISTORY
    set_bits(
        ANALYSIS_CHANNEL,
        EVERYONE,
        0,
        deny_bits=VIEW_CHANNEL | WRITE_BITS,
        clear_bits=VIEW_CHANNEL | WRITE_BITS,
    )
    for target_id, (target_type, _, _) in overwrite_map(channels[ANALYSIS_CHANNEL]).items():
        if target_id not in {PUBLISHER, EVERYONE, *GUILD_AND_FRIEND_ROLES}:
            set_bits(ANALYSIS_CHANNEL, target_id, target_type, clear_bits=WRITE_BITS)
    for role_id in GUILD_AND_FRIEND_ROLES:
        set_bits(
            ANALYSIS_CHANNEL,
            role_id,
            0,
            allow_bits=readonly_bits,
            clear_deny_bits=readonly_bits,
            clear_bits=WRITE_BITS,
        )
    set_bits(
        ANALYSIS_CHANNEL,
        PUBLISHER,
        1,
        allow_bits=PUBLISH_BITS,
        clear_deny_bits=PUBLISH_BITS,
    )

    # Technical feeds remain visible despite living under Service.
    for channel_id in (STREAMS, LOGS):
        set_bits(channel_id, EVERYONE, 0, allow_bits=VIEW_CHANNEL)

    # Archon and WeakAuras are visible to everyone. Existing write settings stay.
    for channel_id in PUBLIC_RESOURCES:
        set_bits(channel_id, EVERYONE, 0, allow_bits=VIEW_CHANNEL)

    # WowUtils contains the private group invite and is visible only to guild ranks.
    guild_roles = {
        ROLE_IDS["РЛ"],
        ROLE_IDS["Знаменосец"],
        ROLE_IDS["Сержант"],
    }
    set_bits(
        WOWUTILS,
        EVERYONE,
        0,
        deny_bits=VIEW_CHANNEL | WRITE_BITS,
        clear_bits=VIEW_CHANNEL | WRITE_BITS,
    )
    for role_id in guild_roles:
        publish = role_id in {ROLE_IDS["РЛ"], ROLE_IDS["Знаменосец"]}
        set_bits(
            WOWUTILS,
            role_id,
            0,
            allow_bits=PUBLISH_BITS if publish else readonly_bits,
            clear_deny_bits=PUBLISH_BITS if publish else readonly_bits,
            clear_bits=0 if publish else WRITE_BITS,
        )
    set_bits(
        WOWUTILS,
        ROLE_IDS["Летописец"],
        0,
        deny_bits=VIEW_CHANNEL,
        clear_bits=VIEW_CHANNEL | WRITE_BITS,
    )

    # Midnight is only for the three active raid ranks.
    resource_bits = PUBLISH_BITS | CREATE_PUBLIC_THREADS
    midnight_roles = {
        ROLE_IDS["РЛ"],
        ROLE_IDS["Знаменосец"],
        ROLE_IDS["Сержант"],
    }
    set_bits(MIDNIGHT, EVERYONE, 0, deny_bits=VIEW_CHANNEL, clear_bits=VIEW_CHANNEL)
    for target_id, (target_type, _, _) in overwrite_map(channels[MIDNIGHT]).items():
        if target_id not in {EVERYONE, *midnight_roles}:
            set_bits(MIDNIGHT, target_id, target_type, clear_bits=VIEW_CHANNEL)
    for role_id in midnight_roles:
        set_bits(
            MIDNIGHT,
            role_id,
            0,
            allow_bits=resource_bits,
            clear_deny_bits=resource_bits,
        )

    for channel_id, target_id, target_type, allow, deny in permission_updates:
        print(
            f"{'APPLY' if args.apply else 'WOULD APPLY'} permissions "
            f"#{channels[channel_id]['name']} target={target_id}"
        )
        api.set_overwrite(channel_id, target_id, target_type, allow, deny)

    delete_old_bot = OLD_BOT_CHANNEL in channels
    if delete_old_bot:
        print(
            f"{'DELETE' if args.apply else 'WOULD DELETE'} "
            f"#{OLD_BOT_CHANNEL_NAME}"
        )
        if args.apply:
            api.request("DELETE", f"/channels/{OLD_BOT_CHANNEL}")

    positions = [
        {"id": category_id, "position": position}
        for position, category_id in enumerate(CATEGORY_ORDER)
    ]
    for parent_id, channel_ids in CHANNEL_ORDER.items():
        positions.extend(
            {"id": channel_id, "position": position}
            for position, channel_id in enumerate(channel_ids)
        )
    print(f"{'APPLY' if args.apply else 'WOULD APPLY'} ordered layout")
    if args.apply:
        api.request("PATCH", f"/guilds/{GUILD_ID}/channels", positions)  # type: ignore[arg-type]

    print(
        f"{'Applied' if args.apply else 'Planned'}: "
        f"renames={len(renames)}, topics={len(topic_updates)}, moves={len(moves)}, "
        f"permissions={len(permission_updates)}, deleted={int(delete_old_bot)}, order=1"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
