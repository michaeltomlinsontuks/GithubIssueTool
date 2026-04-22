"""Orchestrate gh CLI calls to create issues with hierarchy and project assignment."""

from __future__ import annotations

import json
import subprocess

from rich.console import Console
from rich.table import Table

from src.models import (
    CreatedIssue,
    ExecutionResult,
    IssueInput,
    IssueSet,
    ProjectConfig,
)

console = Console()


def _resolve_issue_type(issue: IssueInput, config: ProjectConfig) -> str:
    """Resolve issue type from explicit type or hierarchy labels."""
    if issue.type:
        return issue.type

    label_map = config.get_hierarchy_label_map()  # type_key -> hierarchy_label
    matched_types = [
        type_key for type_key, hierarchy_label in label_map.items()
        if hierarchy_label in issue.labels
    ]

    if len(matched_types) == 1:
        return matched_types[0]

    if len(matched_types) == 0:
        raise ValueError(
            "Issue type could not be inferred from labels. "
            "Provide 'type' or include exactly one hierarchy label."
        )

    raise ValueError(
        "Issue type is ambiguous from labels. "
        f"Matched multiple hierarchy labels for types: {', '.join(sorted(matched_types))}."
    )


def _run_gh(args: list[str], input_data: str | None = None) -> str:
    """Run a gh CLI command and return stdout."""
    cmd = ["gh"] + args
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


def _build_issue_body(
    issue: IssueInput,
    config: ProjectConfig,
    resolved_type: str | None = None,
) -> str:
    """Build the full issue body by rendering the level's body template."""
    type_key = resolved_type or issue.type
    level = config.get_level_for_type(type_key) if type_key else None
    if not level or not level.body_template:
        # No template — just join body fields
        return "\n\n".join(f"{v}" for v in issue.body.values())

    # Render template with body fields
    body = level.body_template
    for key, value in issue.body.items():
        body = body.replace(f"{{{key}}}", value)

    return body.strip()


def _build_full_title(
    issue: IssueInput,
    config: ProjectConfig,
    resolved_type: str | None = None,
) -> str:
    """Build the full title with type prefix from hierarchy level."""
    type_key = resolved_type or issue.type
    level = config.get_level_for_type(type_key) if type_key else None
    if level:
        return f"{level.title_prefix}{issue.title}"
    return issue.title


def _merge_labels(
    issue: IssueInput,
    config: ProjectConfig,
    resolved_type: str | None = None,
) -> list[str]:
    """Merge explicit labels with level default labels (deduped)."""
    labels = list(issue.labels)
    type_key = resolved_type or issue.type
    if type_key:
        hierarchy_label = config.get_hierarchy_label_for_type(type_key)
        if hierarchy_label and hierarchy_label not in labels:
            labels.append(hierarchy_label)

    level = config.get_level_for_type(type_key) if type_key else None
    if level:
        for default_label in level.default_labels:
            if default_label not in labels:
                labels.append(default_label)
    return labels


def _get_github_type(
    issue: IssueInput,
    config: ProjectConfig,
    resolved_type: str | None = None,
) -> str:
    """Get the GitHub native issue type for this issue, if configured."""
    type_key = resolved_type or issue.type
    level = config.get_level_for_type(type_key) if type_key else None
    if level:
        return level.github_type
    return ""


def _check_duplicate(title: str, repo: str) -> bool:
    """Check if issue with exact title exists."""
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
        return any(i["title"] == title for i in existing)
    except subprocess.CalledProcessError:
        return False


