"""generate-skill: Read config files and produce an AI skill prompt."""

from __future__ import annotations

import json
import re
from pathlib import Path

from rich.console import Console

from src.config_loader import load_project_config
from src.models import ProjectConfig

console = Console()


def _extract_template_fields(template: str) -> list[str]:
    """Extract {field_name} placeholders from a body template."""
    return re.findall(r"\{(\w+)\}", template)


def _generate_types_table(config: ProjectConfig) -> str:
    """Generate a markdown table of hierarchy levels and labels."""
    lines = [
        "| Level Key | Hierarchy Label | GitHub Type | Default Labels | Body Fields |",
        "|-----------|-----------------|-------------|----------------|-------------|",
    ]
    for level in config.hierarchy.levels:
        hierarchy_label = config.get_hierarchy_label_for_type(level.name) or "—"
        gh_type = level.github_type if level.github_type else "—"
        labels_str = ", ".join(level.default_labels) if level.default_labels else "*(none)*"
        fields = _extract_template_fields(level.body_template) if level.body_template else []
        fields_str = ", ".join(fields) if fields else "*(none)*"
        lines.append(
            f"| `{level.name}` | `{hierarchy_label}` | {gh_type} | {labels_str} | {fields_str} |"
        )
    return "\n".join(lines)


def _generate_hierarchy_rules(config: ProjectConfig) -> str:
    """Generate hierarchy rules section."""
    lines = []
    for level in config.hierarchy.levels:
        children = ", ".join(f"`{c}`" for c in level.can_have_children) if level.can_have_children else "*(none — leaf node)*"
        lines.append(f"- `{level.name}` can contain: {children}")
    return "\n".join(lines)


def _generate_body_templates(config: ProjectConfig) -> str:
    """Generate body template documentation for each type."""
    sections = []
    for level in config.hierarchy.levels:
        if not level.body_template:
            continue
        fields = _extract_template_fields(level.body_template)
        field_list = "\n".join(f"  - `{f}` — *(string, required)*" for f in fields)
        sections.append(
            f"### `{level.name}`\n\n"
            f"Body fields:\n{field_list}\n\n"
            f"Template:\n```\n{level.body_template.strip()}\n```"
        )
    return "\n\n".join(sections)


def _sample_body_for_level(level_name: str, config: ProjectConfig) -> dict[str, str]:
    """Build a sample body object for a level using its template fields."""
    level = config.hierarchy.get_level(level_name)
    if not level or not level.body_template:
        return {"description": "Example description"}

    fields = _extract_template_fields(level.body_template)
    body: dict[str, str] = {}
    for field in fields:
        if "acceptance" in field.lower() or "criteria" in field.lower():
            body[field] = "- [ ] Example acceptance criterion"
        elif "steps" in field.lower():
            body[field] = "1. Example step"
        else:
            body[field] = f"Example {field.replace('_', ' ')}"
    return body


def _build_example_json(config: ProjectConfig) -> str:
    """Build a config-driven example JSON snippet.

    Avoids hard-coding level names (epic/story/task/etc.) so the example remains
    valid for custom hierarchies.
    """
    levels = config.hierarchy.levels
    if not levels:
        fallback = {
            "issues": [
                {
                    "id": "example-issue",
                    "title": "Example Issue",
                    "type": None,
                    "body": {},
                    "labels": [],
                    "milestone": None,
                    "assignees": [],
                    "project": None,
                    "children": [],
                }
            ]
        }
        return json.dumps(fallback, indent=2)

    # Build a simple chain up to 3 levels deep using can_have_children.
    chain: list[str] = [levels[0].name]
    while len(chain) < 3:
        current = config.hierarchy.get_level(chain[-1])
        if not current or not current.can_have_children:
            break
        child_name = current.can_have_children[0]
        if config.hierarchy.get_level(child_name) is None:
            break
        chain.append(child_name)

    # Build from leaf upward.
    child_payload: list[dict] = []
    for idx in range(len(chain) - 1, -1, -1):
        level_name = chain[idx]

        issue_type: str | None = level_name
        labels: list[str] = []

        # Demonstrate label-driven inference on the leaf, when possible.
        if idx == len(chain) - 1:
            hierarchy_label = config.get_hierarchy_label_for_type(level_name)
            if hierarchy_label:
                issue_type = None
                labels = [hierarchy_label]

        issue = {
            "id": f"example-{level_name}",
            "title": f"Example {level_name.replace('_', ' ').title()}",
            "type": issue_type,
            "body": _sample_body_for_level(level_name, config),
            "labels": labels,
            "milestone": config.milestones.milestones[0] if idx == 0 and config.milestones.milestones else None,
            "assignees": [config.assignees.assignees[0]] if idx == 0 and config.assignees.assignees else [],
            "project": config.repo_info.projects[0].number if idx == 0 and config.repo_info.projects else None,
            "children": child_payload,
        }
        child_payload = [issue]

    return json.dumps({"issues": child_payload}, indent=2)


