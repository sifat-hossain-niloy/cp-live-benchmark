import sqlite3

import pytest

from cflive.db import SCHEMA, SCHEMA_VERSION, connect


def test_migrates_v1_and_preserves_records(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    old = sqlite3.connect(path)
    old.executescript(SCHEMA)
    old.execute("INSERT INTO contests VALUES(1,'Synthetic','Div. 2',100,'FINISHED','{}')")
    old.execute("PRAGMA user_version=1")
    old.commit()
    old.close()
    for _ in range(2):
        with connect(path) as con:
            assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
            assert {"reservation_usd", "error"} <= {
                r[1] for r in con.execute("PRAGMA table_info(generations)")
            }
            assert con.execute("SELECT name FROM contests").fetchone()[0] == "Synthetic"
            assert [
                r[0] for r in con.execute("SELECT version FROM schema_migrations ORDER BY version")
            ] == [1, 2, 3]


def test_refuses_future_schema(tmp_path):
    path = tmp_path / "future.sqlite3"
    old = sqlite3.connect(path)
    old.execute("PRAGMA user_version=99")
    old.close()
    with pytest.raises(ValueError, match="newer than this CLI"):
        with connect(path):
            pass
