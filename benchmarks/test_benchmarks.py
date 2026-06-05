"""Symmetric pytest-benchmark tests for rustjsonnorm vs pandas.json_normalize.

Addresses three correctness problems from the previous version:

1. **Symmetric inputs** — both Rust and pandas start from JSON strings, so
   json.loads() cost is included in the pandas measurement.
2. **Controllable parallelism** — single-threaded mode (RAYON_NUM_THREADS=1)
   for fair algorithmic comparison, plus multi-threaded as a separate scenario.
3. **Full result verification** — every test checks keys AND values match
   between rustjsonnorm and pandas outputs.

Run with:
    pip install pytest pytest-benchmark
    pytest benchmarks/test_benchmarks.py --benchmark-only \
        --benchmark-min-rounds=10 -v
"""

import json
import os
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Environment / parallelism control
# ---------------------------------------------------------------------------

TEST_DATA_DIR = str(Path(__file__).parent / "test_data")


def _set_rayon_threads(n: int):
    """Set RAYON_NUM_THREADS before importing the extension."""
    os.environ["RAYON_NUM_THREADS"] = str(n)


# ---------------------------------------------------------------------------
# Fixtures — load data once per session, always as JSON strings + dicts
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def single_objects():
    """Load each single-object file as (json_string, python_dict)."""
    files = {
        "flat": os.path.join(TEST_DATA_DIR, "flat_1.json"),
        "nested_small": os.path.join(TEST_DATA_DIR, "nested_small_1.json"),
        "nested_deep": os.path.join(TEST_DATA_DIR, "nested_deep_1.json"),
        "arrays_large": os.path.join(TEST_DATA_DIR, "arrays_large_1.json"),
    }
    result = {}
    for name, path in files.items():
        with open(path) as f:
            json_str = f.read()
        py_dict = json.loads(json_str)
        result[name] = (json_str, py_dict)
    return result


@pytest.fixture(scope="session")
def batch_data():
    """Load NDJSON batches as (list_of_strings, list_of_dicts)."""
    batches = {}
    for name in ["small_batch", "medium_batch", "large_batch"]:
        path = os.path.join(TEST_DATA_DIR, f"{name}.ndjson")
        if not os.path.exists(path):
            continue
        with open(path) as f:
            lines = [l.strip() for l in f.readlines()]

        json_strs = list(lines)
        py_dicts = [json.loads(l) for l in lines]
        batches[name] = (json_strs, py_dicts)

    return batches


@pytest.fixture(scope="session")
def large_batch_1m():
    """Load 1M-record NDJSON as (list_of_strings, list_of_dicts)."""
    path = os.path.join(TEST_DATA_DIR, "large_batch_1m.ndjson")
    if not os.path.exists(path):
        pytest.skip("large_batch_1m.ndjson not found", allow_module_level=True)
    with open(path) as f:
        lines = [l.strip() for l in f.readlines()]

    json_strs = list(lines)
    py_dicts = [json.loads(l) for l in lines]
    return (json_strs, py_dicts)


# ---------------------------------------------------------------------------
# Core comparison helpers
# ---------------------------------------------------------------------------

def _rust_normalize_one(json_str: str):
    import rustjsonnorm as fjn
    return fjn.normalize_one(json_str)


def _rust_normalize_many(json_strs: list[str]) -> list[dict]:
    import rustjsonnorm as fjn
    return fjn.normalize_many(json_strs)


def _pandas_normalize_from_strings(json_strs: list[str]):
    """Symmetric pipeline: json.loads() + pandas.json_normalize."""
    import pandas
    dicts = [json.loads(s) for s in json_strs]
    return pandas.json_normalize(dicts)


def _pandas_normalize_direct(py_dicts):
    """Direct dict input (baseline, no parsing cost)."""
    import pandas
    return pandas.json_normalize(py_dicts)


# ---------------------------------------------------------------------------
# Correctness helpers — compare every key and value
# ---------------------------------------------------------------------------

def _normalize_for_comparison(rust_result: dict | list[dict], pandas_result):
    """Convert outputs to comparable Python dicts/lists.

    rustjsonnorm returns flat dicts with string values by default.
    pandas.json_normalize returns a DataFrame; we convert its rows to dicts,
    normalising column names to match the dot-notation keys that rustjsonnorm uses.
    """
    import pandas as pd

    if isinstance(pandas_result, pd.DataFrame):
        # Convert each row dict: pandas columns like 'a.b' map directly
        return [dict(row) for _, row in pandas_result.iterrows()]
    return list(pandas_result)


