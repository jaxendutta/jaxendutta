#!/usr/bin/env python3
"""
Generates a GitHub-contribution-calendar-style SVG heatmap, but colored by
lines of code (LOC) changed per day instead of commit count.

Scans every repo you have access to (public, private, org) via the GitHub
REST API, clones each one, and walks `git log` filtered to YOUR author
identity so collaborators' commits don't inflate your numbers.

Required env vars:
  GH_USERNAME   - your GitHub username (e.g. jaxendutta)
  GH_TOKEN      - a classic PAT with `repo` scope (needs private repo access)
  GIT_AUTHOR_EMAILS - comma-separated list of git emails/names you commit as
                       (e.g. "you@example.com,you@users.noreply.github.com")
"""

import os
import sys
import shutil
import subprocess
from datetime import datetime, timedelta

API_ROOT = "https://api.github.com"


def api_get(url, token, params=None):
    import requests
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp = requests.get(url, headers=headers, params=params or {})
    if resp.status_code != 200:
        print(f"API error {resp.status_code} for {url}: {resp.text[:300]}", file=sys.stderr)
        resp.raise_for_status()
    return resp


def fetch_all_repos(token):
    """Fetch every repo the token's user can see: owned, collaborator, org member."""
    repos = []
    page = 1
    while True:
        resp = api_get(
            f"{API_ROOT}/user/repos",
            token,
            params={
                "per_page": 100,
                "page": page,
                "affiliation": "owner,collaborator,organization_member",
                "visibility": "all",
            },
        )
        batch = resp.json()
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def clone_and_count(repo, token, author_emails, workdir):
    name = repo["full_name"].replace("/", "__")
    clone_url = repo["clone_url"].replace(
        "https://", f"https://x-access-token:{token}@"
    )
    dest = os.path.join(workdir, name)

    try:
        subprocess.run(
            ["git", "clone", "--quiet", clone_url, dest],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=600,
        )
    except Exception as e:
        print(f"  skip {repo['full_name']}: clone failed ({e})", file=sys.stderr)
        return {}

    # Build one --author filter per known identity (git log ORs multiple --author flags)
    author_args = []
    for email in author_emails:
        author_args += ["--author", email]

    cmd = [
        "git", "log", "--no-merges",
        "--date=short",
        "--pretty=format:__COMMIT__%ad",
        "--numstat",
    ] + author_args

    try:
        result = subprocess.run(
            cmd, cwd=dest, capture_output=True, text=True, timeout=300
        ).stdout
    except Exception as e:
        print(f"  skip {repo['full_name']}: log failed ({e})", file=sys.stderr)
        shutil.rmtree(dest, ignore_errors=True)
        return {}

    per_day = {}
    current_date = None
    for line in result.splitlines():
        if line.startswith("__COMMIT__"):
            current_date = line[len("__COMMIT__"):].strip()
            continue
        if not line.strip() or current_date is None:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        added, deleted = parts[0], parts[1]
        if added == "-" or deleted == "-":
            continue  # binary file
        try:
            loc = int(added) + int(deleted)
        except ValueError:
            continue
        per_day[current_date] = per_day.get(current_date, 0) + loc

    shutil.rmtree(dest, ignore_errors=True)
    return per_day


def build_svg(data, weeks=53):
    end_date = datetime.today().date()
    start_date = end_date - timedelta(weeks=weeks)
    while start_date.weekday() != 6:  # snap to preceding Sunday
        start_date -= timedelta(days=1)

    def color_for(loc):
        if loc <= 0:
            return "#ebedf0"
        if loc <= 50:
            return "#9be9a8"
        if loc <= 200:
            return "#40c463"
        if loc <= 600:
            return "#30a14e"
        return "#216e39"

    cell, gap = 11, 3
    step = cell + gap
    columns_svg = []
    month_labels = []
    last_month = None
    current = start_date
    col = 0

    col_squares = ""
    while current <= end_date:
        date_str = current.strftime("%Y-%m-%d")
        loc = data.get(date_str, 0)
        weekday_idx = (current.weekday() + 1) % 7  # Sunday = 0
        y = weekday_idx * step
        col_squares += (
            f'<rect x="0" y="{y}" width="{cell}" height="{cell}" rx="2" ry="2" '
            f'fill="{color_for(loc)}"><title>{loc:,} LOC changed on '
            f'{current.strftime("%b %d, %Y")}</title></rect>\n'
        )
        month = current.strftime("%b")
        if current.day <= 7 and month != last_month:
            month_labels.append(f'<text x="{col * step}" y="-6" class="lbl">{month}</text>')
            last_month = month

        if weekday_idx == 6:
            columns_svg.append(f'<g transform="translate({col * step},0)">{col_squares}</g>')
            col_squares = ""
            col += 1
        current += timedelta(days=1)

    if col_squares:
        columns_svg.append(f'<g transform="translate({col * step},0)">{col_squares}</g>')
        col += 1

    width = 40 + col * step
    height = 20 + 7 * step + 20

    svg = f'''<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">
  <style>.lbl {{ font-size:10px; fill:#57606a; }}</style>
  <g transform="translate(30,20)">
    <text x="-24" y="10" class="lbl">Mon</text>
    <text x="-24" y="36" class="lbl">Wed</text>
    <text x="-24" y="62" class="lbl">Fri</text>
    {''.join(month_labels)}
    {''.join(columns_svg)}
  </g>
</svg>'''
    return svg


def main():
    token = os.environ.get("GH_TOKEN")
    username = os.environ.get("GH_USERNAME")
    author_emails = [e.strip() for e in os.environ.get("GIT_AUTHOR_EMAILS", "").split(",") if e.strip()]

    if not token or not username:
        print("GH_TOKEN and GH_USERNAME are required.", file=sys.stderr)
        sys.exit(1)
    if not author_emails:
        print("GIT_AUTHOR_EMAILS is required (comma-separated git identities).", file=sys.stderr)
        sys.exit(1)

    workdir = "/tmp/loc-scan"
    os.makedirs(workdir, exist_ok=True)

    print("Fetching repo list...")
    repos = fetch_all_repos(token)
    repos = [r for r in repos if not r.get("fork")]
    print(f"Found {len(repos)} non-fork repos.")

    totals = {}
    for i, repo in enumerate(repos, 1):
        print(f"[{i}/{len(repos)}] {repo['full_name']}")
        per_day = clone_and_count(repo, token, author_emails, workdir)
        for d, loc in per_day.items():
            totals[d] = totals.get(d, 0) + loc

    svg = build_svg(totals)
    with open("loc_heatmap.svg", "w") as f:
        f.write(svg)
    print(f"Done. {sum(totals.values()):,} total LOC across {len(totals)} active days.")


if __name__ == "__main__":
    main()
