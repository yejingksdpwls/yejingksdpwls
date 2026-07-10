import datetime as dt
import html
import json
import os
import sys
import unicodedata
import urllib.request
from pathlib import Path


GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
USERNAME = os.getenv("GITHUB_USERNAME", "yejingksdpwls")
TERMINAL_NAME = os.getenv("TERMINAL_NAME", "hanyejin")

OUT_PATH = Path("assets/github-overview.svg")


def fail(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)
    sys.exit(1)


def gql(query: str, variables: dict) -> dict:
    if not GITHUB_TOKEN:
        fail("GITHUB_TOKEN is missing. Check repository secret METRICS_TOKEN.")

    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "github-overview-svg-generator",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            body = json.loads(res.read().decode("utf-8"))
    except Exception as exc:
        fail(f"GitHub API request failed: {exc}")

    if body.get("errors"):
        fail(json.dumps(body["errors"], ensure_ascii=False, indent=2))

    return body["data"]


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def display_width(text: str) -> int:
    total = 0
    for ch in text:
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def wrap_text(text: str, max_width: int, max_lines: int = 2) -> list[str]:
    text = text or ""
    words = text.split()
    lines = []
    current = ""

    for word in words:
        candidate = word if not current else f"{current} {word}"
        if display_width(candidate) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    if not lines:
        lines = [""]

    lines = lines[:max_lines]

    if len(lines) == max_lines and display_width(lines[-1]) > max_width - 2:
        while display_width(lines[-1] + "…") > max_width and lines[-1]:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"

    return lines


def short_num(num: int) -> str:
    if num >= 1000:
        value = num / 1000
        return f"{value:.1f}k".replace(".0k", "k")
    return str(num)


def safe_color(color: str | None, fallback: str = "#4078c0") -> str:
    if isinstance(color, str) and color.startswith("#") and len(color) in (4, 7):
        return color
    return fallback


def language_color(name: str | None, color: str | None) -> str:
    fallback = {
        "Jupyter Notebook": "#DA5B0B",
        "Python": "#3572A5",
        "TypeScript": "#3178C6",
        "JavaScript": "#F1E05A",
        "HTML": "#E34C26",
        "CSS": "#563D7C",
        "SQL": "#D1902F",
    }
    return safe_color(color, fallback.get(name or "", "#4078c0"))


