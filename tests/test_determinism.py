"""Reproducibility settings: identical runs must give bit-identical outputs."""

import os
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd

from ecl.pd.challenger import PARAMS
from ecl.pd.dataset import create_orig_table

# ecl.single_thread cannot be imported here (numpy is loaded): its variables, listed again
FIT_THREAD_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")


def test_lightgbm_challenger_is_deterministic():
    assert PARAMS["deterministic"] is True
    assert PARAMS["force_row_wise"] is True


def test_single_thread_sets_blas_threads_before_numpy_and_refuses_after():
    code = (
        "import os, ecl.single_thread, numpy;"
        "print(os.environ['OMP_NUM_THREADS'], os.environ['OPENBLAS_NUM_THREADS'],"
        " os.environ['MKL_NUM_THREADS'])"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["1", "1", "1"]
    late = subprocess.run(
        [sys.executable, "-c", "import numpy, ecl.single_thread"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert late.returncode != 0 and "before numpy" in late.stderr


def test_rate_spread_is_rate_minus_exact_same_month_mean_in_any_row_order():
    loans = pd.DataFrame(
        {
            "loan_id": ["a", "b", "c", "d"],
            "first_payment_date": pd.to_datetime(["2017-02-01"] * 3 + ["2017-03-01"]),
            "orig_interest_rate": [4.125, 3.875, 4.0, 5.0],
        }
    )
    spreads = []
    for frame in (loans, loans.iloc[::-1].reset_index(drop=True).copy()):
        con = duckdb.connect()
        con.register("loans_all", frame)
        create_orig_table(con)
        spreads.append(con.execute("SELECT loan_id, rate_spread FROM orig ORDER BY 1").df())
    assert spreads[0].equals(spreads[1])
    assert spreads[0].rate_spread.tolist() == [0.125, -0.125, 0.0, 0.0]


def test_ecl_launcher_uses_one_thread_for_fit_commands_only():
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = {k: v for k, v in os.environ.items() if k not in FIT_THREAD_VARS}
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "import os, sys\n"
        "sys.argv = ['ecl', sys.argv[1], '--help']\n"
        "from ecl.launch import main\n"
        "try:\n    main()\nexcept SystemExit:\n    pass\n"
        "print('OMP=' + os.environ.get('OMP_NUM_THREADS', 'unset'))\n"
    )
    for command, expected in [
        ("train", "1"),
        ("scenarios", "1"),
        ("crisis-replay", "1"),
        ("run", "unset"),
        ("report", "unset"),
    ]:
        out = subprocess.run(
            [sys.executable, "-c", code, command],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        assert out.stdout.strip().splitlines()[-1] == f"OMP={expected}", command
