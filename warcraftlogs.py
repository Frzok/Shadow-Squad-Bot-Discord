"""Клиент Warcraft Logs API v2 для рейдовых отчётов Shadow Squad."""

from __future__ import annotations

import asyncio
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar


ThreadResult = TypeVar("ThreadResult")


class WarcraftLogsAPIError(RuntimeError):
    """Warcraft Logs не ответил или вернул ошибку."""


async def run_in_thread(
    function: Callable[..., ThreadResult],
    /,
    *args: Any,
) -> ThreadResult:
    """Запускает блокирующий запрос, в том числе на серверном Python 3.8."""
    if hasattr(asyncio, "to_thread"):
        to_thread = getattr(asyncio, "to_thread")
        return await to_thread(function, *args)
    loop = asyncio.get_running_loop()
    run_in_executor = getattr(loop, "run_in_executor")
    return await run_in_executor(None, lambda: function(*args))


@dataclass(frozen=True)
class WarcraftLogsDeath:
    fight_id: int
    timestamp: int
    player_name: str


@dataclass(frozen=True)
class WarcraftLogsReport:
    code: str
    title: str
    start_time: float
    end_time: float
    zone_name: str
    fights: list[dict[str, Any]]
    actors: dict[int, str]
    deaths: dict[str, int]
    death_events: list[WarcraftLogsDeath]
    rankings: Any

    @property
    def url(self) -> str:
        return f"https://www.warcraftlogs.com/reports/{self.code}"

    @property
    def participants(self) -> list[str]:
        actor_ids: set[int] = set()
        for fight in self.fights:
            if int(fight.get("encounterID") or 0) <= 0:
                continue
            actor_ids.update(
                int(actor_id)
                for actor_id in (fight.get("friendlyPlayers") or [])
            )
        return sorted(
            [
                self.actors[actor_id]
                for actor_id in actor_ids
                if actor_id in self.actors
            ],
            key=lambda player_name: player_name.casefold(),
        )


