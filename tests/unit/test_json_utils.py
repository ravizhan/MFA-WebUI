"""Tests for json_utils.py — thin wrapper around pyjson5 and stdlib json.

Only verifies MWU wrapper contracts: JSONDecodeError alias, load→pyjson5
delegation, and dump formatting kwargs forwarded to stdlib json.
"""

from unittest.mock import patch

import pyjson5

import json_utils as json


class TestJSONDecodeErrorAlias:
    """MWU exports a single name for decode errors regardless of backend."""

    def test_alias_is_pyjson5_exception(self):
        assert json.JSONDecodeError is pyjson5.Json5DecoderException


class TestLoadDelegation:
    """load/loads delegate to pyjson5."""

    def test_loads_delegates_to_pyjson5(self):
        with patch.object(json.pyjson5, "loads", return_value={"delegated": True}) as mock_loads:
            result = json.loads('{"a": 1}')
            mock_loads.assert_called_once_with('{"a": 1}')
            assert result == {"delegated": True}


class TestDumpDelegation:
    """dump/dumps route through stdlib json and forward formatting kwargs.

    Key wrapper choice: pyjson5.dump ignores formatting kwargs, so MWU
    routes dump/dumps through stdlib json instead.
    """

    def test_dumps_forwards_formatting_kwargs_to_stdlib(self):
        with patch.object(
            json._stdlib_json, "dumps", return_value="formatted"
        ) as mock_dumps:
            result = json.dumps({"a": 1}, indent=2, ensure_ascii=False, sort_keys=True)
            mock_dumps.assert_called_once_with(
                {"a": 1},
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            assert result == "formatted"
