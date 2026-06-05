# Tests — full documentation

## Test organization

| File | Purpose | Number of tests |
|---|---|---|
| `test_flatten.py` | Unit tests: flatten correctness, types, options, streaming | ~50 |
| `test_correctness.py` | Compare rustjsonnorm output against pandas.json_normalize on real data | ~18 |

Run all tests via pytest:

```bash
pytest tests/ -v
```

To run specific suites:

```bash
pytest tests/test_flatten.py -v          # unit tests
pytest tests/test_correctness.py -v      # pandas comparison
```

---

## test_flatten.py — Unit tests

Tests cover three function groups: `normalize_one`, `normalize_many`, `stream_ndjson`.

### Single object (normalize_one)

| Test | What it checks |
|---|---|
| `test_empty_object` | `{}` → empty dict, no errors |
| `test_empty_array` | `{"a": []}` → empty dict; empty arrays produce no keys |
| `test_deep_nesting_respects_max_depth` | Deep nesting (`"a":{"b":{"c":{"d":{"e":"deep"}}}}`) correctly stops at `max_depth=3` — key `a.b.c` absent from result |
| `test_key_with_separator_collision` | Key containing a dot (`"a.b": 1`) is not treated as nested path — with `sep="."` result is `{"a.b": "1"}` |
| `test_key_equals_sep` | Key `/` with `sep="/"` — key is not split into `"a"` and `"b"` |
| `test_unicode_keys` | Cyrillic keys (`"привет": "мир"`) pass through unchanged |
| `test_unicode_key_emoji` | Emoji in keys (`"😀": "happy"`) preserved correctly |
| `test_nan_value_throws` | Unparseable JSON (`NaN`) raises ValueError (simd-json is strict about NaN) |
| `test_mixed_types_in_array` | Top-level array `[1, "a", null, true]` raises ValueError |
| `test_large_string_value` | ~500KB string passes through without errors or data loss |
| `test_simple_object` | Simple object `{"a": 1}` → `{"a": "1"}` (preserve_types=False) |
| `test_nested_object` | Nested object `{"a":{"b":2,"c":3}}` → `{"a.b":"2","a.c":"3"}` |
| `test_null` | JSON null with preserve_types=False → string `"null"` |
| `test_boolean` | JSON boolean with preserve_types=False → string `"true"/"false"` |
| `test_string_value` | String value passes through unchanged |
| `test_invalid_json` | Invalid JSON raises ValueError |

### Arrays (normalize_one)

| Test | What it checks |
|---|---|
| `test_array_primitives` | Primitive array: `"a":[1,2,3]` → `{"a[0]":"1","a[1]":"2","a[2]":"3"}` |
| `test_nested_arrays` | Nested arrays: `{"a":[[1,2],[3,4]]}` → `{"a[0][0]":"1",...}` |
| `test_array_of_objects` | Array of objects: `{"a":[{"b":1},{"b":2}]}` → `{"a[0].b":"1","a[1].b":"2"}` |

### Options (sep, array brackets, max_depth)

| Test | What it checks |
|---|---|
| `test_custom_sep` | Custom separator `sep="/"` — `"a":{"b":1}` → `{"a/b":1}` |
| `test_custom_array_brackets` | Custom array brackets: `array_prefix="(", array_suffix=")"` → `a(0), a(1)` |
| `test_max_depth` / `test_max_depth_exact` / `test_max_depth_preserves_shallow` | Three tests at different depths (`max_depth=1, 2`) — keys deeper than the limit are absent from result |

### Batch (normalize_many)

| Test | What it checks |
|---|---|
| `test_normalize_many_empty_list` | Empty list → empty result |
| `test_normalize_many_with_invalid_entry` | Invalid JSON in a batch raises ValueError |
| `test_normalize_many` | Basic parallel flatten of two objects |
| `test_normalize_many_parallel_order` | Output order matches input order (10 elements) |
| `test_normalize_many_with_options` | Options (`sep="/", preserve_types=False`) applied correctly in batch mode |
| `test_normalize_many_preserves_order` | 100 elements — order strictly preserved, values match exactly |

### Stream (stream_ndjson)

