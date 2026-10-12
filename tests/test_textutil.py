from jobad.textutil import norm_key, strip_html, title_stem, truncate


def test_strip_html_keeps_structure():
    s = strip_html("<p>Hello&nbsp;<b>world</b></p><ul><li>a</li><li>b</li></ul>")
    assert "Hello world" in s
    assert "a\nb" in s
    assert "<" not in s


def test_title_stem_drops_seniority_and_noise():
    assert title_stem("Senior Backend Engineer (m/w/d)") == "backend engineer"
    assert title_stem("Lead AI Engineer") == "ai engineer"
    assert title_stem("Head of Platform") == "platform"


def test_truncate_on_word_boundary():
    assert truncate("one two three four", 10).endswith("…")
    assert truncate("short", 10) == "short"


def test_norm_key():
    assert norm_key("  Acme, Inc. ") == "acme inc"
