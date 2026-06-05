"""Generate synthetic JSON datasets for benchmarking rustjsonnorm vs pandas."""

import json
import os
import random
import string
import sys


def rand_str(length: int = 10) -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def flat_object(n_keys: int = 20) -> dict:
    """Flat object with primitive values."""
    obj = {}
    for i in range(n_keys):
        kind = i % 5
        if kind == 0:
            obj[f"field_{i}"] = rand_str(8)
        elif kind == 1:
            obj[f"field_{i}"] = random.randint(-1_000, 1_000_000)
        elif kind == 2:
            obj[f"field_{i}"] = round(random.uniform(-100, 100), 4)
        elif kind == 3:
            obj[f"field_{i}"] = random.choice([True, False])
        else:
            obj[f"field_{i}"] = None
    return obj


def nested_object(depth: int, branching: int = 2) -> dict:
    """Recursively build a nested object."""
    if depth <= 0:
        # Leaf value
        kind = random.randint(0, 4)
        if kind == 0:
            return rand_str(6)
        elif kind == 1:
            return random.randint(0, 10_000)
        elif kind == 2:
            return round(random.uniform(0, 100), 2)
        elif kind == 3:
            return random.choice([True, False])
        else:
            return None

    obj = {}
    for i in range(branching):
        key = f"k{i}_{rand_str(4)}"
        obj[key] = nested_object(depth - 1, branching)
    return obj


def array_heavy_object(array_size: int = 50) -> dict:
    """Object with large arrays."""
    obj = {}
    # A few flat fields
    for i in range(5):
        obj[f"flat_{i}"] = rand_str(10)

    # Large homogeneous array of ints
    obj["large_int_array"] = [random.randint(0, 1_000_000) for _ in range(array_size)]

    # Large homogeneous array of strings
    obj["large_string_array"] = [rand_str(20) for _ in range(array_size)]

    return obj


def mixed_object(depth: int = 3) -> dict:
    """Realistic mixed object with nested objects, arrays, primitives."""
    obj = {
        "id": random.randint(1, 1_000_000),
        "timestamp_ms": random.randint(1_700_000_000_000, 2_000_000_000_000),
    }

    # Nested config object
    obj["config"] = {
        "enabled": random.choice([True, False]),
        "region": rand_str(3).upper(),
        "version": f"{random.randint(1,5)}.{random.randint(0,9)}",
        "tags": [rand_str(6) for _ in range(random.randint(2, 8))],
    }

    # Deep nesting
    deep = obj
    for d in range(depth):
        new_level = {}
        for k in ["meta", "stats"]:
            new_level[k] = {
                "count": random.randint(0, 10_000),
                "score": round(random.uniform(0, 1), 4),
            }
        deep["level"] = new_level
        deep = deep["level"]

    return obj


def generate_single_object_tests(output_dir: str):
    """Generate single-object JSON files for normalize_one benchmark."""
    os.makedirs(output_dir, exist_ok=True)

    # flat_1.json – 20 keys, no nesting
    with open(os.path.join(output_dir, "flat_1.json"), "w") as f:
        json.dump(flat_object(20), f)

    # nested_small_1.json – depth 3, branching 4
    obj = nested_object(depth=3, branching=4)
    with open(os.path.join(output_dir, "nested_small_1.json"), "w") as f:
        json.dump(obj, f)

    # nested_deep_1.json – depth 10, branching 2
    obj = nested_object(depth=10, branching=2)
    with open(os.path.join(output_dir, "nested_deep_1.json"), "w") as f:
        json.dump(obj, f)

    # arrays_large_1.json – large arrays
    obj = array_heavy_object(array_size=100)
    with open(os.path.join(output_dir, "arrays_large_1.json"), "w") as f:
        json.dump(obj, f)

    print(f"Generated 4 single-object test files in {output_dir}")