def fetch_data() -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=365)

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        login

        repositories(
          first: 100
          ownerAffiliations: OWNER
          isFork: false
          orderBy: { field: UPDATED_AT, direction: DESC }
        ) {
          totalCount
          nodes {
            name
            description
            url
            isPrivate
            stargazerCount
            forkCount
            primaryLanguage {
              name
              color
            }
            languages(first: 8, orderBy: { field: SIZE, direction: DESC }) {
              edges {
                size
                node {
                  name
                  color
                }
              }
            }
          }
        }

        pinnedItems(first: 4, types: REPOSITORY) {
          nodes {
            ... on Repository {
              name
              description
              url
              isPrivate
              stargazerCount
              forkCount
              primaryLanguage {
                name
                color
              }
            }
          }
        }

        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          totalPullRequestContributions
          totalIssueContributions
          totalPullRequestReviewContributions
          totalRepositoryContributions
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                contributionCount
                color
              }
            }
          }
        }
      }
    }
    """

    return gql(
        query,
        {
            "login": USERNAME,
            "from": since.isoformat(),
            "to": now.isoformat(),
        },
    )["user"]


def aggregate_languages(repositories: list[dict]) -> list[dict]:
    totals = {}

    for repo in repositories:
        for edge in repo.get("languages", {}).get("edges", []):
            node = edge.get("node") or {}
            name = node.get("name")
            if not name:
                continue

            if name not in totals:
                totals[name] = {
                    "name": name,
                    "size": 0,
                    "color": language_color(name, node.get("color")),
                }
            totals[name]["size"] += edge.get("size", 0)

    total_size = sum(item["size"] for item in totals.values())
    if total_size <= 0:
        return []

    result = sorted(totals.values(), key=lambda x: x["size"], reverse=True)[:5]
    for item in result:
        item["percent"] = item["size"] / total_size * 100

    return result


def stat_card(x: int, y: int, w: int, value: str, label: str) -> str:
    return f"""
    <rect x="{x}" y="{y}" width="{w}" height="92" rx="10" fill="#ffffff" stroke="#d0d7de"/>
    <text x="{x + w / 2}" y="{y + 44}" text-anchor="middle" class="stat-value">{esc(value)}</text>
    <text x="{x + w / 2}" y="{y + 70}" text-anchor="middle" class="stat-label">{esc(label)}</text>
    """


def language_section(languages: list[dict], x: int, y: int) -> str:
    if not languages:
        return ""

    bar_x = x
    bar_y = y + 48
    bar_w = 820
    bar_h = 12

    pieces = [
        f'<text x="{x}" y="{y}" class="section-title">Most Used Languages</text>',
        f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="6" fill="#eef0f4"/>',
    ]

    cursor = bar_x
    for index, lang in enumerate(languages):
        width = bar_w * lang["percent"] / 100
        if index == len(languages) - 1:
            width = bar_x + bar_w - cursor

        rx = 6 if index in (0, len(languages) - 1) else 0
        pieces.append(
            f'<rect x="{cursor:.2f}" y="{bar_y}" width="{width:.2f}" height="{bar_h}" '
            f'rx="{rx}" fill="{esc(lang["color"])}"/>'
        )
        cursor += width

    legend_y = y + 92
    legend_x = x

    for lang in languages[:4]:
        pieces.append(
            f'<circle cx="{legend_x + 6}" cy="{legend_y - 5}" r="5" fill="{esc(lang["color"])}"/>'
        )
        pieces.append(
            f'<text x="{legend_x + 22}" y="{legend_y}" class="legend">'
            f'{esc(lang["name"])} {lang["percent"]:.1f}%</text>'
        )
        legend_x += 190

    return "\n".join(pieces)


def contribution_grid(calendar: dict, x: int, y: int) -> str:
    weeks = calendar.get("weeks", [])
    total = calendar.get("totalContributions", 0)

    cell = 10
    gap = 3
    pieces = [
        f'<text x="{x}" y="{y}" class="section-title">{short_num(total)} contributions in the last year</text>'
    ]

    grid_y = y + 30
    for wx, week in enumerate(weeks[-53:]):
        for dy, day in enumerate(week.get("contributionDays", [])):
            count = day.get("contributionCount", 0)
            color = day.get("color") or "#ebedf0"
            if count == 0:
                color = "#ebedf0"
            pieces.append(
                f'<rect x="{x + wx * (cell + gap)}" y="{grid_y + dy * (cell + gap)}" '
                f'width="{cell}" height="{cell}" rx="2" fill="{esc(color)}"/>'
            )

    legend_x = x + 700
    legend_y = grid_y + 92
    legend_colors = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]
    pieces.append(f'<text x="{legend_x - 48}" y="{legend_y + 8}" class="tiny">Less</text>')
    for i, color in enumerate(legend_colors):
        pieces.append(
            f'<rect x="{legend_x + i * 18}" y="{legend_y}" width="11" height="11" rx="2" fill="{color}"/>'
        )
    pieces.append(f'<text x="{legend_x + 96}" y="{legend_y + 8}" class="tiny">More</text>')

    return "\n".join(pieces)


def repo_card(repo: dict, x: int, y: int, w: int, h: int) -> str:
    name = repo.get("name", "repository")
    description = repo.get("description") or "No description"
    lang = repo.get("primaryLanguage") or {}
    lang_name = lang.get("name") or "Unknown"
    lang_color = language_color(lang_name, lang.get("color"))

    desc_lines = wrap_text(description, max_width=38, max_lines=2)

    tspans = []
    for idx, line in enumerate(desc_lines):
        dy = 0 if idx == 0 else 26
        tspans.append(f'<tspan x="{x + 28}" dy="{dy}">{esc(line)}</tspan>')

    private_badge = ""
    if repo.get("isPrivate"):
        private_badge = f'<text x="{x + w - 76}" y="{y + 38}" class="private">private</text>'

    return f"""
    <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#ffffff" stroke="#d0d7de"/>
    <text x="{x + 28}" y="{y + 38}" class="repo-title">▸ {esc(name)}</text>
    {private_badge}
    <text x="{x + 28}" y="{y + 78}" class="repo-desc">{''.join(tspans)}</text>
    <circle cx="{x + 30}" cy="{y + h - 28}" r="5" fill="{esc(lang_color)}"/>
    <text x="{x + 45}" y="{y + h - 23}" class="repo-meta">{esc(lang_name)}</text>
    <text x="{x + 190}" y="{y + h - 23}" class="repo-meta">★ {repo.get("stargazerCount", 0)}</text>
    <text x="{x + 250}" y="{y + h - 23}" class="repo-meta">⑂ {repo.get("forkCount", 0)}</text>
    """


def projects_section(repos: list[dict], x: int, y: int) -> str:
    pieces = [
        f'<text x="{x}" y="{y}" class="prompt">'
        f'<tspan class="green">{esc(TERMINAL_NAME)}@github</tspan>'
        f'<tspan class="blue">:~/projects</tspan>'
        f'<tspan class="muted">$</tspan>'
        f'<tspan class="cmd"> ls --pinned</tspan>'
        f'</text>'
    ]

    card_w = 398
    card_h = 150
    gap_x = 24
    gap_y = 24

    for idx, repo in enumerate(repos[:4]):
        col = idx % 2
        row = idx // 2
        cx = x + col * (card_w + gap_x)
        cy = y + 34 + row * (card_h + gap_y)
        pieces.append(repo_card(repo, cx, cy, card_w, card_h))

    return "\n".join(pieces)


def generate_svg(data: dict) -> str:
    repos = data["repositories"]["nodes"]
    pinned = data["pinnedItems"]["nodes"]
    if not pinned:
        pinned = sorted(
            repos,
            key=lambda r: (r.get("stargazerCount", 0), r.get("forkCount", 0)),
            reverse=True,
        )[:4]

    contributions = data["contributionsCollection"]
    languages = aggregate_languages(repos)

    commits = contributions.get("totalCommitContributions", 0)
    prs = contributions.get("totalPullRequestContributions", 0)
    issues = contributions.get("totalIssueContributions", 0)
    stars = sum(repo.get("stargazerCount", 0) for repo in repos)
    repo_count = data["repositories"].get("totalCount", len(repos))

    width = 900
    height = 860

    cards = [
        stat_card(32, 86, 152, short_num(commits), "Commits"),
        stat_card(198, 86, 152, short_num(stars), "Stars"),
        stat_card(364, 86, 152, short_num(prs), "Pull Requests"),
        stat_card(530, 86, 152, short_num(issues), "Issues"),
        stat_card(696, 86, 152, short_num(repo_count), "Repos"),
    ]

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="GitHub overview">
  <style>
    .mono {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
    }}
    .prompt {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
      font-size: 17px;
    }}
    .green {{ fill: #2f7d3b; font-weight: 600; }}
    .blue {{ fill: #4f6eea; }}
    .muted {{ fill: #a6adb7; }}
    .cmd {{ fill: #3f4650; }}
    .stat-value {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 32px;
      font-weight: 800;
      fill: #3f7f3f;
    }}
    .stat-label {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 14px;
      fill: #3f4650;
    }}
    .section-title {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 16px;
      fill: #3f4650;
    }}
    .legend {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
      fill: #3f4650;
    }}
    .tiny {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      fill: #586069;
    }}
    .repo-title {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 17px;
      font-weight: 800;
      fill: #2f7d3b;
    }}
    .repo-desc {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Apple SD Gothic Neo", "Malgun Gothic", monospace;
      font-size: 14px;
      fill: #3f4650;
    }}
    .repo-meta {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
      fill: #3f4650;
    }}
    .private {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 11px;
      fill: #8b949e;
    }}
  </style>

  <rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="12" fill="#ffffff" stroke="#d0d7de"/>

  <text x="32" y="50" class="prompt">
    <tspan class="green">{esc(TERMINAL_NAME)}@github</tspan><tspan class="blue">:~/stats</tspan><tspan class="muted">$</tspan><tspan class="cmd"> git log --summary</tspan>
  </text>

  {''.join(cards)}

  {language_section(languages, 32, 230)}

  {contribution_grid(contributions["contributionCalendar"], 32, 360)}

  {projects_section(pinned, 32, 560)}
</svg>
"""
    return svg


def main() -> None:
    data = fetch_data()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(generate_svg(data), encoding="utf-8")
    print(f"Generated {OUT_PATH}")


if __name__ == "__main__":
    main()
