# Phase 2a plan: bus-cut completion bound

Branch: `bus-cut-bound` (local, at `4c1446a`). No code changes yet.
All paths are relative to `crates/bloqade-lanes-search/` unless they start with `python/`, `docs/` or `crates/`.

## Answers

### 1. Blocked sites
- **What it is.** `blocked` is a per-solve input, not a spec property. It holds the sites of atoms this solve must not move.
  - Python builds it per CZ solve: `blocked_native = [loc._inner for loc in state.occupied] + spectator_native` (`python/bloqade/lanes/heuristics/physical/movement.py:434-445`).
  - With `block_spectators`, it contains every non-participant qubit plus the atoms outside the circuit.
  - Participants are disjoint from it by construction (`python/bloqade/lanes/analysis/placement/lattice.py:63-65`).
- **Is it static?** It is fixed for the whole solve, and dynamic only between solves.
  - It travels as `SearchContext.blocked: &HashSet<u64>` (`src/primitives/context.rs:27-35`).
  - It is built once in `target_solver.rs:180-181,331-337` and never mutated. It is shared across restarts and the cascade.
  - Occupancy by atoms *inside* the solve changes per node, but that is `config ∪ blocked` and is computed in the generator (`src/generators/heuristic.rs:363-369`). It is never stored in `blocked`.
- **The carved graph.** `ReverseLaneGraph::build` drops every lane that touches a blocked site: `if blocked.contains(&src_enc) || blocked.contains(&dst_enc) { continue; }` (`src/primitives/reverse_lane_graph.rs:72-75`).
  - A blocked target is unreachable, so the bound returns +inf (`weighted_distance.rs:86-91`, test at `:305-312`).
  - Generators never land on a blocked site (`heuristic.rs:447-458`; `exhaustive.rs:201-204`), and replay rejects it (`src/search/verify.rs:98-116`).
- **Why an atom on a blocked site contributes 0.**
  - That atom is absent from the carved graph, so the table cannot answer for it, which is ignorance, not proof (`src/bounds.rs:279-296`).
  - `target_solver.rs:96-106` says nothing forbids a root atom from sitting on a blocked site.
  - Claiming +inf would cut a solvable instance, so the bound certifies no floor (0.0).
  - This never happens in the CZ pipeline, because participants are disjoint from `blocked`.
- **Inconsistency, not in scope.**
  - The heuristic generator allows an atom to leave a blocked source (`heuristic.rs:447-458` checks only `dst`), and `target_solver.rs:1186-1191` tests this.
  - The exhaustive generator (`exhaustive.rs:8-9,201-204`, "never a source (B1)") and replay (`verify.rs:98-116`) reject it.
  - Either way, the new bound treats such an atom exactly as h0 does: it contributes nothing.

### 2. Search unit
- **One solve is one candidate target layout for one CZ stage.** `_cz_placements_rust` loops over candidates and stops at the first `SOLVED` (`movement.py:456-488`).
  - Backwards or mirror search runs inside the same Rust `solve` (`target_solver.rs:202-293`).
- **Config** is `pub struct Config { entries: Vec<(u32, u64)>, cached_hash }`, sorted by qubit (`src/primitives/config.rs:129-135`).
- **Goal.** `AllAtTarget { targets: Vec<(u32, u64)> }` is point-valued, and `exact_targets()` returns `Some` (`src/goals.rs:11-38`, trait at `src/traits.rs:118-133`).
  - Set-valued goals return `None`, so no bound is built for them (`restarts.rs:307-324`).
- **Cost.** `UniformCost::edge_cost = 1.0` per MoveSet, and `lane_weight = 1.0` (`src/cost.rs:25-40`). `g` counts shots (`frontier.rs:808-814`).
- **CSV `max_optimality_gap`** is confirmed to be the widest gap over per-solve gaps (`movement.py:364-379`), with two caveats:
  - It covers **every candidate solve**, not only the winning one (`:469`).
  - A negative gap, meaning an inadmissible bound, dominates: `min` if either value is negative, else `max`.
  - Per-solve gap = `(incumbent - h(root)) / incumbent` (`src/bounds.rs:116-140`).
