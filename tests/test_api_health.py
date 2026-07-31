from unittest.mock import patch

from apps.api import main


def test_health_reports_matching_runtime_source() -> None:
    with patch.object(main, "_source_build_id", return_value=main.SOURCE_BUILD_ID):
        result = main.health()

    assert result["build_id"] == main.SOURCE_BUILD_ID
    assert result["current_source_build_id"] == main.SOURCE_BUILD_ID
    assert result["restart_required"] is False


def test_health_requires_restart_when_source_tree_changes() -> None:
    with patch.object(main, "_source_build_id", return_value="changedbuild"):
        result = main.health()

    assert result["build_id"] == main.SOURCE_BUILD_ID
    assert result["current_source_build_id"] == "changedbuild"
    assert result["restart_required"] is True
