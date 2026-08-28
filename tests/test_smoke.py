"""Smoke test: the package imports and the toolchain is wired correctly."""

import sys


def test_package_imports():
    import recoup

    assert recoup is not None
    assert recoup.__version__ == "0.1.0"


def test_python_version_meets_the_floor():
    """pyproject declares >=3.11. Fail loudly rather than at a syntax error later."""
    assert sys.version_info >= (3, 11), f"need Python 3.11+, running {sys.version}"
