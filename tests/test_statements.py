from pathlib import Path

import pytest

from cflive.statements import parse_statement

HTML = (Path(__file__).parent / "fixtures" / "statement.html").read_text()


def test_parse_latex_samples_and_flags():
    p = parse_statement(HTML)
    assert "$a$" in p["legend"] and "$$$" not in p["legend"]
    assert p["samples"] == [{"input": "1 2\n3 4\n", "output": "3\n7\n"}]
    assert p["time_limit_seconds"] == 2 and p["memory_limit_mb"] == 256
    assert p["multi_answer"] and not p["essential_images"]


def test_images_excluded_and_interactive_detected():
    p = parse_statement(HTML.replace("Given", '<img src="diagram.png">Interactive problem. Given'))
    assert p["essential_images"] and p["interactive"]


def test_challenge_rejected():
    with pytest.raises(ValueError, match="No problem statement"):
        parse_statement("<h1>Verify you are human</h1>")
