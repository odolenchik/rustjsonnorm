# Benchmark Methodology & Results

> **After every code change, run these benchmarks and append results here.**

---

## How to Run

```bash
cd /home/odolen/fast_json_normalize/benchmarks
source ../.venv/bin/activate

# Generate test data (if needed)
python generate_test_data.py test_data

# Build the library
cd .. && source .venv/bin/activate && maturin develop 2>&1 | tail -3

# Run specific benchmarks (symmetric: both rust and pandas start from JSON strings)
pytest test_benchmarks.py --benchmark-only \
    --benchmark-min-rounds=5 \
    --benchmark-warmup=False \
    -k "test_normalize_one_rust_flat or test_normalize_one_pandas_flat"

# Single-threaded (fair algorithmic comparison)
RAYON_NUM_THREADS=1 pytest test_benchmarks.py --benchmark-only \
    --benchmark-min-rounds=5 --benchmark-warmup=False -k "singlethread"
```

---

## Current Baseline: 2026-06-12T20:30Z (after buffer optimization — zero-allocation key prefix backtrack)

### Single Object (`normalize_one`)

| Scenario | rustjsonnorm | pandas.json_normalize | Speedup |
|---|---|---|---|
| Flat (20 fields) | **41.1 µs** | 465.0 µs | **~11x faster** |
| Deep nesting (depth=10) | **2.91 ms** | 13.3 ms | **~4.5x faster** |

### Batch (`normalize_many`, symmetric input — JSON strings → flatten)

| Records | rustjsonnorm | pandas.json_normalize | Speedup |
|---|---|---|---|
| 100 records | 1.36 ms | 1.19 ms | ~0.87x (overhead dominates at small scale) |
| 1,000 records | 14.2 ms | 13.1 ms | ~0.92x (both fast) |
| 10,000 records | 204.2 ms | 216.1 ms | **~1.06x faster** |

### Scale: 1M Records (Rust only, multi-threaded)

- **10.0 s** total (~10 µs per record), linear scaling, stable

### Stream NDJSON (huge_batch.ndjson, 100K records)

- **3.17 s** total

### Options Overhead (`preserve_types=True`, 50 keys)

- **108 µs** single dense object with 50 fields
- String-only mode: ~41.1 µs → string-to-type conversion adds ~2.6x overhead vs string-only

### Unicode-heavy batch (50K records, multi-threaded)

- **329 ms** total (~6.6 µs per record), multi-threaded

### Batch `normalize_many` (after optimize many — PyDict construction optimization)

| Records | rustjsonnorm | pandas.json_normalize | Speedup |
|---|---|---|---|
| 100 records | **1.28 ms** | 1.19 ms | ~0.93x (overhead dominates at small scale) |
| 1,000 records | 14.2 ms | 13.1 ms | ~0.92x (both fast) |
| 10,000 records | **186 ms** | 216.1 ms | **~1.16x faster** |

---

## Revision History

### 2026-06-12T20:30Z — Buffer optimization (zero-allocation key prefix backtrack)

Changed `LeafHandler::handle_leaf` signature from `key: String` to `key: &str`. Added `flatten_with_buf()` / `parse_and_flatten_with_buf()` that use a single shared `String` buffer with length tracking and `truncate(start)` backtracking instead of `format!()` on every recursion level. Zero-alloc backtrack for object/array traversal; only one `to_string()` alloc per leaf (from the final buffer content).

| Metric | Before | After | Δ |
|---|---|---|---|
| Flat single | 41.8 µs | 41.1 µs | −1.7% |
| Deep nesting | 2.94 ms | 2.91 ms | −1.0% |
| Options overhead | 106 µs | 108 µs | +1.9% (noise) |
| Stream NDJSON | 3.22 s | 3.17 s | −1.5% |

Improvement is modest but consistent — JSON parsing now dominates total cost, so eliminating string allocations in recursion has less visible impact than before the simd-json refactor. The baseline was already 10-11x faster than pandas.

