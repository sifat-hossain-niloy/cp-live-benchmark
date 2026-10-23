"""Polite Codeforces API collection, retaining unrated candidates for later refresh."""

import json
import re
import sqlite3
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import httpx

USER_AGENT = "CF-Live/0.1 (+https://github.com/sifat-hossain-niloy/cp-live-benchmark)"


class CodeforcesAPI:
    def __init__(
        self,
        client: httpx.Client | None = None,
        interval: float = 2.1,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client or httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT})
        self.interval, self.sleep, self.clock = max(2.1, interval), sleep, clock
        self.last_call = float("-inf")

    def call(self, method: str, **params: Any) -> Any:
        for attempt in range(6):
            self.sleep(max(0, self.interval - (self.clock() - self.last_call)))
            self.last_call = self.clock()
            try:
                response = self.client.get(
                    f"https://codeforces.com/api/{method}", params={"lang": "en", **params}
                )
                response.raise_for_status()
                body = response.json()
                if body["status"] == "OK":
                    return body["result"]
                if "Call limit exceeded" not in body.get("comment", ""):
                    raise ValueError(f"Codeforces: {body.get('comment', 'unknown error')}")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500 and exc.response.status_code != 429:
                    raise
            except (httpx.TimeoutException, httpx.TransportError):
                pass
            if attempt < 5:
                self.sleep(2.1 * 2**attempt)
        raise RuntimeError(f"Codeforces {method} failed after six attempts")


def division(contest: dict[str, Any]) -> str | None:
    """API type is CF/IOI/ICPC, not division. Conservative name-based allowlist."""
    name = contest.get("name", "")
    if (
        contest.get("phase") != "FINISHED"
        or not contest.get("startTimeSeconds")
        or contest.get("id", 100000) >= 100000
        or re.search(r"april|fool|team|marathon|unrated|challenge", name, re.I)
    ):
        return None
    if "educational" in name.lower() and "codeforces" in name.lower():
        return "Educational"
    matches = re.findall(r"Div\.?\s*([1-4])", name, re.I)
    if not matches or "codeforces" not in name.lower():
        return None
    return "+".join(f"Div. {n}" for n in sorted(set(matches)))


def collect(con: sqlite3.Connection, api: CodeforcesAPI, since: date) -> dict[str, Any]:
    since_ts = int(datetime.combine(since, datetime.min.time(), UTC).timestamp())
    contests = {
        c["id"]: c
        for c in api.call("contest.list", gym="false")
        if division(c) and c["startTimeSeconds"] >= since_ts
    }
    for contest in contests.values():
        con.execute(
            """INSERT INTO contests VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
          name=excluded.name,division=excluded.division,phase=excluded.phase,
          start_time=excluded.start_time,raw_json=excluded.raw_json""",
            (
                contest["id"],
                contest["name"],
                division(contest),
                contest["startTimeSeconds"],
                contest["phase"],
                json.dumps(contest),
            ),
        )
    for p in api.call("problemset.problems")["problems"]:
        if p.get("contestId") not in contests or p.get("type") != "PROGRAMMING":
            continue
        contest = contests[p["contestId"]]
        tags = p.get("tags", [])
        reason = (
            "special"
            if "*special" in tags
            else "interactive"
            if "interactive" in tags
            else "unrated"
            if not p.get("rating")
            else None
        )
        pid = f"{p['contestId']}{p['index']}"
        con.execute(
            """INSERT INTO problems(id,contest_id,problem_index,name,rating,contest_start,
          exclusion_reason,status) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
          rating=excluded.rating,name=excluded.name,contest_start=excluded.contest_start,
          exclusion_reason=CASE WHEN problems.exclusion_reason
          IN ('unrated','interactive','special')
          OR problems.exclusion_reason IS NULL THEN excluded.exclusion_reason
          ELSE problems.exclusion_reason END, updated_at=CURRENT_TIMESTAMP""",
            (
                pid,
                p["contestId"],
                p["index"],
                p["name"],
                p.get("rating"),
                contest["startTimeSeconds"],
                reason,
                "collected",
            ),
        )
        con.execute("DELETE FROM problem_tags WHERE problem_id=?", (pid,))
        con.executemany("INSERT INTO problem_tags VALUES(?,?)", [(pid, t) for t in tags])
    return collection_summary(con)


def collection_summary(con: sqlite3.Connection) -> dict[str, Any]:
    rows = con.execute("""SELECT p.*,c.division FROM problems p JOIN contests c
      ON c.id=p.contest_id WHERE p.exclusion_reason IS NULL""").fetchall()
    return {
        "eligible_candidates": len(rows),
        "division": dict(sorted(Counter(r["division"] for r in rows).items())),
        "rating_band": dict(sorted(Counter(str(r["rating"] // 100 * 100) for r in rows).items())),
        "excluded": dict(
            con.execute(
                "SELECT exclusion_reason,count(*) FROM problems WHERE "
                "exclusion_reason IS NOT NULL GROUP BY exclusion_reason"
            )
        ),
    }
