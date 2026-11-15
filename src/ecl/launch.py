"""Entry point of the `ecl` command (and `python -m ecl`).

Fit steps run with one BLAS / OpenMP thread so that two runs give bit-identical outputs
(`ecl.single_thread`); the thread count must be fixed before numpy is imported, and `ecl.cli`
imports numpy (via pandas), so it is set here, before `ecl.cli` loads. Other commands keep
multithreading.
"""

from __future__ import annotations

import sys

# Commands that fit models: the 12m PD scorecard and challenger, PIT Z solver and satellite,
# lifetime hazard, LGD cure / severity (`train`), the scenario VAR (`scenarios`) and the CO-3
# calibration (`crisis-replay`).
FIT_COMMANDS = frozenset({"train", "scenarios", "crisis-replay"})


def main() -> None:
    """Fix the thread count for fit commands, then run the CLI."""
    if len(sys.argv) > 1 and sys.argv[1] in FIT_COMMANDS:
        import ecl.single_thread  # noqa: F401  before numpy

    from ecl.cli import main as cli_main  # after the thread count is fixed

    cli_main()
