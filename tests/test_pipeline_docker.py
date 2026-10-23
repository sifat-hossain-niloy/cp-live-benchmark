"""Optional full 500-case integration, using only synthetic inputs and an offline model.

Run explicitly with CFLIVE_DOCKER_TESTS=1 CFLIVE_FULL_VERIFY=1 uv run pytest
 tests/test_pipeline_docker.py -q. This never creates a public benchmark result.
"""

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from cflive.db import connect
from cflive.evaluate import evaluate
from cflive.export import public_dataset
from cflive.judge import DockerJudge
from cflive.providers import FakeAdapter
from cflive.workflow import approve, current_approval, read_meta, verify, write_meta
from tests.helpers import synthetic_problem
from tests.test_evaluate import config


@pytest.mark.docker
@pytest.mark.skipif(
    os.environ.get("CFLIVE_FULL_VERIFY") != "1",
    reason="Opt-in: starts >2000 fresh containers for full verification",
)
def test_real_500_case_pipeline(tmp_path):
    if os.environ.get("CFLIVE_DOCKER_TESTS") != "1":
        pytest.skip("Build the image and enable CFLIVE_DOCKER_TESTS")
    code = '#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}\n'
    with connect(tmp_path / "db") as con:
        ws, directory = synthetic_problem(con, tmp_path)
        (directory / "reference.cpp").write_text(code)
        (directory / "brute.py").write_text(
            "import sys\nprint(sum(map(int,sys.stdin.read().split())))\n"
        )
        (directory / "validator.py").write_text(
            "import sys\nx=sys.stdin.read().split()\nassert len(x)==2\n"
            "assert all(-10**9<=int(v)<=10**9 for v in x)\n"
        )
        (directory / "gen.py").write_text("""import argparse,random
p=argparse.ArgumentParser();p.add_argument('--mode');p.add_argument('--seed',type=int)
a=p.parse_args();r=random.Random(a.seed)
if a.mode=='edge':
    edges=[(0,0),(1,-1),(-1,1),(10**9,10**9),(-10**9,-10**9),(10**9,-10**9),(-10**9,10**9),(0,1),(1,0),(-1,0)]
    x,y=edges[a.seed%len(edges)]
elif a.mode=='max_size':x,y=10**9-a.seed%100,-10**9+r.randrange(100)
else:x,y=r.randint(-1000,1000),r.randint(-1000,1000)
print(x,y)
""")
        meta = read_meta(directory)
        # Synthetic fixture attestation only; never represented as real CF Accepted evidence.
        meta["provenance"]["source_sha256"] = hashlib.sha256(code.encode()).hexdigest()
        write_meta(directory, meta)
        approve(con, ws, "2000A", "synthetic offline test fixture")
        judge = DockerJudge(artifact_dir=tmp_path / "compiled")
        report = verify(con, ws, "2000A", judge)
        assert report["status"] == "verified", report
        assert report["counts"] == {"sample": 1, "small_random": 500, "edge": 10, "max_size": 5}
        assert report["final_count"] == 28
        current_approval(con, directory, verified=True)
        adapter = FakeAdapter(["```cpp\n" + code + "```"])
        result = asyncio.run(
            evaluate(
                con,
                ws,
                name="synthetic-only",
                config=config(),
                adapter=adapter,
                judge=judge,
                template=Path("prompts/single-shot.txt").read_text(),
                budget_usd=1,
                samples=2,
                judge_workers=2,
                require_calibration=False,
            )
        )
        assert result["status"] == "complete"
        assert [r[0] for r in con.execute("SELECT verdict FROM judgments")] == ["AC", "AC"]
        assert public_dataset(con, ws)["models"] == []
        destination = Path.cwd() / "artifacts" / "full-pipeline-smoke.json"
        destination.parent.mkdir(exist_ok=True)
        destination.write_text(
            json.dumps(
                {"synthetic_only": True, "verification": report, "evaluation": result}, indent=2
            )
        )
