import json
from pathlib import Path

from recoup.simulator import curve, generator
from recoup.simulator.freeze import (
    SIM_DIR,
    hash_simulator_dir,
    locked_params,
    verify_lock,
    write_lock,
)

# --- the hash ------------------------------------------------------------------


def test_the_directory_hash_is_stable_across_calls():
    assert hash_simulator_dir() == hash_simulator_dir()


def test_the_hash_is_a_sha256():
    h = hash_simulator_dir()
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_the_hash_changes_when_a_simulator_file_changes(tmp_path):
    # If it does not, the freeze proves nothing.
    before = hash_simulator_dir()
    scratch = SIM_DIR / "_drift_probe.py"
    scratch.write_text("X = 1\n", encoding="utf-8")
    try:
        assert hash_simulator_dir() != before
    finally:
        scratch.unlink()
    assert hash_simulator_dir() == before


def test_the_hash_ignores_line_endings():
    """A CRLF checkout must not read as tampering.

    The hash covers content, not literal bytes. `.gitattributes` forces LF today,
    but a file type it does not cover would land as CRLF on Windows and LF on the
    Linux runner -- and CI would report SIMULATOR DRIFT with nobody having
    touched anything. That failure is indistinguishable from the real one.
    """
    from recoup.simulator.freeze import _normalise

    assert _normalise(b"a\r\nb\r\n") == _normalise(b"a\nb\n")
    assert _normalise(b"a\rb") == _normalise(b"a\nb")


def test_freeze_py_is_excluded_from_its_own_hash():
    # Including it would make the hash depend on its own output.
    files = [p.name for p in SIM_DIR.rglob("*") if p.is_file()]
    assert "freeze.py" in files
    from recoup.simulator.freeze import _hashed_files

    assert "freeze.py" not in [p.name for p in _hashed_files()]


def test_params_md_is_inside_the_hash():
    # The provenance document is part of what is frozen. Editing a source URL
    # after the freeze must be drift.
    assert "PARAMS.md" in [p.name for p in _hashed_files_names()]


def _hashed_files_names():
    from recoup.simulator.freeze import _hashed_files

    return _hashed_files()


# --- the lock -------------------------------------------------------------------


def test_write_lock_captures_hash_and_params(tmp_path):
    lock_path = tmp_path / "PARAMS.lock.json"
    lock = write_lock(str(lock_path))

    assert lock["simulator_sha256"] == hash_simulator_dir()
    assert "params" in lock
    assert "frozen_at" in lock
    assert lock_path.exists()

    on_disk = json.loads(lock_path.read_text(encoding="utf-8"))
    assert on_disk == lock


def test_the_lock_covers_the_generator_not_only_the_curve():
    """PLAN.md locked `curve.PARAMS` alone.

    The generator holds `self_recovery_rate_soft` and `_hard` -- the numbers that
    define the counterfactual the entire lift claim is measured against. Locking
    the curve and not the generator would freeze the less consequential half.
    """
    params = locked_params()
    assert "day_offset_curve" in params
    assert "self_recovery_rate_soft" in params
    assert "self_recovery_rate_hard" in params
    for key in curve.PARAMS:
        assert key in params
    for key in generator.PARAMS:
        assert key in params


def test_the_lock_timestamp_is_utc_with_a_z(tmp_path):
    lock = write_lock(str(tmp_path / "l.json"))
    assert lock["frozen_at"].endswith("Z")
    assert "+00:00" not in lock["frozen_at"]


def test_write_lock_also_writes_the_freeze_document(tmp_path):
    lock_path = tmp_path / "PARAMS.lock.json"
    write_lock(str(lock_path))
    doc = lock_path.parent / "SIMULATOR_FREEZE.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert hash_simulator_dir() in text


# --- verification ----------------------------------------------------------------


def test_verify_passes_against_a_fresh_lock(tmp_path):
    lock_path = str(tmp_path / "PARAMS.lock.json")
    write_lock(lock_path)
    ok, message = verify_lock(lock_path)
    assert ok is True, message


def test_verify_fails_when_the_lock_hash_does_not_match(tmp_path):
    lock_path = tmp_path / "PARAMS.lock.json"
    lock = write_lock(str(lock_path))
    lock["simulator_sha256"] = "f" * 64
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    ok, message = verify_lock(str(lock_path))
    assert ok is False
    assert "drift" in message.lower()


def test_verify_fails_when_a_curve_param_changed(tmp_path):
    lock_path = tmp_path / "PARAMS.lock.json"
    lock = write_lock(str(lock_path))
    lock["params"]["baseline_recovery_rate"]["value"] = 0.99
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    ok, message = verify_lock(str(lock_path))
    assert ok is False


def test_verify_fails_when_a_generator_param_changed(tmp_path):
    # The half PLAN.md would not have locked.
    lock_path = tmp_path / "PARAMS.lock.json"
    lock = write_lock(str(lock_path))
    lock["params"]["self_recovery_rate_soft"]["value"] = 0.99
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    ok, message = verify_lock(str(lock_path))
    assert ok is False
    assert "params" in message.lower()


def test_verify_names_which_parameter_drifted(tmp_path):
    # "PARAMS changed" sends someone diffing a 17-entry dict by eye.
    lock_path = tmp_path / "PARAMS.lock.json"
    lock = write_lock(str(lock_path))
    lock["params"]["hard_decline_multiplier"]["value"] = 0.11
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    ok, message = verify_lock(str(lock_path))
    assert ok is False
    assert "hard_decline_multiplier" in message


def test_verify_fails_loudly_when_the_lock_is_missing(tmp_path):
    ok, message = verify_lock(str(tmp_path / "nope.json"))
    assert ok is False
    assert "not found" in message.lower()


def test_verify_fails_on_a_corrupt_lock_rather_than_raising(tmp_path):
    bad = tmp_path / "PARAMS.lock.json"
    bad.write_text("{not json", encoding="utf-8")
    ok, message = verify_lock(str(bad))
    assert ok is False
    assert "unreadable" in message.lower() or "parse" in message.lower()


# --- the committed lock, if the freeze has happened -------------------------------


def test_the_repository_lock_verifies_if_it_exists():
    """Once frozen, `simulator/` must match the committed lock at all times.

    This is the same check CI runs. Having it in the suite means drift fails
    locally before it fails the build.
    """
    repo_lock = Path(__file__).resolve().parents[1] / "PARAMS.lock.json"
    if not repo_lock.exists():
        return  # pre-freeze
    ok, message = verify_lock(str(repo_lock))
    assert ok, message
