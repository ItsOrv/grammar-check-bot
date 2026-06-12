from app.services.llm.base import GrammarResult, parse_result, should_reply


def result(**kwargs) -> GrammarResult:
    defaults = dict(has_issues=True, severity=3, confidence=0.95, corrected="Fixed text.", explanation="Fix.")
    defaults.update(kwargs)
    return GrammarResult(**defaults)


def test_no_issues_never_replies():
    assert not should_reply(result(has_issues=False, severity=0), "strict", "original", 0.8)


def test_none_result_never_replies():
    assert not should_reply(None, "normal", "original", 0.8)


def test_low_confidence_suppressed():
    assert not should_reply(result(confidence=0.5), "normal", "original", 0.8)


def test_thresholds_per_level():
    minor = result(severity=1)
    standard = result(severity=3)
    critical = result(severity=5)

    assert should_reply(minor, "strict", "original", 0.8)
    assert not should_reply(minor, "normal", "original", 0.8)
    assert not should_reply(standard, "casual", "original", 0.8)
    assert should_reply(standard, "normal", "original", 0.8)
    assert should_reply(critical, "casual", "original", 0.8)


def test_identical_correction_suppressed():
    assert not should_reply(result(corrected="same text"), "strict", "same text", 0.8)


def test_off_level_never_replies():
    assert not should_reply(result(severity=5), "off", "original", 0.8)


def test_parse_result_valid():
    data = {"has_issues": True, "severity": 7, "confidence": 1.5, "corrected": " x ", "explanation": "e"}
    parsed = parse_result(data)
    assert parsed is not None
    assert parsed.severity == 5  # clamped
    assert parsed.confidence == 1.0  # clamped
    assert parsed.corrected == "x"


def test_parse_result_invalid():
    assert parse_result({}) is None
    assert parse_result({"has_issues": True, "severity": "bad"}) is None