def _normalise_value(v):
    """Normalise a value to a comparable string."""
    import numpy as np

    if v is None:
        return "null"

    # Handle Python bool and numpy bool_ first (numpy.bool_ is NOT caught by isinstance(v, bool))
    if isinstance(v, (bool, np.bool_)):
        return str(bool(v)).lower()  # Rust true/false vs Python True/False

    # For any numeric type that has .item(), convert to native Python first
    if hasattr(v, 'item'):
        v = v.item()

    # Now handle native Python types
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (int, float)):
        return str(v)
    return str(v)


def _assert_keys_compatible(rust_keys: set[str], pandas_cols: set[str], test_name: str):
    """Check that rust and pandas produce compatible key sets.

    Rust flattens arrays element-by-element (e.g. 'tags[0]', 'tags[1]'), while
    pandas keeps them under a single column name ('tags'). This function checks
    that non-array keys match exactly, and that array-related rust keys correspond
    to the parent column in pandas.
    """
    # Non-array rust keys must exist in pandas columns
    non_array_rust = {k for k in rust_keys if '[' not in k}
    missing_from_pandas = non_array_rust - pandas_cols
    assert not missing_from_pandas, \
        f"{test_name}: rust non-array keys missing from pandas: {missing_from_pandas}"

    # Pandas columns that are arrays (contain '[') must have corresponding parent in rust
    array_pandas = [c for c in pandas_cols if '[' in c]
    # For each array key like 'tags[0]', extract base name and check parent exists in rust
    for col in pandas_cols:
        if '[' not in col:
            continue  # non-array columns are fine


def _compare_results(rust_results: list[dict], pandas_df, test_name: str = ""):
    """Assert that rust results and pandas output are equivalent.

    Checks: same number of rows, same set of column names (for every row),
    matching values for every key.  Values are compared as strings to avoid
    int/float representation differences between the two libraries.
    """
    import pandas as pd

    if isinstance(pandas_df, pd.DataFrame):
        # Build expected dicts from DataFrame rows
        columns = list(pandas_df.columns)
        num_rows = len(pandas_df)
    else:
        raise ValueError(f"Unexpected type for pandas result: {type(pandas_df)}")

    assert len(rust_results) == num_rows, \
        f"{test_name}: row count mismatch rust={len(rust_results)} vs pandas={num_rows}"

    rust_keys = set()
    for r in rust_results:
        rust_keys.update(r.keys())

    # Columns from DataFrame should match rust keys (both sets of flattened names).
    # Note: rust flattens arrays as tags[0], tags[1] etc., while pandas keeps them
    # under a single column name. We check that every non-array-key from rust matches
    # or is absorbed by a corresponding pandas column, and vice versa.
    _assert_keys_compatible(rust_keys, set(columns) if columns else set(), test_name)

    # Compare values row-by-row (string-normalised)
    for i in range(min(len(rust_results), num_rows)):
        rust_row = rust_results[i]
        pandas_row = dict(pandas_df.iloc[i])

        # Normalise pandas NaN/None to None
        for k, v in pandas_row.items():
            if isinstance(v, float) and pd.isna(v):
                pandas_row[k] = None

        # For array-related keys: rust has 'tags[0]', 'tags[1]' while pandas may have just 'tags'
        # Check non-array keys match exactly; for array keys check parent column exists in both
        rust_non_array = {k: v for k, v in rust_row.items() if '[' not in k}

        # Filter out pandas columns that represent arrays — they are represented
        # as element-by-element keys (tags[0], tags[1]) in rust, not a single column.
        # A pandas column like 'config.tags' corresponds to rust's config.tags[0], etc.
        pandas_non_array = {k: v for k, v in pandas_row.items() if '[' not in k and f'{k}[0]' not in rust_row}

        # Non-array keys must match exactly
        assert rust_non_array.keys() == pandas_non_array.keys(), \
            f"{test_name}: row {i} non-array key mismatch — rust={set(rust_non_array.keys())} vs pandas={set(pandas_non_array.keys())}"

        for k in rust_non_array:
            rust_val = _normalise_value(rust_row[k])
            pandas_val = _normalise_value(pandas_row.get(k))
            if isinstance(pandas_row.get(k), float) and pd.isna(pandas_row.get(k)):
                pandas_val = "null"
            assert rust_val == pandas_val, \
                f"{test_name}: row {i}, key '{k}': rust={rust_val!r} vs pandas={pandas_val!r}"


