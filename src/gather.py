"""gather-config: Pull repo metadata from GitHub via gh CLI into YAML config files."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml
from rich.console import Console

console = Console()


def _run_gh(args: list[str], repo: str | None = None, input_data: str | None = None) -> str:
    """Run a gh CLI command and return stdout."""
    cmd = ["gh"] + args
    if repo:
        cmd.extend(["--repo", repo])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            input=input_data,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        console.print(f"[red]gh command failed:[/red] {' '.join(cmd)}")
        console.print(f"[red]stderr:[/red] {e.stderr.strip()}")
        raise


def _run_gh_json(args: list[str], repo: str | None = None, input_data: str | None = None) -> list | dict:
    """Run a gh CLI command and parse JSON output."""
    output = _run_gh(args, repo=repo, input_data=input_data)
    if not output:
        return []
    return json.loads(output)


def gather_repo_info(repo: str) -> dict:
    """Fetch repo name, owner, and owner type."""
    data = _run_gh_json(["api", f"repos/{repo}"])
    owner_data = data.get("owner", {})
    owner = owner_data.get("login", repo.split("/")[0])
    owner_type = owner_data.get("type", "Organization")
    return {
        "repo": repo,
        "owner": owner,
        "owner_type": owner_type,
    }


def gather_milestones(repo: str) -> list[str]:
    """Fetch milestone titles from the repo."""
    try:
        output = _run_gh(
            ["api", f"repos/{repo}/milestones", "--jq", ".[].title"],
            repo=None,
        )
        if not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]
    except subprocess.CalledProcessError:
        console.print("[yellow]Warning: Could not fetch milestones[/yellow]")
        return []


def gather_labels(repo: str) -> list[dict]:
    """Fetch labels from the repo."""
    try:
        data = _run_gh_json(
            ["label", "list", "--json", "name,color,description", "--limit", "200"],
            repo=repo,
        )
        return [
            {
                "name": label["name"],
                "color": label.get("color", ""),
                "description": label.get("description", ""),
            }
            for label in data
        ]
    except subprocess.CalledProcessError:
        console.print("[yellow]Warning: Could not fetch labels[/yellow]")
        return []


def gather_assignees(repo: str) -> list[str]:
    """Fetch assignable users from the repo."""
    try:
        output = _run_gh(
            ["api", f"repos/{repo}/assignees", "--jq", ".[].login"],
            repo=None,
        )
        if not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]
    except subprocess.CalledProcessError:
        console.print("[yellow]Warning: Could not fetch assignees[/yellow]")
        return []


def gather_projects_by_title(
    repo: str,
    owner: str,
    owner_type: str = "Organization",
) -> list[dict]:
    """
    Find owner-owned ProjectsV2 whose title matches the repo name.
    Requires you to enforce naming convention: project title == repo.

    For organization repos, queries `organization(login: ...)`.
    For user repos, queries `user(login: ...)`.
    """
    try:
        _owner, repo_name = repo.split("/", 1)

        owner_type_lower = owner_type.lower()
        if owner_type_lower == "organization":
            root_field = "organization"
        elif owner_type_lower == "user":
            root_field = "user"
        else:
            return []

        query = (
            "query($owner: String!, $after: String) {"
            f"  {root_field}(login: $owner) {{"
            "    projectsV2(first: 50, after: $after) {"
            "      nodes { number title }"
            "      pageInfo { hasNextPage endCursor }"
            "    }"
            "  }"
            "}"
        )

        matches: list[dict] = []
        after: str = ""

        while True:
            cmd_args = [
                "api", "graphql",
                "-f", f"query={query}",
                "-f", f"owner={owner}",
            ]
            if after:
                cmd_args.extend(["-f", f"after={after}"])

            data = _run_gh_json(cmd_args)

            owner_data = (data or {}).get("data", {}).get(root_field)
            if not owner_data:
                return []

            pv2 = owner_data["projectsV2"]
            for n in (pv2.get("nodes") or []):
                if not n:
                    continue
                if (n.get("title") or "").strip() == repo_name:
                    matches.append({"number": n["number"], "title": n.get("title") or ""})

            page = pv2["pageInfo"]
            if not page["hasNextPage"]:
                break
            after = page["endCursor"] or ""

        return matches

    except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError):
        console.print("[yellow]Warning: Could not fetch projects[/yellow]")
        return []

def gather_issue_types(repo: str, owner_type: str = "Organization") -> list[dict]:
    """Fetch native GitHub issue types available for this repo.

    Issue types are defined at the org level. We try the org endpoint first;
    if the repo owner is not an org, we return an empty list.
    """
    if owner_type.lower() != "organization":
        return []

    try:
        owner = repo.split("/")[0]
        output = _run_gh(
            ["api", f"orgs/{owner}/issue-types", "--jq", '.[] | {name, description}'],
            repo=None,
        )
        if not output:
            return []
        types = []
        for line in output.splitlines():
            if line.strip():
                types.append(json.loads(line))
        return types
    except subprocess.CalledProcessError:
        # Not an org, or issue types not enabled
        return []


def _write_yaml(path: Path, data: dict, header: str = "") -> None:
    """Write a dict to a YAML file with an optional header comment."""
    with open(path, "w", encoding="utf-8") as f:
        if header:
            for line in header.strip().splitlines():
                f.write(f"# {line}\n")
            f.write("\n")
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _write_raw(path: Path, content: str) -> None:
    """Write raw text content to a file."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ─── Hierarchy Starter Template ─────────────────────────────────────────────


