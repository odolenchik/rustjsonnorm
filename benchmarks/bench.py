"""Benchmark: rustjsonnorm vs pandas.json_normalize."""

import json
import os
import sys
import time


def load_records(filepath: str, count: int = 50_000) -> list[dict]:
    with open(filepath) as f:
        data = []
        for i, line in enumerate(f):
            if i >= count:
                break
            data.append(json.loads(line))
    return data


def bench_normalize_many(records: list[dict], repeats: int = 3) -> tuple[float, float]:
    import rustjsonnorm as fjn

    json_strs = [json.dumps(r) for r in records]
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        results = fjn.normalize_many(json_strs)
        elapsed = time.perf_counter() - start
        assert len(results) == len(records), "normalize_many returned wrong count"
        times.append(elapsed)
    return min(times), max(times)


def bench_pandas_normalize(records: list[dict], repeats: int = 3) -> tuple[float, float]:
    import pandas

    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        df = pandas.json_normalize(records)
        elapsed = time.perf_counter() - start
        assert len(df) == len(records), "pandas returned wrong count"
        times.append(elapsed)
    return min(times), max(times)


def bench_stream_ndjson(filepath: str, count: int = 50_000) -> float:
    import rustjsonnorm as fjn

    start = time.perf_counter()
    with open(filepath) as f:
        for i, _ in enumerate(f):
            if i >= count:
                break
    # Use the actual stream_ndjson API on a temp file
    import tempfile, os
    tmp_path = filepath + ".bench_tmp"
    with open(tmp_path, "w") as out_f:
        with open(filepath) as in_f:
            for i, line in enumerate(in_f):
                if i >= count:
                    break
                out_f.write(line)

    start = time.perf_counter()
    processed = sum(1 for _ in fjn.stream_ndjson(tmp_path))
    elapsed = time.perf_counter() - start
    os.unlink(tmp_path)
    assert processed == count, f"stream_ndjson only processed {processed}/{count}"
    return elapsed


def main():
    filepath = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "bluesky_file_0001.json")

    records = load_records(filepath, count=50_000)
    print(f"Dataset: {filepath} ({len(records)} records)\n")

    # fjn normalize_many (parallel batch)
    best_fjn, worst_fjn = bench_normalize_many(records)
    print(
        f"rustjsonnorm.normalize_many  : best={best_fjn:.3f}s  "
        f"worst={worst_fjn:.3f}s"
    )

    # pandas.json_normalize
    try:
        best_pd, worst_pd = bench_pandas_normalize(records)
        print(
            f"pandas.json_normalize : best={best_pd:.3f}s  "
            f"worst={worst_pd:.3f}s"
        )
        speedup = best_pd / best_fjn if best_fjn > 0 else float("inf")
        print(f"\nSpeedup: {speedup:.1f}x faster (pandas={best_pd:.3f}s vs fjn={best_fjn:.3f}s)")
    except ImportError:
        print("\npandas not installed — skipping pandas comparison\n")

    # stream_ndjson benchmark
    try:
        stream_time = bench_stream_ndjson(filepath, count=50_000)
        rate = 50_000 / stream_time if stream_time > 0 else float("inf")
        print(
            f"\nrustjsonnorm.stream_ndjson   : 50,000 lines in {stream_time:.3f}s "
            f"({rate:,.0f} lines/sec)"
        )
    except Exception as e:
        print(f"\nstream_ndjson benchmark error: {e}")


if __name__ == "__main__":
    main()