- **Terminal `gap`** is an aggregate: `100 * (Σ incumbent_cost - Σ root_lower_bound) / Σ incumbent_cost` over measured solves (`python/benchmarks/harness/runner.py:91-113`, sums from `movement.py:344-356`).
  - `certs` = solves with `|gap| <= 1e-9`, over measured solves.
  - `proven` = `Proof.OPTIMAL` count (`Termination::Exhausted{proof:true}`, `src/search/result.rs:141-143`).
  - All three are console-only (`output.py:76-82`).
- **`move_count_events` is not shots.** It counts `move.Move` statements in the compiled program (`runner.py:332-350`). That explains 38 events against cost 19 on adder_4, plausibly move-in plus return moves. Use `cost`/`h_root` for bound analysis.

### 3. phil/class-completion-bound
**Unreachable.**
- `git fetch https://github.com/QuEraComputing/bloqade-lanes phil/class-completion-bound` fails with `fatal: couldn't find remote ref`.
- `git ls-remote` on upstream (854 refs) has no ref containing `class` or `completion`, and the fork has none either.
- Stopping on this item as instructed.

What the in-repo docs say, unverified:
- The branch is unmerged. Commit `aae13ab9` there held `examples/candidate_ranking.rs` (`docs/superpowers/plans/2026-08-18-search-refactor-epics.md:47,831`).
- "Class-bound pruning" was meant to discard target candidates whose class lower bound exceeds the best upper bound (`:925-934`).
- `MaxBound` "can come back from git if the class bound ... needs to be combined with h0" (`:370`).
- The overlap with a required-bus-group bound cannot be judged without the code.