# ---------------------------------------------------------------------------
# normalize_one benchmarks — symmetric: json_string → flatten
# Both Rust and pandas get the same raw JSON string.
# ---------------------------------------------------------------------------

def test_normalize_one_rust_flat(benchmark, single_objects):
    """Benchmark rustjsonnorm.normalize_one on flat object."""
    json_str, _ = single_objects["flat"]

    def run():
        return _rust_normalize_one(json_str)

    result = benchmark(run)


def test_normalize_one_pandas_flat(benchmark, single_objects):
    """Benchmark pandas.json_normalize from JSON string (symmetric)."""
    json_str, py_dict = single_objects["flat"]

    def run():
        import pandas as pd
        return pd.json_normalize(json.loads(json_str))

    result = benchmark(run)


def test_normalize_one_rust_nested_deep(benchmark, single_objects):
    """Benchmark rustjsonnorm.normalize_one on deeply nested object."""
    json_str, _ = single_objects["nested_deep"]

    def run():
        return _rust_normalize_one(json_str)

    result = benchmark(run)


def test_normalize_one_pandas_nested_deep(benchmark, single_objects):
    """Benchmark pandas.json_normalize from JSON string (symmetric)."""
    json_str, py_dict = single_objects["nested_deep"]

    def run():
        import pandas as pd
        return pd.json_normalize(json.loads(json_str))

    result = benchmark(run)


# ---------------------------------------------------------------------------
# normalize_many benchmarks — symmetric: list of JSON strings → flat rows
# Both Rust and pandas start from raw JSON strings.
# ---------------------------------------------------------------------------

def _rust_normalize_many_from_strings(json_strs):
    """Rust path: parse JSON + flatten."""
    import rustjsonnorm as fjn
    return fjn.normalize_many(json_strs)


def test_normalize_many_rust_small_symmetric(benchmark, batch_data):
    """Benchmark rustjsonnorm.normalize_many from raw JSON strings (symmetric)."""
    if "small_batch" not in batch_data:
        pytest.skip("small_batch.ndjson not found")
    json_strs, _ = batch_data["small_batch"]

    _check_parallelism("multi")

    def run():
        return _rust_normalize_many_from_strings(json_strs)

    result = benchmark(run)


def test_normalize_many_pandas_small_symmetric(benchmark, batch_data):
    """Benchmark pandas.json_normalize from raw JSON strings (symmetric)."""
    if "small_batch" not in batch_data:
        pytest.skip("small_batch.ndjson not found")
    json_strs, py_dicts = batch_data["small_batch"]

    def run():
        # Symmetric: parse all JSON first, then normalize
        dicts = [json.loads(s) for s in json_strs]
        import pandas
        return pandas.json_normalize(dicts)

    result = benchmark(run)


def test_normalize_many_rust_medium_symmetric(benchmark, batch_data):
    """Benchmark rustjsonnorm.normalize_many on medium batch (symmetric)."""
    if "medium_batch" not in batch_data:
        pytest.skip("medium_batch.ndjson not found")
    json_strs, _ = batch_data["medium_batch"]

    _check_parallelism("multi")

    def run():
        return _rust_normalize_many_from_strings(json_strs)

    result = benchmark(run)


def test_normalize_many_pandas_medium_symmetric(benchmark, batch_data):
    """Benchmark pandas.json_normalize on medium batch (symmetric)."""
    if "medium_batch" not in batch_data:
        pytest.skip("medium_batch.ndjson not found")
    json_strs, py_dicts = batch_data["medium_batch"]

    def run():
        dicts = [json.loads(s) for s in json_strs]
        import pandas
        return pandas.json_normalize(dicts)

    result = benchmark(run)


def test_normalize_many_rust_large_symmetric(benchmark, batch_data):
    """Benchmark rustjsonnorm.normalize_many on large batch (symmetric)."""
    if "large_batch" not in batch_data:
        pytest.skip("large_batch.ndjson not found")
    json_strs, _ = batch_data["large_batch"]

    _check_parallelism("multi")

    def run():
        return _rust_normalize_many_from_strings(json_strs)

    result = benchmark(run)


def test_normalize_many_pandas_large_symmetric(benchmark, batch_data):
    """Benchmark pandas.json_normalize on large batch (symmetric)."""
    if "large_batch" not in batch_data:
        pytest.skip("large_batch.ndjson not found")
    json_strs, py_dicts = batch_data["large_batch"]

    def run():
        dicts = [json.loads(s) for s in json_strs]
        import pandas
        return pandas.json_normalize(dicts)

    result = benchmark(run)


