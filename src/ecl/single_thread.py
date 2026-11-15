"""Reproducible numerics for model fits: one BLAS / OpenMP thread.

Import this module before numpy, scipy, scikit-learn or statsmodels in a fit command. Multi-
threaded BLAS splits sums across threads in an order that can vary from run to run, so the last
digits of a fit can change between identical runs; with one thread every fit is bit-for-bit
reproducible. LightGBM sets its own thread count (`num_threads`) and is made deterministic by its
parameters (`ecl.pd.challenger.PARAMS`). Non-fit commands keep multi-threading.
"""

import os
import sys

FIT_THREAD_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")

_loaded = [m for m in ("numpy", "scipy") if m in sys.modules]
if _loaded:
    raise RuntimeError(f"ecl.single_thread must be imported before {', '.join(_loaded)}")
for _var in FIT_THREAD_VARS:
    os.environ[_var] = "1"
