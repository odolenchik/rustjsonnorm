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

    print("\nDone. All test data generated in:", output_dir)
