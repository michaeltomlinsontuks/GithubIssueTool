"""Validate AI-generated JSON against config files."""

from __future__ import annotations

import difflib
import json
import re
import subprocess
from pathlib import Path

import jsonschema
from rich.console import Console

from src.models import IssueInput, IssueSet, ProjectConfig, ValidationResult

console = Console()


def _load_json_schema(schema_path: Path) -> dict:
    """Load the JSON Schema file."""
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _fuzzy_match(value: str, valid_values: set[str], n: int = 3) -> list[str]:
    """Find close matches for a misspelled value."""
    return difflib.get_close_matches(value, sorted(valid_values), n=n, cutoff=0.5)


def _extract_template_fields(template: str) -> set[str]:
    """Extract {field_name} placeholders from a body template."""
    return set(re.findall(r"\{(\w+)\}", template))


# ─── Structural Validation ──────────────────────────────────────────────────


def validate_structure(data: dict, schema_path: Path) -> list[str]:
    """Validate JSON data against the JSON Schema. Returns list of error messages."""
    schema = _load_json_schema(schema_path)
    validator = jsonschema.Draft7Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        path_str = " → ".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"[{path_str}] {error.message}")
    return errors


# ─── Duplicate Detection ────────────────────────────────────────────────────


def check_duplicate_title(title: str, repo: str) -> bool:
    """Check if an issue with this exact title already exists in the repo."""
    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--repo", repo,
                "--search", f'"{title}" in:title',
                "--json", "title",
                "--state", "all",
                "--limit", "100",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        if not result.stdout.strip():
            return False
        existing = json.loads(result.stdout)
        # Exact match check (search is fuzzy, we need exact)
        return any(issue["title"] == title for issue in existing)
    except subprocess.CalledProcessError:
        # If we can't check, don't block — just warn
        return False


# ─── Semantic Validation ────────────────────────────────────────────────────


