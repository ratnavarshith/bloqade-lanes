"""A forward dataflow analysis of site occupancy over move IR.

Independent of the Rust validator on purpose: it resolves each lane to its
endpoints (``ArchSpec.try_get_endpoints``) and then follows the atoms with its
own rules, so the two can be compared (``tests/test_occupancy_diff.py``).

Lattice. A state value is a :class:`Layout`, a map from site to a cell: absent
means empty, an ``int`` is the id of the atom there (the index in the ``Fill``),
``Cell.UNKNOWN`` is top. Sites touched by a reported violation become unknown, so
one error is not reported again at every later move. ``Unreached`` is bottom
(also the value of every non-state SSA value) and ``Anything`` is top.

Violations (``OccupancyAnalysis.violations``), per ``move.Move`` statement:

* ``inconsistent-lanes``: lanes of one move set differ in zone, bus, move type or
  direction;
* ``invalid-lane``: a lane that is not a lane of the architecture;
* ``empty-source``: lanes of a move set whose source site is empty (reported once
  per set, with how many of its lanes);
* ``collision``: a lane lands on an occupied site that no lane of the same set
  vacates, or two lanes land on one site (``Fill`` onto an occupied site too).

The IR carries only the initial layout (``Fill``), not an expected final one, so
final occupancy is not checked.

Kirin API used: ``Forward`` / ``ForwardFrame`` (``kirin/analysis/forward.py:29-70``),
``BoundedLattice`` (``kirin/lattice/abc.py:76``), ``Dialect.register(key=...)``
(``kirin/ir/dialect.py:73``), ``interp.impl`` (``kirin/interp/table.py:106``),
mirroring ``bloqade/lanes/analysis/atom``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from kirin import interp, ir
from kirin.analysis import Forward
from kirin.analysis.forward import ForwardFrame
from kirin.dialects import func
from kirin.lattice import BoundedLattice

from bloqade.lanes.arch.spec import ArchSpec
from bloqade.lanes.bytecode.encoding import LocationAddress
from bloqade.lanes.dialects import move


class Cell(enum.Enum):
    UNKNOWN = "unknown"  # top: an atom or nothing, we cannot tell


def _join_cell(a: int | Cell | None, b: int | Cell | None) -> int | Cell | None:
    """``None`` is an empty site."""
    return a if a == b else Cell.UNKNOWN


def _meet_cell(a: int | Cell | None, b: int | Cell | None) -> int | Cell | None:
    """Raises ``ValueError`` when the cells are incompatible (meet is bottom)."""
    if a == Cell.UNKNOWN:
        return b
    if b == Cell.UNKNOWN or a == b:
        return a
    raise ValueError


class Occupancy(BoundedLattice["Occupancy"]):
    @classmethod
    def bottom(cls) -> Occupancy:
        return Unreached()

    @classmethod
    def top(cls) -> Occupancy:
        return Anything()

    def join(self, other: Occupancy) -> Occupancy:
        if isinstance(other, Unreached):
            return self
        if isinstance(self, Unreached):
            return other
        if isinstance(self, Layout) and isinstance(other, Layout):
            return Layout(
                {
                    s: _join_cell(self.at(s), other.at(s))  # type: ignore[misc]
                    for s in self.sites.keys() | other.sites.keys()
                }
            )
        return Anything()

    def meet(self, other: Occupancy) -> Occupancy:
        if isinstance(other, Anything):
            return self
        if isinstance(self, Anything):
            return other
        if isinstance(self, Layout) and isinstance(other, Layout):
            try:
                return Layout(
                    {
                        s: _meet_cell(self.at(s), other.at(s))  # type: ignore[misc]
                        for s in self.sites.keys() | other.sites.keys()
                    }
                )
            except ValueError:
                pass
        return Unreached()

    def is_subseteq(self, other: Occupancy) -> bool:
        return self.join(other).is_structurally_equal(other)

    def is_structurally_equal(
        self, other: Occupancy, context: dict | None = None
    ) -> bool:
        if isinstance(self, Layout) and isinstance(other, Layout):
            sites = self.sites.keys() | other.sites.keys()
            return all(self.at(s) == other.at(s) for s in sites)
        return type(self) is type(other)


@dataclass(frozen=True, eq=False)
class Unreached(Occupancy):
    """Bottom: not reached, or not a layout (floats, futures, ...)."""


@dataclass(frozen=True, eq=False)
class Anything(Occupancy):
    """Top: some layout we know nothing about."""


@dataclass(frozen=True, eq=False)
class Layout(Occupancy):
    """Site -> atom id / ``Cell.UNKNOWN``; absent sites are empty. Never mutated."""

    sites: dict[LocationAddress, int | Cell] = field(default_factory=dict)

    def at(self, site: LocationAddress) -> int | Cell | None:
        return self.sites.get(site)


@dataclass(frozen=True)
class Violation:
    kind: str
    detail: str


@dataclass
class OccupancyAnalysis(Forward[Occupancy]):
    lattice = Occupancy
    keys = ("occupancy",)

    arch_spec: ArchSpec = field(kw_only=True)
    violations: list[Violation] = field(init=False, default_factory=list)
    current_state: Occupancy = field(init=False, default_factory=Unreached)

    def initialize(self) -> OccupancyAnalysis:
        self.violations = []
        self.current_state = Layout()
        return super().initialize()

    def method_self(self, method) -> Occupancy:
        return Unreached()

    def eval_fallback(self, frame: ForwardFrame[Occupancy], node: ir.Statement):
        return tuple(Unreached() for _ in node.results)

    def report(self, kind: str, detail: str) -> None:
        self.violations.append(Violation(kind, detail))


def _lane_key(lane) -> tuple:
    return (lane.zone_id, lane.bus_id, lane.move_type, lane.direction)


@move.dialect.register(key="occupancy")
class MoveMethods(interp.MethodTable):
    @interp.impl(move.Load)
    def load(self, interp_: OccupancyAnalysis, frame, stmt: move.Load):
        return (interp_.current_state,)

    @interp.impl(move.Store)
    def store(self, interp_: OccupancyAnalysis, frame, stmt: move.Store):
        interp_.current_state = frame.get(stmt.current_state)
        return ()

    @interp.impl(move.Fill)
    def fill(self, interp_: OccupancyAnalysis, frame, stmt: move.Fill):
        state = frame.get(stmt.current_state)
        if not isinstance(state, Layout):
            return (Anything(),)
        sites = dict(state.sites)
        for atom, site in enumerate(stmt.location_addresses):
            if site in sites:
                interp_.report("collision", f"fill of atom {atom} onto occupied {site}")
                sites[site] = Cell.UNKNOWN
            else:
                sites[site] = atom
        return (Layout(sites),)

    @interp.impl(move.Move)
    def move_(self, interp_: OccupancyAnalysis, frame, stmt: move.Move):
        state = frame.get(stmt.current_state)
        if not isinstance(state, Layout):
            return (Anything(),)

        lanes = stmt.lanes
        if len({_lane_key(lane) for lane in lanes}) > 1:
            interp_.report(
                "inconsistent-lanes",
                "lanes differ in "
                + ", ".join(
                    name
                    for i, name in enumerate(("zone", "bus", "move type", "direction"))
                    if len({_lane_key(lane)[i] for lane in lanes}) > 1
                ),
            )

        hops: list[tuple[LocationAddress, LocationAddress]] = []
        for lane in lanes:
            ends = interp_.arch_spec.try_get_endpoints(lane)
            if ends is None:
                interp_.report("invalid-lane", f"{lane!r} is not a lane of the arch")
            else:
                hops.append(ends)

        sites = dict(state.sites)
        movers = []  # (src, dst, atom id or UNKNOWN)
        empty = [src for src, _ in hops if state.at(src) is None]
        for src, dst in hops:
            if state.at(src) is not None:
                movers.append((src, dst, state.at(src)))
        if empty:
            interp_.report(
                "empty-source",
                f"{len(empty)} of {len(hops)} lanes start from empty sites"
                f" (first: {empty[0]})",
            )

        vacated = {src for src, _, _ in movers}
        for src in vacated:
            del sites[src]
        landed: set[LocationAddress] = set()
        for _, dst, atom in movers:
            occupied = isinstance(state.at(dst), int) and dst not in vacated
            if occupied or dst in landed:
                interp_.report("collision", f"move into occupied {dst}")
                sites[dst] = Cell.UNKNOWN
            else:
                sites[dst] = atom
            landed.add(dst)
        return (Layout(sites),)

    @interp.impl(move.CZ)
    @interp.impl(move.LocalR)
    @interp.impl(move.LocalRz)
    @interp.impl(move.StarRz)
    @interp.impl(move.GlobalR)
    @interp.impl(move.GlobalRz)
    @interp.impl(move.LogicalInitialize)
    @interp.impl(move.PhysicalInitialize)
    def same_layout(self, interp_: OccupancyAnalysis, frame, stmt):
        return (frame.get(stmt.current_state),)

    @interp.impl(move.Measure)
    def measure(self, interp_: OccupancyAnalysis, frame, stmt: move.Measure):
        return (frame.get(stmt.current_state), Unreached())


@func.dialect.register(key="occupancy")
class FuncMethods(interp.MethodTable):
    @interp.impl(func.Return)
    def return_(self, interp_: OccupancyAnalysis, frame, stmt: func.Return):
        return interp.ReturnValue(frame.get(stmt.value))


def analyze(move_mt: ir.Method, arch_spec: ArchSpec) -> list[Violation]:
    """All violations found in ``move_mt``; empty means the analysis accepts it."""
    analysis = OccupancyAnalysis(move_mt.dialects, arch_spec=arch_spec)
    analysis.run(move_mt)
    return analysis.violations

