# Phases

Copy `phase.md` for each task phase. Use ordered filenames such as `01-discovery.md`, `02-implementation.md`, and `03-validation.md`.

Each phase file should record its goal, status, one recommended model for Codex, one recommended model for Claude Code, work completed, validation, and next steps.

Discover both providers' current native sub-agent catalogs before choosing recommendations. Record only model and effort for each provider; mark Claude effort advisory and never recommend `fable`.

Recommendations are advisory until implementation. `implement-phase` selects only the subsection matching the active agent and ignores the other provider's recommendation. Reassess both when phase scope changes materially.

When creating a real task from `docs/template/`, remove this README and rename `phase.md` to the first ordered phase filename, such as `01-discovery.md`.
