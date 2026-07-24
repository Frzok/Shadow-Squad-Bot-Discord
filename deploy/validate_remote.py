import os
import sqlite3
import sys


APP_DIR = "/opt/shadow-squad-bot"
STATE_DB_PATH = "/var/lib/shadow-squad-bot/bot_state.sqlite3"

sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)
os.environ.setdefault("STATE_DB_PATH", STATE_DB_PATH)
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

with sqlite3.connect(STATE_DB_PATH) as connection:
    quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]

if quick_check != "ok":
    raise RuntimeError(f"SQLite quick_check failed: {quick_check}")

import bot  # noqa: E402

guild = bot.discord.Object(id=bot.config.GUILD_ID)
command_count = len(bot.bot.tree.get_commands(guild=guild))
bot.store.close()

print(f"VALIDATION_OK commands={command_count}")
