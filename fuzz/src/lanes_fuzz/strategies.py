"""The lanes placement strategies the fuzzer exercises.

Each strategy is one expression, evaluated against an ``arch`` name, so the
same text can be pasted into a standalone repro script. The constructors mirror
the benchmark matrix (``python/benchmarks/harness/matrix.py``) where it has a
row for the strategy, and use the strategy's defaults otherwise:

========================  ===============================================
``astar``/``ids``/...     ``RustPlacementTraversal(strategy=...)`` in a
                          ``PalindromePlacementStrategy`` (matrix.py:116-281)
``entropy``               ``rust_entropy_5`` (matrix.py:116-140)
``greedy``                matrix.py:206-221
``cascade-*``             no matrix row for dfs/entropy; defaults
``pipeline_default``      ``make_physical_placement_strategy`` (matrix.py:68-88)
``pipeline_route_all``    same with ``MoverSelection.ROUTE_ALL`` (matrix.py:89-101)
``loose_goal``            ``NoReturnPlacementStrategy`` (matrix.py:282-293)
``receding_horizon``      ``RecedingHorizonNoReturnPlacementStrategy``
========================  ===============================================

``cascade`` is an alias of ``cascade-ids`` (``_solver_dispatch.py:24-25``) and is
not listed twice.
"""

from __future__ import annotations

from typing import Any

from bloqade.lanes.analysis.placement import PalindromePlacementStrategy
from bloqade.lanes.arch.gemini import physical
from bloqade.lanes.bytecode import MoverSelection
from bloqade.lanes.heuristics.physical import (
    NoReturnPlacementStrategy,
    RecedingHorizonNoReturnPlacementStrategy,
    make_physical_placement_strategy,
)
from bloqade.lanes.heuristics.physical.placement import (
    PhysicalPlacementStrategy,
    RustPlacementTraversal,
)

IMPORTS = """\
from bloqade.lanes.analysis.placement import PalindromePlacementStrategy
from bloqade.lanes.bytecode import MoverSelection
from bloqade.lanes.heuristics.physical import (
    NoReturnPlacementStrategy,
    RecedingHorizonNoReturnPlacementStrategy,
    make_physical_placement_strategy,
)
from bloqade.lanes.heuristics.physical.placement import (
    PhysicalPlacementStrategy,
    RustPlacementTraversal,
)
"""


def _palindrome(traversal: str) -> str:
    return (
        "PalindromePlacementStrategy(inner=PhysicalPlacementStrategy("
        f"arch_spec=arch, traversal=RustPlacementTraversal({traversal})))"
    )


STRATEGY_CODE: dict[str, str] = {
    "astar": _palindrome('strategy="astar"'),
    "dfs": _palindrome('strategy="dfs"'),
    "bfs": _palindrome('strategy="bfs"'),
    "ids": _palindrome('strategy="ids"'),
    "greedy": _palindrome(
        'strategy="greedy", max_movesets_per_group=50, max_expansions=1000'
    ),
    "push-rotate": _palindrome('strategy="push-rotate"'),
    "entropy": _palindrome(
        'strategy="entropy", max_goal_candidates=5, max_expansions=2000'
    ),
    "cascade-ids": _palindrome('strategy="cascade-ids"'),
    "cascade-dfs": _palindrome('strategy="cascade-dfs"'),
    "cascade-entropy": _palindrome('strategy="cascade-entropy"'),
    "pipeline_default": "make_physical_placement_strategy(arch_spec=arch)",
    "pipeline_route_all": (
        "make_physical_placement_strategy("
        "arch_spec=arch, mover_selection=MoverSelection.ROUTE_ALL)"
    ),
    "loose_goal": "NoReturnPlacementStrategy(arch_spec=arch)",
    "receding_horizon": "RecedingHorizonNoReturnPlacementStrategy(arch_spec=arch)",
}

STRATEGY_NAMES: tuple[str, ...] = tuple(STRATEGY_CODE)

_NAMESPACE: dict[str, Any] = {
    "PalindromePlacementStrategy": PalindromePlacementStrategy,
    "MoverSelection": MoverSelection,
    "NoReturnPlacementStrategy": NoReturnPlacementStrategy,
    "RecedingHorizonNoReturnPlacementStrategy": RecedingHorizonNoReturnPlacementStrategy,
    "make_physical_placement_strategy": make_physical_placement_strategy,
    "PhysicalPlacementStrategy": PhysicalPlacementStrategy,
    "RustPlacementTraversal": RustPlacementTraversal,
}

_ARCH = None


def physical_arch():
    """The built-in Gemini physical arch spec, parsed once per process."""
    global _ARCH
    if _ARCH is None:
        _ARCH = physical.get_arch_spec()
    return _ARCH


def build_strategy(name: str):
    """A fresh strategy object (they carry per-compile counters)."""
    return eval(STRATEGY_CODE[name], {**_NAMESPACE, "arch": physical_arch()})
