import hashlib
import json
from pathlib import Path

from cflive.config import Workspace
from cflive.workflow import read_meta, scaffold, write_meta


def synthetic_problem(con, root: Path, pid="2000A", start=1750000000, rating=1200):
    workspace = Workspace(root)
    workspace.initialize()
    con.execute(
        "INSERT OR IGNORE INTO contests VALUES(2000,'Synthetic (Div. 2)',"
        "'Div. 2',?,'FINISHED','{}')",
        (start,),
    )
    statement = root / "statement.json"
    statement.write_text(
        json.dumps(
            {
                "title": "Synthetic",
                "legend": "Add integers.",
                "input": "Two integers",
                "output": "Sum",
                "notes": "",
                "samples": [{"input": "1 2\n", "output": "3\n"}],
            }
        )
    )
    con.execute(
        "INSERT INTO problems(id,contest_id,problem_index,name,rating,contest_start,"
        "statement_path,time_limit,memory_limit) VALUES(?,2000,?,'Synthetic',?,?,?,2,256)",
        (pid, pid[4:], rating, start, str(statement)),
    )
    directory = scaffold(con, workspace, pid)
    (directory / "reference.cpp").write_text("// synthetic independently verified source\n")
    meta = read_meta(directory)
    meta["provenance"] = {
        "kind": "accepted_submission",
        "verified": True,
        "url": "https://example.org/ac",
        "attested_by": "test-reviewer",
        "submission_id": 123,
        "api_evidence": {"id": 123, "verdict": "OK"},
        "source_sha256": hashlib.sha256((directory / "reference.cpp").read_bytes()).hexdigest(),
    }
    write_meta(directory, meta)
    return workspace, directory
