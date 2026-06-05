# Benchmarks

Comprehensive pytest-benchmark suite comparing `rustjsonnorm` vs `pandas.json_normalize`.

## Setup

```bash
pip install pytest pytest-benchmark pandas numpy
cd benchmarks
python generate_test_data.py test_data   # generates synthetic datasets
```

## Warmup (required)

Rayon thread pool must be initialised before benchmarking. Run this once:

```bash
cd path/to/rustjsonnorm
python -c "import rustjsonnorm; rustjsonnorm.normalize_many([f'{chr(123)}\"a\":{i}{chr(125)}' for i in range(10)])"
```

## Run benchmarks

### Multi-threaded (real-world throughput)

```bash
cd path/to/rustjsonnorm/benchmarks
pytest test_benchmarks.py --benchmark-only \
    --benchmark-warmup=False \
    --benchmark-min-rounds=10 \
    --benchmark-min-time=0.2 -v -k "multithread"
```

### Single-threaded (algorithmic comparison)

```bash
cd path/to/rustjsonnorm/benchmarks
RAYON_NUM_THREADS=1 pytest test_benchmarks.py --benchmark-only \
    --benchmark-warmup=False \
    --benchmark-min-rounds=10 \
    --benchmark-min-time=0.2 -v -k "singlethread"
```

## Test categories

| Group | Tests | What it measures |
|---|---|---|
| `_singlethread` / `_multithread` | Isolated parallelism modes | Algorithmic vs real-world throughput |
| `*_symmetric` | Rust + Pandas on same JSON strings | Fair speed comparison (multi-threaded) |
| `correctness_*`, `stress_*` | Row-by-row key+value comparison | Output equivalence |
| `test_stream_ndjson_rust_huge` | Streaming NDJSON throughput | I/O-bound performance |
| `test_options_*` | preserve_types, max_depth overheads | Feature cost |

## Full run (all tests)

```bash
# Correctness checks (regular pytest, no benchmark calibration)
python -m pytest test_benchmarks.py -k "correctness or stress" -v

# Single-threaded benchmarks
RAYON_NUM_THREADS=1 python -m pytest test_benchmarks.py --benchmark-only \
    --benchmark-warmup=False --benchmark-min-rounds=10 --benchmark-min-time=0.2 \
    -v -k "singlethread"

# Multi-threaded benchmarks
python -m pytest test_benchmarks.py --benchmark-only \
    --benchmark-warmup=False --benchmark-min-rounds=10 --benchmark-min-time=0.2 \
    -v -k "multithread"
```

## Running on external datasets

The benchmark fixture loads data from the `test_data/` directory. To use your own dataset:

```bash
# Place a .ndjson file in benchmarks/test_data/
# Update test_benchmarks.py batch_data fixture to reference it
pytest -k "your_dataset_name" --benchmark-only ...
```
