"""Time-aware data splitting.

The problem this module exists to solve
--------------------------------------
Hourly irradiance is strongly autocorrelated. A random train/test split puts 13:00 in
training and 14:00 in test on the same afternoon, under the same cloud field. The model
is then scored on conditions it has effectively already seen, and the resulting metric
describes interpolation, not forecasting.

Mabodi & Hammujuddy [P2, Sec. III-B] use ``train_test_split`` and describe it as
preventing leakage. Vijay Babu et al. [P5, Sec. V-D] use random sampling and state
plainly that time-based splits are future work:

    "Although the current validation was performed using random sampling, future work
     will involve testing generalization using time-based and location-specific data
     splits."

This module implements that future work. :func:`random_split` is provided *only* so the
platform can quantify the difference on the user's own data — see
``evaluation.leakage``. It is never the default.

The gap parameter
-----------------
Even a chronological split leaks a little: the last training hour and the first validation
hour are 60 minutes apart and share a weather system. Every splitter therefore inserts a
configurable embargo gap (default 24 h) between train and validation.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Split:
    """One train/validation split, with the boundary timestamps recorded."""

    train_idx: np.ndarray
    test_idx: np.ndarray
    fold: int
    train_start: pd.Timestamp | None = None
    train_end: pd.Timestamp | None = None
    test_start: pd.Timestamp | None = None
    test_end: pd.Timestamp | None = None
    gap_hours: int = 0

    def describe(self) -> dict[str, object]:
        return {
            "fold": self.fold,
            "n_train": int(self.train_idx.size),
            "n_test": int(self.test_idx.size),
            "train_start": self.train_start.isoformat() if self.train_start is not None else None,
            "train_end": self.train_end.isoformat() if self.train_end is not None else None,
            "test_start": self.test_start.isoformat() if self.test_start is not None else None,
            "test_end": self.test_end.isoformat() if self.test_end is not None else None,
            "gap_hours": self.gap_hours,
        }


def chronological_split(
    index: pd.DatetimeIndex, *, test_fraction: float = 0.2, gap_hours: int = 24
) -> tuple[np.ndarray, np.ndarray]:
    """Split into an earlier training block and a later test block.

    The test set is always the most recent data, which is the only arrangement that
    mirrors deployment: a model trained on the past, used on the future.
    """
    n = len(index)
    if n < 10:
        raise ValueError(f"Need at least 10 observations to split; got {n}.")
    if not 0.05 <= test_fraction <= 0.5:
        raise ValueError(f"test_fraction must be within [0.05, 0.5]; got {test_fraction}.")
    if not index.is_monotonic_increasing:
        raise ValueError(
            "Index must be in chronological order before splitting. Sort the dataset first."
        )

    cut = int(n * (1.0 - test_fraction))
    train_idx = np.arange(0, cut)
    test_idx = np.arange(cut, n)

    if gap_hours > 0 and train_idx.size:
        boundary = index[cut] - pd.Timedelta(hours=gap_hours)
        keep = index[train_idx] <= boundary
        train_idx = train_idx[keep]

    if train_idx.size < 5 or test_idx.size < 3:
        raise ValueError(
            f"Split produced too few observations (train={train_idx.size}, "
            f"test={test_idx.size}). Use a longer training window or a smaller gap."
        )
    return train_idx, test_idx


def _fold_positions(
    n: int, *, n_splits: int, expanding: bool
) -> Iterator[tuple[int, int, int, int, int]]:
    """Fold geometry, in row positions and nothing else.

    Split out so that every rolling-origin splitter in the platform lays its folds down in
    the same places, whether or not it has a time index to apply an embargo against. Yields
    ``(fold, train_start, train_end, test_start, test_end)`` as half-open positions.
    """
    if n_splits < 2:
        raise ValueError(f"n_splits must be at least 2; got {n_splits}.")

    fold_size = n // (n_splits + 1)
    if fold_size < 5:
        raise ValueError(
            f"Only {n} observations available for {n_splits} folds "
            f"({fold_size} per fold). Reduce the number of folds or widen the window."
        )

    for fold in range(n_splits):
        train_end = fold_size * (fold + 1)
        test_start = train_end
        test_end = min(train_end + fold_size, n)
        if test_end - test_start < 3:
            return
        train_start = 0 if expanding else max(0, train_end - fold_size * 2)
        yield fold, train_start, train_end, test_start, test_end


def rolling_origin_splits(
    index: pd.DatetimeIndex,
    *,
    n_splits: int = 5,
    gap_hours: int = 24,
    expanding: bool = True,
    min_train_size: int | None = None,
) -> Iterator[Split]:
    """Rolling-origin (walk-forward) cross-validation.

    Each fold trains on everything before a cut point and validates on the block just
    after it, so the model is never fitted on data that postdates its validation set.
    With ``expanding=True`` the training window grows fold by fold, mimicking a system
    retrained as data accumulates; with ``expanding=False`` a fixed-length window slides.
    """
    n = len(index)
    if not index.is_monotonic_increasing:
        raise ValueError("Index must be in chronological order before splitting.")

    fold_size = n // (n_splits + 1) if n_splits >= 2 else 0
    min_train = min_train_size or fold_size

    for fold, train_start_pos, train_end_pos, test_start_pos, test_end_pos in _fold_positions(
        n, n_splits=n_splits, expanding=expanding
    ):
        train_idx = np.arange(train_start_pos, train_end_pos)

        if gap_hours > 0 and train_idx.size:
            boundary = index[test_start_pos] - pd.Timedelta(hours=gap_hours)
            train_idx = train_idx[index[train_idx] <= boundary]

        if train_idx.size < min_train // 2:
            continue

        test_idx = np.arange(test_start_pos, test_end_pos)
        yield Split(
            train_idx=train_idx,
            test_idx=test_idx,
            fold=fold,
            train_start=index[train_idx[0]] if train_idx.size else None,
            train_end=index[train_idx[-1]] if train_idx.size else None,
            test_start=index[test_idx[0]],
            test_end=index[test_idx[-1]],
            gap_hours=gap_hours,
        )


class BlockedChronologicalCV:
    """Contiguous time-ordered validation blocks with an embargo, as a scikit-learn CV.

    Exists for one caller: the stacking ensemble in ``models.registry``. A
    ``StackingRegressor`` fits its meta-learner on out-of-fold predictions collected by
    ``cross_val_predict``, whose default here is a plain K-fold. On autocorrelated hourly
    data that trains the meta-learner on predictions made with access to each row's
    immediate neighbours, and the weights go to whichever base model overfits hardest.

    Each fold's validation set is a contiguous block of hours, and the rows on either side
    of that block are *purged* from the fold's training set. So no base prediction the
    meta-learner sees was made by a model that had just been shown the surrounding hours.

    Why this is blocked rather than rolling-origin
    ----------------------------------------------
    ``cross_val_predict`` requires the folds to partition the data — every row must be an
    out-of-fold prediction exactly once. A forward-only scheme cannot satisfy that: its
    earliest block has no past to be predicted from, so those rows are never covered and
    scikit-learn rejects the splitter outright. This is the strongest time-aware inner
    validation that fits inside stacking's contract, and it is not the same thing as
    forward-only. Saying so matters, because the platform's *outer* evaluation is strictly
    chronological (:func:`chronological_split`, :func:`rolling_origin_splits`) and that is
    where every reported figure comes from. This splitter only chooses blending weights.

    **The embargo is counted in samples, not hours**, because an estimator is handed a
    matrix and never sees the time index. On the daytime-only hourly data this platform
    builds a day contributes roughly ten to fourteen rows, so the default of 12 is about a
    calendar day — the same order as the 24-hour embargo used elsewhere, an approximation
    of it rather than the thing itself.
    """

    def __init__(self, *, n_splits: int = 5, embargo_samples: int = 12) -> None:
        if n_splits < 2:
            raise ValueError(f"n_splits must be at least 2; got {n_splits}.")
        if embargo_samples < 0:
            raise ValueError(f"embargo_samples must not be negative; got {embargo_samples}.")
        self.n_splits = n_splits
        self.embargo_samples = embargo_samples

    def get_n_splits(self, X=None, y=None, groups=None) -> int:  # noqa: N803 - sklearn API
        return self.n_splits

    def split(self, X, y=None, groups=None):  # noqa: N803 - sklearn API
        """Yield ``(train_positions, validation_positions)`` for each fold.

        Rows are assumed to be in chronological order, which is what the feature pipeline
        produces and what every splitter in this module already requires. The validation
        blocks together cover every row exactly once, which is what ``cross_val_predict``
        demands of a cross-validator.
        """
        n = len(X)
        bounds = np.linspace(0, n, self.n_splits + 1).astype(int)
        positions = np.arange(n)

        for fold in range(self.n_splits):
            start, stop = int(bounds[fold]), int(bounds[fold + 1])
            test_idx = positions[start:stop]

            purge_from = max(0, start - self.embargo_samples)
            purge_to = min(n, stop + self.embargo_samples)
            train_idx = np.concatenate(
                [positions[:purge_from], positions[purge_to:]]
            )

            if train_idx.size < 5 or test_idx.size == 0:
                # Too little left to fit anything useful. Fall back to the unpurged
                # complement rather than yielding an empty training set, which would make
                # the whole ensemble unfittable on a short record.
                train_idx = np.concatenate([positions[:start], positions[stop:]])
            yield train_idx, test_idx


def random_split(
    index: pd.DatetimeIndex, *, test_fraction: float = 0.2, seed: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Shuffled split. **Leaks temporal information — for demonstration only.**

    Present solely so that ``evaluation.leakage`` can measure how much optimism this
    introduces on the user's own dataset. Never use it to report performance.
    """
    n = len(index)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(n)
    cut = int(n * (1.0 - test_fraction))
    return np.sort(perm[:cut]), np.sort(perm[cut:])


