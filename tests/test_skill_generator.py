"""Tests for the skill generator."""

import pytest
from pathlib import Path
import yaml

from src.config_loader import load_project_config
from src.skill_generator import generate_skill_prompt


@pytest.fixture
def config_dir(tmp_path):
    """Create a minimal valid config directory."""
    (tmp_path / "repo.yaml").write_text(yaml.dump({
        "repo": "owner/repo",
        "owner": "owner",
        "projects": [{"number": 1, "title": "My Project"}],
    }))
    (tmp_path / "milestones.yaml").write_text(yaml.dump({
        "milestones": ["MVP Release"],
    }))
    (tmp_path / "labels.yaml").write_text(yaml.dump({
        "labels": [
            {"name": "bug", "color": "d73a4a", "description": ""},
            {"name": "backend", "color": "008672", "description": ""},
        ],
    }))
    (tmp_path / "assignees.yaml").write_text(yaml.dump({
        "assignees": ["michaeltomlinsontuks"],
    }))
    (tmp_path / "types.yaml").write_text(yaml.dump({
        "types": [
            {"name": "Bug", "description": ""},
            {"name": "Task", "description": ""},
        ],
    }))
    hierarchy_content = """\
hierarchy:
  levels:
    - name: task
      can_have_children: []
      title_prefix: "📋 "
      default_labels: []
      github_type: "Task"
      body_template: "## Task\\n{description}"

    - name: bug
      can_have_children: []
      title_prefix: "🐛 "
      default_labels: [bug]
      github_type: "Bug"
      body_template: "## Bug\\n{description}\\n## Steps\\n{steps}"

linking:
  method: sub_issues
"""
    (tmp_path / "hierarchy.yaml").write_text(hierarchy_content)
    return tmp_path


@pytest.fixture
def config(config_dir):
    return load_project_config(config_dir)


def test_generate_skill_contains_repo(config):
    """Test that the skill prompt contains the repo name."""
    prompt = generate_skill_prompt(config)
    assert "owner/repo" in prompt


def test_generate_skill_contains_types(config):
    """Test that the skill prompt lists available types."""
    prompt = generate_skill_prompt(config)
    assert "`task`" in prompt
    assert "`bug`" in prompt


def test_generate_skill_contains_labels(config):
    """Test that the skill prompt lists available labels."""
    prompt = generate_skill_prompt(config)
    assert "`bug`" in prompt
    assert "`backend`" in prompt


def test_generate_skill_contains_milestones(config):
    """Test that the skill prompt lists available milestones."""
    prompt = generate_skill_prompt(config)
    assert "MVP Release" in prompt


def test_generate_skill_contains_assignees(config):
    """Test that the skill prompt lists available assignees."""
    prompt = generate_skill_prompt(config)
    assert "michaeltomlinsontuks" in prompt


def test_generate_skill_contains_hierarchy(config):
    """Test that the skill prompt contains hierarchy rules."""
    prompt = generate_skill_prompt(config)
    assert "Hierarchy" in prompt


def test_generate_skill_contains_body_fields(config):
    """Test that the skill prompt documents body template fields."""
    prompt = generate_skill_prompt(config)
    assert "description" in prompt
    assert "steps" in prompt


def test_generate_skill_contains_json_format(config):
    """Test that the skill prompt contains the JSON output format."""
    prompt = generate_skill_prompt(config)
    assert '"issues"' in prompt
    assert '"children"' in prompt
    assert '"id"' in prompt


def test_generate_skill_contains_constraints(config):
    """Test that the skill prompt contains constraints."""
    prompt = generate_skill_prompt(config)
    assert "Constraints" in prompt
    assert "Only use valid values" in prompt
