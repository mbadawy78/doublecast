import json


def _split_everywhere(engine, text, escape=False):
    """Feed `text` to a stream restorer split at every possible position."""
    expected = engine.restore(text) if not escape else None
    for i in range(1, len(text)):
        r = engine.stream_restorer(escape_json=escape)
        out = r.feed(text[:i]) + r.feed(text[i:]) + r.flush()
        yield i, out, expected


def test_stream_restore_any_split(engine):
    scrambled = engine.scramble("Ask Nordia Hellas and Eleni Papadopoulou about €1.250,00.").text
    for i, out, expected in _split_everywhere(engine, scrambled):
        assert out == expected, f"split at {i}"


def test_stream_restore_tiny_chunks(engine):
    scrambled = engine.scramble("Larissa Plant ships to Nordia Hellas every Monday.").text
    r = engine.stream_restorer()
    out = "".join(r.feed(ch) for ch in scrambled) + r.flush()
    assert out == "Larissa Plant ships to Nordia Hellas every Monday."


def test_stream_restore_inside_json_arguments(engine):
    scrambled = engine.scramble("Write to Eleni Papadopoulou").text.replace("Write to ", "")
    fragment = json.dumps({"to": scrambled, "note": 'say "hi"'})
    for i, out, _ in _split_everywhere(engine, fragment, escape=True):
        assert json.loads(out)["to"] == "Eleni Papadopoulou", f"split at {i}"


def test_stream_restores_prefix_currency_far_from_the_end(engine):
    """A currency sign and its number must never be split across emitted chunks."""
    import random

    original = "The account owes a total of €1.234.567,89 plus $500 and EUR 12.400 this quarter, " + "x" * 120
    scrambled = engine.scramble(original).text
    rng = random.Random(3)
    for _ in range(300):
        r = engine.stream_restorer()
        out, i = "", 0
        while i < len(scrambled):
            n = rng.randint(1, 6)
            out += r.feed(scrambled[i : i + n])
            i += n
        out += r.flush()
        assert out == original
