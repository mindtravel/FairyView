"""Sampling shared by every adapter: reservoir sampling, optional stratification.

Sampling lives here, not in adapters, so a new adapter does not have to
reimplement it and `sample` means the same thing in every config.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable
from typing import Any


def reservoir(records: Iterable[Any], n: int, seed: int = 0) -> list[Any]:
    rng = random.Random(seed)
    out: list[Any] = []
    for index, item in enumerate(records):
        if len(out) < n:
            out.append(item)
        else:
            slot = rng.randrange(index + 1)
            if slot < n:
                out[slot] = item
    return out


def sample_records(
    records: Iterable[Any],
    sample: dict[str, Any] | None,
    facet_key=lambda record: None,
) -> list[Any]:
    """Return all records when `sample` is falsy.

    sample = {"n": 200, "seed": 0, "stratify": "source"}
    With `stratify`, `n` is the total budget, split evenly across strata;
    see `allocate` for small strata.
    """
    if not sample:
        return list(records)

    n = int(sample["n"])
    seed = int(sample.get("seed", 0))
    stratify = sample.get("stratify")

    if not stratify:
        return reservoir(records, n, seed)

    strata: dict[Any, list[Any]] = defaultdict(list)
    order: list[Any] = []
    for record in records:
        key = facet_key(record)
        if key not in strata:
            order.append(key)
        strata[key].append(record)

    take = allocate([len(strata[key]) for key in order], n)
    out: list[Any] = []
    for index, key in enumerate(order):
        out.extend(reservoir(strata[key], take[index], seed + index))
    return out


def allocate(sizes: list[int], n: int) -> list[int]:
    """Split budget `n` evenly across strata, never above a stratum's size.

    A stratum smaller than its share is taken whole and the unused budget is
    re-split among the rest, so `n >= sum(sizes)` keeps every row and the
    budget is never left unspent while rows remain.
    """
    take = [0] * len(sizes)
    open_ = [i for i, size in enumerate(sizes) if size > 0]
    budget = n
    while budget > 0 and open_:
        share, extra = divmod(budget, len(open_))
        if share == 0:
            for i in open_[:extra]:
                take[i] += 1
            break
        still_open = []
        for i in open_:
            room = sizes[i] - take[i]
            got = min(room, share)
            take[i] += got
            budget -= got
            if take[i] < sizes[i]:
                still_open.append(i)
        open_ = still_open
    return take
