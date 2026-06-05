# Contributing to rustjsonnorm

## Development setup

```bash
cd fast_json_normalize  # or your project path
pip install maturin
maturin develop --release
```

This builds the Rust extension and installs it as a local editable package. Then `import rustjsonnorm` works in Python immediately.

## Running tests

```bash
# Fast tests only (CI subset)
pytest tests/ --ignore=tests/test_correctness.py && pytest tests/test_correctness.py::test_correctness_single_flat tests/test_correctness.py::test_correctness_single_nested_deep tests/test_correctness.py::test_stream_malformed -v

# All tests locally
pytest tests/

# With coverage
pytest tests/ --cov rustjsonnorm --cov-report=term-missing
```

## Rust checks

```bash
cargo clippy -- -D warnings    # lint
cargo test                     # Rust-side tests (none yet)
cargo fmt                      # format code
```

## Building a wheel locally

```bash
maturin build --release --out dist
pip install dist/rustjsonnorm-*.whl
```
