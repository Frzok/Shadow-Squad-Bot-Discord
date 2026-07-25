"""Запросы к Battle.net API: состав гильдии и профили персонажей."""

from __future__ import annotations

import asyncio
import base64
import json
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError
from dataclasses import dataclass


@dataclass(frozen=True)
class GuildCharacter:
    name: str
    realm_slug: str
    rank: int


class BlizzardAPIError(RuntimeError):
    pass


class BlizzardClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        region: str,
        locale: str,
        realm_slug: str,
        guild_slug: str,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.region = region
        self.locale = locale
        self.realm_slug = realm_slug
        self.guild_slug = guild_slug
        self._access_token = ""
        self._token_expires_at = 0.0

    @property
    def configured(self) -> bool:
        return all(
            (
                self.client_id,
                self.client_secret,
                self.region,
                self.realm_slug,
                self.guild_slug,
            )
        )

    @staticmethod
    def _request_json(
        request: urllib.request.Request, timeout: int = 30
    ) -> dict:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code == 404:
                raise BlizzardAPIError(
                    "Blizzard API вернул 404. Проверьте регион, игровой мир "
                    "и название гильдии/персонажа."
                ) from error
            raise BlizzardAPIError(
                f"Blizzard API вернул HTTP {error.code}: {error.reason}"
            ) from error
        except Exception as error:
            raise BlizzardAPIError(f"Ошибка запроса Blizzard API: {error}") from error

    def _get_token_sync(self) -> str:
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        request = urllib.request.Request(
            f"https://{self.region}.battle.net/oauth/token",
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        payload = self._request_json(request)
        try:
            self._access_token = payload["access_token"]
            self._token_expires_at = time.time() + int(payload["expires_in"]) - 60
        except (KeyError, TypeError, ValueError) as error:
            raise BlizzardAPIError("Blizzard OAuth вернул неполный ответ") from error
        return self._access_token

    def _guild_roster_sync(self) -> list[GuildCharacter]:
        token = self._get_token_sync()
        realm = urllib.parse.quote(self.realm_slug, safe="")
        guild = urllib.parse.quote(self.guild_slug, safe="")
        query = urllib.parse.urlencode(
            {"namespace": f"profile-{self.region}", "locale": self.locale}
        )
        request = urllib.request.Request(
            f"https://{self.region}.api.blizzard.com/data/wow/guild/"
            f"{realm}/{guild}/roster?{query}",
            headers={"Authorization": f"Bearer {token}"},
        )
        payload = self._request_json(request)
        members = payload.get("members")
        if not isinstance(members, list) or not members:
            raise BlizzardAPIError("Blizzard API вернул пустой состав гильдии")
        result = []
        for item in members:
            character = item.get("character", {})
            name = character.get("name")
            character_realm = character.get("realm", {}).get("slug", "")
            rank = item.get("rank")
            if name and isinstance(rank, int):
                result.append(GuildCharacter(name, character_realm, rank))
        return result

    def _character_active_spec_sync(
        self, character_name: str, realm_slug: str
    ) -> tuple[int, str]:
        token = self._get_token_sync()
        realm = urllib.parse.quote(realm_slug, safe="")
        character = urllib.parse.quote(character_name.lower(), safe="")
        query = urllib.parse.urlencode(
            {"namespace": f"profile-{self.region}", "locale": self.locale}
        )
        request = urllib.request.Request(
            f"https://{self.region}.api.blizzard.com/profile/wow/character/"
            f"{realm}/{character}?{query}",
            headers={"Authorization": f"Bearer {token}"},
        )
        payload = self._request_json(request)
        active_spec = payload.get("active_spec") or {}
        spec_id = active_spec.get("id")
        spec_name = active_spec.get("name")
        if not isinstance(spec_id, int) or not spec_name:
            raise BlizzardAPIError(
                f"Не найдена активная специализация {character_name}"
            )
        return spec_id, str(spec_name)

    def _specialization_role_sync(self, spec_id: int) -> str:
        token = self._get_token_sync()
        query = urllib.parse.urlencode(
            {"namespace": f"static-{self.region}", "locale": self.locale}
        )
        request = urllib.request.Request(
            f"https://{self.region}.api.blizzard.com/data/wow/"
            f"playable-specialization/{spec_id}?{query}",
            headers={"Authorization": f"Bearer {token}"},
        )
        payload = self._request_json(request)
        role_type = (payload.get("role") or {}).get("type")
        if not role_type:
            raise BlizzardAPIError(
                f"Не найдена игровая роль специализации {spec_id}"
            )
        return str(role_type).upper()

    async def _retry(self, function, *args):
        if not self.configured:
            raise BlizzardAPIError("Параметры Blizzard API не настроены")
        last_error: BlizzardAPIError | None = None
        for attempt in range(3):
            try:
                return await asyncio.to_thread(function, *args)
            except BlizzardAPIError as error:
                last_error = error
                # Новый токен на следующей попытке также исправляет случай
                # досрочного отзыва OAuth-токена.
                self._access_token = ""
                self._token_expires_at = 0.0
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
        raise last_error or BlizzardAPIError("Неизвестная ошибка Blizzard API")

    async def guild_roster(self) -> list[GuildCharacter]:
        return await self._retry(self._guild_roster_sync)

    async def character_active_spec(
        self, character_name: str, realm_slug: str
    ) -> tuple[int, str]:
        return await self._retry(
            self._character_active_spec_sync, character_name, realm_slug
        )

    async def specialization_role(self, spec_id: int) -> str:
        return await self._retry(self._specialization_role_sync, spec_id)
