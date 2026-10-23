from datetime import date

import httpx
import pytest

from cflive.collect import CodeforcesAPI, collect, division
from cflive.db import connect


def contest(name="Codeforces Round 999 (Div. 2)", **kwargs):
    return dict(id=2000, name=name, phase="FINISHED", startTimeSeconds=1750000000, **kwargs)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Codeforces Round 999 (Div. 2)", "Div. 2"),
        ("Codeforces Round 999 (Div. 1 + Div. 2)", "Div. 1+Div. 2"),
        ("Educational Codeforces Round 100 (Rated for Div. 2)", "Educational"),
        ("April Fools Codeforces Round (Div. 2)", None),
        ("Codeforces Team Round (Div. 2)", None),
        ("ICPC World Finals", None),
    ],
)
def test_division(name, expected):
    assert division(contest(name)) == expected


def test_not_finished_and_gym():
    c = contest()
    c["phase"] = "CODING"
    assert division(c) is None
    c.update(phase="FINISHED", id=100001)
    assert division(c) is None


def test_collection_idempotent_and_refreshes_unrated(tmp_path):
    class API:
        rated = False

        def call(self, method, **kwargs):
            if method == "contest.list":
                return [contest()]
            return {
                "problems": [
                    dict(
                        contestId=2000,
                        index="A",
                        name="Synthetic",
                        type="PROGRAMMING",
                        tags=["math"],
                        **({"rating": 800} if self.rated else {}),
                    )
                ]
            }

    api = API()
    with connect(tmp_path / "db") as con:
        assert collect(con, api, date(2025, 1, 1))["eligible_candidates"] == 0
        api.rated = True
        assert collect(con, api, date(2025, 1, 1))["eligible_candidates"] == 1
        collect(con, api, date(2025, 1, 1))
        assert con.execute("SELECT count(*) FROM problems").fetchone()[0] == 1


def test_api_retries_and_spaces_calls():
    now = [0.0]
    calls = []

    def sleep(seconds):
        now[0] += seconds

    def handle(request):
        calls.append(now[0])
        return httpx.Response(
            200,
            json={"status": "FAILED", "comment": "Call limit exceeded"}
            if len(calls) < 2
            else {"status": "OK", "result": []},
        )

    api = CodeforcesAPI(
        httpx.Client(transport=httpx.MockTransport(handle)), sleep=sleep, clock=lambda: now[0]
    )
    assert api.call("contest.list") == []
    api.call("contest.list")
    assert all(b - a >= 2.1 for a, b in zip(calls, calls[1:]))


def test_corrected_contest_start_refreshes_contamination_timestamp(tmp_path):
    class API:
        start = 1750000000

        def call(self, method, **kwargs):
            if method == "contest.list":
                return [{**contest(), "startTimeSeconds": self.start}]
            return {
                "problems": [
                    dict(
                        contestId=2000,
                        index="A",
                        name="Synthetic",
                        type="PROGRAMMING",
                        tags=[],
                        rating=800,
                    )
                ]
            }

    api = API()
    with connect(tmp_path / "db") as con:
        collect(con, api, date(2025, 1, 1))
        api.start -= 10000
        collect(con, api, date(2025, 1, 1))
        assert con.execute("SELECT start_time FROM contests").fetchone()[0] == api.start
        assert con.execute("SELECT contest_start FROM problems").fetchone()[0] == api.start