| Test | What it checks |
|---|---|
| `test_stream_ndjson_basic` | Basic NDJSON file streaming with two records |
| `test_stream_ndjson_empty_file` | Empty file → empty iteration, no errors |
| `test_stream_ndjson_skips_blank_lines` | Blank lines between JSON records are skipped correctly |
| `test_stream_ndjson_with_options` | Stream options (`sep="/"`) applied correctly |
| `test_stream_ndjson_skips_bad_lines` | Invalid lines silently skipped in non-strict mode (strict=False) |
| `test_stream_ndjson_max_depth` | max_depth works in streaming mode |
| `test_stream_ndjson_strict_raises_on_bad_line` | Strict mode: ValueError raised on first bad line with line number |
| `test_stream_ndjson_strict_correct_line_number` | Line number in error is exact (blank lines not counted) |
| `test_stream_ndjson_non_strict_default` | Non-strict default skips bad lines silently |

### Type preservation

| Test | What it checks |
|---|---|
| `test_normalize_one_accepts_bytes` | Input can be bytes, not only str — `b'{"a": 1}'` works |
| `test_preserve_types_numbers_booleans_null` | preserve_types=True: int→int, float→float, bool→bool, null→None |
| `test_preserve_types_default_returns_native_types` | By default preserve_types=True returns native Python types |
| `test_preserve_types_disabled_returns_strings` | preserve_types=False returns everything as strings |
| `test_normalize_many_preserve_types` | Batch mode with preserve_types: int, bool correctly preserved |
| `test_stream_ndjson_preserve_types` | Stream mode with preserve_types: int, bool, float correctly preserved |
| `test_preserve_types_nested_arrays` | Arrays with preserve_types: `[1, true, null, 2.5]` → int, bool, None, float |
| `test_preserve_types_null_string_not_converted` | JSON `"null"` (string) ≠ JSON null — string stays string, null → None |
| `test_preserve_types_large_int` | u64/i64 boundaries: `18446744073709551615` and `-9223372036854775808` preserved exactly |

---

## test_correctness.py — pandas comparison tests

Each test compares rustjsonnorm output with `pandas.json_normalize` on the same data. Uses helper `_compare_results` which normalizes types (numbers, booleans, NaN) for accurate comparison.

### Fixtures (test data)

| Fixture | Source | Description |
|---|---|---|
| `single_objects` | 4 JSON files | flat, nested_small, nested_deep, arrays_large |
| `batch_data` | NDJSON files | small_batch, medium_batch, large_batch |
| `dense_schema` | dense_schema.ndjson (105 fields per record) |
| `sparse_schema` | sparse_schema.ndjson (~5% filled of 200 possible keys) |
| `deep_nesting_data` | deep_nesting.ndjson (depth=4, branching=2) |
| `unicode_heavy_data` | unicode_heavy.ndjson (lots of non-ASCII characters) |
| `malformed_stream_file` | malformed_stream.ndjson (contains invalid JSON lines) |

### Correctness tests

| Test | What it checks |
|---|---|
| `test_correctness_rust_vs_pandas_small` | Batch mode: rust normalize_many vs pandas json_normalize on small_batch.ndjson — results identical |
| `test_correctness_rust_vs_pandas_medium` | Same on medium_batch.ndjson (more records, tests parallelism) |
| `test_correctness_single_flat` | Single object: flat JSON → rust normalize_one vs pandas json_normalize — identical |
| `test_correctness_single_nested_deep` | Single object: deep nesting → rust vs pandas — identical |
| `test_correctness_dense` | 105 fields per record — both produce the same set of keys and values |
| `test_correctness_sparse` | ~5% filled out of 200 keys — each record may have different key sets, handled correctly |
| `test_correctness_deep` | Deep nesting (depth=4) — rust vs pandas identical |
| `test_correctness_unicode` | Unicode-heavy data — all characters preserved without encoding loss |
| `test_stream_malformed` | Stream iterator skips invalid lines, returns only valid records |
| `test_stream_malformed_strict_mode` | Strict mode: ValueError raised on first invalid line with line number |
| `test_stress_single_thread_sync` | Multi-threaded normalize_many is deterministic: results match across repeated runs, key ordering consistent |

### Comparison helpers

- `_normalise_value(v)` — normalizes a value to string for comparison (handles None, bool, int, float with Decimal precision, numpy types)
- `_assert_keys_compatible(rust_keys, pandas_cols)` — checks that all non-array rust keys exist in pandas output
- `_compare_results(rust_results, pandas_df)` — compares results row by row; for sparse data uses per-row comparison handling array notation (`a[0]` vs `a`)