### 4. MaxBound history
- `git log --all -S "MaxBound"` gives 2 commits:
  - `489fe80` (#978) introduced it, inside a squash.
  - **`8beadea` "feat(search)!: land the search-crate refactor (#1089)"** removed it from code (Phillip Weinberg, 2026-09-28).
- **Old impl**, `git show 8beadea^:crates/bloqade-lanes-search/src/bounds.rs:210-268` (saved to `/tmp/phase2/bounds_before_8beadea.rs`):
  - `struct MaxBound<A, B> { a, b }` with private fields.
  - `new(a, b)` does `assert_eq!(a.objective_id(), b.objective_id(), "composed bounds must target the same objective instance")`.
  - It implements `CompletionBound` with `type Obj = A::Obj`, `const TRIVIAL = A::TRIVIAL && B::TRIVIAL`, `objective_id = a.objective_id()`, and `estimate = a.estimate(c).max(b.estimate(c))`.
  - Tests at `:798-855`: takes the larger estimate, composes recursively, and `#[should_panic]` on mismatched instances (uses `WeightedDuration`, still available under `cfg(test)`).
- **Restorable as is: yes.** The current trait (`src/bounds.rs:150-164`) is the old trait minus `as_heuristic`, with the same `Obj`, `TRIVIAL`, `objective_id` and `estimate`. MaxBound never used `as_heuristic`.
  - It needs re-export in `src/lib.rs:42`.
  - Caveat: the refactor deleted it because it had only test callers (dead-code lint, epics doc `:367-371`). Restore it only together with a production caller.

### 5. Multi-zone specs
- **Benchmarked specs:** the Gemini physical (`python/bloqade/lanes/arch/gemini/physical/_physical_spec.json`) and logical (`.../logical/_logical_spec.json`) specs are both 1 zone with 0 zone buses.
- **Specs with more than 1 zone or any zone buses:**

| Spec | Zones | Zone buses |
|---|---|---|
| `examples/arch/full.json` (= `test_utils::full_arch_json`) | 2 | 0 |
| `examples/arch/gemini-logical.json` (not the one the pipeline uses) | 2 | 0 |
| `tests/fixtures/behaviour/arch/two_zone_aligned_site_bus.json` / `test_utils::two_zone_aligned_site_bus_arch_json` | 2 | 0 |
| `tests/fixtures/behaviour/arch/two_zone_bus.json` / `test_utils::two_zone_bus_arch_json` | 2 | 1 |
| `tests/fixtures/behaviour/arch/two_zone_grid.json` / `test_utils::storage_gate_arch_json` | 2 | 1 |
| `python/bloqade/lanes/arch/gemini_full/spec.py`, `generic_full/spec.py` (ArchBlueprint) | 3 | >0 (count not computed) |
| `python/tests/bytecode/test_zone_bus_search.py:30-53` (inline) | 2 | 1 |

- About 60 other Python test files match a `zones` grep but were not opened.
- **Why this matters:** the zone-bus and two-zone fixtures are where per-zone groups exist. They are the best unit-test arches for "required group" cases.

### 6. Admissibility harness
- **Fixture.** `src/bounds.rs` `mod tests` (`:437`) uses `make_index()` = `test_utils::example_arch_json` (2 words, 10 sites, 1 zone; `:474-477`).
- **Brute force.** `ExhaustiveGenerator` + `BfsFrontier`, budget 60k, `SeedPolicy::Any` (`:740-804`). BFS under uniform cost is exact when it completes.
  - `h0_is_exact_for_a_single_atom` (`:825`).
  - `h0_never_exceeds_brute_force_optimum_on_tiny_instances` (`:850`): 6 instances, 1-3 atoms, one blocked site; requires at least 4 verified.
  - `..._on_randomized_instances` (`:919`): seed `0xB01E_5EED`, 24 instances; requires at least 18 verified.
- **Contract.** `assert_objective_contract` (`:331`, `cfg(any(test, feature = "test-util"))`). It checks C2, C3, C4 (min shot cost) and C5 (filler-lane monotonicity). Tests are at `:489-591`.
- **Public API.** `tests/public_bound_api.rs` (`:231,277,341,442`).
- **Golden.** `tests/behaviour/cases.rs` `bound_cases()` (`:999`) and the cascade-gate cases (`:1335-1416`); golden file at `tests/fixtures/behaviour/golden.txt`.
- **Commands:**
  ```
  cargo test -p bloqade-lanes-search --lib bounds::tests
  cargo test -p bloqade-lanes-search --lib h0_
  cargo test -p bloqade-lanes-search --test public_bound_api
  cargo test -p bloqade-lanes-search --test behaviour
  BEHAVIOUR_BLESS=1 cargo test -p bloqade-lanes-search --test behaviour   # only for an intended change
  just test-rust
  just bench-search bound
  ```

## Soundness review of the proposed design (UniformCost)

**Definitions.**
- **Graph `H`:** the carved lane graph, i.e. the same graph `WeightedDistanceTable` uses, with blocked endpoints removed.
- **Group:** `(zone, bus, move_type, direction)`. This is exactly the `check_lane_group_consistency` key (`crates/bloqade-lanes-bytecode-core/src/arch/query.rs:742-778`). There are 44 groups on the Gemini physical spec.
- **Unresolved atom:** `i` with `loc_i != t_i`, where `loc_i` is in `H`. Atoms on blocked sites are skipped, as in h0.

**Fact used everywhere.** Any completion moves atom `i` along a walk in `H`, so the lane graph over-approximates real moves.
- Occupancy and collision rules only remove moves, never add them.
- Each shot uses exactly one group (Phase 1, item d).
- An atom takes at most one lane per shot (`src/bounds.rs:201-203`).

**(A) `h_cut = |R|`: sound.**
- `G` is required for `i` if `t_i` is unreachable from `loc_i` in `H \ G`.
- Then every walk of `i` uses a lane of `G`, so the completion contains at least one shot of `G`.
- Taking `R = ∪ required groups`, the completion has a distinct shot for each group in `R`, because one shot means one group. So cost ≥ |R|.

**(B) `h_i = d_i + |R \ U_i|`: sound, provided `U_i` is defined exactly as written.**
- `U_i` is every group with a lane `u → v` such that `u` is reachable from `loc_i` and `t_i` is reachable from `v` in `H`.
- The `d_i ≥ hop distance` shots that move `i` all use groups in `U_i`.
- Each `G ∈ R \ U_i` needs a shot of `G`, and that shot cannot move `i`, since `i` never uses `G`. So the shots are distinct, and cost ≥ d_i + |R \ U_i|.
- **Unsound variants to avoid:**
  - Restricting `U_i` to shortest paths. An optimal completion may detour `i` through some `G ∈ R`, and that shot would then be counted twice.
  - Computing `U_i` or `R` on a graph that is *smaller* than what the generators allow, for example by also carving dynamic occupancy.

**(C) `max(h0, h)` via MaxBound: sound, but partly redundant.**
- Under UniformCost, h0 = `max_i d_i` (`lane_weight = 1`, and `WeightedDistanceTable` is BFS). This is dominated by `max_i h_i`.
- `|R|` is **not** dominated by `max_i h_i`: atom `i` may be able to use groups that are required by others.
- So the tightest sound form is `h = max(|R|, max_i (d_i + |R \ U_i|))`. Write it as `MaxBound(h0, BusCutBound)` with BusCutBound returning `max(|R|, max_i h_i)`. h0 then only adds the infeasibility handling that BusCutBound must mirror anyway.
- **Recommendation:** have BusCutBound own `d_i` by reusing `WeightedDistanceTable`, and not restore MaxBound unless you want `max(h0, ·)` for the other objective (`WeightedDuration`).
  - With `WeightedDuration`, the `d_i` term is not shot-counting, and `|R|` must be scaled by `min_shot_cost`.
  - **Scope this to UniformCost only.** Assert `objective.id().kind == "uniform"`, or require `Obj = UniformCost` in the type.

**(D) Infeasibility and blocked handling: must match h0 exactly.**
- Return +inf when a targeted qubit is missing, or when `loc_i` is unblocked and `t_i` is unreachable.
- Skip an atom on a blocked site: no `d_i`, no required groups, no `h_i` term. That is sound, because it is a subset of the atoms.
- Resolved atoms contribute nothing, even if an optimal plan moves them aside. This is still a lower bound.

**(E) Consistency: needed, and it holds.**
- The cascade A* driver uses a closed set without re-opening (`src/drivers/frontier.rs:721-741,868-870`). An admissible but inconsistent `h` could therefore lose optimality there, so consistency must hold.
- **`|R|`:** after a shot of group `G`, the walks from an atom's new location are suffixes of walks from its old one. So every required group except `G` stays required. `|R|` drops by at most 1, which is the shot cost.
- **`d_i + |R \ U_i|`:** reachable sets only shrink, so `U_i` only shrinks and `R \ U_i` loses at most `G`.
  - If `i` moved via `G`, then `G ∈ U_i`: `d_i` drops by at most 1, and `|R \ U_i|` does not drop.
  - If `i` did not move, `d_i` is unchanged and `|R \ U_i|` drops by at most 1.
- So `h(parent) ≤ 1 + h(child)`. Add a test for this.

**(F) Precompute and lookups: fine.** Per solve, for each unique target `t` and group `G` (2 bitsets over locations of `H`):
- `NoG[t][G]` = sources that reach `t` in `H \ G`. Reverse BFS from `t` skipping `G`'s lanes.
- `Uses[t][G]` = sources with a walk to `t` that uses `G`.
  - First, `A = { u : u→v ∈ G, v ∈ Reach[t] }`.
  - Then, `Uses[t][G]` = reverse-reachable set of `A` in `H`.
- `required(i, G)` ⇔ `loc_i ∈ Reach[t_i] \ NoG[t_i][G]`; `G ∈ U_i` ⇔ `loc_i ∈ Uses[t_i][G]`.
- `estimate()` is then `O(atoms × groups)` bit lookups, with `R` as a 64-bit mask (44 groups ≤ 64; fall back to a `Vec<u64>` mask if more).
- **Cost (physical):** about 160 locations, 1,120 lanes, 44 groups.
  - Building is `targets × groups × O(lanes)` ≈ 70 × 44 × 1,120 ≈ 3.5M edge visits per solve, at large k.
  - Memory ≈ targets × 44 × 2 × 24 B.
  - That is not free per candidate solve. Measure the wall time.

**Expected payoff: uncertain, so state it up front.**
- On single-zone Gemini, word buses offer several routes between words. Many targets may have no required group except a direction or site-bus bottleneck.
- `|R \ U_i|` gains only when atoms need disjoint group sets.
- Suggest a one-off read-only diagnostic before or alongside the implementation: at each root, log `h0`, `|R|` and `max_i h_i`. If `max(|R|, h) == h0` on almost all roots, the bound will not move gaps.

## Final bound
```
h(c) = +inf                                  if any target qubit missing, or unblocked loc_i with t_i unreachable in H
h(c) = max( |R|, max_{i unresolved, loc_i ∉ blocked} ( d_i + |R \ U_i| ) )   otherwise (0 if no unresolved atoms)
R    = ∪_i { G : loc_i ∈ Reach[t_i] \ NoG[t_i][G] }
d_i  = hop distance in H (= WeightedDistanceTable under UniformCost)
U_i  = { G : loc_i ∈ Uses[t_i][G] }
```
**Soundness, in short:**
- Each completion moves `i` along a walk in `H`, and each shot uses exactly one group.
- Required groups therefore force at least `|R|` distinct shots.
- `i`'s own `d_i` shots use only `U_i` groups, so they are disjoint from the shots that the groups in `R \ U_i` force.
- It is consistent by (E). It dominates h0 under UniformCost.

## Files to touch
- `src/bounds.rs`: add `BusCutBound` (UniformCost-only) and its precompute. Optionally restore `MaxBound` from `8beadea^`, only if wired.
- `src/lib.rs:42`: re-export.
- `src/search/options.rs` (`BoundKind`): add a `BusCut` variant (the current one is `WeightedDistance`).
- `src/search/restarts.rs:319-325` (entropy) and `:441-447` (cascade A*): add match arms that construct the new bound. These are monomorphised arms, as now (`:368-393`).
- Probably a group-key helper on `LaneIndex` (`src/primitives/lane_index.rs:473` `bus_groups()` already exists, so reuse it).
- **Python binding / strategy registry** (`crates/bloqade-lanes-bytecode-python/src/search_python.rs`, `python/bloqade/lanes/heuristics/physical/movement.py:146-152`, `python/benchmarks` registry): needed to select the bound from Python, for example a `rust_cascade_ids_buscut` strategy row. **This changes the benchmark CSVs. A new row means regenerating both baselines.**
- `tests/behaviour/cases.rs` + golden: add cases, and bless only the new ones.

## Tests
1. **Unit (`bounds.rs`)**
   - Zero when resolved.
   - +inf for a missing qubit or an unreachable target.
   - Blocked-source atom skipped.
   - A hand-built required-group case: `|R| = 2` where h0 = 1, on `two_zone_bus` / `storage_gate` / `non_separable_bus` fixtures.
   - The `R \ U_i` case.
   - Never below h0.
2. **Single-atom exactness:** for one atom, `h == d_i` (since `R ⊆ U_i` for a single atom, `h = max(|R|, d_i) = d_i`). Assert equality with brute force on the existing 4 pairs.
3. **Admissibility vs exhaustive:** reuse the `bounds.rs` brute-force harness and assert `h ≤ BFS optimum` on:
   - the tiny and randomized suites (same verified-count floors);
   - new randomized suites on `two_zone_bus`, `storage_gate`, `two_zone_aligned_site_bus`, `non_separable_bus` and `chain_with_siding`;
   - also assert `h ≥ h0` on every instance.
4. **Consistency:** on random instances, for each generated child, `h(parent) ≤ 1 + h(child)`.
5. **Contract C1-C3:** `assert_objective_contract(&UniformCost, ...)` (already exists). Add a test that constructing BusCutBound with `WeightedDuration` is rejected, by panic or by compile-time type.
6. **Public API / driver:** extend `tests/public_bound_api.rs` `entropy_search_solves_for_every_public_bound` and the at-most-once-per-node test to cover the new bound.
7. **Behaviour net:** new `bound/buscut/*` cases. The existing golden must not move.

## Measurement
Run `rust_cascade_ids` (h0) against `rust_cascade_ids_buscut` (`max(|R|, h)`) on physical and logical. Per case:
- root gap (terminal aggregate `(Σcost - Σh_root)/Σcost`);
- per-solve max gap (CSV `max_optimality_gap`);
- certificates (`certs`) and `proven` (`Proof.OPTIMAL`) counts;
- `cuts_by_g`, `cuts_by_h`, `cuts_infeasible`;
- `nodes_explored`, `move_count_events`, `cost` (must not get worse);
- wall time, split into bound-precompute time and search time, on the same machine, 3 runs, median;
- diagnostic: the fraction of roots where `|R| > h0` or `max_i h_i > h0`.

**Acceptance:**
- No negative gap anywhere.
- `success` is unchanged.
- The h0 rows are byte-identical to baseline, which shows the existing path is untouched.
