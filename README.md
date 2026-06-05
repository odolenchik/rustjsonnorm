# rustjsonnorm v0.2.4

Ultra-fast JSON normalization in Rust, exposed as a Python package. Drop-in replacement for `pandas.json_normalize` — up to **4.3x faster** at scale.

## Install

```bash
pip install rustjsonnorm
```

Python 3.8+. No build tools required — pre-built wheels for Linux/macOS/Windows.

## Usage

### Single object

Flatten a nested JSON string into dot-notation key-value pairs:

```python
import rustjsonnorm as fjn

result = fjn.normalize_one('{"user": {"name": "Ivan", "city": "Moscow"}}')
# {'user.name': 'Ivan', 'user.city': 'Moscow'}
```

### Batch (parallel)

Process thousands of JSON strings in parallel across all CPU cores:

```python
json_strings = [
    '{"id": 1, "tags": ["a", "b"]}',
    '{"id": 2, "tags": ["c", "d"]}',
]
results = fjn.normalize_many(json_strings)
# [{'id': '1', 'tags[0]': 'a', 'tags[1]': 'b'},
#  {'id': '2', 'tags[0]': 'c', 'tags[1]': 'd'}]
```

### Stream NDJSON files

Process line-delimited JSON files lazily without loading into memory:

```python
for row in fjn.stream_ndjson("large_file.ndjson"):
    process(row)  # yields flattened dicts one at a time
```

## API Reference

| Function | Description |
|---|---|
| `normalize_one(json_input, sep=".", array_prefix="[", array_suffix="]", max_depth=100)` | Flatten a single JSON string or bytes to a dict. Top-level must be an object. Accepts `str` or `bytes`. |
| `normalize_many(json_inputs, ...options)` | Parallel batch flatten. Accepts a list of strings or bytes per item. Returns list of dicts in input order. |
| `stream_ndjson(filepath, ...options)` | Iterator that yields flattened dicts from a NDJSON file line-by-line. |

### Options (all functions)

| Parameter | Default | Description |
|---|---|---|
| `sep` | `"."` | Separator between nested keys |
| `array_prefix` | `"["` | Opening bracket for array indices |
| `array_suffix` | `"]"` | Closing bracket for array indices |
| `max_depth` | `100` | Stop recursing at this depth (leaf values returned as-is, respecting preserve_types) |
| `preserve_types` | `True` | Numeric and boolean JSON values are returned as native Python types (`int`, `float`, `bool`). `null` becomes `None`. Set to `False` for string-only mode (max performance). |

### Example: preserve original types

```python
result = fjn.normalize_one(
    '{"age": 30, "active": true, "score": 95.5}',
    preserve_types=True,
)
# {'age': 30, 'active': True, 'score': 95.5}
# types are int, bool, float — not strings
```

### Example: custom separator and depth limit

```python
result = fjn.normalize_one(
    '{"a": {"b": {"c": 42}}}',
    sep="/",
    max_depth=2,
)
# {'a/b': '42'}  — stops before reaching "c" at depth 3
```

## Performance

Benchmarked on Bluesky NDJSON dataset (first N records from a 1M-line file). Both rustjsonnorm and pandas receive identical input — JSON strings converted to Python dicts via `json.loads()`. Single run per size.

| Records | rustjsonnorm | pandas.json_normalize | Speedup |
|---|---|---|---|
| 50,000 | **0.221s** (227K rec/s) | 0.582s | **2.6x faster** |
| 250,000 | **0.951s** (263K rec/s) | 3.645s | **3.8x faster** |
| 500,000 | **1.780s** (281K rec/s) | 7.305s | **4.1x faster** |
| 1,000,000 | **3.545s** (282K rec/s) | 15.156s | **4.3x faster** |

rustjsonnorm scales linearly (~280K records/sec). Pandas time grows quadratically as the dataset increases.

### Running benchmarks locally

```bash
# Install dependencies
pip install rustjsonnorm pandas

# Run the benchmark script on your own NDJSON file
cd benchmarks && python generate_test_data.py test_data && pytest test_benchmarks.py --benchmark-only -v
```

The benchmark script loads N records (default 50,000) and compares `rustjsonnorm.normalize_many` against `pandas.json_normalize`. It also measures `stream_ndjson` throughput.

### Running the full benchmark suite locally

```bash
pip install pytest pytest-benchmark pandas numpy

# Generate all synthetic test fixtures
cd benchmarks && python generate_test_data.py test_data

# Correctness checks (regular pytest, no benchmark calibration)
python -m pytest test_benchmarks.py -k "correctness or stress" -v

# Single-threaded benchmarks (algorithmic comparison)
RAYON_NUM_THREADS=1 python -m pytest test_benchmarks.py --benchmark-only \
    --benchmark-warmup=False --benchmark-min-rounds=10 --benchmark-min-time=0.2 -v -k "singlethread"

# Multi-threaded benchmarks (real-world throughput)
python -m pytest test_benchmarks.py --benchmark-only \
    --benchmark-warmup=False --benchmark-min-rounds=10 --benchmark-min-time=0.2 -v -k "multithread"
```

The suite includes fixtures for dense schemas (105 fields), sparse objects (~5% keys), deep nesting, unicode-heavy data, and malformed streams — ensuring robustness across real-world JSON shapes.

## How it works

The library is written in Rust and uses three key crates:

- **[simd-json](https://crates.io/crates/simd-json)** — SIMD-accelerated JSON parsing (Google's simdjson backend)
- **[rayon](https://crates.io/crates/rayon)** — data-parallel iterators for multi-core batch processing
- **[indexmap](https://crates.io/crates/indexmap)** — insertion-order-preserving hash map

The Rust crate compiles to a C-compatible shared library (`cdylib`) and is exposed via PyO3. Release builds use LTO + opt-level 3.

## API Reference — stream_ndjson strict mode

| Parameter | Default | Description |
|---|---|---|
| `strict` | `False` | When `True`, raises `ValueError` on malformed lines with line number and error message. When `False` (default), silently skips bad lines for backwards compatibility. |

Example:

```python
# Strict mode — raises ValueError on first bad line
for row in fjn.stream_ndjson("data.ndjson", strict=True):
    process(row)
```

## Test suite

```bash
pytest tests/
```

48 tests covering primitives, arrays, nested objects, unicode, custom options, depth limits, parallel ordering, streaming, strict-mode error handling, bytes input, and type preservation.

## License

MIT
