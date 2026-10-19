"""Write a failing example as a standalone repro script.

The script needs only ``bloqade-lanes`` and ``stim`` (not this package): it
contains the kernel source, the strategy expression, the equivalence helpers
(the source of :mod:`lanes_fuzz.equiv`) and the compile/validate steps (the
source of the functions in :mod:`lanes_fuzz.check`). Running it prints
``REPRODUCED: <category>`` and exits 1 if the failure still happens, or
``NOT REPRODUCED`` and exits 0 if it does not.
"""

from __future__ import annotations

import hashlib
import inspect
import re
from pathlib import Path

from lanes_fuzz import check, equiv, plant
from lanes_fuzz.gen import KernelSpec, render
from lanes_fuzz.strategies import IMPORTS, STRATEGY_CODE

_TEMPLATE = '''\
"""Standalone repro found by lanes-fuzz.

strategy: {strategy}
category: {category}
detail:   {detail}
kernel:   {n_qubits} qubits, {n_ops} ops, terminal measure: {measure}

Run with bloqade-lanes and stim installed:  python {filename}
"""

{imports}
{kernel_source}

# ── equivalence helpers (lanes_fuzz.equiv) ──────────────────────────
{equiv_source}

# ── compile and validate (lanes_fuzz.check) ─────────────────────────
import re  # noqa: E402
import sys  # noqa: E402

from bloqade.lanes.analysis import atom  # noqa: E402
from bloqade.lanes.analysis.placement.exceptions import PlacementError  # noqa: E402
from bloqade.lanes.arch.gemini import physical  # noqa: E402
from bloqade.lanes.dialects import move, place  # noqa: E402
from bloqade.lanes.heuristics.physical.layout import (  # noqa: E402
    PhysicalLayoutHeuristicGraphPartitionCenterOut,
)
from bloqade.lanes.passes import SequentialPlacePass  # noqa: E402
from bloqade.lanes.transform import (  # noqa: E402
    MoveToSquinPhysical,
    NativeToPlace,
    PhysicalPipeline,
    PlaceToMove,
)

_ARCH = physical.get_arch_spec()


def physical_arch():
    return _ARCH


{signature_source}

{compile_source}

{validate_source}
{plant_source}

HAS_MEASURE = {measure}
CLIFFORD = {clifford}
EXPECTED_CATEGORY = {category!r}


def reproduce() -> str:
    """Run the steps of lanes_fuzz.check.check_kernel; return the category."""
    arch = physical_arch()
    strategy = {strategy_code}
    try:
        move_mt = compile_to_move(main, strategy, HAS_MEASURE)
    except Exception as exc:  # noqa: BLE001
        return expected_category(exc) or "compile: " + signature(exc)
    if any(isinstance(s, place.CZ) for s in move_mt.callable_region.walk()):
        return "not lowered: place.CZ left"
    try:
        rust_validate(move_mt)
    except Exception as exc:  # noqa: BLE001
        return "validator: " + signature(exc)
    try:
        lifted = MoveToSquinPhysical(arch).emit(move_mt, no_raise=False)
{plant_call}    except Exception as exc:  # noqa: BLE001
        return "to-squin: " + signature(exc)
    try:
        if CLIFFORD:
            equal, kind = tableaus_equal(main, lifted), "tableau"
        else:
            equal = statevectors_equal_up_to_phase(
                statevector(main), statevector(lifted)
            )
            kind = "statevector"
    except Exception as exc:  # noqa: BLE001
        return "equivalence-crash: " + signature(exc)
    return "ok" if equal else "equivalence: " + kind + " differs"


if __name__ == "__main__":
    got = reproduce()
    if got == EXPECTED_CATEGORY:
        print("REPRODUCED: " + got)
        sys.exit(1)
    print("NOT REPRODUCED (got " + repr(got) + ")")
    sys.exit(0)
'''


def _strip_future(source: str) -> str:
    return "\n".join(
        line for line in source.splitlines() if not line.startswith("from __future__")
    )


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:48]


def repro_filename(strategy: str, category: str) -> str:
    digest = hashlib.sha1(category.encode()).hexdigest()[:6]
    return f"{_slug(strategy)}__{_slug(category)}__{digest}.py"


def render_repro(
    spec: KernelSpec,
    strategy: str,
    category: str,
    detail: str = "",
    *,
    planted: bool = False,
    filename: str = "repro.py",
) -> str:
    equiv_source = _strip_future(inspect.getsource(equiv))
    # The module docstring would otherwise sit in the middle of the script.
    equiv_source = re.sub(r'^""".*?"""\n', "", equiv_source, count=1, flags=re.DOTALL)
    return _TEMPLATE.format(
        strategy=strategy,
        category=category,
        detail=" ".join(detail.split())[:200],
        n_qubits=spec.n_qubits,
        n_ops=len(spec.ops),
        measure=spec.measure,
        filename=filename,
        imports=IMPORTS,
        kernel_source=render(spec).rstrip(),
        equiv_source=equiv_source,
        signature_source=(
            inspect.getsource(check.expected_category)
            + "\n\n"
            + inspect.getsource(check.signature)
        ),
        compile_source=inspect.getsource(check.compile_to_move),
        validate_source=inspect.getsource(check.rust_validate),
        plant_source=(
            "\n\nfrom kirin.dialects import func, ilist  # noqa: E402\n"
            "from bloqade import qubit  # noqa: E402\n"
            "from bloqade.squin import gate  # noqa: E402\n\n\n"
            + inspect.getsource(plant.plant_extra_x)
            if planted
            else ""
        ),
        plant_call=("        lifted = plant_extra_x(lifted)\n" if planted else ""),
        strategy_code=STRATEGY_CODE[strategy],
        clifford=check.is_clifford(spec),
    )


def write_repro(
    directory: Path,
    spec: KernelSpec,
    strategy: str,
    category: str,
    detail: str = "",
    *,
    planted: bool = False,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    name = repro_filename(strategy, category)
    path = directory / name
    path.write_text(
        render_repro(spec, strategy, category, detail, planted=planted, filename=name)
    )
    return path