class WarcraftLogsClient:
    TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
    GRAPHQL_URL = "https://www.warcraftlogs.com/api/v2/client"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        guild_name: str,
        server_slug: str,
        region: str = "eu",
    ) -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.guild_name = guild_name.strip()
        self.server_slug = server_slug.strip().casefold()
        self.region = region.strip().upper()
        self._access_token = ""
        self._token_expires_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return all(
            (
                self.client_id,
                self.client_secret,
                self.guild_name,
                self.server_slug,
                self.region,
            )
        )

    @staticmethod
    def _request_json(request: urllib.request.Request, timeout: int = 30) -> Any:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")[:500]
            raise WarcraftLogsAPIError(
                f"Warcraft Logs HTTP {error.code}: {details or error.reason}"
            ) from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise WarcraftLogsAPIError(
                f"Ошибка запроса Warcraft Logs: {error}"
            ) from error

    def _token_sync(self) -> tuple[str, int]:
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode("utf-8")
        ).decode("ascii")
        payload = urllib.parse.urlencode(
            {"grant_type": "client_credentials"}
        ).encode("ascii")
        request = urllib.request.Request(
            self.TOKEN_URL,
            data=payload,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Shadow-Squad-Discord-Bot/1.0",
            },
            method="POST",
        )
        response = self._request_json(request)
        token = str(response.get("access_token") or "")
        if not token:
            raise WarcraftLogsAPIError(
                "Warcraft Logs не вернул access_token"
            )
        return token, int(response.get("expires_in") or 3600)

    async def _token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token
        async with self._lock:
            if self._access_token and time.time() < self._token_expires_at:
                return self._access_token
            token, expires_in = await run_in_thread(self._token_sync)
            self._access_token = token
            self._token_expires_at = time.time() + max(60, expires_in - 60)
            return token

    def _graphql_sync(
        self, token: str, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            self.GRAPHQL_URL,
            data=json.dumps(
                {"query": query, "variables": variables}
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "Shadow-Squad-Discord-Bot/1.0",
            },
            method="POST",
        )
        response = self._request_json(request)
        if response.get("errors"):
            message = "; ".join(
                str(item.get("message") or item)
                for item in response["errors"]
            )
            raise WarcraftLogsAPIError(f"GraphQL: {message[:800]}")
        data = response.get("data")
        if not isinstance(data, dict):
            raise WarcraftLogsAPIError("Warcraft Logs вернул пустой ответ")
        return data

    async def _graphql(
        self, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        if not self.configured:
            raise WarcraftLogsAPIError("Warcraft Logs API не настроен")
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                token = await self._token()
                return await run_in_thread(
                    self._graphql_sync, token, query, variables
                )
            except WarcraftLogsAPIError as error:
                last_error = error
                if "HTTP 401" in str(error):
                    self._access_token = ""
                    self._token_expires_at = 0
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
        raise WarcraftLogsAPIError(str(last_error or "Неизвестная ошибка"))

    async def latest_report(
        self, start_time: float, end_time: float
    ) -> Optional[WarcraftLogsReport]:
        list_query = """
        query LatestGuildReports(
          $guildName: String!,
          $serverSlug: String!,
          $region: String!,
          $start: Float!,
          $end: Float!
        ) {
          reportData {
            reports(
              guildName: $guildName,
              guildServerSlug: $serverSlug,
              guildServerRegion: $region,
              startTime: $start,
              endTime: $end,
              limit: 10
            ) {
              data {
                code
                title
                startTime
                endTime
                zone { name }
              }
            }
          }
        }
        """
        variables = {
            "guildName": self.guild_name,
            "serverSlug": self.server_slug,
            "region": self.region,
            "start": start_time * 1000,
            "end": end_time * 1000,
        }
        data = await self._graphql(list_query, variables)
        reports = (
            data.get("reportData", {})
            .get("reports", {})
            .get("data", [])
        )
        if not reports:
            return None
        summary = max(
            reports,
            key=lambda item: float(item.get("endTime") or 0),
        )
        return await self.report(str(summary["code"]))

    async def report(self, code: str) -> WarcraftLogsReport:
        detail_query = """
        query GuildReport($code: String!) {
          reportData {
            report(code: $code) {
              code
              title
              startTime
              endTime
              zone { name }
              fights {
                id
                encounterID
                name
                kill
                startTime
                endTime
                fightPercentage
                friendlyPlayers
              }
              masterData(translate: true) {
                actors(type: "Player") { id name }
              }
              deaths: table(
                dataType: Deaths,
                killType: Encounters,
                startTime: 0,
                endTime: 999999999.0
              )
              rankings
            }
          }
        }
        """
        data = await self._graphql(detail_query, {"code": code})
        report = data.get("reportData", {}).get("report")
        if not report:
            raise WarcraftLogsAPIError(f"Отчёт {code} не найден")
        actors = {
            int(actor["id"]): str(actor["name"])
            for actor in (
                (report.get("masterData") or {}).get("actors") or []
            )
            if actor.get("id") is not None and actor.get("name")
        }
        death_events = self._extract_death_events(report.get("deaths"))
        deaths: dict[str, int] = {}
        for event in death_events:
            deaths[event.player_name] = deaths.get(event.player_name, 0) + 1
        return WarcraftLogsReport(
            code=str(report["code"]),
            title=str(report.get("title") or "Без названия"),
            start_time=float(report.get("startTime") or 0) / 1000,
            end_time=float(report.get("endTime") or 0) / 1000,
            zone_name=str((report.get("zone") or {}).get("name") or ""),
            fights=list(report.get("fights") or []),
            actors=actors,
            deaths=deaths,
            death_events=death_events,
            rankings=report.get("rankings"),
        )

    @staticmethod
    def _extract_death_events(payload: Any) -> list[WarcraftLogsDeath]:
        death_entries: list[tuple[int, int, str]] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                player_name = value.get("name")
                if player_name and (
                    "deathTime" in value
                    or "deathWindow" in value
                    or value.get("type") == "death"
                    or "killingAbility" in value
                    or "killingBlow" in value
                ):
                    death_entries.append(
                        (
                            int(value.get("fight") or 0),
                            int(
                                value.get("timestamp")
                                or value.get("deathTime")
                                or 0
                            ),
                            str(player_name),
                        )
                    )
                    # Вложенные события описывают эту же смерть и не должны
                    # рассматриваться как самостоятельные записи.
                    return
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(payload)
        result: list[WarcraftLogsDeath] = []
        deaths_per_fight: dict[int, int] = {}
        for fight_id, timestamp, name in sorted(
            death_entries, key=lambda item: (item[0], item[1])
        ):
            # После первых двух смертей в пуле обычно уже дана команда «вайп».
            # Последующие смерти этого пула не отражают качество игры.
            if deaths_per_fight.get(fight_id, 0) >= 2:
                continue
            deaths_per_fight[fight_id] = deaths_per_fight.get(fight_id, 0) + 1
            result.append(
                WarcraftLogsDeath(
                    fight_id=fight_id,
                    timestamp=timestamp,
                    player_name=name,
                )
            )
        return result

    @classmethod
    def _extract_deaths(cls, payload: Any) -> dict[str, int]:
        result: dict[str, int] = {}
        for event in cls._extract_death_events(payload):
            result[event.player_name] = result.get(event.player_name, 0) + 1
        return result

    @staticmethod
    def best_rankings(payload: Any, limit: int = 5) -> list[tuple[str, float]]:
        found: dict[str, float] = {}

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                name = value.get("name")
                percent = value.get("rankPercent")
                if name and isinstance(percent, (int, float)):
                    label = str(name)
                    found[label] = max(found.get(label, 0.0), float(percent))
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(payload)
        return sorted(
            found.items(), key=lambda item: (-item[1], item[0].casefold())
        )[:limit]