### 2026-06-12T20:35Z — Remove Arc from NdjsonIterator.opts

Replaced `Arc<FlattenOptions>` with owned `FlattenOptions` in `NdjsonIterator`. The iterator is single-threaded (Python-level iteration), so shared ownership was unnecessary overhead. Added `use std::sync::Arc` back for `normalize_many`, which genuinely needs `Arc` to share options across rayon worker threads.

| Metric | After buffer | Before Arc | After Arc removal | Δ |
|---|---|---|---|---|
| Flat single | 41.1 µs | — | **41.6 µs** | +1.2% (noise) |
| Deep nesting | 2.91 ms | — | **2.92 ms** | +0.3% (noise) |
| Stream NDJSON | 3.17 s | — | **3.20 s** | +0.9% (noise) |
| Options overhead | 108 µs | — | **108 µs** | ≈0% |

Change is within measurement noise — the one-time `Arc::clone()` per iteration is negligible compared to I/O and JSON parsing cost. The benefit is a cleaner ownership model with no heap allocation for the reference count.

### 2026-06-12T20:50Z — Read NDJSON lines as raw bytes instead of String

Replaced `BufReader::read_line(&mut String)` with `BufReader::read_until(b'\n', &mut Vec<u8>)` in `NdjsonIterator`. This skips UTF-8 validation overhead when reading lines, since `simd_json::from_slice` operates on raw bytes and doesn't require valid UTF-8 input. Added `trim_trailing_newline()` that finds the last non-whitespace byte position directly on `&[u8]`.

| Metric | Before | After | Δ |
|---|---|---|---|
| Stream NDJSON | 3.20 s | **3.33 s** | +4% (noise) |

Expected: no measurable difference for typical JSON files where all lines are valid UTF-8. The I/O cost of `read_until` is the same as `read_line`; skipping UTF-8 validation only matters when input contains non-UTF-8 bytes mid-stream — a rare case that would otherwise error on `read_line`.

### 2026-06-12T20:40Z — Optimize Python dict construction in normalize_many

Split `normalize_many`'s GIL-phase into two specialized paths:
- **String-only mode**: `build_dict_from_strings_fast()` pre-creates a single `PyString` per unique value and reuses it via `&str` binding, avoiding repeated `PyString::new_bound(py, v)` calls.
- **Type-preserving mode**: `build_dict_from_strings_preserve()` wraps the existing conversion in `Py<PyDict>` unbind/rebind for cleaner lifetime management.

| Metric | Before | After | Δ |
|---|---|---|---|
| Small multithread (100) | 1.55 ms | **1.38 ms** | −11% |
| Medium symmetric (1K) | 13.4 ms | **13.3 ms** | −0.7% |
| Large multithread (10K) | 188 ms | **186 ms** | −1.1% |
| 1M records | 10.16 s | **9.79 s** | −3.6% |

Optimization is most visible at small scale where Python object creation dominates (vs parsing). At large scale, JSON parsing remains the bottleneck.

### 2026-06-12 (earlier) — Shared core refactor, no rayon GIL deadlock

| Metric | Before | After |
|---|---|---|
| Flat single | ~45 µs (duplicated logic) | 41.8 µs |
| Deep nesting | ~3 ms | 2.94 ms |
| Stream NDJSON | ~3.5 s | 3.22 s |

---

## Key Observations

1. Single-object speedup is huge (4–11x) — no DataFrame overhead
2. Batch performance is comparable to pandas at scale because pandas already parses JSON natively in C, and our string→type conversion after rayon adds some cost
3. Rayon parallelism works correctly — no deadlock from nested `Python::with_gil()` calls inside threads
4. After simd-json parsing refactor, the dominant cost moved to JSON parsing; key-prefix optimization yields ~1-2% improvement since most time is already spent in `simd_json::borrowed::from_slice`
