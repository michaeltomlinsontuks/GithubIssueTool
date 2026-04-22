"""generate-skill: Read config files and produce an AI skill prompt."""

from __future__ import annotations

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
    """Generate a markdown table of available issue types (hierarchy levels)."""
    lines = [
        "| Type Key | GitHub Type | Default Labels | Body Fields |",
        "|----------|-------------|----------------|-------------|",
    ]
    for level in config.hierarchy.levels:
        gh_type = level.github_type if level.github_type else "—"
        labels_str = ", ".join(level.default_labels) if level.default_labels else "*(none)*"
        fields = _extract_template_fields(level.body_template) if level.body_template else []
        fields_str = ", ".join(fields) if fields else "*(none)*"
        lines.append(f"| `{level.name}` | {gh_type} | {labels_str} | {fields_str} |")
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

    prompt = f"""\
# GitHub Issue Planner — AI Skill

You are a GitHub issue planner for the **{repo}** project. Your job is to break down
work into well-structured GitHub issues following the project's configured hierarchy
and issue types.

## Output Format

You MUST output valid JSON matching this exact structure. Do NOT include any text
before or after the JSON block.

```json
{{
  "issues": [
    {{
      "id": "unique-local-id",
      "title": "Issue title (without type prefix — the tool adds it)",
      "type": "type_key",
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

## Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Unique local ID for this issue (not sent to GitHub). Use kebab-case. |
| `title` | string | ✅ | Issue title. Do NOT include type prefixes (emojis) — the tool adds them. |
| `type` | string | ✅ | Must be one of the type keys listed below. |
| `body` | object | ✅ | Key-value pairs matching the body template fields for this type. |
| `labels` | string[] | ❌ | Additional labels. Type default labels are added automatically. |
| `milestone` | string | ❌ | Exact milestone title. Use `null` if not applicable. |
| `assignees` | string[] | ❌ | GitHub usernames. Use `[]` if no assignee. |
| `project` | int | ❌ | Project board number. Use `null` if not applicable. |
| `children` | object[] | ❌ | Child issues (recursive). Must follow hierarchy rules. |

---

## Available Issue Types

{types_table}

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
2. **Follow hierarchy rules** — Parent-child relationships must be valid.
3. **Fill all body fields** — Every field in the type's body template must be provided.
4. **Unique IDs** — Every `id` must be unique across the entire JSON.
5. **No title prefixes** — Do not add emoji prefixes to titles; the tool does this.
6. **Markdown in body fields** — Use Markdown formatting (checklists, headers, etc.)
   in body field values.
7. **Use kebab-case IDs** — e.g., `auth-login-endpoint`, not `authLoginEndpoint`.

---

## Example

```json
{{
  "issues": [
    {{
      "id": "auth-epic",
      "title": "User Authentication System",
      "type": "epic",
      "body": {{
        "description": "Implement complete user authentication including JWT and session management.",
        "goals": "- Secure API access\\n- Token refresh flow\\n- Role-based permissions"
      }},
      "labels": ["backend"],
      "milestone": {f'"{config.milestones.milestones[0]}"' if config.milestones.milestones else 'null'},
      "assignees": {f'["{config.assignees.assignees[0]}"]' if config.assignees.assignees else '[]'},
      "project": {config.repo_info.projects[0].number if config.repo_info.projects else 'null'},
      "children": [
        {{
          "id": "auth-login-story",
          "title": "Login Flow",
          "type": "story",
          "body": {{
            "description": "As a user, I want to log in so I can access my account.",
            "acceptance_criteria": "- [ ] POST /auth/login returns JWT\\n- [ ] Invalid credentials return 401"
          }},
          "labels": ["backend"],
          "milestone": {f'"{config.milestones.milestones[0]}"' if config.milestones.milestones else 'null'},
          "assignees": [],
          "project": null,
          "children": [
            {{
              "id": "auth-login-endpoint",
              "title": "Implement POST /auth/login endpoint",
              "type": "task",
              "body": {{
                "description": "Create the login endpoint that validates credentials and returns a JWT pair."
              }},
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
  ]
}}
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