def generate_skill_prompt(config: ProjectConfig) -> str:
    """Generate the full AI skill prompt markdown."""
    repo = config.repo_info.repo

    # Valid values lists
    milestones_list = "\n".join(f'- `"{m}"`' for m in config.milestones.milestones)
    if not milestones_list:
        milestones_list = "*(no milestones configured)*"

    labels_list = ", ".join(f"`{l.name}`" for l in config.labels.labels)
    if not labels_list:
        labels_list = "*(no labels configured)*"

    assignees_list = ", ".join(f"`{a}`" for a in config.assignees.assignees)
    if not assignees_list:
        assignees_list = "*(no assignees configured)*"

    projects_list = "\n".join(
        f"- `{p.number}` — {p.title}" for p in config.repo_info.projects
    )
    if not projects_list:
        projects_list = "*(no projects configured)*"

    types_table = _generate_types_table(config)
    hierarchy_rules = _generate_hierarchy_rules(config)
    body_templates = _generate_body_templates(config)
    example_json = _build_example_json(config)
    hierarchy_labels_map = config.get_hierarchy_label_map()
    hierarchy_labels_list = "\n".join(
        f"- `{level}` → `{label}`" for level, label in sorted(hierarchy_labels_map.items())
    )
    if not hierarchy_labels_list:
        hierarchy_labels_list = "*(no hierarchy labels configured)*"

    prompt = f"""\
# GitHub Issue Planner — AI Skill

You are a GitHub issue planner for the **{repo}** project. Your job is to break down
work into well-structured GitHub issues following the project's configured hierarchy
and hierarchy labels.

## Output Format

You MUST output valid JSON matching this exact structure. Do NOT include any text
before or after the JSON block.

```json
{{
  "issues": [
    {{
      "id": "unique-local-id",
      "title": "Issue title (without type prefix — the tool adds it)",
      "type": "level_key_or_null",
      "body": {{
        "field_name": "field value"
      }},
      "labels": ["label1", "label2"],
      "milestone": "Milestone Title",
      "assignees": ["username"],
      "project": 1,
      "children": [
        {{
          "id": "child-id",
          "title": "Child issue title",
          "type": "task",
          "body": {{"description": "..."}},
          "labels": [],
          "milestone": null,
          "assignees": [],
          "project": null,
          "children": []
        }}
      ]
    }}
  ]
}}
```

### Hard Schema Guardrails (must follow)

- Use **only** these issue keys: `id`, `title`, `type`, `body`, `labels`, `milestone`, `assignees`, `project`, `children`.
- Do **not** use unsupported keys such as `assignee`, `point`, `points`, `story_points`, `estimate`.
- `body` must be an object where **every value is a string**.
- Do not use arrays/objects inside `body` values. Convert checklists and DoD into markdown strings.

Example (valid):
```json
{{
  "body": {{
    "description": "Implement login flow",
    "acceptance_criteria": "- [ ] User can log in\\n- [ ] Invalid credentials show error",
    "definition_of_done": "- Code reviewed\\n- Tests passing"
  }}
}}
```

## Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Unique local ID for this issue (not sent to GitHub). Use kebab-case. |
| `title` | string | ✅ | Issue title. Do NOT include type prefixes (emojis) — the tool adds them. |
| `type` | string\\|null | ❌ | Optional hierarchy level key. If omitted, the tool infers level from hierarchy labels. |
| `body` | object | ✅ | Key-value pairs matching the body template fields for this type. |
| `labels` | string[] | ❌ | Additional labels. Level default labels are added automatically. |
| `milestone` | string | ❌ | Exact milestone title. Use `null` if not applicable. |
| `assignees` | string[] | ❌ | GitHub usernames. Use `[]` if no assignee. |
| `project` | int | ❌ | Project board number. Use `null` if not applicable. |
| `children` | object[] | ❌ | Child issues (recursive). Must follow hierarchy rules. |

---

## Available Hierarchy Levels

{types_table}

## Hierarchy Labels

These labels define hierarchy semantics. In label-driven mode, include exactly one hierarchy label per issue:

{hierarchy_labels_list}

## Body Templates

{body_templates}

---

## Hierarchy Rules

Issues follow a strict hierarchy. A parent issue can only contain children of the
allowed types:

{hierarchy_rules}

**Rules:**
- Root-level issues (in the top-level `issues` array) can be any type
- Child issues MUST follow the hierarchy rules above
- You can nest up to 8 levels deep (GitHub sub-issues limit)

---

## Valid Values

### Milestones
{milestones_list}

Use `null` if the issue doesn't belong to a milestone.

### Labels
{labels_list}

Only use labels from this list. Type default labels are added automatically — you
don't need to repeat them.

### Assignees
{assignees_list}

Use `[]` for unassigned issues.

### Projects
{projects_list}

Use `null` if the issue doesn't belong to a project.

---

## Constraints

1. **Only use valid values** — Every type, label, milestone, assignee, and project
   must come from the lists above.
2. **Hierarchy is label-driven** — Include exactly one hierarchy label per issue (or provide `type`).
3. **Follow hierarchy rules** — Parent-child relationships must be valid.
4. **Fill all body fields** — Every field in the type's body template must be provided.
5. **Unique IDs** — Every `id` must be unique across the entire JSON.
6. **No title prefixes** — Do not add emoji prefixes to titles; the tool does this.
7. **Markdown in body fields** — Use Markdown formatting (checklists, headers, etc.)
   in body field values.
8. **Use kebab-case IDs** — e.g., `auth-login-endpoint`, not `authLoginEndpoint`.
9. **No unsupported fields** — Never emit `assignee` or `points`; use `assignees` and allowed schema keys only.
10. **Body values are strings only** — Flatten arrays/objects into markdown text in a single string value.
11. **Pre-flight self-check** — Before final output, verify every issue object has only allowed keys and each `body` value is a string.

---

## Example

```json
{example_json}
```
"""
    return prompt


def generate_skill(
    config_dir: str = "./config",
    output_path: str = "skill/github_issues.md",
) -> None:
    """Load configs and generate the AI skill prompt file."""
    config = load_project_config(Path(config_dir))

    prompt = generate_skill_prompt(config)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(prompt, encoding="utf-8")

    console.print(f"\n[bold green]✅ Skill prompt generated![/bold green]")
    console.print(f"   Output: [cyan]{output.resolve()}[/cyan]")
    console.print(f"   Hierarchy levels: {len(config.hierarchy.levels)}")
    console.print(f"   Labels: {len(config.labels.labels)}")
    console.print(f"   Milestones: {len(config.milestones.milestones)}")
    console.print(f"   Assignees: {len(config.assignees.assignees)}")
    console.print(
        f"\n[bold yellow]Next step:[/bold yellow]"
        f" Give this skill to an AI, then run [cyan]create-issues[/cyan]"
        f" with the JSON it produces.\n"
    )
