import pytest

from recoup.simulator import curve as curve_mod
from recoup.simulator.curve import (
    ATTEMPT_DECAY,
    CHANNEL_MULTIPLIER,
    CLASSES,
    DAY_OFFSET_CURVE,
    PARAMS,
    UNREGISTERED_OK,
    recovery_probability,
)
from recoup.simulator.provenance import params_problems, unregistered_constants

# --- the sourced curve, verbatim ----------------------------------------------


def test_the_sourced_day_offset_curve_is_present_verbatim():
    assert DAY_OFFSET_CURVE[0] == pytest.approx(0.1325)
    assert DAY_OFFSET_CURVE[3] == pytest.approx(0.1146)
    assert DAY_OFFSET_CURVE[7] == pytest.approx(0.1151)
    assert DAY_OFFSET_CURVE[15] == pytest.approx(0.0422)
    assert DAY_OFFSET_CURVE[30] == pytest.approx(0.0420)


def test_intent_decays_roughly_threefold_between_day_7_and_day_15():
    """The load-bearing structural fact from the Baremetrics data."""
    ratio = DAY_OFFSET_CURVE[7] / DAY_OFFSET_CURVE[15]
    assert 2.5 < ratio < 3.5


def test_the_curve_is_not_smoothed_into_monotonicity():
    # Day 30 (4.20%) exceeds day 20 (3.83%) in the source. Preserved, not tidied.
    # If this fails, someone "fixed" the data to look nicer than it is.
    assert DAY_OFFSET_CURVE[30] > DAY_OFFSET_CURVE[20]


def test_attempt_decay_is_monotonic():
    assert ATTEMPT_DECAY == sorted(ATTEMPT_DECAY, reverse=True)


def test_attempt_decay_is_the_stated_derivation_of_the_source_figures():
    # PARAMS.md claims [2.8, 1.9, 1.7, 1.5, 1.5] / 2.8. A DERIVED number whose
    # derivation is not checkable is an ASSUMPTION wearing a citation.
    raw = [2.8, 1.9, 1.7, 1.5, 1.5]
    assert ATTEMPT_DECAY == [round(v / raw[0], 2) for v in raw]


# --- the shape of the function ------------------------------------------------


def test_probability_is_always_a_valid_probability():
    for day in range(0, 31):
        for channel in CHANNEL_MULTIPLIER:
            for attempt in range(1, 6):
                for hard in (True, False):
                    p = recovery_probability(day, channel, attempt, hard)
                    assert 0.0 <= p <= 1.0


def test_later_attempts_recover_less():
    a1 = recovery_probability(3, "email", 1, False)
    a3 = recovery_probability(3, "email", 3, False)
    assert a3 < a1


def test_hard_declines_recover_less_than_soft():
    soft = recovery_probability(3, "email", 1, is_hard_decline=False)
    hard = recovery_probability(3, "email", 1, is_hard_decline=True)
    assert hard < soft


def test_interpolation_between_known_days():
    """Day 5 is not in the source table; it must sit between day 3 and day 7."""
    p5 = recovery_probability(5, "email", 1, False)
    p3 = recovery_probability(3, "email", 1, False)
    p7 = recovery_probability(7, "email", 1, False)
    assert min(p3, p7) <= p5 <= max(p3, p7)


def test_beyond_the_curve_decays_rather_than_erroring():
    assert recovery_probability(90, "email", 1, False) < DAY_OFFSET_CURVE[30]
    assert recovery_probability(90, "email", 1, False) >= 0.0


def test_measured_days_return_the_measured_value_exactly():
    # Interpolation must not perturb the points it interpolates between.
    for day, rate in DAY_OFFSET_CURVE.items():
        assert recovery_probability(day, "email", 1, False) == pytest.approx(rate)


# --- inputs that must not be guessed ------------------------------------------
# An unknown channel silently taking email parity is the same error shape as an
# unlabelled transport defaulting to `real`: the optimistic value is exactly the
# wrong default. A typo in a channel name would model the most effective channel
# available and nothing would say so.


def test_an_unknown_channel_is_refused_not_given_email_parity():
    with pytest.raises(ValueError, match="channel"):
        recovery_probability(3, "whatsap", 1, False)  # one letter short


def test_a_negative_day_offset_is_refused():
    # Outreach before the halt that caused it is an upstream bug. Clamping to
    # day 0 would hide it behind the most favourable rate in the whole curve.
    with pytest.raises(ValueError, match="day_offset"):
        recovery_probability(-1, "email", 1, False)


def test_an_attempt_number_below_one_is_refused():
    with pytest.raises(ValueError, match="attempt_no"):
        recovery_probability(3, "email", 0, False)


def test_attempts_past_the_measured_tail_reuse_the_last_measured_decay():
    # Not an error: the policy engine caps attempts, but the curve should degrade
    # gracefully rather than explode if asked about attempt 9.
    tail = recovery_probability(3, "email", len(ATTEMPT_DECAY), False)
    assert recovery_probability(3, "email", 99, False) == pytest.approx(tail)


