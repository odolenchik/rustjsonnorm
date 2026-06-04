# rustjsonnorm

Ultra-fast JSON normalization in Rust, exposed as a Python package. Drop-in replacement for `pandas.json_normalize` — up to **7x faster** at scale.

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
| `normalize_one(json_str, sep=".", array_prefix="[", array_suffix="]", max_depth=100)` | Flatten a single JSON string to a dict. Top-level must be an object. |
| `normalize_many(json_strings, ...options)` | Parallel batch flatten. Returns list of dicts in input order. |
| `stream_ndjson(filepath, ...options)` | Iterator that yields flattened dicts from a NDJSON file line-by-line. |

### Options (all functions)

| Parameter | Default | Description |
|---|---|---|
| `sep` | `"."` | Separator between nested keys |
| `array_prefix` | `"["` | Opening bracket for array indices |
| `array_suffix` | `"]"` | Closing bracket for array indices |
| `max_depth` | `100` | Stop recursing at this depth (leaf values converted to strings) |

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

Benchmarked on Bluesky NDJSON dataset (first N records from a 1M-line file):

#### 50,000 records

| Benchmark | Result |
|---|---|
| `normalize_many` | **0.19s** |
| `pandas.json_normalize` | 1.04s |
| Speedup | **5.5x faster than pandas** |
| `stream_ndjson` throughput | ~263K lines/sec |

#### 500,000 records

| Benchmark | Result |
|---|---|
| `normalize_many` | **1.80s** |
| `pandas.json_normalize` | 13.09s |
| Speedup | **7.3x faster than pandas** |
| `stream_ndjson` throughput | ~263K lines/sec |

Note: benchmarks use fair comparison — both rustjsonnorm and pandas receive the same input format (JSON strings → Python dicts). Pandas receives a pre-converted list of dicts for its portion. Stream throughput measured on full 1M-line file, constant across dataset sizes.

Run the benchmark:

```bash
python benchmarks/bench.py path/to/data.ndjson
```

## How it works

The library is written in Rust and uses three key crates:

- **[simd-json](https://crates.io/crates/simd-json)** — SIMD-accelerated JSON parsing (Google's simdjson backend)
- **[rayon](https://crates.io/crates/rayon)** — data-parallel iterators for multi-core batch processing
- **[indexmap](https://crates.io/crates/indexmap)** — insertion-order-preserving hash map

The Rust crate compiles to a C-compatible shared library (`cdylib`) and is exposed via PyO3. Release builds use LTO + opt-level 3.

## Test suite

```bash
pytest tests/
```

37 tests covering primitives, arrays, nested objects, unicode, custom options, depth limits, parallel ordering, and streaming.

## License

MIT
