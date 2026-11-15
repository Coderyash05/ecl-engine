"""Model inventory check (Module 9; ACPIR paras 120-121).

Para 120: the inventory shall include "model owners, developers, and users; tiering based on
risk and materiality; intended users (e.g., regulatory or internal); dependencies with upstream
and downstream models; and the status of validation and monitoring". Para 121: risk-based
tiering by "risk and output materiality".

`check_inventory` returns a list of findings (empty = pass):
- every model has the required fields (config/governance.yaml `inventory.required_fields`);
- tier is 1, 2 or 3 and has a rationale;
- dependencies are other inventory models or existing files, with no cycles. Files under
  `data/` are user-supplied inputs (Freddie Mac, FRED / FHFA; gitignored, never in the
  repository): they are checked only when a local `data/` folder exists, so a fresh clone passes;
- overlays named by a model exist in config/overlays.yaml;
- the code commit exists in the git history (when a resolver is given);
- validation status is stated (never "validated" without a date).
"""

from collections.abc import Callable
from pathlib import Path


def _cycle(graph: dict[str, list[str]]) -> list[str] | None:
    state: dict[str, int] = {}
    path: list[str] = []

    def visit(n: str) -> list[str] | None:
        state[n] = 1
        path.append(n)
        for d in graph.get(n, []):
            if state.get(d) == 1:
                return path[path.index(d) :] + [d]
            if d not in state and (c := visit(d)):
                return c
        state[n] = 2
        path.pop()
        return None

    for n in graph:
        if n not in state and (c := visit(n)):
            return c
    return None


def check_inventory(
    models: dict,
    required: list[str],
    overlays: dict,
    root: Path,
    commit_exists: Callable[[str], bool] | None = None,
) -> list[str]:
    """Findings for config/models.yaml `models` (see module docstring)."""
    out = []
    graph: dict[str, list[str]] = {}
    for key, m in models.items():
        missing = [f for f in required if f not in m or m[f] in (None, "")]
        if missing:
            out.append(f"{key}: missing {missing}")
        if m.get("tier") not in (1, 2, 3):
            out.append(f"{key}: tier must be 1, 2 or 3")
        deps = m.get("dependencies") or []
        graph[key] = []
        for d in deps:
            d = str(d).split("#")[0].strip()
            if d in models:
                graph[key].append(d)
            elif d.startswith("data/") and not (root / "data").is_dir():
                continue  # user-supplied data not downloaded (fresh clone): nothing to check
            elif not (root / d).exists():
                out.append(f"{key}: dependency {d!r} is neither a model nor an existing file")
        for o in m.get("overlays") or []:
            if o not in overlays:
                out.append(f"{key}: overlay {o} not in config/overlays.yaml")
        v = m.get("validation") or {}
        if "status" not in v:
            out.append(f"{key}: validation status missing")
        elif "validated" == str(v["status"]).strip() and not v.get("last_validated"):
            out.append(f"{key}: validated without a date")
        if commit_exists and m.get("code_commit") and not commit_exists(str(m["code_commit"])):
            out.append(f"{key}: code commit {m['code_commit']} not in git history")
    if c := _cycle(graph):
        out.append(f"dependency cycle: {' -> '.join(c)}")
    return out
