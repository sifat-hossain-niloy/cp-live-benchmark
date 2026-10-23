"""Versioned SQLite storage. Private content never belongs in site exports."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 2
SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations(
 version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS contests(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, division TEXT NOT NULL,
 start_time INTEGER NOT NULL, phase TEXT NOT NULL, raw_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS problems(
 id TEXT PRIMARY KEY, contest_id INTEGER NOT NULL REFERENCES contests(id),
 problem_index TEXT NOT NULL, name TEXT NOT NULL, rating INTEGER,
 contest_start INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'collected',
 exclusion_reason TEXT, statement_path TEXT, time_limit REAL, memory_limit INTEGER,
 multi_answer INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(contest_id,problem_index));
CREATE TABLE IF NOT EXISTS problem_tags(
 problem_id TEXT NOT NULL REFERENCES problems(id), tag TEXT NOT NULL,
 PRIMARY KEY(problem_id,tag));
CREATE TABLE IF NOT EXISTS test_sets(
 id INTEGER PRIMARY KEY, problem_id TEXT NOT NULL REFERENCES problems(id),
 artifact_hash TEXT NOT NULL, test_hash TEXT, status TEXT NOT NULL,
 approved_by TEXT, approved_at TEXT, report_json TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS models(
 name TEXT PRIMARY KEY, provider TEXT NOT NULL, model_id TEXT NOT NULL,
 display_name TEXT NOT NULL, cutoff TEXT, cutoff_source TEXT, config_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prompts(
 hash TEXT PRIMARY KEY, template TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS runs(
 id TEXT PRIMARY KEY, model_name TEXT NOT NULL REFERENCES models(name),
 config_json TEXT NOT NULL, image_digest TEXT NOT NULL, compiler_versions TEXT NOT NULL,
 status TEXT NOT NULL, budget_usd REAL NOT NULL, spent_usd REAL NOT NULL DEFAULT 0,
 reserved_usd REAL NOT NULL DEFAULT 0, stop_reason TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TEXT);
CREATE TABLE IF NOT EXISTS generations(
 id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
 model_name TEXT NOT NULL REFERENCES models(name), problem_id TEXT NOT NULL REFERENCES problems(id),
 prompt_hash TEXT NOT NULL REFERENCES prompts(hash), config_hash TEXT NOT NULL,
 sample_index INTEGER NOT NULL, status TEXT NOT NULL, raw_response TEXT, code TEXT,
 input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER,
 cost_usd REAL, latency_ms REAL, response_json TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(model_name,problem_id,prompt_hash,config_hash,sample_index));
CREATE TABLE IF NOT EXISTS judgments(
 id INTEGER PRIMARY KEY, generation_id INTEGER NOT NULL REFERENCES generations(id),
 test_set_id INTEGER NOT NULL REFERENCES test_sets(id), run_id TEXT NOT NULL REFERENCES runs(id),
 verdict TEXT NOT NULL, failing_test TEXT, failing_category TEXT,
 cpu_ms REAL, wall_ms REAL, memory_kb INTEGER, details_json TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(generation_id,test_set_id,run_id));
CREATE INDEX IF NOT EXISTS idx_problems_start ON problems(contest_start);
CREATE INDEX IF NOT EXISTS idx_problems_status ON problems(status,rating);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON problem_tags(tag);
CREATE INDEX IF NOT EXISTS idx_tests_problem ON test_sets(problem_id,status);
CREATE INDEX IF NOT EXISTS idx_generations_lookup ON generations(model_name,problem_id,status);
CREATE INDEX IF NOT EXISTS idx_judgments_generation ON judgments(generation_id);
"""


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open a foreign-key checked transaction; migrate on every entry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        con.close()
        raise ValueError(f"Database version {version} is newer than this CLI")
    con.executescript(SCHEMA)
    con.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(1)")
    if version < 2:
        con.execute("ALTER TABLE generations ADD COLUMN reservation_usd REAL NOT NULL DEFAULT 0")
        con.execute("ALTER TABLE generations ADD COLUMN error TEXT")
        con.execute("INSERT INTO schema_migrations(version) VALUES(2)")
    con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    con.commit()
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()
