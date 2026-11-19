#!/usr/bin/env python3
"""Run or stop a development component using shared process cleanup."""

import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


def identity(pid):
    try:
        # starttime distinguishes a saved PID from an unrelated reused PID.
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (FileNotFoundError, ProcessLookupError):
        # macOS does not expose /proc. `lstart` gives us a stable process
        # marker so task restarts can clean up old children there as well.
        try:
            started = subprocess.check_output(
                ["ps", "-o", "lstart=", "-p", str(pid)],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return None
        return started or None


def stop(pid):
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(50):
        try:
            os.killpg(pid, 0)
        except (ProcessLookupError, PermissionError):
            # macOS returns EPERM when only an unreaped exited process
            # remains in the group. Nothing signalable is left to stop.
            return
        time.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        # The group may have exited between the last probe and SIGKILL.
        pass


def stop_port(port):
    """Stop listeners on a task-owned development port when discoverable."""
    try:
        output = subprocess.check_output(
            ["lsof", "-tiTCP:%d" % port, "-sTCP:LISTEN"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return
    for value in output.splitlines():
        try:
            pid = int(value.strip())
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, ValueError, PermissionError):
            continue
    for _ in range(50):
        try:
            subprocess.check_output(
                ["lsof", "-tiTCP:%d" % port, "-sTCP:LISTEN"],
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            return
        time.sleep(0.1)


def component_paths(name):
    root = Path(__file__).resolve().parents[2]
    components = {
        "frontend": root / "app/frontend",
        "proxy": root / "app/proxy",
        **{name: root / f"app/backend/{name}-service"
           for name in ("movie", "recommendation", "user")},
    }
    ports = {
        "frontend": 4204,
        "proxy": 4205,
        "movie": 4206,
        "recommendation": 4207,
        "user": 4208,
    }
    if name not in components:
        raise SystemExit(f"Unknown component: {name}")
    component = components[name]
    runtime = component / ".run"
    runtime.mkdir(exist_ok=True)
    return component, runtime, runtime / "process.json", ports[name]


def stop_component(name, state, port):
    """Clean up a component while the caller holds its runtime lock."""
    if state.exists():
        previous = json.loads(state.read_text())
        if previous["start"] is not None and identity(previous["pid"]) == previous["start"]:
            print(f"Stopping previous {name} instance", flush=True)
            stop(previous["pid"])
    # Reclaim the fixed dev port if a killed task left orphaned children.
    stop_port(port)
    state.unlink(missing_ok=True)


def ensure_component(name, component, runtime, state, port):
    """Reuse backend dependencies; never stop an existing process."""
    if name not in ("movie", "recommendation", "user"):
        raise SystemExit("ensure supports backend services only")
    subprocess.run(["sh", str(component / "scripts/database/run-db.sh"), "--ensure"], check=True)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            running = True
    except OSError:
        running = False
    if state.exists():
        previous = json.loads(state.read_text())
        running = running or (previous["start"] is not None and identity(previous["pid"]) == previous["start"])
    child = None
    if not running:
        with (runtime / "ensure.log").open("ab") as log:
            child = subprocess.Popen(
                [str(component / "scripts/development/run.sh")],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        state.write_text(json.dumps({"pid": child.pid, "start": identity(child.pid)}))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                health = json.load(response)
            if health.get("service") == f"{name}-service" and health.get("status") == "ok":
                print(f"{name}: ready ({'reused' if running else 'started'}).", flush=True)
                return 0
        except (URLError, OSError, ValueError):
            pass
        if child is not None and child.poll() is not None:
            raise SystemExit(f"{name} startup failed. See {runtime / 'ensure.log'}")
        time.sleep(.25)
    raise SystemExit(f"{name} did not become ready. No existing process was restarted. See {runtime / 'ensure.log'}")


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("run", "stop", "ensure"):
        raise SystemExit("Usage: manage-component.py run|stop|ensure frontend|proxy|movie|recommendation|user")
    name = sys.argv[2]
    component, runtime, state, port = component_paths(name)
    with (runtime / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if sys.argv[1] == "ensure":
            return ensure_component(name, component, runtime, state, port)
        stop_component(name, state, port)
        if sys.argv[1] == "stop":
            print(f"{name} stopped", flush=True)
            return 0
        child = subprocess.Popen(
            [str(component / "scripts/development/run.sh")], start_new_session=True
        )
        state.write_text(json.dumps({"pid": child.pid, "start": identity(child.pid)}))
        fcntl.flock(lock, fcntl.LOCK_UN)

    def shutdown(signum, frame):
        stop(child.pid)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        return child.wait()
    finally:
        # Do not remove a newer launcher's state.
        with (runtime / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if state.exists() and json.loads(state.read_text())["pid"] == child.pid:
                state.unlink()


if __name__ == "__main__":
    sys.exit(main())
