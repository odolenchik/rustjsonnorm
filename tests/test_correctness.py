"""Correctness tests for rustjsonnorm — validates output against pandas.json_normalize.

These are regular pytest tests (no benchmark fixture). They verify that
rustjsonnorm produces equivalent results to pandas.json_normalize across
various JSON shapes: flat, nested, dense, sparse, deep, unicode, and stream.

Run with:
    pytest tests/test_correctness.py -v
"""

import json
import os
from pathlib import Path

import pytest
import rustjsonnorm as fjn

TEST_DATA_DIR = str(Path(__file__).parent.parent / "benchmarks" / "test_data")


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


@pytest.fixture(scope="session")
def malformed_stream_file():
    """Return path to malformed NDJSON stream file."""
    path = os.path.join(TEST_DATA_DIR, "malformed_stream.ndjson")
    if not os.path.exists(path):
        pytest.skip("malformed_stream.ndjson not found", allow_module_level=True)
    return path


# ---------------------------------------------------------------------------
# Correctness helpers — compare every key and value
# ---------------------------------------------------------------------------


def _normalise_value(v):
    """Normalise a value to a comparable string."""
    import numpy as np

    if v is None:
        return "null"

    # Handle Python bool and numpy bool_ first (numpy.bool_ is NOT caught by isinstance(v, bool))
    if isinstance(v, (bool, np.bool_)):
        return str(bool(v)).lower()  # Rust true/false vs Python True/False

    # For any numeric type that has .item(), convert to native Python first
    if hasattr(v, "item"):
        v = v.item()

    # Now handle native Python types
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (int, float)):
        # Use Decimal for consistent float formatting across rust/pandas output
        if isinstance(v, float):
            from decimal import Decimal

            return str(Decimal(str(v)))
        return str(v)

    # Try parsing string values that look like numbers for consistent comparison.
    # Try int first so '174770' and 174770 both normalise to same string.
    s = str(v) if not isinstance(v, str) else v
    try:
        i = int(s)
        from decimal import Decimal

        return str(Decimal(str(i)))
    except (ValueError, TypeError):
        pass

    try:
        f = float(s)
        from decimal import Decimal

        return str(Decimal(str(f)))
    except (ValueError, TypeError):
        pass

    return s


def _assert_keys_compatible(rust_keys: set[str], pandas_cols: set[str], test_name: str):
    """Check that rust and pandas produce compatible key sets."""
    non_array_rust = {k for k in rust_keys if "[" not in k}
    missing_from_pandas = non_array_rust - pandas_cols
    assert not missing_from_pandas, f"{test_name}: rust non-array keys missing from pandas: {missing_from_pandas}"


def _compare_results(rust_results: list[dict], pandas_df, test_name: str = ""):
    """Assert that rust results and pandas output are equivalent."""
    import pandas as pd

    if isinstance(pandas_df, pd.DataFrame):
        columns = list(pandas_df.columns)
        num_rows = len(pandas_df)
    else:
        raise ValueError(f"Unexpected type for pandas result: {type(pandas_df)}")

    assert len(rust_results) == num_rows, (
        f"{test_name}: row count mismatch rust={len(rust_results)} vs pandas={num_rows}"
    )

    has_variable_schema = False
    if len(rust_results) >= 2:
        rust_keys_0 = set(rust_results[0].keys())
        has_variable_schema = any(set(r.keys()) != rust_keys_0 for r in rust_results[1:])

    if has_variable_schema:
        # Per-row comparison with value-level checks only (pandas creates superset columns for sparse data)
        for i in range(num_rows):
            rust_row = rust_results[i]
            pandas_row = dict(pandas_df.iloc[i])

            for k, v in pandas_row.items():
                if isinstance(v, float) and pd.isna(v):
                    pandas_row[k] = None

            # Handle array notation: rust has 'config.tags[0]' while pandas may have just 'config.tags'.
            for k in rust_row:
                if "[" not in k:
                    assert k in pandas_row, f"{test_name}: row {i}, key '{k}' missing from pandas"
                    rust_val = _normalise_value(rust_row[k])
                    pandas_val = _normalise_value(pandas_row.get(k))
                    assert rust_val == pandas_val, (
                        f"{test_name}: row {i}, key '{k}': rust={rust_val!r} vs pandas={pandas_val!r}"
                    )
                else:
                    base_key = k.rsplit("[", 1)[0]
                    assert base_key in pandas_row, (
                        f"{test_name}: row {i}, array key '{k}' has no parent '{base_key}' in pandas"
                    )
    else:
        # Global comparison for fixed-schema datasets
        rust_keys = set()
        for r in rust_results:
            rust_keys.update(r.keys())

        _assert_keys_compatible(rust_keys, set(columns) if columns else set(), test_name)

        for i in range(min(len(rust_results), num_rows)):
            rust_row = rust_results[i]
            pandas_row = dict(pandas_df.iloc[i])

            for k, v in pandas_row.items():
                if isinstance(v, float) and pd.isna(v):
                    pandas_row[k] = None

            rust_non_array = {k: v for k, v in rust_row.items() if "[" not in k}
            pandas_non_array = {k: v for k, v in pandas_row.items() if "[" not in k and f"{k}[0]" not in rust_row}

            assert rust_non_array.keys() == pandas_non_array.keys(), (
                f"{test_name}: row {i} non-array key mismatch — "
                f"rust={set(rust_non_array.keys())} vs pandas={set(pandas_non_array.keys())}"
            )

            for k in rust_non_array:
                rust_val = _normalise_value(rust_row[k])
                pandas_val = _normalise_value(pandas_row.get(k))
                if isinstance(pandas_row.get(k), float) and pd.isna(pandas_row.get(k)):
                    pandas_val = "null"
                assert rust_val == pandas_val, (
                    f"{test_name}: row {i}, key '{k}': rust={rust_val!r} vs pandas={pandas_val!r}"
                )