def create_single_issue(
    issue: IssueInput,
    config: ProjectConfig,
    resolved_type: str | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> CreatedIssue | None:
    """Create a single issue via gh CLI. Returns CreatedIssue or None on failure."""
    repo = config.repo_info.repo
    resolved_type = resolved_type or _resolve_issue_type(issue, config)
    title = _build_full_title(issue, config, resolved_type=resolved_type)
    body = _build_issue_body(issue, config, resolved_type=resolved_type)
    labels = _merge_labels(issue, config, resolved_type=resolved_type)
    github_type = _get_github_type(issue, config, resolved_type=resolved_type)

    if dry_run:
        # Print the command that would be executed
        if github_type:
            cmd_display = (
                f'gh api -X POST repos/{repo}/issues '
                f'--field title="{title}" '
                f'--field body="..." '
                f'--field type="{github_type}"'
            )
            for label in labels:
                cmd_display += f' --field labels[]="{label}"'
        else:
            cmd_display = f'gh issue create --repo {repo} --title "{title}" --body "..."'
            for label in labels:
                cmd_display += f' --label "{label}"'
            if issue.milestone:
                cmd_display += f' --milestone "{issue.milestone}"'
            for assignee in issue.assignees:
                cmd_display += f' --assignee "{assignee}"'

        console.print(f"  [dim]DRY-RUN:[/dim] {cmd_display}")
        return CreatedIssue(
            local_id=issue.id,
            number=0,
            url="(dry-run)",
            title=title,
            type=resolved_type,
        )

    try:
        if github_type:
            # Use gh api to set native issue type
            payload: dict = {
                "title": title,
                "body": body,
                "type": github_type,
            }
            if labels:
                payload["labels"] = labels
            if issue.milestone:
                payload["milestone_title"] = issue.milestone
            if issue.assignees:
                payload["assignees"] = issue.assignees

            result_json = _run_gh(
                ["api", "-X", "POST", f"repos/{repo}/issues", "--input", "-"],
                input_data=json.dumps(payload),
            )
            result_data = json.loads(result_json)
            number = result_data["number"]
            url = result_data["html_url"]
        else:
            # Standard gh issue create
            cmd = [
                "issue", "create",
                "--repo", repo,
                "--title", title,
                "--body", body,
            ]
            for label in labels:
                cmd.extend(["--label", label])
            if issue.milestone:
                cmd.extend(["--milestone", issue.milestone])
            for assignee in issue.assignees:
                cmd.extend(["--assignee", assignee])

            output = _run_gh(cmd)
            url = output.strip().splitlines()[-1]
            number = int(url.rstrip("/").split("/")[-1])

        if verbose:
            console.print(f"  [green]✅ Created #{number}:[/green] {title}")

        return CreatedIssue(
            local_id=issue.id,
            number=number,
            url=url,
            title=title,
            type=resolved_type,
        )
    except Exception as e:
        console.print(f"  [red]❌ Failed to create '{title}':[/red] {e}")
        return None


def link_sub_issue(
    parent_number: int,
    child_number: int,
    repo: str,
    dry_run: bool = False,
    verbose: bool = False,
) -> bool:
    """Link a child issue as a sub-issue of the parent using GitHub's sub-issues API."""
    if dry_run:
        console.print(
            f"  [dim]DRY-RUN: Link #{child_number} as sub-issue of #{parent_number}[/dim]"
        )
        return True

    try:
        # Get the child issue's database ID (numeric, not node ID)
        issue_data = _run_gh([
            "api", f"repos/{repo}/issues/{child_number}",
            "--jq", ".id",
        ])
        child_db_id = int(issue_data.strip())

        # Add as sub-issue via REST API
        payload = json.dumps({"sub_issue_id": child_db_id})
        _run_gh(
            [
                "api", "-X", "POST",
                f"repos/{repo}/issues/{parent_number}/sub_issues",
                "--input", "-",
            ],
            input_data=payload,
        )

        if verbose:
            console.print(
                f"  [blue]🔗 Linked #{child_number} as sub-issue of #{parent_number}[/blue]"
            )
        return True
    except Exception as e:
        console.print(
            f"  [red]❌ Failed to link #{child_number} → #{parent_number}:[/red] {e}"
        )
        return False


def add_body_reference(
    child_number: int,
    parent_number: int,
    repo: str,
    prefix: str = "Parent: ",
    dry_run: bool = False,
) -> bool:
    """Add a parent reference to the child issue body (body_reference linking method)."""
    if dry_run:
        console.print(
            f"  [dim]DRY-RUN: Add '{prefix}#{parent_number}' to #{child_number} body[/dim]"
        )
        return True
    try:
        body = _run_gh([
            "issue", "view", str(child_number),
            "--repo", repo,
            "--json", "body",
            "--jq", ".body",
        ])
        new_body = f"{prefix}#{parent_number}\n\n{body}"
        _run_gh([
            "issue", "edit", str(child_number),
            "--repo", repo,
            "--body", new_body,
        ])
        return True
    except Exception as e:
        console.print(f"  [red]❌ Failed to add body reference:[/red] {e}")
        return False


def add_task_list_item(
    parent_number: int,
    child_number: int,
    repo: str,
    dry_run: bool = False,
) -> bool:
    """Add a task list item referencing the child in the parent issue body."""
    if dry_run:
        console.print(
            f"  [dim]DRY-RUN: Add '- [ ] #{child_number}' to #{parent_number} body[/dim]"
        )
        return True
    try:
        body = _run_gh([
            "issue", "view", str(parent_number),
            "--repo", repo,
            "--json", "body",
            "--jq", ".body",
        ])
        new_body = f"{body}\n- [ ] #{child_number}"
        _run_gh([
            "issue", "edit", str(parent_number),
            "--repo", repo,
            "--body", new_body,
        ])
        return True
    except Exception as e:
        console.print(f"  [red]❌ Failed to add task list item:[/red] {e}")
        return False


def add_to_project(
    issue_url: str,
    project_number: int,
    owner: str,
    dry_run: bool = False,
    verbose: bool = False,
) -> bool:
    """Add an issue to a GitHub Projects v2 board."""
    if dry_run:
        console.print(
            f"  [dim]DRY-RUN: Add issue to project #{project_number}[/dim]"
        )
        return True
    try:
        _run_gh([
            "project", "item-add", str(project_number),
            "--owner", owner,
            "--url", issue_url,
        ])
        if verbose:
            console.print(
                f"  [blue]📋 Added to project #{project_number}[/blue]"
            )
        return True
    except Exception as e:
        console.print(f"  [red]❌ Failed to add to project:[/red] {e}")
        return False


# ─── Recursive Execution ────────────────────────────────────────────────────


def _execute_issue_tree(
    issue: IssueInput,
    config: ProjectConfig,
    result: ExecutionResult,
    parent_created: CreatedIssue | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> None:
    """Recursively create an issue and its children, linking as we go."""
    repo = config.repo_info.repo
    try:
        resolved_type = _resolve_issue_type(issue, config)
    except ValueError as e:
        console.print(f"  [red]❌ Failed to resolve type for '{issue.id}':[/red] {e}")
        result.failed.append({"id": issue.id, "title": issue.title})
        return

    full_title = _build_full_title(issue, config, resolved_type=resolved_type)

    # Duplicate check
    if not dry_run and _check_duplicate(full_title, repo):
        console.print(f"  [yellow]⏭️  Skipping duplicate: '{full_title}'[/yellow]")
        result.skipped_duplicates.append(full_title)
        return

    # Create the issue
    created = create_single_issue(
        issue,
        config,
        resolved_type=resolved_type,
        dry_run=dry_run,
        verbose=verbose,
    )
    if created is None:
        result.failed.append({"id": issue.id, "title": full_title})
        return

    if parent_created:
        created.parent_number = parent_created.number

    result.created.append(created)

    # Link to parent if applicable
    if parent_created and created.number > 0:
        linking = config.hierarchy.linking
        if linking.method == "sub_issues":
            link_sub_issue(
                parent_created.number, created.number, repo,
                dry_run=dry_run, verbose=verbose,
            )
        elif linking.method == "body_reference":
            add_body_reference(
                created.number, parent_created.number, repo,
                prefix=linking.parent_prefix, dry_run=dry_run,
            )
        elif linking.method == "task_list":
            add_task_list_item(
                parent_created.number, created.number, repo,
                dry_run=dry_run,
            )

    # Add to project if specified
    if issue.project is not None and created.url and created.url != "(dry-run)":
        add_to_project(
            created.url, issue.project, config.repo_info.owner,
            dry_run=dry_run, verbose=verbose,
        )
    elif issue.project is not None and dry_run:
        console.print(
            f"  [dim]DRY-RUN: Add to project #{issue.project}[/dim]"
        )

    # Recurse into children
    for child in issue.children:
        _execute_issue_tree(
            child, config, result,
            parent_created=created,
            dry_run=dry_run, verbose=verbose,
        )


def execute_issues(
    data: dict,
    config: ProjectConfig,
    dry_run: bool = False,
    verbose: bool = False,
) -> ExecutionResult:
    """Execute the full issue creation pipeline."""
    issue_set = IssueSet(**data)
    result = ExecutionResult()

    total = _count_issues(issue_set.issues)
    console.print(
        f"\n[bold blue]{'DRY RUN — ' if dry_run else ''}"
        f"Creating {total} issues in [cyan]{config.repo_info.repo}[/cyan]...[/bold blue]\n"
    )

    for issue in issue_set.issues:
        _execute_issue_tree(
            issue, config, result,
            dry_run=dry_run, verbose=verbose,
        )

    _print_summary(result, dry_run)

    return result


def _count_issues(issues: list[IssueInput]) -> int:
    """Count total issues including children recursively."""
    count = len(issues)
    for issue in issues:
        count += _count_issues(issue.children)
    return count


def _print_summary(result: ExecutionResult, dry_run: bool) -> None:
    """Print a summary table of created issues."""
    prefix = "DRY RUN — " if dry_run else ""

    if result.created:
        table = Table(title=f"\n{prefix}Issue Summary")
        table.add_column("#", style="cyan", justify="right")
        table.add_column("Type", style="magenta")
        table.add_column("Title", style="white")
        table.add_column("Parent", style="blue", justify="right")
        table.add_column("URL", style="dim")

        for issue in result.created:
            parent_str = f"#{issue.parent_number}" if issue.parent_number else "—"
            num_str = f"#{issue.number}" if issue.number > 0 else "(dry-run)"
            table.add_row(
                num_str,
                issue.type,
                issue.title,
                parent_str,
                issue.url if not dry_run else "",
            )

        console.print(table)

    console.print()
    created_count = len(result.created)
    failed_count = len(result.failed)
    skipped_count = len(result.skipped_duplicates)

    if created_count:
        console.print(f"  [green]✅ Created: {created_count}[/green]")
    if skipped_count:
        console.print(f"  [yellow]⏭️  Skipped (duplicates): {skipped_count}[/yellow]")
    if failed_count:
        console.print(f"  [red]❌ Failed: {failed_count}[/red]")
        for f in result.failed:
            console.print(f"     - {f['title']}")
    console.print()
