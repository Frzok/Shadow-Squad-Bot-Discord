"""Validated settings that officers can change without restarting the bot."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SettingSpec:
    label: str
    default: str
    kind: str
    minimum: int = 0
    maximum: int = 0


SETTING_SPECS = {
    "raid_start_time": SettingSpec("начало РТ", "21:00", "time"),
    "raid_end_time": SettingSpec("окончание РТ", "00:00", "time"),
    "raid_announcement_time": SettingSpec("анонс РТ", "20:30", "time"),
    "raid_late_minutes": SettingSpec("порог опоздания, мин.", "15", "int", 1, 120),
    "raid_attendance_percent": SettingSpec(
        "минимум присутствия, %", "60", "int", 1, 100
    ),
    "raid_announcement_channel": SettingSpec(
        "канал анонсов", "", "channel"
    ),
    "raid_analysis_channel": SettingSpec("канал итогов РТ", "", "channel"),
    "raid_feedback_channel": SettingSpec("канал оценки РТ", "", "channel"),
    "blizzard_stale_hours": SettingSpec(
        "устаревший состав Blizzard, ч.", "8", "int", 1, 72
    ),
    "frequent_late_count": SettingSpec(
        "частые опоздания, количество", "3", "int", 2, 20
    ),
    "frequent_late_window": SettingSpec(
        "окно проверки опозданий, РТ", "6", "int", 3, 30
    ),
    "wcl_missing_hours": SettingSpec(
        "ожидание Warcraft Logs, ч.", "24", "int", 1, 72
    ),
    "raid_schedule_days": SettingSpec(
        "период календаря, дней", "30", "int", 7, 90
    ),
}


def parse_setting_value(name: str, raw_value: str) -> str:
    spec = SETTING_SPECS.get(name)
    if spec is None:
        raise ValueError("Неизвестная настройка")
    value = raw_value.strip()
    if spec.kind == "time":
        match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value)
        if not match:
            raise ValueError("Время должно быть в формате ЧЧ:ММ")
        return value
    if spec.kind == "channel":
        match = re.fullmatch(r"(?:<#)?(\d{15,22})>?", value)
        if not match:
            raise ValueError("Укажите канал упоминанием или его Discord ID")
        return match.group(1)
    try:
        number = int(value)
    except ValueError as error:
        raise ValueError("Значение должно быть целым числом") from error
    if not spec.minimum <= number <= spec.maximum:
        raise ValueError(
            f"Допустимое значение: от {spec.minimum} до {spec.maximum}"
        )
    return str(number)
