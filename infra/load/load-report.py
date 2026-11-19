#!/usr/bin/env python3
"""Presentation wrapper around the project's load driver.

Imports run-health-load.py unchanged and reuses its worker and pct functions,
so the workload, think time and metrics are exactly the ones behind the
report's study. Only the presentation differs: a live in-place progress line
per stage and a final table instead of raw JSON.

Usage: python3 load-report.py <base_url> [vus:secs,vus:secs,...]
"""
import importlib.util
import os
import sys
import threading
import time

base = sys.argv[1] if len(sys.argv) > 1 else "http://34.175.170.59:30080"
spec_arg = sys.argv[2] if len(sys.argv) > 2 else None

# The driver lives next to this script, so the pair can be checked out anywhere.
DRIVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run-health-load.py")
spec = importlib.util.spec_from_file_location("drv", DRIVER)
drv = importlib.util.module_from_spec(spec)
saved_argv = sys.argv
sys.argv = ["drv", base]
spec.loader.exec_module(drv)
sys.argv = saved_argv

stages = drv.STAGES
if spec_arg:
    stages = []
    for part in spec_arg.split(","):
        vus, dur = part.split(":")
        stages.append((int(vus), int(dur)))

print("\033[1;36m  stage    vus   elapsed  requests    rps    ok%    p95_ms   502\033[0m")


def progress(idx, target, duration, offset, stop):
    """In-place progress line, reading the shared sample list as it grows."""
    start = time.monotonic()
    while not stop.is_set():
        elapsed = time.monotonic() - start
        rows = drv.samples[offset:]
        lats = [r[3] for r in rows]
        ok = sum(1 for r in rows if r[1])
        bad502 = sum(1 for r in rows if str(r[4]) == "502")
        p95 = drv.pct(lats, 0.95)
        print("\r\033[K  %-6d %5d %8.1fs %9d %6.1f %6.1f %9.1f %5d" % (
            idx, target, elapsed, len(rows),
            len(rows) / elapsed if elapsed else 0,
            100.0 * ok / len(rows) if rows else 0,
            (p95 or 0) * 1000, bad502), end="", flush=True)
        if elapsed >= duration:
            break
        stop.wait(2.0)
    print("\r\033[K", end="", flush=True)


rows_out = []
t_start = time.time()
for idx, (vus, dur) in enumerate(stages):
    offset = len(drv.samples)
    drv.stop_all.clear()
    workers = [threading.Thread(target=drv.worker, args=(idx, i), daemon=True)
               for i in range(vus)]
    for t in workers:
        t.start()

    stop = threading.Event()
    prog = threading.Thread(target=progress, args=(idx, vus, dur, offset, stop), daemon=True)
    prog.start()
    time.sleep(dur)
    drv.stop_all.set()
    stop.set()
    for t in workers:
        t.join(timeout=15)
    prog.join(timeout=5)

    rows = drv.samples[offset:]
    lats = [r[3] for r in rows]
    ok2xx = sum(1 for r in rows if r[1])
    timeouts = sum(1 for r in rows if r[2])
    by_status = {}
    for r in rows:
        by_status[str(r[4])] = by_status.get(str(r[4]), 0) + 1
    rows_out.append({
        "vus": vus, "duration_s": dur, "requests": len(rows),
        "rps": round(len(rows) / dur, 1) if dur else 0,
        "ok_2xx": ok2xx, "ok_rate": round(ok2xx / len(rows), 4) if rows else None,
        "timeouts": timeouts, "by_status": by_status,
        "p50_ms": round(drv.pct(lats, 0.5) * 1000, 1) if lats else None,
        "p95_ms": round(drv.pct(lats, 0.95) * 1000, 1) if lats else None,
    })

print()
hdr = "%-6s %9s %8s %10s %9s %9s %9s %7s %9s" % (
    "vus", "requests", "rps", "ok_2xx", "ok_rate", "p50_ms", "p95_ms", "502", "timeouts")
print("\033[1m" + hdr + "\033[0m")
print("-" * len(hdr))


def num(value, spec="%.1f"):
    """Format a metric, showing n/a instead of inventing a zero."""
    return spec % value if value is not None else "n/a"


for r in rows_out:
    line = "%-6d %9d %8s %10d %9s %9s %9s %7d %9d" % (
        r["vus"], r["requests"], num(r["rps"]),
        r["ok_2xx"], num(None if r["ok_rate"] is None else 100.0 * r["ok_rate"]),
        num(r["p50_ms"]), num(r["p95_ms"]),
        r["by_status"].get("502", 0), r["timeouts"])
    rate = r["ok_rate"]
    colour = "\033[32m" if (rate or 0) > 0.99 else ("\033[33m" if (rate or 0) > 0.8 else "\033[31m")
    print(colour + line + "\033[0m")

print()
print("total requests: %d   elapsed: %.1fs" % (
    sum(r["requests"] for r in rows_out), time.time() - t_start))

# Verdict against the thresholds declared in infra/load/k6-health.js.
P95_MAX_MS = 500.0
FAIL_MAX = 0.01
print()
print("\033[1mthreshold check (declared in infra/load/k6-health.js)\033[0m")
p95_bad = [str(r["vus"]) for r in rows_out if (r["p95_ms"] or 0) > P95_MAX_MS]
fail_bad = [str(r["vus"]) for r in rows_out
            if r["ok_rate"] is not None and (1.0 - r["ok_rate"]) > FAIL_MAX]
print("  p(95) < %.0f ms  : %s" % (
    P95_MAX_MS, "NOT met at " + ", ".join(p95_bad) + " clients" if p95_bad else "met at every stage"))
print("  failures < %.0f%%  : %s" % (
    FAIL_MAX * 100, "NOT met at " + ", ".join(fail_bad) + " clients" if fail_bad else "met at every stage"))
