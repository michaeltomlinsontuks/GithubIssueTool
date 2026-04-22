"""Pydantic data models for config files and issue input."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ─── Config Models ──────────────────────────────────────────────────────────


class ProjectInfo(BaseModel):
    """Top-level repo config from repo.yaml."""
    repo: str = Field(..., description="Full repo path, e.g. owner/repo-name")
    owner: str = Field(..., description="Repo owner username or org")
    projects: list[ProjectBoard] = Field(default_factory=list)


class ProjectBoard(BaseModel):
    """A GitHub Projects v2 board."""
    number: int
    title: str


class LabelEntry(BaseModel):
    """A single label from labels.yaml."""
    name: str
    color: str = ""
    description: str = ""


class GitHubIssueType(BaseModel):
    """A native GitHub issue type from types.yaml (auto-generated)."""
    name: str
    description: str = ""


class HierarchyLevel(BaseModel):
    """One level in the issue hierarchy.

    Levels now carry the full type configuration: title prefix, default labels,
    body templates, and an optional mapping to a GitHub native issue type.
    """
    name: str
    can_have_children: list[str] = Field(default_factory=list)
    title_prefix: str = ""
    default_labels: list[str] = Field(default_factory=list)
    hierarchy_label: str = Field(
        default="",
        description="Primary label that identifies this hierarchy level. "
                    "If omitted, the tool falls back to a label matching the level name.",
    )
    body_template: str = ""
    github_type: str = Field(
        default="",
        description="Maps to a GitHub native issue type name from types.yaml. "
                    "If set, the tool passes this as the 'type' field via the API.",
    )


class LinkingConfig(BaseModel):
    """How parent-child relationships are represented on GitHub."""
    method: str = Field(
        default="sub_issues",
        description="One of: sub_issues, body_reference, task_list",
    )
    parent_prefix: str = Field(
        default="Parent: ",
        description="Prefix for body_reference method",
    )

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        allowed = {"sub_issues", "body_reference", "task_list"}
        if v not in allowed:
            raise ValueError(f"Linking method must be one of {allowed}, got '{v}'")
        return v


class HierarchyConfig(BaseModel):
    """Full hierarchy config from hierarchy.yaml.

    Contains level definitions with type configuration (title prefix, default
    labels, body template, github type), parent-child rules, and linking method.
    """
    levels: list[HierarchyLevel] = Field(default_factory=list)
    linking: LinkingConfig = Field(default_factory=LinkingConfig)

    def get_level(self, name: str) -> HierarchyLevel | None:
        """Look up a hierarchy level by name."""
        for level in self.levels:
            if level.name == name:
                return level
        return None

    def get_level_names(self) -> list[str]:
        """Return all level names in order."""
        return [level.name for level in self.levels]

    def can_parent(self, parent_level: str, child_level: str) -> bool:
        """Check if parent_level can have child_level as a child."""
        level = self.get_level(parent_level)
        if level is None:
            return False
        return child_level in level.can_have_children


class MilestoneConfig(BaseModel):
    """Milestones config from milestones.yaml."""
    milestones: list[str] = Field(default_factory=list)


class LabelsConfig(BaseModel):
    """Labels config from labels.yaml."""
    labels: list[LabelEntry] = Field(default_factory=list)

    def get_label_names(self) -> set[str]:
        """Get the set of all valid label names."""
        return {label.name for label in self.labels}


class AssigneesConfig(BaseModel):
    """Assignees config from assignees.yaml."""
    assignees: list[str] = Field(default_factory=list)


class TypesConfig(BaseModel):
    """Native GitHub issue types from types.yaml (auto-generated, always overwritten).

    This is a flat list of type names available in the repo, pulled from GitHub's
    org-level issue types. It is NOT user-editable — body templates, title prefixes,
    and default labels now live in hierarchy.yaml.
    """
    types: list[GitHubIssueType] = Field(default_factory=list)

    def get_type_names(self) -> set[str]:
        """Get the set of all valid GitHub native type names."""
        return {t.name for t in self.types}


class ProjectConfig(BaseModel):
    """Merged config from all YAML files."""
    repo_info: ProjectInfo
    milestones: MilestoneConfig
    labels: LabelsConfig
    assignees: AssigneesConfig
    types: TypesConfig
    hierarchy: HierarchyConfig

    def get_valid_type_keys(self) -> set[str]:
        """Valid issue type keys = hierarchy level names."""
        return set(self.hierarchy.get_level_names())

    def get_valid_github_types(self) -> set[str]:
        """Valid GitHub native issue type names from types.yaml."""
        return self.types.get_type_names()

    def get_valid_label_names(self) -> set[str]:
        return self.labels.get_label_names()

    def get_valid_milestone_titles(self) -> set[str]:
        return set(self.milestones.milestones)

    def get_valid_assignees(self) -> set[str]:
        return set(self.assignees.assignees)

    def get_valid_project_numbers(self) -> set[int]:
        return {p.number for p in self.repo_info.projects}

    def get_level_for_type(self, type_key: str) -> HierarchyLevel | None:
        """Get the hierarchy level config for a given type key."""
        return self.hierarchy.get_level(type_key)

    def get_hierarchy_label_for_type(self, type_key: str) -> str:
        """Resolve the canonical hierarchy label for a type key.

        Resolution order:
        1) level.hierarchy_label
        2) label with same name as level (if it exists in labels.yaml)
        3) first default_label (if present)
        """
        level = self.get_level_for_type(type_key)
        if level is None:
            return ""

        valid_labels = self.get_valid_label_names()

        if level.hierarchy_label:
            return level.hierarchy_label

        if level.name in valid_labels:
            return level.name

        if level.default_labels:
            return level.default_labels[0]

        return ""

    def get_hierarchy_label_map(self) -> dict[str, str]:
        """Return {type_key: hierarchy_label} for levels with a resolved label."""
        mapping: dict[str, str] = {}
        for level in self.hierarchy.levels:
            label = self.get_hierarchy_label_for_type(level.name)
            if label:
                mapping[level.name] = label
        return mapping

    def get_hierarchy_labels(self) -> set[str]:
        """Return all resolved hierarchy labels."""
        return set(self.get_hierarchy_label_map().values())


# ─── Issue Input Models ─────────────────────────────────────────────────────


class IssueInput(BaseModel):
    """A single issue from the AI-generated JSON. Recursive via children."""
    id: str = Field(..., description="Local reference key (not sent to GitHub)")
    title: str
    type: Optional[str] = Field(
        default=None,
        description="Optional hierarchy level key. If omitted, the level is inferred from labels.",
    )
    body: dict[str, str] = Field(
        default_factory=dict,
        description="Body fields matching template placeholders for the type",
    )
    labels: list[str] = Field(default_factory=list)
    milestone: Optional[str] = Field(
        default=None,
        description="Exact milestone title from milestones.yaml",
    )
    assignees: list[str] = Field(default_factory=list)
    project: Optional[int] = Field(
        default=None,
        description="Project board number from repo.yaml",
    )
    children: list[IssueInput] = Field(default_factory=list)


class IssueSet(BaseModel):
    """Top-level wrapper for the AI-generated JSON."""
    issues: list[IssueInput] = Field(..., min_length=1)


# ─── Validation Result Models ───────────────────────────────────────────────


class ValidationError(BaseModel):
    """A single validation error."""
    issue_id: str
    field: str
    message: str
    suggestion: Optional[str] = None
    path: list[str] = Field(
        default_factory=list,
        description="Hierarchy path from root to this issue",
    )


class ValidationResult(BaseModel):
    """Aggregated validation results."""
    errors: list[ValidationError] = Field(default_factory=list)
    warnings: list[ValidationError] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(
        self,
        issue_id: str,
        field: str,
        message: str,
        suggestion: str | None = None,
        path: list[str] | None = None,
    ) -> None:
        self.errors.append(
            ValidationError(
                issue_id=issue_id,
                field=field,
                message=message,
                suggestion=suggestion,
                path=path or [],
            )
        )

    def add_warning(
        self,
        issue_id: str,
        field: str,
        message: str,
        suggestion: str | None = None,
        path: list[str] | None = None,
    ) -> None:
        self.warnings.append(
            ValidationError(
                issue_id=issue_id,
                field=field,
                message=message,
                suggestion=suggestion,
                path=path or [],
            )
        )


# ─── Execution Result Models ────────────────────────────────────────────────


class CreatedIssue(BaseModel):
    """Record of a successfully created issue."""
    local_id: str
    number: int
    url: str
    title: str
    type: str
    parent_number: Optional[int] = None


class ExecutionResult(BaseModel):
    """Aggregated execution results."""
    created: list[CreatedIssue] = Field(default_factory=list)
    failed: list[dict] = Field(default_factory=list)
    skipped_duplicates: list[str] = Field(default_factory=list)
