"""Tests for the validator."""

import pytest
from pathlib import Path
import yaml

from src.config_loader import load_project_config
from src.validator import validate_issues, validate_structure, _fuzzy_match, _extract_template_fields


@pytest.fixture
def config_dir(tmp_path):
    """Create a minimal valid config directory."""
    (tmp_path / "repo.yaml").write_text(yaml.dump({
        "repo": "owner/repo",
        "owner": "owner",
        "projects": [{"number": 1, "title": "My Project"}],
    }))
    (tmp_path / "milestones.yaml").write_text(yaml.dump({
        "milestones": ["MVP Release", "Beta Release"],
    }))
    (tmp_path / "labels.yaml").write_text(yaml.dump({
        "labels": [
            {"name": "bug", "color": "d73a4a", "description": ""},
            {"name": "enhancement", "color": "a2eeef", "description": ""},
            {"name": "backend", "color": "008672", "description": ""},
            {"name": "frontend", "color": "7057ff", "description": ""},
            {"name": "testing", "color": "bfd4f2", "description": ""},
            {"name": "security", "color": "ff0000", "description": ""},
        ],
    }))
    (tmp_path / "assignees.yaml").write_text(yaml.dump({
        "assignees": ["michaeltomlinsontuks", "teammate1"],
    }))
    (tmp_path / "types.yaml").write_text(yaml.dump({
        "types": [
            {"name": "Bug", "description": ""},
            {"name": "Feature", "description": ""},
            {"name": "Task", "description": ""},
        ],
    }))
    hierarchy_content = """\
hierarchy:
  levels:
    - name: epic
      can_have_children: [story, task]
      title_prefix: "🏔️ "
      hierarchy_label: "enhancement"
      default_labels: []
      github_type: ""
      body_template: "## Overview\\n{description}\\n\\n## Goals\\n{goals}"

    - name: story
      can_have_children: [task, subtask]
      title_prefix: "📖 "
      hierarchy_label: "frontend"
      default_labels: []
      github_type: "Feature"
      body_template: "## Story\\n{description}\\n\\n## AC\\n{acceptance_criteria}"

    - name: task
      can_have_children: [subtask]
      title_prefix: "📋 "
      hierarchy_label: "backend"
      default_labels: []
      github_type: "Task"
      body_template: "## Task\\n{description}"

    - name: subtask
      can_have_children: []
      title_prefix: "🔹 "
      hierarchy_label: "testing"
      default_labels: []
      body_template: "## Sub-task\\n{description}"

    - name: bug
      can_have_children: [subtask]
      title_prefix: "🐛 "
      hierarchy_label: "bug"
      default_labels: [bug]
      github_type: "Bug"
      body_template: "## Bug\\n{description}\\n\\n## Steps\\n{steps}\\n\\n## Expected\\n{expected}"

linking:
  method: sub_issues
"""
    (tmp_path / "hierarchy.yaml").write_text(hierarchy_content)
    return tmp_path


@pytest.fixture
def config(config_dir):
    return load_project_config(config_dir)


def _make_issue(overrides=None):
    """Create a minimal valid issue dict."""
    issue = {
        "id": "test-issue",
        "title": "Test Issue",
        "type": "task",
        "body": {"description": "Test description"},
        "labels": [],
        "milestone": None,
        "assignees": [],
        "project": None,
        "children": [],
    }
    if overrides:
        issue.update(overrides)
    return issue


# ── Unit Tests ───────────────────────────────────────────────────────────────


def test_fuzzy_match():
    """Test fuzzy matching for suggestions."""
    valid = {"bug", "enhancement", "backend", "frontend", "security"}
    matches = _fuzzy_match("securty", valid)
    assert "security" in matches

    matches = _fuzzy_match("bgu", valid)
    assert "bug" in matches

    matches = _fuzzy_match("zzzzzzz", valid)
    assert len(matches) == 0


def test_extract_template_fields():
    """Test template field extraction."""
    template = "## Desc\n{description}\n\n## Steps\n{steps}\n\n## Expected\n{expected}"
    fields = _extract_template_fields(template)
    assert fields == {"description", "steps", "expected"}


# ── Validation Tests ─────────────────────────────────────────────────────────


def test_valid_issue(config):
    """Test that a valid issue passes validation."""
    data = {"issues": [_make_issue()]}
    result = validate_issues(data, config, check_duplicates=False)
    assert result.is_valid


def test_invalid_type(config):
    """Test that an invalid type produces an error with suggestion."""
    data = {"issues": [_make_issue({"type": "tsk"})]}
    result = validate_issues(data, config, check_duplicates=False)
    assert not result.is_valid
    assert any("tsk" in e.message for e in result.errors)
    assert any(e.suggestion and "task" in e.suggestion for e in result.errors)


def test_infer_type_from_hierarchy_label(config):
    """Test that missing type is inferred from hierarchy label."""
    data = {"issues": [_make_issue({"type": None, "labels": ["backend"]})]}
    result = validate_issues(data, config, check_duplicates=False)
    assert result.is_valid


def test_missing_type_without_hierarchy_label_errors(config):
    """Test that missing type and missing hierarchy label fails."""
    data = {"issues": [_make_issue({"type": None, "labels": ["security"]})]}
    result = validate_issues(data, config, check_duplicates=False)
    assert not result.is_valid
    assert any("could not be inferred" in e.message for e in result.errors)


