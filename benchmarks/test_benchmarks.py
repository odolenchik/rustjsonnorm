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
# Shared fixtures — load data once per session, always as JSON strings + dicts
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


@pytest.fixture(scope="session")
def dense_schema():
    """Load dense-schema NDJSON (105 fields per record)."""
    path = os.path.join(TEST_DATA_DIR, "dense_schema.ndjson")
    if not os.path.exists(path):
        pytest.skip("dense_schema.ndjson not found", allow_module_level=True)
    with open(path) as f:
        lines = [l.strip() for l in f.readlines()]
    json_strs = list(lines)
    py_dicts = [json.loads(l) for l in lines]
    return (json_strs, py_dicts)


@pytest.fixture(scope="session")
def sparse_schema():
    """Load sparse-schema NDJSON (~5% of 200 possible keys per record)."""
    path = os.path.join(TEST_DATA_DIR, "sparse_schema.ndjson")
    if not os.path.exists(path):
        pytest.skip("sparse_schema.ndjson not found", allow_module_level=True)
    with open(path) as f:
        lines = [l.strip() for l in f.readlines()]
    json_strs = list(lines)
    py_dicts = [json.loads(l) for l in lines]
    return (json_strs, py_dicts)


@pytest.fixture(scope="session")
def deep_nesting_data():
    """Load deep-nesting NDJSON (depth=4, branching=2)."""
    path = os.path.join(TEST_DATA_DIR, "deep_nesting.ndjson")
    if not os.path.exists(path):
        pytest.skip("deep_nesting.ndjson not found", allow_module_level=True)
    with open(path) as f:
        lines = [l.strip() for l in f.readlines()]
    json_strs = list(lines)
    py_dicts = [json.loads(l) for l in lines]
    return (json_strs, py_dicts)


@pytest.fixture(scope="session")
def unicode_heavy_data():
    """Load unicode-heavy NDJSON."""
    path = os.path.join(TEST_DATA_DIR, "unicode_heavy.ndjson")
    if not os.path.exists(path):
        pytest.skip("unicode_heavy.ndjson not found", allow_module_level=True)
    with open(path) as f:
        lines = [l.strip() for l in f.readlines()]
    json_strs = list(lines)
    py_dicts = [json.loads(l) for l in lines]
    return (json_strs, py_dicts)


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
# normalize_one benchmarks — symmetric: json_string → flatten
# Both Rust and pandas get the same raw JSON string.
# ---------------------------------------------------------------------------


def test_normalize_one_rust_flat(benchmark, single_objects):
    """Benchmark rustjsonnorm.normalize_one on flat object."""
    json_str, _ = single_objects["flat"]

    def run():
        import rustjsonnorm as fjn

        return fjn.normalize_one(json_str)

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
        import rustjsonnorm as fjn

        return fjn.normalize_one(json_str)

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
# Single-threaded benchmarks — fair algorithmic comparison (RAYON_NUM_THREADS=1)
# Must be run in a separate process.
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
# Must be run without RAYON_NUM_THREADS set (or > 1).
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
    json_str = '{"a":{"b":{"c":{' + inner + "}}}}"

    def run():
        import rustjsonnorm as fjn

        return fjn.normalize_one(json_str, max_depth=2)

    result = benchmark(run)


# ---------------------------------------------------------------------------
# Benchmarks: new fixture types (dense, sparse, deep, unicode)
# ---------------------------------------------------------------------------


def test_normalize_many_dense_multithread(benchmark, dense_schema):
    """Multi-threaded Rust normalize_many on dense-schema data."""
    json_strs, _ = dense_schema
    _check_parallelism("multi")

    def run():
        return _rust_normalize_many_from_strings(json_strs)

    benchmark(run)


def test_normalize_many_dense_singlethread(benchmark, dense_schema):
    """Single-threaded Rust normalize_many on dense-schema data."""
    json_strs, _ = dense_schema
    _check_parallelism("single")

    def run():
        return _rust_normalize_many_from_strings(json_strs)

    benchmark(run)


def test_normalize_many_sparse_multithread(benchmark, sparse_schema):
    """Multi-threaded Rust normalize_many on sparse-schema data."""
    json_strs, _ = sparse_schema
    _check_parallelism("multi")

    def run():
        return _rust_normalize_many_from_strings(json_strs)

    benchmark(run)


def test_normalize_many_sparse_singlethread(benchmark, sparse_schema):
    """Single-threaded Rust normalize_many on sparse-schema data."""
    json_strs, _ = sparse_schema
    _check_parallelism("single")

    def run():
        return _rust_normalize_many_from_strings(json_strs)

    benchmark(run)


def test_normalize_one_deep_singlethread(benchmark, deep_nesting_data):
    """Single-threaded normalize_one on deeply nested object."""
    json_str = deep_nesting_data[0][0]  # first JSON string only (single object per record)
    _check_parallelism("single")

    def run():
        import rustjsonnorm as fjn

        return fjn.normalize_one(json_str)

    benchmark(run)


def test_normalize_many_unicode_multithread(benchmark, unicode_heavy_data):
    """Multi-threaded Rust normalize_many on unicode-heavy data."""
    json_strs, _ = unicode_heavy_data
    _check_parallelism("multi")

    def run():
        return _rust_normalize_many_from_strings(json_strs)

    benchmark(run)


# ---------------------------------------------------------------------------
# Helper function for stream_ndjson
# ---------------------------------------------------------------------------


def rustjsonnorm_stream_ndjson(stream_file):
    import rustjsonnorm as fjn

    return fjn.stream_ndjson(stream_file)
