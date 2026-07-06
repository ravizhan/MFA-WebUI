"""Tests for json_utils.py — a thin wrapper around pyjson5 and stdlib json.

Only verifies wrapper delegation: load/loads → pyjson5, dump/dumps → stdlib json
(with formatting kwargs), and the JSONDecodeError alias. pyjson5's own codec
is already rigorously tested upstream.
"""

import io

import pyjson5

import json_utils as json


class TestJSONDecodeErrorAlias:
    """MWU exports a single name for decode errors regardless of backend."""

    def test_alias_is_pyjson5_exception(self):
        assert json.JSONDecodeError is pyjson5.Json5DecoderException


class TestLoadLoads:
    """load/loads delegate to pyjson5."""

    def test_loads_returns_parsed_value(self):
        assert json.loads('{"a": 1}') == {"a": 1}

    def test_load_from_fp(self):
        fp = io.StringIO('{"a": 1}')
        assert json.load(fp) == {"a": 1}


class TestDumpDumps:
    """dump/dumps delegate to stdlib json, forwarding formatting kwargs.

    This is the key wrapper choice: pyjson5.dump ignores formatting kwargs,
    so MWU routes dump/dumps through stdlib json instead.
    """

    def test_dumps_returns_str(self):
        assert json.dumps({"a": 1}) == '{"a": 1}'

    def test_dumps_indent(self):
        assert json.dumps({"a": 1}, indent=2) == '{\n  "a": 1\n}'

    def test_dump_to_fp(self):
        fp = io.StringIO()
        json.dump({"a": 1}, fp)
        assert fp.getvalue() == '{"a": 1}'

    def test_dump_indent(self):
        fp = io.StringIO()
        json.dump({"a": 1}, fp, indent=2)
        assert fp.getvalue() == '{\n  "a": 1\n}'

    def test_dumps_ensure_ascii_false(self):
        result = json.dumps({"char": "ü"}, ensure_ascii=False)
        assert "ü" in result

    def test_dumps_kwargs_separators(self):
        assert json.dumps({"a": 1, "b": 2}, separators=(",", ":")) == '{"a":1,"b":2}'

    def test_dump_kwargs_sort_keys(self):
        fp = io.StringIO()
        json.dump({"b": 1, "a": 2}, fp, sort_keys=True)
        assert fp.getvalue() == '{"a": 2, "b": 1}'