def test_missing_type_with_ambiguous_hierarchy_labels_errors(config):
    """Test that multiple hierarchy labels without type is ambiguous."""
    data = {
        "issues": [_make_issue({"type": None, "labels": ["backend", "frontend"]})]
    }
    result = validate_issues(data, config, check_duplicates=False)
    assert not result.is_valid
    assert any("ambiguous" in e.message for e in result.errors)


def test_explicit_type_conflicts_with_hierarchy_label(config):
    """Test explicit type must match provided hierarchy label."""
    data = {
        "issues": [_make_issue({"type": "task", "labels": ["frontend"]})]
    }
    result = validate_issues(data, config, check_duplicates=False)
    assert not result.is_valid
    assert any("implies type" in e.message for e in result.errors)


def test_invalid_label(config):
    """Test that an invalid label produces an error."""
    data = {"issues": [_make_issue({"labels": ["securty"]})]}
    result = validate_issues(data, config, check_duplicates=False)
    assert not result.is_valid
    assert any("securty" in e.message for e in result.errors)
    assert any(e.suggestion and "security" in e.suggestion for e in result.errors)


def test_invalid_milestone(config):
    """Test that an invalid milestone produces an error."""
    data = {"issues": [_make_issue({"milestone": "v99"})]}
    result = validate_issues(data, config, check_duplicates=False)
    assert not result.is_valid
    assert any("v99" in e.message for e in result.errors)


def test_invalid_assignee(config):
    """Test that an invalid assignee produces an error."""
    data = {"issues": [_make_issue({"assignees": ["nobody"]})]}
    result = validate_issues(data, config, check_duplicates=False)
    assert not result.is_valid
    assert any("nobody" in e.message for e in result.errors)


def test_invalid_project(config):
    """Test that an invalid project number produces an error."""
    data = {"issues": [_make_issue({"project": 999})]}
    result = validate_issues(data, config, check_duplicates=False)
    assert not result.is_valid
    assert any("999" in e.message for e in result.errors)


def test_missing_body_fields(config):
    """Test that missing body fields produce errors."""
    data = {"issues": [_make_issue({
        "type": "bug",
        "body": {"description": "Bug desc"},  # missing steps, expected
    })]}
    result = validate_issues(data, config, check_duplicates=False)
    assert not result.is_valid
    assert any("steps" in e.message for e in result.errors)
    assert any("expected" in e.message for e in result.errors)


def test_extra_body_fields_warn(config):
    """Test that extra body fields produce warnings (not errors)."""
    data = {"issues": [_make_issue({
        "body": {"description": "Desc", "extra_field": "Extra"},
    })]}
    result = validate_issues(data, config, check_duplicates=False)
    assert result.is_valid  # Warnings don't block
    assert len(result.warnings) > 0


def test_duplicate_ids(config):
    """Test that duplicate IDs produce errors."""
    data = {"issues": [
        _make_issue({"id": "same-id"}),
        _make_issue({"id": "same-id", "title": "Another Issue"}),
    ]}
    result = validate_issues(data, config, check_duplicates=False)
    assert not result.is_valid
    assert any("Duplicate" in e.message for e in result.errors)


def test_hierarchy_violation(config):
    """Test that hierarchy violations produce errors."""
    data = {"issues": [_make_issue({
        "id": "parent",
        "type": "subtask",
        "body": {"description": "Subtask"},
        "children": [_make_issue({
            "id": "child",
            "type": "epic",
            "body": {"description": "Epic desc", "goals": "Goals"},
        })],
    })]}
    result = validate_issues(data, config, check_duplicates=False)
    assert not result.is_valid
    assert any("Hierarchy" in e.message for e in result.errors)


def test_valid_hierarchy(config):
    """Test that valid hierarchy passes."""
    data = {"issues": [_make_issue({
        "id": "parent-epic",
        "type": "epic",
        "body": {"description": "Epic desc", "goals": "Goals"},
        "children": [_make_issue({
            "id": "child-story",
            "type": "story",
            "body": {"description": "Story desc", "acceptance_criteria": "AC"},
            "children": [_make_issue({
                "id": "child-task",
                "type": "task",
                "body": {"description": "Task desc"},
            })],
        })],
    })]}
    result = validate_issues(data, config, check_duplicates=False)
    assert result.is_valid


def test_collects_all_errors(config):
    """Test that validation collects all errors, not just the first."""
    data = {"issues": [_make_issue({
        "type": "nonexistent",
        "labels": ["fake_label"],
        "milestone": "fake_milestone",
        "assignees": ["fake_user"],
    })]}
    result = validate_issues(data, config, check_duplicates=False)
    assert not result.is_valid
    # Should have at least 4 errors (type, label, milestone, assignee)
    assert len(result.errors) >= 4


def test_json_schema_validation():
    """Test structural JSON Schema validation."""
    schema_path = Path(__file__).parent.parent / "schemas" / "issues_schema.json"
    if not schema_path.exists():
        pytest.skip("JSON Schema file not found")

    # Valid
    valid_data = {"issues": [{"id": "x", "title": "X", "type": "task", "body": {}}]}
    errors = validate_structure(valid_data, schema_path)
    assert len(errors) == 0

    # Invalid: missing required field
    invalid_data = {"issues": [{"title": "X"}]}
    errors = validate_structure(invalid_data, schema_path)
    assert len(errors) > 0

    # Invalid: empty issues
    invalid_data2 = {"issues": []}
    errors = validate_structure(invalid_data2, schema_path)
    assert len(errors) > 0
