#!/usr/bin/env python3
"""Live test: gather projects for COS301-SE-2026/UMTAS."""
from src.gather import gather_projects_by_title

results = gather_projects_by_title("COS301-SE-2026/UMTAS", "COS301-SE-2026")
print(f"Found {len(results)} project(s):")
for p in results:
    print(f"  #{p['number']}: {p['title']}")
