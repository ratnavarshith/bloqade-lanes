"""Hypothesis strategy for random squin kernels, valid by construction.

A kernel is drawn as a small immutable :class:`KernelSpec` (so Hypothesis can
shrink it), rendered to Python source, and imported from a real file because
kirin lowers a kernel from its source text (``inspect.getsource``).

Validity by construction:

* every qubit index is in ``range(n_qubits)``;
* every two-qubit gate acts on two *distinct* qubits;
* every broadcast layer (``bcz``) uses pairwise-disjoint qubits;
* the body is straight-line code, so kirin always lowers it;
* the only measurement is one terminal ``measure`` over all qubits, which is
  what ``PhysicalPipeline`` requires.

Ops are plain tuples:

==========================  ============================================
``("h" | "s" | "x" | "z" | "t", q)``   single-qubit gate
``("rz" | "rx", q, k)``                 rotation by ``k * pi / 8``
``("cz" | "cx", control, target)``      two-qubit gate
``("bcz", ((c0, t0), (c1, t1), ...))``  one broadcast CZ layer
==========================  ============================================
"""

from __future__ import annotations

import atexit
import hashlib
import importlib.util
import math
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from hypothesis import strategies as st
from kirin import ir

Op = tuple[Any, ...]

CLIFFORD_GATES: dict[str, int] = {
    "h": 3,
    "s": 2,
    "x": 1,
    "z": 1,
    "cz": 3,
    "cx": 3,
    "bcz": 2,
}
"""Default relative weights in Clifford mode (H, S, X, Z, CZ, CX, broadcast CZ)."""

NON_CLIFFORD_GATES: dict[str, int] = {**CLIFFORD_GATES, "t": 2, "rz": 2, "rx": 2}
"""Default relative weights in non-Clifford mode (Clifford gates plus T, RZ, RX)."""

MAX_NON_CLIFFORD_QUBITS = 6


@dataclass(frozen=True)
class GenConfig:
    """Size and gate mix of generated kernels.

    ``weights`` maps gate name to a positive relative weight; gates left out are
    never generated. ``measure`` is ``"always"``/``"never"``/``"any"`` for the
    terminal measurement; the default is ``"always"`` in Clifford mode (checked
    with Stim, which ignores the measurement) and ``"never"`` in non-Clifford
    mode (checked with statevectors, which need a measurement-free kernel).
    """

    mode: Literal["clifford", "nonclifford"] = "clifford"
    min_qubits: int = 2
    max_qubits: int = 6
    min_ops: int = 1
    max_ops: int = 12
    weights: tuple[tuple[str, int], ...] | None = None
    measure: Literal["always", "never", "any"] | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("clifford", "nonclifford"):
            raise ValueError(f"unknown mode {self.mode!r}")
        if self.min_qubits < 2:
            raise ValueError("min_qubits must be >= 2 (two-qubit gates need two)")
        if self.max_qubits < self.min_qubits:
            raise ValueError("max_qubits < min_qubits")
        if self.mode == "nonclifford" and self.max_qubits > MAX_NON_CLIFFORD_QUBITS:
            raise ValueError(
                f"non-Clifford kernels are checked by statevector and are limited "
                f"to {MAX_NON_CLIFFORD_QUBITS} qubits"
            )
        if self.mode == "nonclifford" and self.measure_mode() != "never":
            raise ValueError(
                "non-Clifford kernels are compared by statevector, so measure must be 'never'"
            )
        if not 0 <= self.min_ops <= self.max_ops:
            raise ValueError("need 0 <= min_ops <= max_ops")
        table = self.gate_weights()
        allowed = CLIFFORD_GATES if self.mode == "clifford" else NON_CLIFFORD_GATES
        unknown = set(table) - set(allowed)
        if unknown:
            raise ValueError(
                f"gates {sorted(unknown)} are not allowed in {self.mode} mode"
            )
        if not table or any(w <= 0 for w in table.values()):
            raise ValueError("weights must be a non-empty map of positive integers")

    def gate_weights(self) -> dict[str, int]:
        if self.weights is not None:
            return dict(self.weights)
        return dict(CLIFFORD_GATES if self.mode == "clifford" else NON_CLIFFORD_GATES)

    def measure_mode(self) -> str:
        if self.measure is not None:
            return self.measure
        return "always" if self.mode == "clifford" else "never"


@dataclass(frozen=True)
class KernelSpec:
    n_qubits: int
    ops: tuple[Op, ...]
    measure: bool


# ── drawing ──────────────────────────────────────────────────────────


def _single(name: str, n: int) -> st.SearchStrategy[Op]:
    return st.integers(0, n - 1).map(lambda q: (name, q))


