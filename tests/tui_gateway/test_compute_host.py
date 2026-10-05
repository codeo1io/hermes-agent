import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path


def _stdout_queue(proc: subprocess.Popen) -> queue.Queue[dict]:
    out: queue.Queue[dict] = queue.Queue()
    assert proc.stdout is not None

    def drain() -> None:
        for line in proc.stdout or []:
            out.put(json.loads(line))

    threading.Thread(target=drain, daemon=True).start()
    return out


def _read_json_line(out: queue.Queue[dict], timeout: float = 10.0) -> dict:
    # 10s matches the suite's house convention for waits on a REAL subprocess
    # (interpreter startup + module imports of the compute host routinely take
    # 5-8s cold; the old 2.0s bound failed every cold start under CI's 12
    # parallel workers — run 37315983749, job 111911509264).
    try:
        return out.get(timeout=timeout)
    except queue.Empty as exc:
        raise AssertionError("timed out waiting for compute host JSON") from exc


def test_compute_host_line_json_hello_and_shutdown():
    repo = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [sys.executable, "-m", "tui_gateway.compute_host"],
        cwd=str(repo),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdin is not None
    out = _stdout_queue(proc)
    try:
        hello = _read_json_line(out)
        assert hello["type"] == "hello"
        assert hello["host_pid"] == proc.pid

        proc.stdin.write(json.dumps({"type": "bogus", "request_id": "b"}) + "\n")
        proc.stdin.flush()
        error = _read_json_line(out)
        assert error["type"] == "error"
        assert error["message"] == "unknown frame type: bogus"

        proc.stdin.write(json.dumps({"type": "shutdown", "request_id": "stop"}) + "\n")
        proc.stdin.flush()
        assert _read_json_line(out)["type"] == "shutdown.ack"
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
