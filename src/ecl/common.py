"""Helpers shared by the pipeline entry points: logging set-up, run provenance (git state) and
Markdown tables for the model cards."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TextIO

import pandas as pd


def project_root() -> Path:
    """Repository root: the folder holding config/, data/, models/ and reports/.

    `ECL_ROOT` overrides it; otherwise it is found from the package location (src layout, used
    with an editable install `pip install -e .`)."""
    env = os.environ.get("ECL_ROOT")
    return Path(env).resolve() if env else Path(__file__).resolve().parents[2]


# Paths whose uncommitted changes make a run "not clean". Model fits check the code and the two
# regulatory / data-layout configs; ECL and reporting runs check every config file.
CODE_AND_CONFIG = ("src", "scripts", "config")
CODE_AND_REGULATORY_CONFIG = (
    "src",
    "scripts",
    "config/rbi_2026.yaml",
    "config/freddie_layout.yaml",
)


class _ElapsedFormatter(logging.Formatter):
    """`[  12s] message`: seconds since logging was configured (progress of long runs)."""

    def __init__(self) -> None:
        super().__init__()
        self.start = time.time()

    def format(self, record: logging.LogRecord) -> str:
        return f"[{record.created - self.start:6.0f}s] {record.getMessage()}"


def configure_logging(stream: TextIO | None = None, level: int = logging.INFO) -> None:
    """Send the `ecl` package's log records to `stream` (default stdout) with elapsed seconds.

    Only the package logger gets a handler (replaced on each call), so a second call does not
    duplicate output and the root logger (used by pytest's log capture) is left alone."""
    logger = logging.getLogger("ecl")
    for h in [h for h in logger.handlers if getattr(h, "ecl_handler", False)]:
        logger.removeHandler(h)
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.ecl_handler = True
    handler.setFormatter(_ElapsedFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)


def git_state(root: Path, paths: tuple[str, ...] = CODE_AND_CONFIG) -> dict:
    """Commit the run uses and whether `paths` are clean (no uncommitted change), recorded in
    every output so a result can be traced to its code and configuration."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()

    return {
        "commit": git("rev-parse", "HEAD"),
        "clean": not git("status", "--porcelain", "--", *paths),
    }


def md_table(df: pd.DataFrame, floatfmt: str = "{:.4f}") -> str:
    """DataFrame as a Markdown table; floats formatted with `floatfmt`, other values with str."""
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    lines += [
        "| " + " | ".join(floatfmt.format(v) if isinstance(v, float) else str(v) for v in r) + " |"
        for r in df.itertuples(index=False)
    ]
    return "\n".join(lines)
