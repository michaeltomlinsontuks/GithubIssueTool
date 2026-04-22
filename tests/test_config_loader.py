"""Tests for the config loader."""

import pytest
from pathlib import Path
import yaml

from src.config_loader import (
    load_project_config,
    load_repo_config,
    load_milestones_config,
    load_labels_config,
    load_assignees_config,
    load_types_config,
    load_hierarchy_config,
    validate_hierarchy,
)


@pytest.fixture
def config_dir(tmp_path):
    """Create a minimal valid config directory."""
    # repo.yaml
    (tmp_path / "repo.yaml").write_text(yaml.dump({
        "repo": "owner/repo",
        "owner": "owner",
        "projects": [{"number": 1, "title": "My Project"}],
    }))

    # milestones.yaml
    (tmp_path / "milestones.yaml").write_text(yaml.dump({
        "milestones": ["MVP Release", "Beta Release"],
    }))

    # labels.yaml
    (tmp_path / "labels.yaml").write_text(yaml.dump({
        "labels": [
            {"name": "bug", "color": "d73a4a", "description": "Something isn't working"},
            {"name": "enhancement", "color": "a2eeef", "description": "New feature"},
            {"name": "backend", "color": "008672", "description": "Backend work"},
            {"name": "frontend", "color": "7057ff", "description": "Frontend work"},
            {"name": "testing", "color": "bfd4f2", "description": "Testing"},
        ],
    }))

    # assignees.yaml
    (tmp_path / "assignees.yaml").write_text(yaml.dump({
        "assignees": ["michaeltomlinsontuks", "teammate1"],
    }))

    # types.yaml — auto-generated list of GitHub native types
    (tmp_path / "types.yaml").write_text(yaml.dump({
        "types": [
            {"name": "Bug", "description": "Something isn't working"},
            {"name": "Feature", "description": "New feature request"},
            {"name": "Task", "description": "A piece of work"},
        ],
    }))

    # hierarchy.yaml — user-edited with full type config
    hierarchy_content = """\
hierarchy:
  levels:
    - name: epic
      can_have_children: [story, task]
      title_prefix: "🏔️ "
      default_labels: []
      github_type: ""
      body_template: "## Overview\\n{description}\\n\\n## Goals\\n{goals}"

    - name: story
      can_have_children: [task, subtask]
      title_prefix: "📖 "
      default_labels: []
      github_type: "Feature"
      body_template: "## Story\\n{description}\\n\\n## AC\\n{acceptance_criteria}"

    - name: task
      can_have_children: [subtask]
      title_prefix: "📋 "
      default_labels: []
      github_type: "Task"
      body_template: "## Task\\n{description}"

    - name: subtask
      can_have_children: []
      title_prefix: "🔹 "
      default_labels: []
      github_type: ""
      body_template: "## Sub-task\\n{description}"

    - name: bug
      can_have_children: [subtask]
      title_prefix: "🐛 "
      default_labels: [bug]
      github_type: "Bug"
      body_template: "## Bug\\n{description}\\n\\n## Steps\\n{steps}\\n\\n## Expected\\n{expected}"

linking:
  method: sub_issues
"""
    (tmp_path / "hierarchy.yaml").write_text(hierarchy_content)

    return tmp_path


def test_load_project_config(config_dir):
    """Test loading a complete valid config."""
    config = load_project_config(config_dir)
    assert config.repo_info.repo == "owner/repo"
    assert config.repo_info.owner == "owner"
    assert len(config.repo_info.projects) == 1
    assert len(config.milestones.milestones) == 2
    assert len(config.labels.labels) == 5
    assert len(config.assignees.assignees) == 2
    assert len(config.types.types) == 3  # GitHub native types
    assert len(config.hierarchy.levels) == 5  # hierarchy levels
    assert config.hierarchy.linking.method == "sub_issues"


def test_valid_type_keys_are_hierarchy_levels(config_dir):
    """Test that valid type keys come from hierarchy level names."""
    config = load_project_config(config_dir)
    assert config.get_valid_type_keys() == {"epic", "story", "task", "subtask", "bug"}


