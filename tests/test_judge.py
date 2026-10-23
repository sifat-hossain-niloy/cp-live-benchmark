import os
from dataclasses import asdict

import pytest

from cflive.checkers import check
from cflive.judge import DockerJudge


@pytest.mark.parametrize(
    "kind,expected,actual,accepted",
    [
        ("exact", "1\n", "1", False),
        ("tokens", "1 2\n", " 1\n2 ", True),
        ("tokens", "1", "2", False),
        ("float:1e-6", "100.0 ok", "100.00001 ok", True),
        ("float:1e-6", "1", "1.001", False),
        ("float:1e-6", "1", "nan", False),
        ("float:1e-6", "inf", "inf", False),
    ],
)
def test_checker_types(kind, expected, actual, accepted):
    assert check(kind, "", expected, actual).accepted == accepted


@pytest.fixture(scope="module")
def judge(tmp_path_factory):
    if os.environ.get("CFLIVE_DOCKER_TESTS") != "1":
        pytest.skip("Set CFLIVE_DOCKER_TESTS=1 after building the image")
    return DockerJudge(artifact_dir=tmp_path_factory.mktemp("compiled"), output_limit=1024 * 1024)


@pytest.mark.docker
@pytest.mark.parametrize(
    "code,language,verdict",
    [
        ("#include <iostream>\nint main(){std::cout<<42;}", "cpp17", "AC"),
        ("#include <iostream>\nint main(){std::cout<<41;}", "cpp17", "WA"),
        ("int main( {", "cpp17", "CE"),
        ("int main(){while(true){}}", "cpp17", "TLE"),
        ("int main(){return 3;}", "cpp17", "RE"),
        ("import os\na=[]\nwhile True:a.append(bytearray(8*1024*1024))", "python3", "MLE"),
        ("while True:print('x'*10000)", "python3", "OUTPUT_LIMIT"),
        (None, "cpp17", "NO_CODE"),
    ],
)
def test_real_verdicts(judge, code, language, verdict):
    result = judge.judge(
        code,
        [{"id": "s1", "category": "sample", "input": "", "output": "42"}],
        time_limit=0.2,
        memory_mb=64,
        language=language,
    )
    assert result.verdict == verdict, asdict(result)
    if verdict in {"WA", "TLE", "RE", "MLE", "OUTPUT_LIMIT"}:
        assert result.failing_category == "sample"


@pytest.mark.docker
def test_security_network_readonly_and_report_channel(judge):
    code = """
import os, socket
assert os.getuid() != 0
s=socket.socket(); s.settimeout(.1)
try:
    s.connect(('1.1.1.1',53))
except OSError: pass
else: raise AssertionError('Network escape')
for path in ['/etc/escape', '/artifact/escape', '/proc/1/fd/1']:
    try:
        f=open(path,'w')
    except OSError: pass
    else:
        f.close(); raise AssertionError('Writable '+path)
open('/work/allowed','w').write('yes')
print('safe')
"""
    result = judge.judge(
        code,
        [{"id": "security", "category": "edge", "input": "", "output": "safe"}],
        time_limit=1,
        memory_mb=64,
        language="python3",
    )
    assert result.verdict == "AC", asdict(result)


@pytest.mark.docker
def test_fork_bomb_is_killed_safely(judge):
    program, _ = judge.compile(
        "import os,time\nwhile True:\n try: os.fork()\n except OSError: time.sleep(10)", "python3"
    )
    result = judge.run(program, "", time_limit=0.1, memory_mb=64)
    assert result.verdict in {"TLE", "MLE", "RE"}
    assert result.wall_ms < 10000


@pytest.mark.docker
def test_custom_checker_json_protocol(judge, tmp_path):
    checker = tmp_path / "checker.py"
    checker.write_text(
        "import json,sys\nfrom pathlib import Path\n"
        'print(json.dumps({"accepted": len(Path(sys.argv[3]).read_text().split())==2}))'
    )
    assert check("custom", "", "1 2", "2 1", custom_path=checker, sandbox=judge).accepted
    assert not check("custom", "", "1 2", "1", custom_path=checker, sandbox=judge).accepted


@pytest.mark.docker
def test_output_path_replacement_cannot_hang_supervisor(judge):
    code = "import os\nos.unlink('/work/stdout')\nos.symlink('/dev/zero','/work/stdout')\nprint(42)"
    result = judge.judge(
        code,
        [{"id": "path", "category": "edge", "input": "", "output": "42"}],
        time_limit=1,
        memory_mb=64,
        language="python3",
    )
    assert result.verdict == "AC", asdict(result)


@pytest.mark.docker
def test_python_hash_seed_is_reproducible(judge):
    code = 'print(hash("cflive deterministic generator"))'
    program, _ = judge.compile(code, "python3")
    one = judge.run(program, "", time_limit=1, memory_mb=64)
    two = judge.run(program, "", time_limit=1, memory_mb=64)
    assert one.verdict == two.verdict == "OK"
    assert one.stdout == two.stdout
