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


def _read_json_line(out: queue.Queue[dict], timeout: float = 15.0) -> dict:
    # The handshake budget must cover a COLD interpreter boot: run_host()
    # imports tui_gateway.server (~1.6s of module imports on an idle dev
    # box) before emitting hello, and CI shard contention multiplies that.
    # 15s keeps the test fast when healthy while leaving real headroom —
    # the contract under test is the frame protocol, not boot speed.
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
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
