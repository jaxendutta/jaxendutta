import os
import requests
import subprocess
import shutil
from datetime import datetime, timedelta

# 1. Configuration & Authentication
TOKEN = os.environ.get("METRICS_TOKEN") or os.environ.get("GITHUB_TOKEN")

if not TOKEN:
    print("❌ ERROR: No authentication token found!")
    exit(1)

HEADERS = {
    "Authorization": f"token {TOKEN}"
}
DATA = {}

# 2. Fetch all repositories across paginated chunks safely
print("Fetching repository list...")
repos = []
page = 1

while True:
    # FIXED: Reconstructed with the correct absolute api base domain format
    repos_url = f"https://github.com{page}&type=all"
    response = requests.get(repos_url, headers=HEADERS)

    if response.status_code != 200:
        print(f"❌ API REQUEST FAILED ({response.status_code})")
        print(f"Response: {response.text[:200]}")
        exit(1)

    try:
        page_data = response.json()
    except Exception as e:
        print(f"❌ JSON Parsing Error on page {page}: {e}")
        exit(1)

    if not page_data or not isinstance(page_data, list):
        break

    repos.extend(page_data)
    if len(page_data) < 100:
        break
    page += 1

print(f"Found {len(repos)} repositories. Starting analysis...")

# 3. Analyze each repository
for repo in repos:
    repo_name = repo["name"]
    clone_url = repo["clone_url"].replace("https://", f"https://x-access-token:{TOKEN}@")
    
    print(f"Analyzing {repo_name}...")
    try:
        subprocess.run(["git", "clone", "--depth=500", clone_url, repo_name], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cmd = "git log --shortstat --date=short --pretty=format:'%ad'"
        result = subprocess.check_output(cmd, shell=True, cwd=repo_name).decode('utf-8', errors='ignore')
        
        current_date = None
        for line in result.split('\n'):
            line = line.strip()
            if not line: continue
            if "-" in line and len(line) == 10:
                current_date = line
            elif "changed" in line and current_date:
                parts = line.split(',')
                loc = sum(int(p.strip().split()) for p in parts if "insertion" in p or "deletion" in p)
                DATA[current_date] = DATA.get(current_date, 0) + loc
                
        shutil.rmtree(repo_name)
    except Exception:
        pass

# 4. Generate GitHub-Standard Structured SVG Layout Matrix
print("Building responsive SVG matrix layout...")
end_date = datetime.today()
start_date = end_date - timedelta(weeks=52)

while start_date.weekday() != 6: # Snap grid mapping precisely to Sunday
    start_date -= timedelta(days=1)

current = start_date
columns_svg = ""
current_column_squares = ""
month_labels_svg = ""

last_month = None
x_offset = 0

while current <= end_date:
    date_str = current.strftime('%Y-%m-%d')
    loc_count = DATA.get(date_str, 0)
    
    # Classic GitHub Green Spectrum Profile
    color = "#ebedf0"
    if loc_count > 0: color = "#9be9a8"
    if loc_count > 100: color = "#40c463"
    if loc_count > 500: color = "#30a14e"
    if loc_count > 1500: color = "#216e39"
    
    weekday_idx = (current.weekday() + 1) % 7 # Normalize index sequence layout maps
    y_offset = weekday_idx * 13
    
    current_column_squares += f"""
        <rect x="0" y="{y_offset}" width="10" height="10" fill="{color}" rx="2" ry="2">
            <title>{loc_count:,} lines of code modified on {current.strftime('%b %d, %Y')}</title>
        </rect>"""
    
    if current.day <= 7 and current.strftime('%b') != last_month:
        month_labels_svg += f'<text x="{x_offset}" y="-10">{current.strftime("%b")}</text>\n'
        last_month = current.strftime('%b')
        
    if weekday_idx == 6: # Saturday closure splits row groups
        columns_svg += f'<g transform="translate({x_offset}, 0)">{current_column_squares}</g>\n'
        current_column_squares = ""
        x_offset += 13
        
    current += timedelta(days=1)

if current_column_squares:
    columns_svg += f'<g transform="translate({x_offset}, 0)">{current_column_squares}</g>\n'

full_svg = f"""<svg width="720" height="140" viewBox="0 0 720 140" xmlns="http://w3.org">
    <style>
        text {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #57606a; font-size: 9px; }}
    </style>
    <rect width="100%" height="100%" fill="transparent" />
    <g transform="translate(30, 25)">
        <text x="-25" y="18">Mon</text>
        <text x="-25" y="44">Wed</text>
        <text x="-25" y="70">Fri</text>
        {month_labels_svg}
        {columns_svg}
    </g>
</svg>"""

with open('loc_heatmap.svg', 'w') as f:
    f.write(full_svg)
print("Successfully generated beautifully structured loc_heatmap.svg!")