def _rotation(name: str, n: int) -> st.SearchStrategy[Op]:
    return st.tuples(st.just(name), st.integers(0, n - 1), st.integers(-7, 8))


def _two(name: str, n: int) -> st.SearchStrategy[Op]:
    return (
        st.tuples(st.integers(0, n - 1), st.integers(0, n - 1))
        .filter(lambda p: p[0] != p[1])
        .map(lambda p: (name, p[0], p[1]))
    )


def _broadcast_cz(n: int) -> st.SearchStrategy[Op]:
    @st.composite
    def draw_layer(draw: st.DrawFn) -> Op:
        order = draw(st.permutations(range(n)))
        pairs = draw(st.integers(1, n // 2))
        return ("bcz", tuple((order[2 * i], order[2 * i + 1]) for i in range(pairs)))

    return draw_layer()


def _op(n: int, cfg: GenConfig) -> st.SearchStrategy[Op]:
    makers = {
        "h": lambda: _single("h", n),
        "s": lambda: _single("s", n),
        "x": lambda: _single("x", n),
        "z": lambda: _single("z", n),
        "t": lambda: _single("t", n),
        "rz": lambda: _rotation("rz", n),
        "rx": lambda: _rotation("rx", n),
        "cz": lambda: _two("cz", n),
        "cx": lambda: _two("cx", n),
        "bcz": lambda: _broadcast_cz(n),
    }
    table = cfg.gate_weights()
    # Weighted choice: pick a gate name by weight, then draw that gate.
    names = [name for name, w in sorted(table.items()) for _ in range(w)]
    return st.sampled_from(names).flatmap(lambda name: makers[name]())


def _measure(cfg: GenConfig) -> st.SearchStrategy[bool]:
    mode = cfg.measure_mode()
    if mode == "always":
        return st.just(True)
    if mode == "never":
        return st.just(False)
    return st.booleans()


def kernel_specs(cfg: GenConfig = GenConfig()) -> st.SearchStrategy[KernelSpec]:
    """Strategy over :class:`KernelSpec` drawn according to ``cfg``."""

    def for_size(n: int) -> st.SearchStrategy[KernelSpec]:
        return st.builds(
            KernelSpec,
            n_qubits=st.just(n),
            ops=st.lists(_op(n, cfg), min_size=cfg.min_ops, max_size=cfg.max_ops).map(
                tuple
            ),
            measure=_measure(cfg),
        )

    return st.integers(cfg.min_qubits, cfg.max_qubits).flatmap(for_size)


# ── rendering ────────────────────────────────────────────────────────


def _angle(k: int) -> float:
    return k * math.pi / 8


def render_op(op: Op) -> str:
    name = op[0]
    if name in ("h", "s", "x", "z", "t"):
        return f"squin.{name}(reg[{op[1]}])"
    if name in ("rz", "rx"):
        return f"squin.{name}({_angle(op[2])!r}, reg[{op[1]}])"
    if name in ("cz", "cx"):
        return f"squin.{name}(reg[{op[1]}], reg[{op[2]}])"
    if name == "bcz":
        controls = ", ".join(f"reg[{c}]" for c, _ in op[1])
        targets = ", ".join(f"reg[{t}]" for _, t in op[1])
        return (
            f"squin.broadcast.cz(ilist.IList([{controls}]), ilist.IList([{targets}]))"
        )
    raise ValueError(f"unknown op {op!r}")


def render(spec: KernelSpec) -> str:
    """Python source of the kernel ``main`` for ``spec``."""
    lines = [
        "from kirin.dialects import ilist",
        "",
        "from bloqade import squin",
        "",
        "",
        "@squin.kernel",
        "def main():",
        f"    reg = squin.qalloc({spec.n_qubits})",
    ]
    lines += [f"    {render_op(op)}" for op in spec.ops]
    if spec.measure:
        lines.append("    return squin.broadcast.measure(reg)")
    return "\n".join(lines) + "\n"


# ── building ─────────────────────────────────────────────────────────

_TMP = Path(tempfile.mkdtemp(prefix="lanes_fuzz_"))
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)
_BUILT: dict[str, ir.Method] = {}


def build_kernel(spec: KernelSpec) -> ir.Method:
    """Import the rendered kernel and return a fresh copy of the squin method."""
    source = render(spec)
    digest = hashlib.sha1(source.encode()).hexdigest()[:16]
    if digest not in _BUILT:
        name = f"lanes_fuzz_kernel_{digest}"
        path = _TMP / f"{name}.py"
        path.write_text(source)
        module_spec = importlib.util.spec_from_file_location(name, path)
        assert module_spec is not None and module_spec.loader is not None
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[name] = module
        module_spec.loader.exec_module(module)
        _BUILT[digest] = module.main
    return _BUILT[digest].similar()
