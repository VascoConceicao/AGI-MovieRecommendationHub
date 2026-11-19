#!/usr/bin/env python3
"""VU load driver mirroring infra/load/k6-health.js stages.

k6 is unavailable in this environment, so this stdlib-only driver
reproduces the same workload: concurrent virtual users looping over
the entrypoint paths with 0.2 s think time, in stages
50 (60 s) -> 100 (120 s) -> 200 (90 s) -> 0 (30 s ramp-down).

Usage: python3 run-health-load.py [BASE_URL]
Writes JSON summary to stdout.
"""
import http.client
import json
import random
import statistics
import sys
import threading
import time
import urllib.parse

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://34.175.251.169:30080"
PATHS = [
    "/api/movie/health",
    "/api/recommendation/health",
    "/api/user/health",
    "/api/movie/movies?limit=5",
    "/",
]
STAGES = [(50, 60), (100, 120), (200, 90), (0, 30)]

stop_all = threading.Event()
results_lock = threading.Lock()
samples = []  # (stage, ok_2xx, timeout, latency_s)


def worker(stage_idx, vu_id):
    parsed = urllib.parse.urlparse(BASE)
    host, port = parsed.hostname, parsed.port or 80
    while not stop_all.is_set():
        path = random.choice(PATHS)
        t0 = time.monotonic()
        ok, timeout, status = False, False, None
        try:
            conn = http.client.HTTPConnection(host, port, timeout=10)
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.read()
            status = resp.status
            ok = 200 <= status < 300
            conn.close()
        except TimeoutError:
            timeout, status = True, "timeout"
        except (OSError, http.client.HTTPException) as e:
            timeout, status = True, type(e).__name__
        lat = time.monotonic() - t0
        with results_lock:
            samples.append((stage_idx, ok, timeout, lat, status))
        time.sleep(0.2)


def run_stage(stage_idx, target, duration):
    global stop_all
    stop_all.clear()
    threads = [
        threading.Thread(target=worker, args=(stage_idx, i), daemon=True)
        for i in range(target)
    ]
    for t in threads:
        t.start()
    time.sleep(duration)
    stop_all.set()
    for t in threads:
        t.join(timeout=15)


def pct(data, q):
    if not data:
        return None
    s = sorted(data)
    i = min(int(q * len(s)), len(s) - 1)
    return s[i]


def main():
    t_start = time.time()
    stage_rows = []
    for idx, (vus, dur) in enumerate(STAGES):
        n0 = len(samples)
        run_stage(idx, vus, dur)
        rows = samples[n0:]
        lats = [r[3] for r in rows]
        ok2xx = sum(1 for r in rows if r[1])
        timeouts = sum(1 for r in rows if r[2])
        by_status = {}
        for r in rows:
            k = str(r[4])
            by_status[k] = by_status.get(k, 0) + 1
        stage_rows.append(
            {
                "stage": idx,
                "vus": vus,
                "duration_s": dur,
                "requests": len(rows),
                "rps": round(len(rows) / dur, 1) if dur else 0,
                "ok_2xx": ok2xx,
                "ok_rate": round(ok2xx / len(rows), 4) if rows else None,
                "timeouts": timeouts,
                "by_status": by_status,
                "p50_ms": round(pct(lats, 0.5) * 1000, 1) if lats else None,
                "p95_ms": round(pct(lats, 0.95) * 1000, 1) if lats else None,
                "mean_ms": round(statistics.mean(lats) * 1000, 1) if lats else None,
            }
        )
    total = len(samples)
    print(
        json.dumps(
            {
                "base": BASE,
                "elapsed_s": round(time.time() - t_start, 1),
                "total_requests": total,
                "stages": stage_rows,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
