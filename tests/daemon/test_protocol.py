from sheppy.daemon.protocol import Decoder, encode


def test_encode_appends_newline_and_roundtrips():
    d = Decoder()
    msgs = d.feed(encode({"op": "status", "id": 1}))
    assert msgs == [{"op": "status", "id": 1}]


def test_decoder_buffers_partial_lines():
    d = Decoder()
    raw = encode({"a": 1}) + encode({"b": 2})
    assert d.feed(raw[:5]) == []
    assert d.feed(raw[5:]) == [{"a": 1}, {"b": 2}]


def test_malformed_line_is_flagged_not_fatal():
    d = Decoder()
    msgs = d.feed(b"{not json}\n" + encode({"ok": 1}))
    assert msgs[0] == {"malformed": "{not json}"}
    assert msgs[1] == {"ok": 1}


def test_blank_lines_are_ignored():
    d = Decoder()
    assert d.feed(b"\n\n" + encode({"x": 1}) + b"\n") == [{"x": 1}]