def generate_batch_datasets(output_dir: str):
    """Generate batch NDJSON datasets for normalize_many benchmark."""
    os.makedirs(output_dir, exist_ok=True)

    # small_batch.ndjson – 100 flat objects
    with open(os.path.join(output_dir, "small_batch.ndjson"), "w") as f:
        for _ in range(100):
            f.write(json.dumps(flat_object(n_keys=20)) + "\n")

    # medium_batch.ndjson – 1_000 mixed objects with moderate nesting
    with open(os.path.join(output_dir, "medium_batch.ndjson"), "w") as f:
        for _ in range(1_000):
            f.write(json.dumps(mixed_object(depth=3)) + "\n")

    # large_batch.ndjson – 10_000 mixed objects including arrays
    with open(os.path.join(output_dir, "large_batch.ndjson"), "w") as f:
        for _ in range(10_000):
            obj = array_heavy_object(array_size=20) if random.random() < 0.3 else mixed_object(depth=4)
            f.write(json.dumps(obj) + "\n")

    # huge_batch.ndjson – 100_000 flat objects (for streaming benchmark)
    with open(os.path.join(output_dir, "huge_batch.ndjson"), "w") as f:
        for _ in range(100_000):
            f.write(json.dumps(flat_object(n_keys=15)) + "\n")

    print("Generated batch datasets:")
    for name in sorted(os.listdir(output_dir)):
        path = os.path.join(output_dir, name)
        lines = sum(1 for _ in open(path))
        size_kb = os.path.getsize(path) / 1024
        print(f"  {name}: {lines} records ({size_kb:.0f} KB)")


def generate_corrupt_stream(output_dir: str, total_lines: int = 50_000):
    """Generate a stream file with ~2% corrupt lines for strict-mode testing."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "corrupt_stream.ndjson")

    bad_templates = ["NOT_JSON", "", "{invalid}", '{"incomplete":', "{{}"]
    bad_count = max(1, int(total_lines * 0.02))
    good_count = total_lines - bad_count

    lines: list[str] = []
    for _ in range(good_count):
        lines.append(json.dumps(flat_object(15)))
    for _ in range(bad_count):
        lines.append(random.choice(bad_templates))

    # Shuffle but keep roughly 2% corruption rate distributed evenly
    random.shuffle(lines)
    with open(path, "w") as f:
        for line in lines:
            f.write(line + "\n")

    size_kb = os.path.getsize(path) / 1024
    actual_bad = sum(1 for l in open(path) if not _is_valid_json_line(l.strip()))
    print(f"Generated corrupt_stream.ndjson: {total_lines} lines ({size_kb:.0f} KB, ~{actual_bad} bad)")


# ---------------------------------------------------------------------------
# New fixture generators (dense, sparse, deep, unicode, malformed)
# ---------------------------------------------------------------------------

def dense_schema_object(n_fields: int = 105) -> dict:
    """Flat object with 100+ fields — tests column allocation and indexmap traversal."""
    return {f"f{i}": rand_str(6) for i in range(n_fields)}


def sparse_object(all_keys: list, sample_rate: float = 0.05) -> dict:
    """Sparse object with ~5% of possible keys present — tests dynamic schema building overhead."""
    count = max(1, int(len(all_keys) * sample_rate))
    chosen = random.sample(all_keys, min(count, len(all_keys)))
    return {k: rand_str(6) for k in sorted(chosen)}


def deep_object(depth: int = 10, branching: int = 3) -> dict:
    """Deeply nested object — tests recursive traversal and path key generation."""
    if depth <= 0:
        kind = random.randint(0, 4)
        if kind == 0:
            return rand_str(6)
        elif kind == 1:
            return random.randint(0, 10_000)
        elif kind == 2:
            return round(random.uniform(0, 100), 2)
        elif kind == 3:
            return random.choice([True, False])
        else:
            return None

    obj = {}
    for i in range(branching):
        key = f"l{depth}_k{i}"
        obj[key] = deep_object(depth - 1, branching)
    return obj


def unicode_object() -> dict:
    """Unicode-heavy object — tests UTF-8 correctness and non-ASCII performance."""
    scripts = [
        ("name", "мир"),
        ("emoji", "\U0001f600\U0001f389"),
        ("chinese", "你好世界"),
        ("cyrillic", "привет мир"),
        ("mixed", "test 日本語 \U0001f680 test"),
    ]
    obj = {}
    random.shuffle(scripts)
    for key, value in scripts:
        obj[key] = value
    # Add a few normal fields too
    obj["id"] = random.randint(1, 1_000_000)
    obj["count"] = random.randint(0, 1000)
    return obj


def generate_dense_schema(output_dir: str, n_records: int = 100_000):
    """Generate dense-schema NDJSON (105 fields per record)."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "dense_schema.ndjson")
    with open(path, "w", encoding="utf-8") as f:
        for _ in range(n_records):
            f.write(json.dumps(dense_schema_object(105)) + "\n")
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"Generated dense_schema.ndjson: {n_records} records ({size_mb:.1f} MB)")


