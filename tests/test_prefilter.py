from types import SimpleNamespace

from app.services.prefilter import should_check


def entity(type_: str, offset: int, length: int):
    return SimpleNamespace(type=type_, offset=offset, length=length)


def test_normal_english_sentence_passes():
    assert should_check("she go to school yesterday", None)


def test_empty_and_none_skipped():
    assert not should_check(None, None)
    assert not should_check("", None)


def test_command_skipped():
    assert not should_check("/strict", None)


def test_too_short_skipped():
    assert not should_check("hi there", None)  # < 3 words
    assert not should_check("a b c", None)  # < 12 chars


def test_emoji_only_skipped():
    assert not should_check("😂😂😂 🎉🎉 👍👍👍", None)


def test_url_only_skipped():
    text = "https://example.com/some/long/path"
    assert not should_check(text, [entity("url", 0, len(text))])


def test_code_block_skipped():
    text = "def foo():\n    return 1"
    assert not should_check(text, [entity("pre", 0, len(text))])


def test_persian_text_skipped():
    assert not should_check("سلام دوستان حال شما چطوره امروز", None)


def test_mixed_mostly_english_passes():
    assert should_check("ok guys lets meet at 5pm tomorrow", None)


def test_text_with_trailing_url_still_checked():
    text = "check this article its really intresting https://example.com"
    url_offset = text.index("https://")
    assert should_check(text, [entity("url", url_offset, len(text) - url_offset)])
