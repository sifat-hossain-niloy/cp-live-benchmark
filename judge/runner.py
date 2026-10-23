"""Container-only process supervisor. Untrusted children cannot write the report channel.

The supervisor disables ptrace/proc-fd access to itself before forking. Each invocation
is a fresh PID/mount/network namespace. It never reads host credentials or hidden answers.
"""

import argparse
import base64
import ctypes
import json
import math
import os
import resource
import signal
import time
from pathlib import Path


def oom_count() -> int:
    try:
        events = Path("/sys/fs/cgroup/memory.events").read_text().splitlines()
        return sum(int(line.split()[1]) for line in events if line.startswith("oom_kill "))
    except OSError:
        return 0


def cpu_usage_ms() -> float:
    """Include all descendants, even if a submission fails to wait for them."""
    for line in Path("/sys/fs/cgroup/cpu.stat").read_text().splitlines():
        if line.startswith("usage_usec "):
            return int(line.split()[1]) / 1000
    raise RuntimeError("cgroup v2 CPU accounting unavailable")


def supervise(args: argparse.Namespace) -> dict:
    # PR_SET_DUMPABLE=0 denies same-UID children access to our /proc/<pid>/fd.
    if ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) != 0:
        raise RuntimeError("Cannot protect supervisor report channel")
    output, error = Path("/work/stdout"), Path("/work/stderr")
    # Keep inodes open: a submission may replace paths with symlinks or named pipes.
    output_fd = os.open(output, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    error_fd = os.open(error, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    before_oom = oom_count()
    before_cpu = cpu_usage_ms()
    start = time.monotonic()
    pid = os.fork()
    if pid == 0:
        try:
            os.setsid()
            resource.setrlimit(resource.RLIMIT_CPU, (math.ceil(args.cpu), math.ceil(args.cpu) + 1))
            resource.setrlimit(resource.RLIMIT_FSIZE, (args.output_limit, args.output_limit))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
            stdin = os.open(args.input, os.O_RDONLY)
            for src, dst in [(stdin, 0), (output_fd, 1), (error_fd, 2)]:
                os.dup2(src, dst)
            os.closerange(3, 1024)
            os.execvp(args.command[0], args.command)
        except BaseException:
            os._exit(127)
    killed = None
    while True:
        done, status, usage = os.wait4(pid, os.WNOHANG)
        if done:
            break
        if cpu_usage_ms() - before_cpu > args.cpu * 1000:
            killed = "TLE"
        elif time.monotonic() - start > args.wall:
            killed = "TLE"
        elif sum(os.fstat(fd).st_size for fd in (output_fd, error_fd)) >= args.output_limit:
            killed = "OUTPUT_LIMIT"
        if killed:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            _, status, usage = os.wait4(pid, 0)
            break
        time.sleep(0.005)
    elapsed = (time.monotonic() - start) * 1000
    cpu = cpu_usage_ms() - before_cpu
    code = os.waitstatus_to_exitcode(status)
    sig = -code if code < 0 else None
    size = sum(os.fstat(fd).st_size for fd in (output_fd, error_fd))
    if oom_count() > before_oom:
        verdict = "MLE"
    elif killed == "OUTPUT_LIMIT" or sig == signal.SIGXFSZ or size >= args.output_limit:
        verdict = "OUTPUT_LIMIT"
    elif killed == "TLE" or sig == signal.SIGXCPU or cpu > args.cpu * 1000:
        verdict = "TLE"
    else:
        verdict = "OK" if code == 0 else "RE"

    def read_bounded(fd: int, limit: int) -> str:
        os.lseek(fd, 0, os.SEEK_SET)
        return os.read(fd, limit).decode(errors="replace")

    payload = {
        "verdict": verdict,
        "exit_code": code,
        "cpu_ms": cpu,
        "wall_ms": elapsed,
        "memory_kb": usage.ru_maxrss,
        "stderr": read_bounded(error_fd, 8192),
    }
    if args.compile:
        artifact = Path("/work/program")
        payload["artifact"] = (
            base64.b64encode(artifact.read_bytes()).decode()
            if verdict == "OK"
            and artifact.exists()
            and artifact.stat().st_size <= args.output_limit
            else None
        )
    else:
        payload["stdout"] = read_bounded(output_fd, args.output_limit)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpu", type=float, required=True)
    parser.add_argument("--wall", type=float, required=True)
    parser.add_argument("--output-limit", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--input", default="/dev/null")
    parser.add_argument("--compile", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command.pop(0)
    print(json.dumps(supervise(args)), flush=True)