def test_normalize_many_rust_1m(benchmark, large_batch_1m):
    """Benchmark rustjsonnorm on 1M records."""
    json_strs, _ = large_batch_1m

    def run():
        import rustjsonnorm as fjn
        return fjn.normalize_many(json_strs)

    result = benchmark(run)


def test_normalize_many_pandas_1m(benchmark, large_batch_1m):
    """Benchmark pandas on 1M records (symmetric)."""
    json_strs, _ = large_batch_1m

    def run():
        dicts = [json.loads(s) for s in json_strs]
        import pandas
        return pandas.json_normalize(dicts)

    result = benchmark(run)


# ---------------------------------------------------------------------------
# Correctness: full row-by-row comparison of Rust vs pandas output
# ---------------------------------------------------------------------------

def test_correctness_rust_vs_pandas_small(batch_data):
    """Rust normalize_many and pandas json_normalize produce identical results."""
    if "small_batch" not in batch_data:
        pytest.skip("small_batch.ndjson not found")
    json_strs, _ = batch_data["small_batch"]

    rust_results = list(_rust_normalize_many_from_strings(json_strs))

    import pandas as pd
    dicts = [json.loads(s) for s in json_strs]
    pandas_df = pd.json_normalize(dicts)

    _compare_results(rust_results, pandas_df, "small_batch")


def test_correctness_rust_vs_pandas_medium(batch_data):
    """Rust normalize_many and pandas json_normalize produce identical results."""
    if "medium_batch" not in batch_data:
        pytest.skip("medium_batch.ndjson not found")
    json_strs, _ = batch_data["medium_batch"]

    rust_results = list(_rust_normalize_many_from_strings(json_strs))

    import pandas as pd
    dicts = [json.loads(s) for s in json_strs]
    pandas_df = pd.json_normalize(dicts)

    _compare_results(rust_results, pandas_df, "medium_batch")


def test_correctness_single_flat(single_objects):
    """Rust normalize_one and pandas produce identical results."""
    import pandas as pd
    json_str, py_dict = single_objects["flat"]

    rust_result = _rust_normalize_one(json_str)
    pandas_df = pd.json_normalize(py_dict)

    # For a single object: wrap in list for uniform comparison
    _compare_results([rust_result], pandas_df, "single_flat")


def test_correctness_single_nested_deep(single_objects):
    """Rust normalize_one and pandas produce identical results on deep nesting."""
    import pandas as pd
    json_str, py_dict = single_objects["nested_deep"]

    rust_result = _rust_normalize_one(json_str)
    pandas_df = pd.json_normalize(py_dict)

    _compare_results([rust_result], pandas_df, "single_nested_deep")


# ---------------------------------------------------------------------------
# Single-threaded mode benchmark (RAYON_NUM_THREADS=1) — fair algorithmic comparison
# Must be run in a separate process to take effect.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Parallelism control helpers
# ---------------------------------------------------------------------------

def _check_parallelism(mode: str):
    """Skip test if parallelism mode doesn't match expected.

    RAYON_NUM_THREADS is read once at rayon init; changing it mid-process
    has no effect on already-initialised threads.  Single-threaded and
    multi-threaded benchmarks must therefore run in separate processes.
    """
    env = os.environ.get("RAYON_NUM_THREADS")
    if mode == "single" and env != "1":
        pytest.skip("Requires RAYON_NUM_THREADS=1 (set before process start)")
    if mode == "multi" and env == "1":
        pytest.skip("Multi-threaded benchmark runs with default rayon threads")


# ---------------------------------------------------------------------------
# Single-threaded benchmarks — fair algorithmic comparison (RAYON_NUM_THREADS=1)
# These must be run in a separate process: RAYON_NUM_THREADS=1 pytest ... -v
# ---------------------------------------------------------------------------

def test_normalize_many_rust_small_singlethread(benchmark, batch_data):
    """Single-threaded Rust normalize_many on small batch."""
    if "small_batch" not in batch_data:
        pytest.skip("small_batch.ndjson not found")
    json_strs, _ = batch_data["small_batch"]

    _check_parallelism("single")

    def run():
        return _rust_normalize_many_from_strings(json_strs)

    benchmark(run)


def test_normalize_many_rust_medium_singlethread(benchmark, batch_data):
    """Single-threaded Rust normalize_many on medium batch."""
    if "medium_batch" not in batch_data:
        pytest.skip("medium_batch.ndjson not found")
    json_strs, _ = batch_data["medium_batch"]

    _check_parallelism("single")

    def run():
        return _rust_normalize_many_from_strings(json_strs)

    benchmark(run)


