"""The kernel generator produces valid kernels and honours its parameters."""

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from lanes_fuzz.gen import (
    CLIFFORD_GATES,
    NON_CLIFFORD_GATES,
    GenConfig,
    build_kernel,
    kernel_specs,
    render,
)

FAST = settings(
    max_examples=60,
    deadline=None,
    database=None,
    suppress_health_check=list(HealthCheck),
)


def check_valid(spec, cfg: GenConfig) -> None:
    n = spec.n_qubits
    assert cfg.min_qubits <= n <= cfg.max_qubits
    assert cfg.min_ops <= len(spec.ops) <= cfg.max_ops
    allowed = set(cfg.gate_weights())
    for op in spec.ops:
        assert op[0] in allowed
        if op[0] in ("h", "s", "x", "z", "t", "rz", "rx"):
            assert 0 <= op[1] < n
        elif op[0] in ("cz", "cx"):
            assert 0 <= op[1] < n and 0 <= op[2] < n and op[1] != op[2]
        elif op[0] == "bcz":
            qubits = [q for pair in op[1] for q in pair]
            assert len(qubits) == len(set(qubits)), "broadcast layer reuses a qubit"
            assert all(0 <= q < n for q in qubits)
            assert all(c != t for c, t in op[1])
    assert spec.measure == (cfg.measure_mode() == "always")


@pytest.mark.parametrize("mode", ["clifford", "nonclifford"])
def test_specs_satisfy_the_construction_invariants(mode):
    cfg = GenConfig(mode=mode)

    @FAST
    @given(kernel_specs(cfg))
    def run(spec):
        check_valid(spec, cfg)

    run()


@pytest.mark.parametrize("mode", ["clifford", "nonclifford"])
def test_every_generated_kernel_lowers_to_squin(mode):
    cfg = GenConfig(mode=mode, max_ops=8)

    @settings(
        max_examples=25,
        deadline=None,
        database=None,
        suppress_health_check=list(HealthCheck),
    )
    @given(kernel_specs(cfg))
    def run(spec):
        kernel = build_kernel(spec)
        assert kernel.callable_region is not None

    run()


def test_clifford_mode_never_draws_a_non_clifford_gate():
    cfg = GenConfig(mode="clifford", max_qubits=4)

    @FAST
    @given(kernel_specs(cfg))
    def run(spec):
        assert {op[0] for op in spec.ops} <= set(CLIFFORD_GATES)

    run()


def test_non_clifford_mode_does_draw_non_clifford_gates():
    cfg = GenConfig(mode="nonclifford", max_ops=10)
    seen: set[str] = set()

    @settings(
        max_examples=200,
        deadline=None,
        database=None,
        suppress_health_check=list(HealthCheck),
    )
    @given(kernel_specs(cfg))
    def run(spec):
        seen.update(op[0] for op in spec.ops)

    run()
    assert {"t", "rz", "rx"} <= seen <= set(NON_CLIFFORD_GATES)


def test_gate_weights_restrict_the_mix():
    cfg = GenConfig(weights=(("h", 1), ("cz", 1)))

    @FAST
    @given(kernel_specs(cfg))
    def run(spec):
        assert {op[0] for op in spec.ops} <= {"h", "cz"}

    run()


def test_size_parameters_are_honoured():
    cfg = GenConfig(min_qubits=4, max_qubits=4, min_ops=3, max_ops=3)

    @FAST
    @given(kernel_specs(cfg))
    def run(spec):
        assert spec.n_qubits == 4 and len(spec.ops) == 3

    run()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "nonclifford", "max_qubits": 7},
        {"mode": "nonclifford", "measure": "always"},
        {"mode": "clifford", "weights": (("t", 1),)},
        {"min_qubits": 1},
        {"weights": ()},
        {"mode": "bogus"},
    ],
)
def test_invalid_configs_are_rejected(kwargs):
    with pytest.raises(ValueError):
        GenConfig(**kwargs)


def test_render_is_deterministic_and_readable():
    spec = next(iter(_one_spec()))
    assert render(spec) == render(spec)
    assert "squin.qalloc" in render(spec)


def _one_spec():
    out = []

    @settings(
        max_examples=1,
        deadline=None,
        database=None,
        suppress_health_check=list(HealthCheck),
    )
    @given(kernel_specs(GenConfig(min_ops=2)))
    def run(spec):
        out.append(spec)

    run()
    return out
