"""Run benchmarks and generate an updated README table.

Usage:
    python run_benchmarks.py          # run full benchmark, print results
    python run_benchmarks.py --json   # output as JSON for programmatic use
"""

import subprocess
import sys
from pathlib import Path


def generate_data():
    """Generate test data if it doesn't exist."""
    script = str(Path(__file__).parent / "generate_test_data.py")
    data_dir = str(Path(__file__).parent / "test_data")
    print(f"Generating test data in {data_dir}...")
    subprocess.run([sys.executable, script, data_dir], check=True)


def run_benchmark(test_names: list[str]):
    """Run specific benchmark tests and return parsed results."""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(Path(__file__).parent / "test_benchmarks.py"),
        "-v",
        "--benchmark-only",
        "--benchmark-min-rounds=3",
        "--benchmark-warmup=False",
        "-k",
        " or ".join(test_names),
    ]

    print(f"\nRunning benchmarks: {', '.join(test_names)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout


def parse_benchmark_results(stdout: str):
    """Parse pytest-benchmark output into structured data."""
    lines = stdout.split("\n")
    results = {}
    for line in lines:
        if "rust" in line.lower() or "pandas" in line.lower():
            # Look for timing info like "10.2 ms ± ..."
            import re

            match = re.search(r"(\d+\.\d+)\s*ms", line)
            if match and ("rustjsonnorm" not in line or "rust" in line):
                test_name = line.strip().split()[0] if line.split() else ""
                results[test_name] = float(match.group(1))
    return results


def main():
    generate_data()

    # Run symmetric benchmarks (both rust and pandas, same input)
    tests_to_run = [
        "test_normalize_one_rust_flat",
        "test_normalize_one_pandas_flat",
        "test_normalize_many_rust_small_symmetric",
        "test_normalize_many_pandas_small_symmetric",
    ]

    stdout = run_benchmark(tests_to_run)
    results = parse_benchmark_results(stdout)

    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)
    for name, value in sorted(results.items()):
        print(f"  {name}: {value:.3f} ms")


if __name__ == "__main__":
    main()