def generate_sparse_schema(output_dir: str, n_records: int = 100_000):
    """Generate sparse-schema NDJSON (~5% of 200 possible keys per record)."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "sparse_schema.ndjson")
    all_keys = [f"key_{i}" for i in range(200)]
    with open(path, "w", encoding="utf-8") as f:
        for _ in range(n_records):
            f.write(json.dumps(sparse_object(all_keys, sample_rate=0.05)) + "\n")
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"Generated sparse_schema.ndjson: {n_records} records ({size_mb:.1f} MB)")


def generate_deep_nesting(output_dir: str, n_records: int = 10_000):
    """Generate deep-nesting NDJSON (depth=4, branching=2 — path depth ~5)."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "deep_nesting.ndjson")
    with open(path, "w", encoding="utf-8") as f:
        for _ in range(n_records):
            f.write(json.dumps(deep_object(depth=4, branching=2)) + "\n")
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"Generated deep_nesting.ndjson: {n_records} records ({size_mb:.1f} MB)")


def generate_unicode_heavy(output_dir: str, n_records: int = 50_000):
    """Generate unicode-heavy NDJSON."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "unicode_heavy.ndjson")
    with open(path, "w", encoding="utf-8") as f:
        for _ in range(n_records):
            f.write(json.dumps(unicode_object(), ensure_ascii=False) + "\n")
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"Generated unicode_heavy.ndjson: {n_records} records ({size_mb:.1f} MB)")


def generate_malformed_stream(output_dir: str, total_lines: int = 100_000):
    """Generate malformed NDJSON (~1% corrupt lines) for stream robustness testing."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "malformed_stream.ndjson")

    bad_templates = [
        "NOT_JSON", "", "{invalid}", '{"incomplete":', "{{}",
        '{"key": "value\x00with\x07control"}',  # control chars
        '{"key": "unescaped"quote}',              # unescaped quote in value
        '{truly broken json!!!',                   # gibberish object
        'null\n123\ntrue',                         # multiple non-objects on one line (counted once)
    ]
    bad_count = max(1, int(total_lines * 0.01))
    good_count = total_lines - bad_count

    lines: list[str] = []
    for _ in range(good_count):
        lines.append(json.dumps(flat_object(15)))
    for _ in range(bad_count):
        lines.append(random.choice(bad_templates))

    random.shuffle(lines)
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")

    size_mb = os.path.getsize(path) / (1024 * 1024)
    actual_bad = sum(1 for l in open(path) if not _is_valid_json_line(l.strip()))
    print(f"Generated malformed_stream.ndjson: {total_lines} lines ({size_mb:.1f} MB, ~{actual_bad} bad)")


def generate_extra_fixtures(output_dir: str):
    """Generate all new fixture types."""
    os.makedirs(output_dir, exist_ok=True)
    random.seed(42)

    generate_dense_schema(output_dir, n_records=100_000)
    generate_sparse_schema(output_dir, n_records=100_000)
    generate_deep_nesting(output_dir, n_records=10_000)
    generate_unicode_heavy(output_dir, n_records=50_000)
    generate_malformed_stream(output_dir, total_lines=100_000)

    print("\nGenerated extra fixtures:")
    for name in ["dense_schema.ndjson", "sparse_schema.ndjson", "deep_nesting.ndjson",
                  "unicode_heavy.ndjson", "malformed_stream.ndjson"]:
        path = os.path.join(output_dir, name)
        if os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"  {name}: {size_mb:.1f} MB")


def _is_valid_json_line(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


if __name__ == "__main__":
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "test_data"

    # Use fixed seed for reproducibility
    random.seed(42)

    generate_single_object_tests(output_dir)
    generate_batch_datasets(output_dir)
    generate_corrupt_stream(output_dir)
    generate_extra_fixtures(output_dir)

    print("\nDone. All test data generated in:", output_dir)