def test_valid_github_types(config_dir):
    """Test that valid GitHub types come from types.yaml."""
    config = load_project_config(config_dir)
    assert config.get_valid_github_types() == {"Bug", "Feature", "Task"}


def test_valid_label_names(config_dir):
    """Test that valid label names are extracted correctly."""
    config = load_project_config(config_dir)
    assert config.get_valid_label_names() == {"bug", "enhancement", "backend", "frontend", "testing"}


def test_valid_milestone_titles(config_dir):
    """Test that valid milestone titles are extracted correctly."""
    config = load_project_config(config_dir)
    assert config.get_valid_milestone_titles() == {"MVP Release", "Beta Release"}


def test_hierarchy_can_parent(config_dir):
    """Test hierarchy parent-child validation."""
    config = load_project_config(config_dir)
    assert config.hierarchy.can_parent("epic", "story") is True
    assert config.hierarchy.can_parent("epic", "task") is True
    assert config.hierarchy.can_parent("epic", "subtask") is False
    assert config.hierarchy.can_parent("story", "task") is True
    assert config.hierarchy.can_parent("story", "subtask") is True
    assert config.hierarchy.can_parent("task", "subtask") is True
    assert config.hierarchy.can_parent("subtask", "task") is False


def test_get_level_for_type(config_dir):
    """Test looking up hierarchy level config by type key."""
    config = load_project_config(config_dir)
    level = config.get_level_for_type("bug")
    assert level is not None
    assert level.title_prefix == "🐛 "
    assert level.github_type == "Bug"
    assert "bug" in level.default_labels


def test_hierarchy_invalid_default_label(config_dir):
    """Test that invalid default labels in hierarchy raise an error."""
    hierarchy_content = """\
hierarchy:
  levels:
    - name: task
      can_have_children: []
      default_labels: [nonexistent_label]
linking:
  method: sub_issues
"""
    (config_dir / "hierarchy.yaml").write_text(hierarchy_content)

    with pytest.raises(ValueError, match="nonexistent_label"):
        load_project_config(config_dir)


def test_hierarchy_invalid_github_type(config_dir):
    """Test that invalid github_type in hierarchy raises an error."""
    hierarchy_content = """\
hierarchy:
  levels:
    - name: task
      can_have_children: []
      github_type: "NonexistentType"
linking:
  method: sub_issues
"""
    (config_dir / "hierarchy.yaml").write_text(hierarchy_content)

    with pytest.raises(ValueError, match="NonexistentType"):
        load_project_config(config_dir)


def test_hierarchy_invalid_child_reference(config_dir):
    """Test that referencing a non-existent child level raises an error."""
    hierarchy_content = """\
hierarchy:
  levels:
    - name: task
      can_have_children: [nonexistent_level]
linking:
  method: sub_issues
"""
    (config_dir / "hierarchy.yaml").write_text(hierarchy_content)

    with pytest.raises(ValueError, match="nonexistent_level"):
        load_project_config(config_dir)


def test_validate_hierarchy_reports_all_errors(config_dir):
    """Test that validate_hierarchy collects all errors, not just the first."""
    config = load_project_config(config_dir)
    # Inject bad data directly
    config.hierarchy.levels[0].default_labels = ["fake_label"]
    config.hierarchy.levels[0].github_type = "FakeType"
    config.hierarchy.levels[0].can_have_children = ["nonexistent"]

    errors = validate_hierarchy(config)
    assert len(errors) == 3  # bad label, bad github_type, bad child ref


def test_missing_repo_yaml(tmp_path):
    """Test that missing repo.yaml raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_repo_config(tmp_path)


def test_missing_types_returns_empty(tmp_path):
    """Test that missing types.yaml returns empty config."""
    types = load_types_config(tmp_path)
    assert len(types.types) == 0


def test_missing_hierarchy_returns_empty(tmp_path):
    """Test that missing hierarchy.yaml returns empty config."""
    hierarchy = load_hierarchy_config(tmp_path)
    assert len(hierarchy.levels) == 0
