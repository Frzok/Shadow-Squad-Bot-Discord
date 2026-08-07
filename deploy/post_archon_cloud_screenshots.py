"""Post the two Cloud Video setup screenshots to the Archon guide channel."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.request
import uuid
from pathlib import Path

from configure_channel_permissions import DiscordAPI, load_dotenv


CHANNEL_ID = "1486988199766265957"
MESSAGE_MARKER = "📸 **Скриншоты настройки Cloud Video**"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def multipart_body(
    content: str,
    files: list[tuple[str, Path]],
) -> tuple[bytes, str]:
    boundary = f"----ShadowSquad{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def add(value: str | bytes) -> None:
        chunks.append(value.encode("utf-8") if isinstance(value, str) else value)

    payload = {
        "content": content,
        "allowed_mentions": {"parse": []},
        "attachments": [
            {"id": index, "filename": filename}
            for index, (filename, _) in enumerate(files)
        ],
    }
    add(f"--{boundary}\r\n")
    add('Content-Disposition: form-data; name="payload_json"\r\n')
    add("Content-Type: application/json\r\n\r\n")
    add(json.dumps(payload, ensure_ascii=False))
    add("\r\n")

    for index, (filename, path) in enumerate(files):
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        add(f"--{boundary}\r\n")
        add(
            f'Content-Disposition: form-data; name="files[{index}]"; '
            f'filename="{filename}"\r\n'
        )
        add(f"Content-Type: {content_type}\r\n\r\n")
        add(path.read_bytes())
        add("\r\n")
    add(f"--{boundary}--\r\n")
    return b"".join(chunks), boundary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--overview", type=Path, required=True)
    parser.add_argument("--rule", type=Path, required=True)
    args = parser.parse_args()

    for path in (args.overview, args.rule):
        if not path.is_file():
            raise FileNotFoundError(path)

    load_dotenv()
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("DISCORD_BOT_TOKEN is missing", file=sys.stderr)
        return 2

    api = DiscordAPI(token, False)
    messages = api.request("GET", f"/channels/{CHANNEL_ID}/messages?limit=50")
    if not isinstance(messages, list):
        raise RuntimeError("Discord returned an invalid message list")
    existing = next(
        (
            message
            for message in messages
            if str(message.get("content", "")).startswith(MESSAGE_MARKER)
        ),
        None,
    )
    if existing:
        print(f"Screenshots already posted: {existing['id']}")
        return 0
    if not args.apply:
        print("WOULD POST two Cloud Video screenshots")
        return 0

    content = (
        f"{MESSAGE_MARKER}\n"
        "`1` Откройте **Video → Upload**, проверьте общий объём гильдии и нажмите **Add Upload Rule**. "
        "Кнопка **Add Storage** игрокам не нужна.\n"
        "`2` Выберите гильдейское хранилище, `Private`, включите рейды и Endgame Raids, "
        "оставьте Mythic+ выключенным и нажмите **Save Changes**."
    )
    body, boundary = multipart_body(
        content,
        [
            ("04-cloud-video-upload.png", args.overview),
            ("05-cloud-video-rule.png", args.rule),
        ],
    )
    request = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages",
        data=body,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "ShadowSquadBot/archon-guide",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        created = json.load(response)
    print(f"Posted Cloud Video screenshots: {created['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
