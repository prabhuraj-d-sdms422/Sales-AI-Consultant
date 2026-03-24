import pytest

from app.agents.orchestrator import _parse_orchestrator_response


def test_parse_valid_json():
    result = _parse_orchestrator_response(
        '{"intent":"GREETING","confidence":0.95,"next_agent":"discovery"}'
    )
    assert result["intent"] == "GREETING"


def test_parse_malformed_returns_default():
    result = _parse_orchestrator_response("invalid json")
    assert result["intent"] == "GENERAL_INQUIRY"
    assert result["next_agent"] == "discovery"