# --- provenance ---------------------------------------------------------------


def test_every_parameter_carries_a_source_or_is_marked_assumption():
    for name, meta in PARAMS.items():
        assert "source" in meta, f"{name} has no source field"
        assert meta["source"], f"{name} has an empty source"
        if meta["class"] == "ASSUMPTION":
            assert "sweep" in meta, f"{name} is an ASSUMPTION but has no sweep range"


def test_every_parameter_carries_a_class_from_the_declared_set():
    for name, meta in PARAMS.items():
        assert meta.get("class") in CLASSES, f"{name} has class {meta.get('class')!r}"


def test_a_measured_parameter_cites_a_url_and_a_population():
    for name, meta in PARAMS.items():
        if meta["class"] == "MEASURED":
            assert meta["source"].startswith("http"), f"{name} is MEASURED without a URL"
            assert meta.get("population"), f"{name} is MEASURED without a population"


def test_an_assumption_never_claims_a_url():
    # The failure this prevents: a number that was invented, given a citation
    # that looks plausible, and read as derived three days later.
    for name, meta in PARAMS.items():
        if meta["class"] == "ASSUMPTION":
            assert not meta["source"].startswith("http"), (
                f"{name} is an ASSUMPTION but cites {meta['source']} -- either it is "
                "sourced or it is not"
            )


def test_every_sweep_range_brackets_its_own_point_estimate():
    # A sweep that cannot reach past the value it is testing is not a test.
    # Container entries hold a dict of members, each of which carries its own
    # sweep; bracketing applies to the scalar parameters.
    checked = 0
    for name, meta in PARAMS.items():
        if "sweep" not in meta:
            continue
        lo, hi = meta["sweep"]
        assert lo < hi, f"{name} sweep is not an interval"
        if isinstance(meta["value"], int | float):
            assert lo <= meta["value"] <= hi, (
                f"{name} value {meta['value']} is outside its sweep {meta['sweep']}"
            )
            checked += 1
    assert checked >= 4, "the bracketing check stopped covering the scalar assumptions"


def test_every_channel_in_the_multiplier_dict_has_its_own_params_entry():
    # The container entry is not a substitute for per-channel provenance. Adding
    # a fourth channel without registering it must fail here.
    for channel in CHANNEL_MULTIPLIER:
        key = f"channel_multiplier_{channel}"
        assert key in PARAMS, f"{channel} is used by the curve but unregistered"
        assert PARAMS[key]["value"] == CHANNEL_MULTIPLIER[channel], (
            f"{key} disagrees with the value the curve actually reads"
        )


def test_the_sms_multiplier_is_an_assumption_not_a_churnkey_figure():
    """Pins a corrected provenance error. See PARAMS.md.

    Churnkey reports SMS at 0.6 PERCENT share of recoveries. An earlier draft
    wrote that as a 0.60 effectiveness multiplier citing Churnkey -- a units
    error on top of a category error, since share of recoveries depends on send
    volumes that are not published. If this test fails, someone has restored the
    citation. The number is not in that source.
    """
    meta = PARAMS["channel_multiplier_sms"]
    assert meta["class"] == "ASSUMPTION"
    assert "churnkey" not in meta["source"].lower()


def test_email_is_definitional_and_does_not_pretend_to_be_evidence():
    assert PARAMS["channel_multiplier_email"]["class"] == "DEFINITIONAL"
    assert CHANNEL_MULTIPLIER["email"] == 1.00


def test_no_channel_multiplier_is_claimed_as_measured():
    # All of them are assumptions or the normalisation anchor. Stating that
    # plainly is the point; a MEASURED channel multiplier would be a regression.
    for name, meta in PARAMS.items():
        if name.startswith("channel_multiplier_"):
            assert meta["class"] in ("ASSUMPTION", "DEFINITIONAL"), name


# --- the guard that sits where the failure actually happens -------------------


def test_every_numeric_constant_in_the_module_is_registered_in_params():
    """The provenance check must cover the constants the FUNCTION reads.

    Iterating PARAMS only proves that everything already registered has a source.
    It says nothing about a constant that was typed straight into the module and
    never registered -- which is exactly how `_DECAY_BEYOND_CURVE = 0.97` sat in
    the draft: used by `_base_rate`, absent from PARAMS, unsourced and unmarked.

    Same failure shape as MAX_ATTEMPTS, and as the three guards before it: the
    check sat fractionally outside the path the failure takes.
    """
    offenders = unregistered_constants(curve_mod, PARAMS, UNREGISTERED_OK)
    assert not offenders, (
        f"numeric constants not registered in PARAMS: {offenders}. Every number "
        "the curve reads needs a class and a source, or an ASSUMPTION mark and a "
        "sweep range -- in the same commit that introduces it."
    )


def test_every_curve_parameter_is_well_formed():
    # Same checker the generator uses. One implementation, so the two registries
    # cannot drift into disagreeing about what a valid entry looks like.
    assert params_problems(PARAMS) == []
