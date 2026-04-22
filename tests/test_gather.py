"""Tests for the gather module (mocked — no real gh CLI calls)."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import json
import yaml

from src.gather import (
    gather_repo_info,
    gather_milestones,
    gather_labels,
    gather_assignees,
    gather_projects_by_title,
    gather_issue_types,
    gather_config,
)


def _mock_run_result(stdout="", returncode=0):
    """Create a mock subprocess.CompletedProcess."""
    mock = MagicMock()
    mock.stdout = stdout
    mock.stderr = ""
    mock.returncode = returncode
    return mock


@patch("src.gather.subprocess.run")
def test_gather_repo_info(mock_run):
    """Test that gather_repo_info parses gh repo view output."""
    mock_run.return_value = _mock_run_result(
        json.dumps({"name": "repo", "owner": {"login": "owner"}})
    )
    result = gather_repo_info("owner/repo")
    assert result["repo"] == "owner/repo"
    assert result["owner"] == "owner"


@patch("src.gather.subprocess.run")
def test_gather_milestones(mock_run):
    """Test that milestones are parsed from gh api output."""
    mock_run.return_value = _mock_run_result("MVP Release\nBeta Release\n")
    result = gather_milestones("owner/repo")
    assert result == ["MVP Release", "Beta Release"]


@patch("src.gather.subprocess.run")
def test_gather_milestones_empty(mock_run):
    """Test that empty milestone output returns empty list."""
    mock_run.return_value = _mock_run_result("")
    result = gather_milestones("owner/repo")
    assert result == []


@patch("src.gather.subprocess.run")
def test_gather_labels(mock_run):
    """Test that labels are parsed from gh label list output."""
    mock_run.return_value = _mock_run_result(
        json.dumps([
            {"name": "bug", "color": "d73a4a", "description": "Something broken"},
            {"name": "feature", "color": "a2eeef", "description": "New feature"},
        ])
    )
    result = gather_labels("owner/repo")
    assert len(result) == 2
    assert result[0]["name"] == "bug"


@patch("src.gather.subprocess.run")
def test_gather_assignees(mock_run):
    """Test that assignees are parsed from gh api output."""
    mock_run.return_value = _mock_run_result("michaeltomlinsontuks\nteammate1\n")
    result = gather_assignees("owner/repo")
    assert result == ["michaeltomlinsontuks", "teammate1"]


@patch("src.gather.subprocess.run")
def test_gather_issue_types(mock_run):
    """Test that native issue types are parsed."""
    mock_run.return_value = _mock_run_result(
        '{"name":"Bug","description":"Something broken"}\n'
        '{"name":"Feature","description":"New feature"}\n'
    )
    result = gather_issue_types("owner/repo")
    assert len(result) == 2
    assert result[0]["name"] == "Bug"


@patch("src.gather.subprocess.run")
def test_gather_projects(mock_run):
    """Test that projects are parsed from gh api graphql output."""
    mock_run.return_value = _mock_run_result(
        json.dumps({
            "data": {
                "organization": {
                    "projectsV2": {
                        "nodes": [
                            {"number": 1, "title": "repo"},
                            {"number": 2, "title": "other_repo"}
                        ],
                        "pageInfo": {
                            "hasNextPage": False,
                            "endCursor": None
                        }
                    }
                }
            }
        })
    )
    result = gather_projects_by_title("owner/repo", "owner")
    assert len(result) == 1
    assert result[0]["title"] == "repo"
    assert result[0]["number"] == 1


@patch("src.gather.subprocess.run")
def test_gather_config_creates_files(mock_run, tmp_path):
    """Test that gather_config creates all expected files."""
    def side_effect(cmd, **kwargs):
        cmd_str = " ".join(cmd)
        if "repo view" in cmd_str:
            return _mock_run_result(json.dumps({"name": "repo", "owner": {"login": "owner"}}))
        elif "graphql" in cmd_str:
            return _mock_run_result(json.dumps({
                "data": {"organization": {"projectsV2": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
            }))
        elif "milestones" in cmd_str:
            return _mock_run_result("MVP Release\n")
        elif "label list" in cmd_str:
            return _mock_run_result(json.dumps([{"name": "bug", "color": "d73a4a", "description": ""}]))
        elif "assignees" in cmd_str:
            return _mock_run_result("user1\n")
        elif "issue-types" in cmd_str:
            return _mock_run_result('{"name":"Bug","description":""}\n')
        return _mock_run_result("")

    mock_run.side_effect = side_effect

    config_dir = str(tmp_path / "config")
    gather_config("owner/repo", config_dir=config_dir)

    config_path = Path(config_dir)
    assert (config_path / "repo.yaml").exists()
    assert (config_path / "milestones.yaml").exists()
    assert (config_path / "labels.yaml").exists()
    assert (config_path / "assignees.yaml").exists()
    assert (config_path / "types.yaml").exists()
    assert (config_path / "hierarchy.yaml").exists()

    # types.yaml should be a flat list
    types_data = yaml.safe_load((config_path / "types.yaml").read_text())
    assert isinstance(types_data["types"], list)
    assert types_data["types"][0]["name"] == "Bug"


@patch("src.gather.subprocess.run")
def test_gather_config_always_overwrites_types(mock_run, tmp_path):
    """Test that gather_config ALWAYS overwrites types.yaml."""
    config_dir = str(tmp_path / "config")
    config_path = Path(config_dir)
    config_path.mkdir(parents=True)

    # Pre-create types.yaml with old content
    (config_path / "types.yaml").write_text("types:\n  - name: OldType\n")

    def side_effect(cmd, **kwargs):
        cmd_str = " ".join(cmd)
        if "repo view" in cmd_str:
            return _mock_run_result(json.dumps({"name": "repo", "owner": {"login": "owner"}}))
        elif "graphql" in cmd_str:
            return _mock_run_result(json.dumps({
                "data": {"organization": {"projectsV2": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
            }))
        elif "milestones" in cmd_str:
            return _mock_run_result("")
        elif "label list" in cmd_str:
            return _mock_run_result(json.dumps([]))
        elif "assignees" in cmd_str:
            return _mock_run_result("")
        elif "issue-types" in cmd_str:
            return _mock_run_result('{"name":"NewType","description":"Fresh"}\n')
        return _mock_run_result("")

    mock_run.side_effect = side_effect
    gather_config("owner/repo", config_dir=config_dir)

    # types.yaml should have been overwritten
    types_data = yaml.safe_load((config_path / "types.yaml").read_text())
    assert types_data["types"][0]["name"] == "NewType"


@patch("src.gather.subprocess.run")
def test_gather_config_preserves_existing_hierarchy(mock_run, tmp_path):
    """Test that gather_config does NOT overwrite existing hierarchy.yaml."""
    config_dir = str(tmp_path / "config")
    config_path = Path(config_dir)
    config_path.mkdir(parents=True)

    original_content = "hierarchy:\n  levels:\n    - name: custom\n"
    (config_path / "hierarchy.yaml").write_text(original_content)

    def side_effect(cmd, **kwargs):
        cmd_str = " ".join(cmd)
        if "repo view" in cmd_str:
            return _mock_run_result(json.dumps({"name": "repo", "owner": {"login": "owner"}}))
        elif "graphql" in cmd_str:
            return _mock_run_result(json.dumps({
                "data": {"organization": {"projectsV2": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
            }))
        elif "milestones" in cmd_str:
            return _mock_run_result("")
        elif "label list" in cmd_str:
            return _mock_run_result(json.dumps([]))
        elif "assignees" in cmd_str:
            return _mock_run_result("")
        elif "issue-types" in cmd_str:
            return _mock_run_result("")
        return _mock_run_result("")

    mock_run.side_effect = side_effect
    gather_config("owner/repo", config_dir=config_dir)

    # hierarchy.yaml should be unchanged
    assert (config_path / "hierarchy.yaml").read_text() == original_content


def test_hierarchy_template_includes_hierarchy_labels():
    """Test starter hierarchy template includes hierarchy_label fields."""
    from src.gather import _hierarchy_template

    template = _hierarchy_template(
        github_types=[{"name": "Task", "description": ""}],
        labels=[
            {"name": "epic", "color": "", "description": ""},
            {"name": "story", "color": "", "description": ""},
            {"name": "task", "color": "", "description": ""},
            {"name": "subtask", "color": "", "description": ""},
        ],
    )

    assert "hierarchy_label:" in template
    assert 'hierarchy_label: "epic"' in template
    assert 'hierarchy_label: "story"' in template