def _validate_issue(
    issue: IssueInput,
    config: ProjectConfig,
    result: ValidationResult,
    path: list[str],
    seen_ids: set[str],
    all_ids: set[str],
    check_duplicates: bool,
) -> None:
    """Recursively validate a single issue and its children."""
    current_path = path + [issue.id]

    # Unique ID check
    if issue.id in seen_ids:
        result.add_error(
            issue_id=issue.id,
            field="id",
            message=f"Duplicate issue ID '{issue.id}' — IDs must be unique within the JSON",
            path=current_path,
        )
    seen_ids.add(issue.id)
    all_ids.add(issue.id)

    # Type validation — type keys are hierarchy level names
    valid_types = config.get_valid_type_keys()
    if issue.type not in valid_types:
        suggestions = _fuzzy_match(issue.type, valid_types)
        result.add_error(
            issue_id=issue.id,
            field="type",
            message=f"Type '{issue.type}' does not exist as a hierarchy level in hierarchy.yaml",
            suggestion=f"Did you mean: {', '.join(suggestions)}?" if suggestions else None,
            path=current_path,
        )

    # Label validation
    valid_labels = config.get_valid_label_names()
    for label in issue.labels:
        if label not in valid_labels:
            suggestions = _fuzzy_match(label, valid_labels)
            result.add_error(
                issue_id=issue.id,
                field="labels",
                message=f"Label '{label}' does not exist in labels.yaml",
                suggestion=f"Did you mean: {', '.join(suggestions)}?" if suggestions else None,
                path=current_path,
            )

    # Milestone validation
    if issue.milestone is not None:
        valid_milestones = config.get_valid_milestone_titles()
        if issue.milestone not in valid_milestones:
            suggestions = _fuzzy_match(issue.milestone, valid_milestones)
            result.add_error(
                issue_id=issue.id,
                field="milestone",
                message=f"Milestone '{issue.milestone}' does not exist in milestones.yaml",
                suggestion=f"Did you mean: {', '.join(suggestions)}?" if suggestions else None,
                path=current_path,
            )

    # Assignee validation
    valid_assignees = config.get_valid_assignees()
    for assignee in issue.assignees:
        if assignee not in valid_assignees:
            suggestions = _fuzzy_match(assignee, valid_assignees)
            result.add_error(
                issue_id=issue.id,
                field="assignees",
                message=f"Assignee '{assignee}' does not exist in assignees.yaml",
                suggestion=f"Did you mean: {', '.join(suggestions)}?" if suggestions else None,
                path=current_path,
            )

    # Project validation
    if issue.project is not None:
        valid_projects = config.get_valid_project_numbers()
        if issue.project not in valid_projects:
            result.add_error(
                issue_id=issue.id,
                field="project",
                message=f"Project number {issue.project} does not exist in repo.yaml",
                path=current_path,
            )

    # Body template field validation — templates now live on hierarchy levels
    level = config.get_level_for_type(issue.type)
    if level and level.body_template:
        expected_fields = _extract_template_fields(level.body_template)
        provided_fields = set(issue.body.keys())
        missing = expected_fields - provided_fields
        extra = provided_fields - expected_fields
        if missing:
            result.add_error(
                issue_id=issue.id,
                field="body",
                message=(
                    f"Missing body fields for type '{issue.type}': "
                    f"{', '.join(sorted(missing))}"
                ),
                path=current_path,
            )
        if extra:
            result.add_warning(
                issue_id=issue.id,
                field="body",
                message=(
                    f"Extra body fields for type '{issue.type}' "
                    f"(will be ignored): {', '.join(sorted(extra))}"
                ),
                path=current_path,
            )

    # Hierarchy validation for children
    if issue.children:
        parent_level = issue.type  # type key IS the level name now

        for child in issue.children:
            child_level = child.type  # type key IS the level name

            if not config.hierarchy.can_parent(parent_level, child_level):
                parent_level_cfg = config.hierarchy.get_level(parent_level)
                allowed = parent_level_cfg.can_have_children if parent_level_cfg else []
                result.add_error(
                    issue_id=child.id,
                    field="hierarchy",
                    message=(
                        f"Hierarchy violation: '{parent_level}' cannot be "
                        f"parent of '{child_level}'"
                    ),
                    suggestion=(
                        f"Allowed children of '{parent_level}': "
                        f"{', '.join(allowed) if allowed else 'none'}"
                    ),
                    path=current_path + [child.id],
                )

    # Duplicate title detection
    if check_duplicates and level:
        full_title = f"{level.title_prefix}{issue.title}"
        if check_duplicate_title(full_title, config.repo_info.repo):
            result.add_warning(
                issue_id=issue.id,
                field="title",
                message=(
                    f"An issue with title '{full_title}' already exists in the repo"
                ),
                path=current_path,
            )

    # Recurse into children
    for child in issue.children:
        _validate_issue(
            child, config, result, current_path, seen_ids, all_ids, check_duplicates
        )


def validate_issues(
    data: dict,
    config: ProjectConfig,
    schema_path: Path | None = None,
    check_duplicates: bool = True,
) -> ValidationResult:
    """
    Run full validation pipeline on AI-generated JSON.

    Pass 1: Structural validation (JSON Schema)
    Pass 2: Semantic validation (cross-reference against config)
    """
    result = ValidationResult()

    # Pass 1: Structural validation
    if schema_path and schema_path.exists():
        structural_errors = validate_structure(data, schema_path)
        for err_msg in structural_errors:
            result.add_error(
                issue_id="(schema)",
                field="structure",
                message=err_msg,
            )
        if structural_errors:
            # Don't continue to semantic validation if structure is broken
            return result

    # Parse into Pydantic models
    try:
        issue_set = IssueSet(**data)
    except Exception as e:
        result.add_error(
            issue_id="(parse)",
            field="structure",
            message=f"Failed to parse issues JSON: {e}",
        )
        return result

    # Pass 2: Semantic validation
    seen_ids: set[str] = set()
    all_ids: set[str] = set()
    for issue in issue_set.issues:
        _validate_issue(
            issue, config, result, [], seen_ids, all_ids, check_duplicates
        )

    return result
