"""Асинхронный клиент WoW Audit для чтения истории лута."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from dataclasses import dataclass
from urllib.error import HTTPError, URLError


class WoWAuditAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class WoWAuditCharacter:
    id: int
    name: str
    realm: str


@dataclass(frozen=True)
class LootHistoryItem:
    id: int
    item_id: int
    name: str
    slot: str
    quality: str
    character_id: int
    recipient_name: str
    awarded_by_name: str
    awarded_at: str
    difficulty: str
    response: str
    note: str
    discarded: bool


class WoWAuditClient:
    def __init__(self, api_key: str, base_url: str = "https://wowaudit.com") -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self._season_id: int | None = None
        self._season_name = ""
        self._season_checked_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _request_json_sync(self, path: str) -> object:
        if not self.configured:
            raise WoWAuditAPIError("WOWAUDIT_API_KEY не настроен")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": "Shadow-Squad-Discord-Bot/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code == 401:
                raise WoWAuditAPIError(
                    "WoW Audit отклонил API-ключ"
                ) from error
            raise WoWAuditAPIError(
                f"WoW Audit вернул HTTP {error.code}: {error.reason}"
            ) from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise WoWAuditAPIError(f"Ошибка запроса WoW Audit: {error}") from error

    async def _request_json(self, path: str) -> object:
        last_error: WoWAuditAPIError | None = None
        for attempt in range(3):
            try:
                return await asyncio.to_thread(self._request_json_sync, path)
            except WoWAuditAPIError as error:
                last_error = error
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
        raise last_error or WoWAuditAPIError("Неизвестная ошибка WoW Audit")

    async def current_season(self, force: bool = False) -> tuple[int, str]:
        now = time.time()
        if (
            not force
            and self._season_id is not None
            and now - self._season_checked_at < 3600
        ):
            return self._season_id, self._season_name
        payload = await self._request_json("/v1/period")
        if not isinstance(payload, dict):
            raise WoWAuditAPIError("WoW Audit вернул некорректный период")
        season = payload.get("current_season")
        if not isinstance(season, dict) or not isinstance(season.get("id"), int):
            raise WoWAuditAPIError("WoW Audit не вернул текущий сезон")
        self._season_id = int(season["id"])
        self._season_name = str(season.get("name") or f"Season {self._season_id}")
        self._season_checked_at = now
        return self._season_id, self._season_name

    async def characters(self) -> dict[int, WoWAuditCharacter]:
        payload = await self._request_json("/v1/characters")
        if not isinstance(payload, list):
            raise WoWAuditAPIError("WoW Audit вернул некорректный состав")
        result: dict[int, WoWAuditCharacter] = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            character_id = row.get("id")
            name = row.get("name")
            if isinstance(character_id, int) and name:
                result[character_id] = WoWAuditCharacter(
                    id=character_id,
                    name=str(name),
                    realm=str(row.get("realm") or ""),
                )
        return result

    async def loot_history(self) -> tuple[str, list[LootHistoryItem]]:
        season_id, season_name = await self.current_season()
        history_payload, characters = await asyncio.gather(
            self._request_json(f"/v1/loot_history/{season_id}"),
            self.characters(),
        )
        if not isinstance(history_payload, dict):
            raise WoWAuditAPIError("WoW Audit вернул некорректную историю лута")
        rows = history_payload.get("history_items")
        if not isinstance(rows, list):
            raise WoWAuditAPIError("В ответе WoW Audit отсутствует история лута")

        result: list[LootHistoryItem] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            loot_id = row.get("id")
            item_id = row.get("item_id")
            character_id = row.get("character_id")
            name = row.get("name")
            if not all(
                (
                    isinstance(loot_id, int),
                    isinstance(item_id, int),
                    isinstance(character_id, int),
                    bool(name),
                )
            ):
                continue
            character = characters.get(character_id)
            response_data = row.get("response_type")
            response = (
                str(response_data.get("name") or "")
                if isinstance(response_data, dict)
                else ""
            )
            result.append(
                LootHistoryItem(
                    id=loot_id,
                    item_id=item_id,
                    name=str(name),
                    slot=str(row.get("slot") or ""),
                    quality=str(row.get("quality") or ""),
                    character_id=character_id,
                    recipient_name=(
                        character.name if character else f"Character {character_id}"
                    ),
                    awarded_by_name=str(row.get("awarded_by_name") or ""),
                    awarded_at=str(row.get("awarded_at") or ""),
                    difficulty=str(row.get("difficulty") or ""),
                    response=response,
                    note=str(row.get("note") or ""),
                    discarded=bool(row.get("discarded")),
                )
            )
        result.sort(key=lambda item: (item.awarded_at, item.id), reverse=True)
        return season_name, result