def _hierarchy_template(github_types: list[dict], labels: list[dict]) -> str:
    """Generate a starter hierarchy.yaml template.

    Includes level definitions with body templates, title prefixes,
    default labels, and optional github_type mappings. This is the
    user-editable config that persists between gather-config runs.
    """
    # Pre-map GitHub native types to hierarchy levels
    bug_type = next(
        (t["name"] for t in github_types if "bug" in t.get("name", "").lower()), ""
    )
    feature_type = next(
        (t["name"] for t in github_types if "feature" in t.get("name", "").lower()), ""
    )
    task_type = next(
        (t["name"] for t in github_types if "task" in t.get("name", "").lower()), ""
    )

    # Build a comment listing available labels for reference
    label_names = [l["name"] for l in labels]
    label_set = set(label_names)
    labels_comment = ", ".join(label_names) if label_names else "(none found)"

    epic_label = "epic" if "epic" in label_set else ""
    story_label = "story" if "story" in label_set else ""
    task_label = "task" if "task" in label_set else ""
    subtask_label = "subtask" if "subtask" in label_set else ""
    bug_label = "bug" if "bug" in label_set else ""
    chore_label = "chore" if "chore" in label_set else ""

    return f"""\
# Issue hierarchy — defines parent-child relationships AND level configuration
# This file is user-editable and is NOT overwritten by gather-config.
#
# Each level defines:
#   - name: the hierarchy level key used in AI-generated JSON
#   - can_have_children: which levels can be nested under this one
#   - title_prefix: emoji/text prepended to issue titles
#   - hierarchy_label: canonical label that identifies this level
#   - default_labels: labels automatically applied (must exist in labels.yaml)
#   - github_type: maps to a GitHub native issue type (must exist in types.yaml)
#   - body_template: markdown template with {{field_name}} placeholders
#
# Available labels from repo: {labels_comment}
# Available GitHub types from repo: {', '.join(t['name'] for t in github_types) if github_types else '(none found)'}

hierarchy:
  levels:
    - name: epic
      can_have_children:
        - story
        - task
      title_prefix: "🏔️ "
      hierarchy_label: "{epic_label}"
      default_labels: []
      github_type: ""
      body_template: |
        ## Epic Overview
        {{description}}

        ## Goals
        {{goals}}

    - name: story
      can_have_children:
        - task
        - subtask
      title_prefix: "📖 "
      hierarchy_label: "{story_label}"
      default_labels: []
      github_type: "{feature_type}"
      body_template: |
        ## User Story
        {{description}}

        ## Acceptance Criteria
        {{acceptance_criteria}}

    - name: task
      can_have_children:
        - subtask
      title_prefix: "📋 "
      hierarchy_label: "{task_label}"
      default_labels: []
      github_type: "{task_type}"
      body_template: |
        ## Task
        {{description}}

    - name: subtask
      can_have_children: []
      title_prefix: "🔹 "
      hierarchy_label: "{subtask_label}"
      default_labels: []
      github_type: ""
      body_template: |
        ## Sub-task
        {{description}}

    - name: bug
      can_have_children:
        - subtask
      title_prefix: "🐛 "
      hierarchy_label: "{bug_label}"
      default_labels: []
      github_type: "{bug_type}"
      body_template: |
        ## Bug Description
        {{description}}

        ## Steps to Reproduce
        {{steps}}

        ## Expected Behaviour
        {{expected}}

    - name: chore
      can_have_children:
        - subtask
      title_prefix: "🔧 "
      hierarchy_label: "{chore_label}"
      default_labels: []
      github_type: "{task_type}"
      body_template: |
        ## Description
        {{description}}

# How parent-child relationships are created on GitHub
linking:
  # sub_issues — uses GitHub's native sub-issues API (recommended, GA since 2025)
  # body_reference — adds "Parent: #123" to child issue body
  # task_list — adds "- [ ] #456" task list items to parent issue body
  method: sub_issues

  # Only used when method is body_reference:
  # parent_prefix: "Parent: "
"""


