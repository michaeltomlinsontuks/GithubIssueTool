# GitHub Issue Tool

AI-powered batch GitHub issue creation with configurable hierarchies, validation, and the `gh` CLI.

## Overview

A Python CLI tool with a three-step pipeline:

1. **`gather-config`** — Pulls milestones, labels, assignees, and projects from a GitHub repo via `gh` CLI → writes YAML config files  
2. *(You manually edit `hierarchy.yaml` to define hierarchy levels, labels, body templates, and parent-child rules)*  
3. **`generate-skill`** — Reads configs → produces an AI skill prompt with all valid values baked in  
4. *(Give the skill to an AI — it outputs structured JSON)*  
5. **`create-issues`** — Validates the JSON against configs, checks for duplicates, and creates issues in hierarchy order via `gh` CLI

## Prerequisites

- **Python 3.11+**
- **[GitHub CLI (`gh`)](https://cli.github.com/)** — installed and authenticated (`gh auth login`)
- `gh` auth must have `project` scope if using project boards (`gh auth refresh -s project`)

## Installation

```bash
# Clone the repo
git clone https://github.com/michaeltomlinsontuks/GithubIssueTool.git
cd GithubIssueTool

# Install dependencies
pip install -r requirements.txt

# Or install as a package
pip install -e .
```

## Usage

### Step 1: Gather Config

Pull repo metadata into YAML config files:

```bash
python -m src.cli gather-config --repo owner/repo-name
```

This creates:
- `config/repo.yaml` — repo name, owner, project boards
- `config/milestones.yaml` — available milestones
- `config/labels.yaml` — available labels with colors
- `config/assignees.yaml` — users with push access
- `config/types.yaml` — auto-detected GitHub native issue types (**read-only; auto-overwritten**)
- `config/hierarchy.yaml` — **starter template** (edit this)

### Step 2: Edit Configs

Edit `config/hierarchy.yaml` to define:
- Hierarchy levels and parent-child relationships (e.g., epic → story → task → subtask)
- `hierarchy_label` mappings (label-driven hierarchy semantics)
- Title prefixes, body templates, default labels, and optional GitHub native type mapping

`config/types.yaml` is auto-generated from GitHub and used only to validate `github_type` mappings.

### Step 3: Generate AI Skill

```bash
python -m src.cli generate-skill
```

This reads all config files and generates `skill/github_issues.md` — a self-contained AI prompt with:
- All valid types, labels, milestones, assignees
- Hierarchy rules
- Body template fields
- JSON output format with examples

### Step 4: Create Issues

Give the skill to an AI, get JSON back, then:

```bash
# Dry run first (prints commands without executing)
python -m src.cli create-issues issues.json --dry-run --verbose

# For real
python -m src.cli create-issues issues.json --verbose
```

## Features

- **Hierarchical Issues** — Epic → Story → Task → Sub-task (configurable)
- **Label-Driven Hierarchy** — Hierarchy semantics come from labels (with optional explicit `type`)
- **GitHub Sub-Issues** — Uses GitHub's native sub-issues API for parent-child linking
- **Duplicate Detection** — Checks for existing issues with the same title before creating
- **Body Templates** — Markdown templates with `{placeholder}` fields per hierarchy level
- **GitHub Native Issue Types** — Supports GitHub's org-level issue types via the API
- **Project Board Assignment** — Assign issues to GitHub Projects v2 boards
- **Fuzzy Error Messages** — Misspelled labels/assignees get "Did you mean?" suggestions
- **Dry Run Mode** — Preview all `gh` commands before executing

## JSON Input Format

```json
{
  "issues": [
    {
      "id": "auth-epic",
      "title": "User Authentication",
      "type": null,
      "body": {
        "description": "Implement auth system",
        "goals": "- JWT tokens\n- OAuth2"
      },
      "labels": ["epic", "backend"],
      "milestone": "MVP Release",
      "assignees": ["username"],
      "project": 1,
      "children": [
        {
          "id": "login-story",
          "title": "Login Flow",
          "type": null,
          "body": { "description": "...", "acceptance_criteria": "..." },
          "labels": ["story"],
          "milestone": null,
          "assignees": [],
          "project": null,
          "children": []
        }
      ]
    }
  ]
}
```

## CLI Reference

```
python -m src.cli gather-config --repo owner/repo [-c ./config]
python -m src.cli generate-skill [-c ./config] [-o skill/github_issues.md]
python -m src.cli create-issues <input.json> [-c ./config] [--dry-run] [--verbose] [--skip-duplicate-check]
```

## Development

```bash
# Install dev deps
pip install -e ".[dev]"

# Run tests
pytest tests/ -v
```

## License

MIT
