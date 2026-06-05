# Roadmap

## Planned Features

### Preserve original types (numbers, booleans)
Currently all values are converted to strings. Add a `preserve_types` option so that numbers remain as numeric Python types and booleans stay as booleans. This is the default behavior users expect from `json_normalize`.

### Optimize normalize_many bytes path — avoid double copy
The current `normalize_many` implementation copies each byte slice into an owned `Vec<u8>` before passing to rayon, resulting in a double-copy (once for the Vec, once inside `process_one`). We could accept `&[u8]` directly from PyBytes and eliminate the intermediate allocation. This requires managing lifetimes carefully since rayon closures need `'static` bounds — potentially via thread-local storage or by collecting into an arena-style buffer before dispatching to rayon.

### Testing & Benchmarking Expansion
Currently, the test suite includes a large homogeneous JSON file (1 million rows), which is a solid baseline for performance and correctness. However, to ensure production-ready reliability, we need to expand coverage with targeted synthetic datasets that reveal edge cases and performance cliffs.

Planned test fixtures:

- **Dense schema** — objects with 100+ fields, all present, short values. Validates column allocation speed and indexmap traversal.
- **Sparse schema** — each object contains only ~5% of all possible keys. Ensures efficient dynamic schema building and insertion overhead.
- **Deep nesting** — nesting depth up to 10 levels with 5–10 keys per level. Tests recursive traversal and path generation (sep, array_prefix, etc.).
- **Unicode-heavy** — strings with emojis, Cyrillic, CJK, and long whitespace sequences. Verifies UTF-8 correctness and simd-json performance on non-ASCII data.
- **Malformed lines** — ~1% invalid JSON (truncated objects, unescaped quotes, control characters). Ensures NdjsonIterator skips garbage without catastrophic slowdown.

Implementation plan:

- Generate fixture files via a script (Rust or Python) placed under `tests/fixtures/`.
- Add fast CI tests on small samples (e.g., 1,000 rows) to catch regressions.
- Integrate benchmarks using `criterion` or `pytest-benchmark` for all fixture types.
- Run full benchmarks on million-row files weekly (or before each release) to track performance over time.

This expansion will make rustjsonnorm truly robust across real-world JSON shapes.
