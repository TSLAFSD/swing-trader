"""Phase 1 smoke test: import all core packages and print versions.

Run: .venv/bin/python tests/smoke_test_phase1.py
"""

import importlib
import sys


def main() -> None:
    """Import every core dependency and print its version."""
    print(f"Python {sys.version}")
    packages = [
        ("numpy", "numpy"),
        ("pandas", "pandas"),
        ("pandas_ta", "pandas_ta"),
        ("yfinance", "yfinance"),
        ("FinanceDataReader", "FinanceDataReader"),
        ("pykrx", "pykrx"),
        ("backtesting", "backtesting"),
        ("plotly", "plotly"),
        ("jinja2", "jinja2"),
        ("duckdb", "duckdb"),
        ("pyarrow", "pyarrow"),
        ("yaml", "pyyaml"),
        ("pytest", "pytest"),
    ]
    failures = []
    for module_name, display_name in packages:
        try:
            mod = importlib.import_module(module_name)
            version = getattr(mod, "__version__", "(no __version__)")
            print(f"  OK  {display_name:<22} {version}")
        except Exception as exc:  # noqa: BLE001 - smoke test reports everything
            failures.append((display_name, exc))
            print(f"  FAIL {display_name:<21} {type(exc).__name__}: {exc}")
    if failures:
        sys.exit(1)
    print("--- ALL IMPORTS OK ---")


if __name__ == "__main__":
    main()