def blocked_random_split(
    index: pd.DatetimeIndex,
    *,
    test_fraction: float = 0.2,
    block: str = "D",
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Random split at whole-day granularity.

    A middle ground: days are assigned randomly, but hours within a day stay together, so
    a morning cannot train a model that is scored on the same afternoon. Useful when
    seasonal coverage matters more than strict forward-in-time evaluation, and materially
    safer than hour-level shuffling. Still not a substitute for chronological evaluation.
    """
    periods = index.to_period(block)
    unique = np.array(sorted(set(periods)))
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(unique))
    cut = int(len(unique) * (1.0 - test_fraction))
    train_periods = set(unique[perm[:cut]].tolist())

    is_train = np.array([p in train_periods for p in periods])
    return np.where(is_train)[0], np.where(~is_train)[0]


def describe_strategy(name: str) -> dict[str, str]:
    """Human-readable description of a splitting strategy, served to the UI."""
    strategies = {
        "chronological": {
            "name": "Chronological hold-out",
            "description": (
                "Train on the earliest portion of the record, test on the most recent. "
                "Mirrors deployment: past data, future predictions."
            ),
            "leakage_risk": "Low",
            "recommended": "Yes — the default for reported performance.",
        },
        "rolling_origin": {
            "name": "Rolling-origin cross-validation",
            "description": (
                "Repeated chronological splits at advancing cut points, so performance is "
                "measured across several distinct periods rather than one."
            ),
            "leakage_risk": "Low",
            "recommended": "Yes — the default for cross-validated estimates.",
        },
        "blocked_random": {
            "name": "Blocked random (whole days)",
            "description": (
                "Whole days assigned randomly to train or test. Hours within a day are "
                "never separated."
            ),
            "leakage_risk": "Moderate — seasonal information crosses the split.",
            "recommended": "Only when seasonal coverage matters more than forward evaluation.",
        },
        "random": {
            "name": "Random hour-level shuffle",
            "description": (
                "Individual hours assigned at random. Adjacent hours land on opposite "
                "sides of the split under identical weather."
            ),
            "leakage_risk": "High — produces optimistic, non-reproducible estimates.",
            "recommended": "No. Provided only to quantify the resulting optimism.",
        },
    }
    return strategies.get(name, {"name": name, "description": "Unknown strategy."})