# ─── Main gather-config Command ─────────────────────────────────────────────


def gather_config(repo: str, config_dir: str = "./config") -> None:
    """Pull repo metadata from GitHub and write YAML config files.

    Auto-generated files (always overwritten):
      - repo.yaml, milestones.yaml, labels.yaml, assignees.yaml, types.yaml

    User-editable files (only created if missing):
      - hierarchy.yaml
    """
    config_path = Path(config_dir)
    config_path.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[bold blue]Gathering config from [cyan]{repo}[/cyan]...[/bold blue]\n")

    # 1. Repo info
    console.print("  📦 Fetching repo info...")
    repo_data = gather_repo_info(repo)
    owner = repo_data["owner"]
    owner_type = repo_data.get("owner_type", "Organization")

    # 2. Projects
    console.print("  📋 Fetching projects...")
    projects = gather_projects_by_title(repo, owner, owner_type)
    repo_data["projects"] = projects
    _write_yaml(
        config_path / "repo.yaml",
        repo_data,
        header="Auto-generated by gather-config — feel free to edit",
    )
    console.print(f"    ✅ repo.yaml ({len(projects)} projects)")

    # 3. Milestones
    console.print("  🏁 Fetching milestones...")
    milestones = gather_milestones(repo)
    _write_yaml(
        config_path / "milestones.yaml",
        {"milestones": milestones},
        header="Auto-generated from repo — these are the milestones available for issues",
    )
    console.print(f"    ✅ milestones.yaml ({len(milestones)} milestones)")

    # 4. Labels
    console.print("  🏷️  Fetching labels...")
    labels = gather_labels(repo)
    _write_yaml(
        config_path / "labels.yaml",
        {"labels": labels},
        header="Auto-generated from repo — these are the labels available for issues",
    )
    console.print(f"    ✅ labels.yaml ({len(labels)} labels)")

    # 5. Assignees
    console.print("  👥 Fetching assignees...")
    assignees = gather_assignees(repo)
    _write_yaml(
        config_path / "assignees.yaml",
        {"assignees": assignees},
        header="Auto-generated from repo — valid GitHub usernames for assignment",
    )
    console.print(f"    ✅ assignees.yaml ({len(assignees)} assignees)")

    # 6. GitHub native issue types — ALWAYS OVERWRITTEN (like labels)
    console.print("  🔖 Fetching issue types...")
    github_types = gather_issue_types(repo, owner_type)
    types_data = [
        {"name": t["name"], "description": t.get("description", "")}
        for t in github_types
    ]
    _write_yaml(
        config_path / "types.yaml",
        {"types": types_data},
        header=(
            "Auto-generated from repo — GitHub native issue types available.\n"
            "This file is always overwritten by gather-config."
        ),
    )
    console.print(f"    ✅ types.yaml ({len(github_types)} types)")

    # 7. Hierarchy template (only created if missing — this is user-editable)
    hierarchy_path = config_path / "hierarchy.yaml"
    if not hierarchy_path.exists():
        _write_raw(hierarchy_path, _hierarchy_template(github_types, labels))
        console.print("    ✅ hierarchy.yaml (starter template created)")
    else:
        console.print("    ⏭️  hierarchy.yaml already exists — preserved")

    console.print(
        f"\n[bold green]✅ Config gathered successfully![/bold green]"
        f"\n   Config directory: [cyan]{config_path.resolve()}[/cyan]"
        f"\n"
        f"\n[bold yellow]Next steps:[/bold yellow]"
        f"\n   1. Review and edit [cyan]hierarchy.yaml[/cyan] — customise hierarchy levels, body templates, and labels"
        f"\n   2. Run [cyan]generate-skill[/cyan] to create the AI skill prompt"
        f"\n"
    )
