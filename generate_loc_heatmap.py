import os
import requests
import subprocess
import shutil
import pandas as pd
from datetime import datetime, timedelta

# 1. Configuration & Authentication
TOKEN = os.environ.get("METRICS_TOKEN")

if not TOKEN:
    print("❌ ERROR: METRICS_TOKEN environment variable is missing!")
    print("Please make sure you added METRICS_TOKEN to your repository secrets.")
    exit(1)

HEADERS = {"Authorization": f"token {TOKEN}"}
DATA = {}

# 2. Fetch all repositories (Public and Private)
print("Fetching repository list...")
repos_url = "https://github.com"
response = requests.get(repos_url, headers=HEADERS)

# Check if the API request actually succeeded
if response.status_code != 200:
    print(f"❌ API ERROR ({response.status_code}): Could not fetch repositories.")
    print(f"Response text from GitHub: {response.text}")
    exit(1)

try:
    repos = response.json()
except Exception as e:
    print(f"❌ JSON Parsing Error: {e}")
    print(f"Raw body received: {response.text}")
    exit(1)

if not isinstance(repos, list):
    print("❌ Unexpected API response format. Expected a list of repositories.")
    print(f"Received: {repos}")
    exit(1)

print(f"Found {len(repos)} repositories. Starting analysis...")

# 3. Analyze each repository
for repo in repos:
    repo_name = repo["name"]
    clone_url = repo["clone_url"]
    # Construct authenticated clone URL to securely access private repos
    clone_url = clone_url.replace("https://", f"https://x-access-token:{TOKEN}@")

    print(f"Analyzing {repo_name}...")
    
    try:
        # Perform a shallow clone (depth 1000 is faster but gets plenty of history)
        subprocess.run(["git", "clone", "--depth=1000", clone_url, repo_name], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Pull git logs from the repository
        cmd = "git log --shortstat --date=short --pretty=format:'%ad'"
        result = subprocess.check_output(cmd, shell=True, cwd=repo_name).decode('utf-8', errors='ignore')
        
        # Parse dates and LOC counts
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
                
        # Clean up directory to preserve disk space on runner
        shutil.rmtree(repo_name)
    except Exception as e:
        print(f"Skipping {repo_name} due to an error: {e}")

# 4. Generate Interactive SVG Calendar Grid
print("Building interactive SVG grid...")
end_date = datetime.today()
start_date = end_date - timedelta(weeks=52)

# Adjust start_date to the nearest previous Sunday so rows align cleanly (Sun-Sat)
while start_date.weekday() != 6:
    start_date -= timedelta(days=1)

current = start_date
svg_squares = ""
x_offset = 0

while current <= end_date:
    date_str = current.strftime('%Y-%m-%d')
    loc_count = DATA.get(date_str, 0)
    
    # Calculate GitHub-like shades of green based on LOC volume
    color = "#ebedf0"
    if loc_count > 0: color = "#9be9a8"
    if loc_count > 100: color = "#40c463"
    if loc_count > 500: color = "#30a14e"
    if loc_count > 1500: color = "#216e39"
    
    # Monday is 0, Sunday is 6 in Python. Shift it so Sunday is row 0.
    weekday_idx = (current.weekday() + 1) % 7
    y_offset = weekday_idx * 15
    
    # Wrap elements with a <title> tag for instant native tooltips on hover
    svg_squares += f"""
    <rect x="{x_offset}" y="{y_offset}" width="11" height="11" fill="{color}" rx="2" ry="2">
        <title>{loc_count:,} lines of code modified on {current.strftime('%b %d, %Y')}</title>
    </rect>
    """
    
    if weekday_idx == 6: # Move to next column after Saturday
        x_offset += 15
    current += timedelta(days=1)

# Compile into a complete, standalone vector graphic
full_svg = f"""<svg width="830" height="130" xmlns="http://w3.org">
    <g transform="translate(15, 15)">
        {svg_squares}
    </g>
</svg>"""

with open('loc_heatmap.svg', 'w') as f:
    f.write(full_svg)
print("Successfully generated loc_heatmap.svg!")