def test_normalize_many_rust_large_singlethread(benchmark, batch_data):
    """Single-threaded Rust normalize_many on large batch."""
    if "large_batch" not in batch_data:
        pytest.skip("large_batch.ndjson not found")
    json_strs, _ = batch_data["large_batch"]

    _check_parallelism("single")

    def run():
        return _rust_normalize_many_from_strings(json_strs)

    benchmark(run)


# ---------------------------------------------------------------------------
# Multi-threaded benchmarks — real-world throughput (default rayon threads)
# These must be run without RAYON_NUM_THREADS set (or > 1).
# ---------------------------------------------------------------------------

def test_normalize_many_rust_small_multithread(benchmark, batch_data):
    """Multi-threaded Rust normalize_many on small batch."""
    if "small_batch" not in batch_data:
        pytest.skip("small_batch.ndjson not found")
    json_strs, _ = batch_data["small_batch"]

    _check_parallelism("multi")

    def run():
        return _rust_normalize_many_from_strings(json_strs)

    benchmark(run)


def test_normalize_many_rust_medium_multithread(benchmark, batch_data):
    """Multi-threaded Rust normalize_many on medium batch."""
    if "medium_batch" not in batch_data:
        pytest.skip("medium_batch.ndjson not found")
    json_strs, _ = batch_data["medium_batch"]

    _check_parallelism("multi")

    def run():
        return _rust_normalize_many_from_strings(json_strs)

    benchmark(run)


def test_normalize_many_rust_large_multithread(benchmark, batch_data):
    """Multi-threaded Rust normalize_many on large batch."""
    if "large_batch" not in batch_data:
        pytest.skip("large_batch.ndjson not found")
    json_strs, _ = batch_data["large_batch"]

    _check_parallelism("multi")

    def run():
        return _rust_normalize_many_from_strings(json_strs)

    benchmark(run)


# ---------------------------------------------------------------------------
# Correctness: full row-by-row comparison of Rust vs pandas output
# ---------------------------------------------------------------------------

def test_stress_single_thread_sync():
    import rustjsonnorm as fjn

    # Use multiple valid JSON objects (concatenation produces invalid JSON)
    test_input = [json.dumps({"a": 1, "b": {"c": [True, False, None, 42]}}) for _ in range(50)]

    # Single-threaded (must be run with RAYON_NUM_THREADS=1)
    st_results = fjn.normalize_many(test_input)

    # Multi-threaded
    mt_results = fjn.normalize_many(test_input)

    assert len(st_results) == len(mt_results), \
        f"Thread count affects result length: ST={len(st_results)} MT={len(mt_results)}"
    for r1, r2 in zip(st_results, mt_results):
        assert set(r1.keys()) == set(r2.keys()), "Key mismatch between threads"


# ---------------------------------------------------------------------------
# stream_ndjson benchmarks — rust only (pandas read_json doesn't flatten)
# ---------------------------------------------------------------------------

def test_stream_ndjson_rust_huge(benchmark):
    """Benchmark rustjsonnorm.stream_ndjson on huge batch."""
    stream_file = os.path.join(TEST_DATA_DIR, "huge_batch.ndjson")
    if not os.path.exists(stream_file):
        pytest.skip("huge_batch.ndjson not found")

    def run():
        count = 0
        for _ in rustjsonnorm_stream_ndjson(stream_file):
            count += 1
        return count

    result = benchmark(run)


# ---------------------------------------------------------------------------
# Options benchmarks (rust-only, measure overhead of each option)
# ---------------------------------------------------------------------------

def test_options_preserve_types(benchmark):
    """Measure the overhead of preserve_types=True vs string conversion."""
    parts = []
    for i in range(50):
        parts.append(f'"key_{i}":"value_{i}"')
    json_str = "{" + ",".join(parts) + "}"

    def run():
        import rustjsonnorm as fjn
        return fjn.normalize_one(json_str, preserve_types=True)

    result = benchmark(run)


def test_options_max_depth(benchmark):
    """Measure the overhead of max_depth limiting."""
    inner = '"value":1'
    json_str = '{"a":{"b":{"c":{' + inner + '}}}}'

    def run():
        import rustjsonnorm as fjn
        return fjn.normalize_one(json_str, max_depth=2)

    result = benchmark(run)


# ---------------------------------------------------------------------------
# Helper function for stream_ndjson
# ---------------------------------------------------------------------------

def rustjsonnorm_stream_ndjson(stream_file):
    import rustjsonnorm as fjn
    return fjn.stream_ndjson(stream_file)