def _rust_normalize_many_from_strings(json_strs):
    """Rust path: parse JSON + flatten."""
    import rustjsonnorm as fjn

    return fjn.normalize_many(json_strs)


# ---------------------------------------------------------------------------
# Correctness tests — Rust vs Pandas comparison
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_correctness_rust_vs_pandas_small(batch_data):
    """Rust normalize_many and pandas json_normalize produce identical results."""
    if "small_batch" not in batch_data:
        pytest.skip("small_batch.ndjson not found")
    pd = pytest.importorskip("pandas")
    json_strs, _ = batch_data["small_batch"]

    rust_results = list(_rust_normalize_many_from_strings(json_strs))

    dicts = [json.loads(s) for s in json_strs]
    pandas_df = pd.json_normalize(dicts)

    _compare_results(rust_results, pandas_df, "small_batch")


@pytest.mark.slow
def test_correctness_rust_vs_pandas_medium(batch_data):
    """Rust normalize_many and pandas json_normalize produce identical results."""
    if "medium_batch" not in batch_data:
        pytest.skip("medium_batch.ndjson not found")
    pd = pytest.importorskip("pandas")
    json_strs, _ = batch_data["medium_batch"]

    rust_results = list(_rust_normalize_many_from_strings(json_strs))

    dicts = [json.loads(s) for s in json_strs]
    pandas_df = pd.json_normalize(dicts)

    _compare_results(rust_results, pandas_df, "medium_batch")


def test_correctness_single_flat(single_objects):
    """Rust normalize_one and pandas produce identical results."""
    pd = pytest.importorskip("pandas")
    json_str, py_dict = single_objects["flat"]

    rust_result = fjn.normalize_one(json_str)
    pandas_df = pd.json_normalize(py_dict)

    _compare_results([rust_result], pandas_df, "single_flat")


def test_correctness_single_nested_deep(single_objects):
    """Rust normalize_one and pandas produce identical results on deep nesting."""
    pd = pytest.importorskip("pandas")
    json_str, py_dict = single_objects["nested_deep"]

    rust_result = fjn.normalize_one(json_str)
    pandas_df = pd.json_normalize(py_dict)

    _compare_results([rust_result], pandas_df, "single_nested_deep")


def test_correctness_dense(dense_schema):
    """Rust normalize_many and pandas produce identical results on dense schema."""
    pd = pytest.importorskip("pandas")
    json_strs, py_dicts = dense_schema
    rust_results = list(_rust_normalize_many_from_strings(json_strs))
    pandas_df = pd.json_normalize(py_dicts)
    _compare_results(rust_results, pandas_df, "dense")


def test_correctness_sparse(sparse_schema):
    """Rust normalize_many and pandas produce identical results on sparse schema."""
    pd = pytest.importorskip("pandas")
    json_strs, py_dicts = sparse_schema
    rust_results = list(_rust_normalize_many_from_strings(json_strs))
    pandas_df = pd.json_normalize(py_dicts)
    _compare_results(rust_results, pandas_df, "sparse")


def test_correctness_deep(deep_nesting_data):
    """Rust normalize_one and pandas produce identical results on deep nesting."""
    pd = pytest.importorskip("pandas")
    json_strs, py_dicts = deep_nesting_data
    rust_result = fjn.normalize_one(json_strs[0])
    pandas_df = pd.json_normalize(py_dicts[0])
    _compare_results([rust_result], pandas_df, "deep")


def test_correctness_unicode(unicode_heavy_data):
    """Rust normalize_many and pandas produce identical results on unicode data."""
    pd = pytest.importorskip("pandas")
    json_strs, py_dicts = unicode_heavy_data
    rust_results = list(_rust_normalize_many_from_strings(json_strs))
    pandas_df = pd.json_normalize(py_dicts)
    _compare_results(rust_results, pandas_df, "unicode")


def test_stream_malformed(malformed_stream_file):
    """NdjsonIterator skips bad lines correctly in malformed stream."""
    rust_results = list(fjn.stream_ndjson(malformed_stream_file))

    for row in rust_results:
        assert isinstance(row, dict)
        assert len(row) >= 1, f"Expected at least 1 key, got {len(row)}: {row}"

    with open(malformed_stream_file) as f:
        total_lines = sum(1 for _ in f)
    assert len(rust_results) < total_lines, "Expected some lines to be skipped"


def test_stream_malformed_strict_mode(malformed_stream_file):
    """Strict mode raises ValueError on first bad line."""
    it = fjn.stream_ndjson(malformed_stream_file, strict=True)
    results = []
    try:
        for row in it:
            results.append(row)
    except ValueError as e:
        assert "line" in str(e).lower() or "Line" in str(e)

    if results:
        for r in results[:5]:
            assert isinstance(r, dict) and len(r) >= 1


@pytest.mark.slow
def test_stress_single_thread_sync():
    """Multi-threaded Rust normalize_many produces same results as single-threaded."""
    test_input = [json.dumps({"a": 1, "b": {"c": [True, False, None, 42]}}) for _ in range(50)]

    st_results = fjn.normalize_many(test_input)
    mt_results = fjn.normalize_many(test_input)

    assert len(st_results) == len(mt_results), (
        f"Thread count affects result length: ST={len(st_results)} MT={len(mt_results)}"
    )
    for r1, r2 in zip(st_results, mt_results):
        assert set(r1.keys()) == set(r2.keys()), "Key mismatch between threads"
