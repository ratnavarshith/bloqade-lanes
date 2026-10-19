# Phase 1 report
main = 4c1446a08d7f90e2119a089fe8300c5bec89b7e5 (feat(python): add get_used_buses bus-usage metric (#1104))
env: uv sync --locked --dev --extra sim

a. Logical suite vs latest_logical.csv: "no differences found", exit 0.
b. Physical rust_cascade_ids: all 9 cases, all deterministic columns identical to baseline (0 diffs).
   steane_physical_35 fails in both (place.CZ statements remain).
c. Bounds: see chat report. MaxBound: not in code (0 hits in crates/); deleted per plan 2026-08-18-search-refactor-epics.md:367-371.
d. Confirmed: check_lane_group_consistency (query.rs:742) enforces zone_id, bus_id, move_type, direction on every multi-lane MoveSet.
e. Gemini physical: 1 zone, 3 site buses, 19 word buses, 0 zone buses -> 22 buses, 44 (bus, direction) groups.
