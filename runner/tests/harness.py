"""What every test file shares: `check(name, condition, extra)` prints one line per claim, and
`finish()` prints the total and exits 1 if any failed. Each test file runs by itself:
`uv run python tests/test_<name>.py`."""
import sys

FAILED = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILED.append(name)


def finish():
    print(f"\n{len(FAILED)} failed: " + "; ".join(FAILED) if FAILED else "\nall passed")
    sys.exit(1 if FAILED else 0)
