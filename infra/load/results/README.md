# Load study results: provenance

| File | Run | Provenance |
|---|---|---|
| `load-2026-10-16.json` | HTTP load study used in the report | **Raw driver output** written by `run-health-load.py` during the run; it is the data behind the report's table and figure. Run on a separate three-VM Google Cloud cluster, not on the main deployment. |
| `load-2026-09-25-k6.json` | September rehearsal with k6 | **Transcribed** from the figures reported at the time. The k6 summary was printed to a terminal and never archived, so there is no per-stage breakdown. Health endpoints and frontend only, earlier cluster, before the product endpoints existed. Not comparable with the October study. |
| `load-2026-10-17-video.json` | the run shown in the demonstration video | **Transcribed** from the recorded terminal output (the driver prints a table). Shorter stages (25/30/35 s) than the study; the per-status counts are reconstructed from the identity requests = 200 + 502 + failures. Run on the cluster of the team member who ran the study. |

The three files are not interchangeable: they differ in tool, workload, step duration and cluster. Only the 16 Oct file is used in the report.
