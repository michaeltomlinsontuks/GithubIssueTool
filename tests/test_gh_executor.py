"""Tests for the gh_executor module (mocked — no real gh CLI calls)."""

import pytest
from unittest.mock import patch

from src.models import (
    IssueInput, ProjectConfig, ProjectInfo, ProjectBoard,
    MilestoneConfig, LabelsConfig, LabelEntry, AssigneesConfig,
    TypesConfig, GitHubIssueType,
    HierarchyConfig, HierarchyLevel, LinkingConfig,
)
from src.gh_executor import (
    _build_issue_body,
    _build_full_title,
    _merge_labels,
    _get_github_type,
    execute_issues,
)


@pytest.fixture
def config():
    """Create a minimal ProjectConfig for testing."""
    return ProjectConfig(
        repo_info=ProjectInfo(
            repo="owner/repo",
            owner="owner",
            projects=[ProjectBoard(number=1, title="Board")],
        ),
        milestones=MilestoneConfig(milestones=["MVP Release"]),
        labels=LabelsConfig(labels=[
            LabelEntry(name="bug", color="d73a4a"),
            LabelEntry(name="backend", color="008672"),
        ]),
        assignees=AssigneesConfig(assignees=["user1"]),
        types=TypesConfig(types=[
            GitHubIssueType(name="Bug", description=""),
            GitHubIssueType(name="Task", description=""),
        ]),
        hierarchy=HierarchyConfig(
            levels=[
                HierarchyLevel(
                    name="task",
                    can_have_children=[],
                    title_prefix="📋 ",
                    hierarchy_label="backend",
                    default_labels=[],
                    github_type="Task",
                    body_template="## Task\n{description}",
                ),
                HierarchyLevel(
                    name="bug",
                    can_have_children=[],
                    title_prefix="🐛 ",
                    hierarchy_label="bug",
                    default_labels=["bug"],
                    github_type="Bug",
                    body_template="## Bug\n{description}\n\n## Steps\n{steps}",
                ),
            ],
            linking=LinkingConfig(method="sub_issues"),
        ),
    )


def _issue(overrides=None):
    """Create a minimal IssueInput."""
    data = {
        "id": "test",
        "title": "Test Issue",
        "type": "task",
        "body": {"description": "Test desc"},
    }
    if overrides:
        data.update(overrides)
    return IssueInput(**data)


def test_build_full_title(config):
    """Test title prefix application."""
    issue = _issue()
    assert _build_full_title(issue, config) == "📋 Test Issue"


def test_build_full_title_bug(config):
    """Test title prefix for bug type."""
    issue = _issue({"type": "bug", "body": {"description": "d", "steps": "s"}})
    assert _build_full_title(issue, config) == "🐛 Test Issue"


def test_build_issue_body(config):
    """Test body template rendering."""
    issue = _issue()
    body = _build_issue_body(issue, config)
    assert "## Task" in body
    assert "Test desc" in body


def test_build_issue_body_bug(config):
    """Test bug body template rendering."""
    issue = _issue({
        "type": "bug",
        "body": {"description": "Bug desc", "steps": "1. Do thing"},
    })
    body = _build_issue_body(issue, config)
    assert "## Bug" in body
    assert "Bug desc" in body
    assert "1. Do thing" in body


def test_merge_labels_with_defaults(config):
    """Test that default labels are merged with explicit labels."""
    issue = _issue({"type": "bug", "labels": ["backend"],
                    "body": {"description": "d", "steps": "s"}})
    labels = _merge_labels(issue, config)
    assert "backend" in labels
    assert "bug" in labels


def test_merge_labels_no_duplicates(config):
    """Test that default labels don't create duplicates."""
    issue = _issue({"type": "bug", "labels": ["bug", "backend"],
                    "body": {"description": "d", "steps": "s"}})
    labels = _merge_labels(issue, config)
    assert labels.count("bug") == 1


def test_get_github_type(config):
    """Test GitHub native type resolution."""
    issue = _issue({"type": "bug", "body": {"description": "d", "steps": "s"}})
    assert _get_github_type(issue, config) == "Bug"

    issue = _issue({"type": "task"})
    assert _get_github_type(issue, config) == "Task"


def test_dry_run_creates_no_real_issues(config):
    """Test that dry-run mode doesn't call gh."""
    data = {
        "issues": [{
            "id": "test",
            "title": "Test",
            "type": "task",
            "body": {"description": "Test"},
            "labels": [],
            "milestone": None,
            "assignees": [],
            "project": None,
            "children": [],
        }]
    }
    with patch("src.gh_executor._run_gh") as mock_gh:
        result = execute_issues(data, config, dry_run=True)
        mock_gh.assert_not_called()
        assert len(result.created) == 1
        assert result.created[0].number == 0


def test_dry_run_infers_type_from_label(config):
    """Test dry-run can infer type when type is omitted."""
    data = {
        "issues": [{
            "id": "test",
            "title": "Test",
            "type": None,
            "body": {"description": "Test"},
            "labels": ["backend"],
            "milestone": None,
            "assignees": [],
            "project": None,
            "children": [],
        }]
    }
    with patch("src.gh_executor._run_gh") as mock_gh:
        result = execute_issues(data, config, dry_run=True)
        mock_gh.assert_not_called()
        assert len(result.created) == 1
        assert result.created[0].type == "task"
