"""Private HTML cache and conservative Codeforces statement extraction."""

import json
import re
import sqlite3
import time
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from cflive.collect import USER_AGENT
from cflive.config import Workspace

MULTI_ANSWER = re.compile(
    r"(?:print|output|find|construct)\s+(?:any|an arbitrary)|"
    r"(?:multiple|several|many)\s+(?:possible\s+)?(?:answers|solutions)|"
    r"if there (?:are|is) (?:more than one|a number of)|"
    r"(?:answer|solution) is not unique",
    re.I,
)


def _text(node: Tag | None, sample: bool = False) -> str:
    if node is None:
        return ""
    node = BeautifulSoup(str(node), "html.parser")
    for br in node.find_all("br"):
        br.replace_with("\n")
    if sample:
        lines = node.select(".test-example-line")
        text = "\n".join(line.get_text() for line in lines) if lines else node.get_text()
    else:
        for para in node.select("p, li"):
            para.append("\n")
        text = node.get_text()
    return text.replace("\r\n", "\n").replace("$$$", "$").replace("\xa0", " ").strip()


def parse_statement(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    statement = soup.select_one(".problem-statement")
    if statement is None:
        raise ValueError("No problem statement: access challenge or unexpected Codeforces HTML")
    title = _text(statement.select_one(".title"))
    time_text = _text(statement.select_one(".time-limit"))
    memory_text = _text(statement.select_one(".memory-limit"))
    time_match = re.search(r"([\d.]+)\s*(?:second|ms|millisecond)", time_text)
    memory_match = re.search(r"([\d.]+)\s*(?:megabyte|mebibyte|MB)", memory_text, re.I)
    if not title or not time_match or not memory_match:
        raise ValueError("Missing title or unrecognized time/memory limits")
    time_limit = float(time_match[1])
    if re.search(r"ms|millisecond", time_match[0]):
        time_limit /= 1000
    legend = "\n\n".join(
        _text(n) for n in statement.find_all("div", recursive=False) if not n.get("class")
    )
    inputs = statement.select(".sample-test .input pre")
    outputs = statement.select(".sample-test .output pre")
    if len(inputs) != len(outputs) or not inputs:
        raise ValueError("Missing or unpaired official samples")
    text = _text(statement)
    return {
        "title": title,
        "time_limit_seconds": time_limit,
        "memory_limit_mb": int(float(memory_match[1])),
        "legend": legend,
        "input": _text(statement.select_one(".input-specification")),
        "output": _text(statement.select_one(".output-specification")),
        "samples": [
            {"input": _text(i, True) + "\n", "output": _text(o, True) + "\n"}
            for i, o in zip(inputs, outputs)
        ],
        "notes": _text(statement.select_one(".note")),
        # Treat every statement image as potentially essential; human review may be needed.
        "essential_images": bool(statement.select("img, svg, canvas, object")),
        "multi_answer": bool(MULTI_ANSWER.search(text)),
        "interactive": bool(re.search(r"\binteraction\b|interactive problem", text, re.I)),
    }


class StatementFetcher:
    """HTTP by default; optional Chromium rendering for JS-delivered pages."""

    def __init__(self, workspace: Workspace, browser: bool = False) -> None:
        self.workspace, self.browser = workspace, browser
        self.last_request = 0.0

    def fetch(self, pid: str, contest: int, index: str) -> str:
        cache = self.workspace.data / "html" / f"{pid}.html"
        if cache.exists():
            return cache.read_text()
        time.sleep(max(0, 3 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        url = f"https://codeforces.com/contest/{contest}/problem/{index}?locale=en"
        if self.browser:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(user_agent=USER_AGENT)
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector(".problem-statement", timeout=30000)
                html = page.content()
                browser.close()
        else:
            response = httpx.get(
                url, timeout=45, headers={"User-Agent": USER_AGENT}, follow_redirects=True
            )
            response.raise_for_status()
            html = response.text
        parse_statement(html)  # Never poison the immutable cache with access-challenge HTML.
        cache.write_text(html)
        return html


def scrape(
    con: sqlite3.Connection,
    workspace: Workspace,
    *,
    limit: int = 60,
    browser: bool = False,
    problem_ids: list[str] | None = None,
) -> dict[str, Any]:
    fetcher = StatementFetcher(workspace, browser)
    report: dict[str, Any] = {"parsed": 0, "errors": {}}
    rows = con.execute(
        "SELECT * FROM problems WHERE exclusion_reason IS NULL "
        "AND statement_path IS NULL ORDER BY rating,id"
    ).fetchall()
    if problem_ids:
        rows = [r for r in rows if r["id"] in problem_ids]
    for row in rows[:limit]:
        pid = row["id"]
        try:
            statement = parse_statement(fetcher.fetch(pid, row["contest_id"], row["problem_index"]))
            path = workspace.data / "statements" / f"{pid}.json"
            path.write_text(json.dumps(statement, indent=2, ensure_ascii=False))
            reason = (
                "essential_images"
                if statement["essential_images"]
                else "interactive"
                if statement["interactive"]
                else None
            )
            con.execute(
                "UPDATE problems SET statement_path=?,time_limit=?,memory_limit=?,"
                "multi_answer=?,exclusion_reason=?,status='scraped' WHERE id=?",
                (
                    str(path),
                    statement["time_limit_seconds"],
                    statement["memory_limit_mb"],
                    int(statement["multi_answer"]),
                    reason,
                    pid,
                ),
            )
            con.commit()
            report["parsed"] += 1
        except (ValueError, httpx.HTTPError, TimeoutError) as exc:
            report["errors"][pid] = str(exc)
            # A site-wide access challenge should not trigger dozens of retries.
            if len(report["errors"]) >= 3:
                break
    return report
