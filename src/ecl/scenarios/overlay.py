"""CO-3: downside-only multiplier on default odds (post-model adjustment, RBI para 131).

What (docs/methodology/scenarios.md):
- In the **downside scenario only**, the quarterly default odds (against survival; the prepayment
  hazard is unchanged) are multiplied by M^s in every **stressed quarter**, z_q(t) < Z_lr.
- s = min(1, (Z_lr - min_t Z_down(t)) / (Z_lr - min_t Z_replay(t))): the downside's Z trough
  relative to the crisis replay's (satellite Z, as in replay step R3). s <= 1 caps the uplift at
  the full crisis value (no extrapolation); a downside with no stressed quarter gets nothing.
- M is calibrated on the R3 crisis replay (replay.py) so that the predicted 5-year cumulative
  default of the 2006 and 2007 holdout vintages, pooled, equals the actual.

Why: the hazard with the satellite Z and beta-derived state house prices under-predicts the
2007-09 crisis (no regional factor in Z; the satellite's trough is shallower than
measured Z). Base and upside are never adjusted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ecl.lifetime.paths import MacroPath


def stressed(path: MacroPath, q: np.ndarray, z_lr: float) -> np.ndarray:
    """True where the path's quarterly Z at quarter index q is below the long-run Z."""
    return path.at(path.z_q, q) < z_lr


def severity_scale(z_lr: float, z_min_downside: float, z_min_replay: float) -> float:
    """s in [0, 1]: the downside trough's depth below Z_lr relative to the replay's."""
    if z_min_replay >= z_lr:
        raise ValueError("the replay path has no stressed quarter")
    return float(np.clip((z_lr - z_min_downside) / (z_lr - z_min_replay), 0.0, 1.0))


def multiplier(mask: np.ndarray, m: float | np.ndarray, s: float) -> np.ndarray:
    """Odds multiplier per loan-quarter: (M ** s) in stressed quarters, 1 elsewhere. `m` may be a
    scalar or per loan (n,) when sand / other values are split."""
    m = np.asarray(m, dtype=float)
    mm = m[:, None] if m.ndim == 1 else m
    return np.where(mask, mm**s, 1.0)
