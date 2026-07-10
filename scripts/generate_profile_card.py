import datetime as dt
import html
import json
import os
import re
import sys
import urllib.request
from pathlib import Path


GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
USERNAME = os.getenv("GITHUB_USERNAME", "yejingksdpwls")
TERMINAL_NAME = os.getenv("TERMINAL_NAME", "hanyejin")

BASE_PROFILE_PATH = Path("assets/profile-card-base.svg")
OUT_PATH = Path("assets/profile-card.svg")


def fail(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)
    sys.exit(1)


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


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
            "User-Agent": "profile-card-svg-generator",
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
        "R": "#198CE7",
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
            stargazerCount
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

        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          totalPullRequestContributions
          totalIssueContributions
        }
      }
    }
    """

    data = gql(
        query,
        {
            "login": USERNAME,
            "from": since.isoformat(),
            "to": now.isoformat(),
        },
    )

    return data["user"]


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

    result = sorted(totals.values(), key=lambda x: x["size"], reverse=True)[:4]

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

    for lang in languages:
        pieces.append(
            f'<circle cx="{legend_x + 6}" cy="{legend_y - 5}" r="5" fill="{esc(lang["color"])}"/>'
        )
        pieces.append(
            f'<text x="{legend_x + 22}" y="{legend_y}" class="legend">'
            f'{esc(lang["name"])} {lang["percent"]:.1f}%</text>'
        )
        legend_x += 190

    return "\n".join(pieces)


def remove_existing_footer(svg: str) -> str:
    """
    기존 profile-card-base.svg 안에 있던
    '# Thanks for stopping by :)' footer를 제거한다.
    """

    svg = re.sub(
        r'\s*<line[^>]*stroke="#f0f2f4"[^>]*/>\s*'
        r'<text[^>]*>\s*'
        r'<tspan[^>]*>yejingksdpwls@github</tspan>.*?'
        r'Thanks for stopping by :\).*?'
        r'</text>\s*',
        "\n",
        svg,
        flags=re.S,
    )

    svg = re.sub(
        r'\s*<text[^>]*>\s*'
        r'<tspan[^>]*>yejingksdpwls@github</tspan>.*?'
        r'Thanks for stopping by :\).*?'
        r'</text>\s*',
        "\n",
        svg,
        flags=re.S,
    )

    return svg


def resize_svg(svg: str, height: int) -> str:
    svg = re.sub(
        r'width="900"\s+height="\d+"\s+viewBox="0 0 900 \d+"',
        f'width="900" height="{height}" viewBox="0 0 900 {height}"',
        svg,
        count=1,
    )

    svg = re.sub(
        r'<rect x="1" y="1" width="898" height="\d+"',
        f'<rect x="1" y="1" width="898" height="{height - 2}"',
        svg,
        count=1,
    )

    return svg


def stats_style() -> str:
    return """
  <style>
    .prompt {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
      font-size: 15px;
    }
    .green { fill: #1a7f37; font-weight: 700; }
    .blue { fill: #0969da; }
    .muted { fill: #afb8c1; }
    .cmd { fill: #3f4650; }
    .stat-value {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 30px;
      font-weight: 800;
      fill: #2f7d3b;
    }
    .stat-label {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12.5px;
      fill: #1f2328;
    }
    .section-title {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 15px;
      fill: #1f2328;
    }
    .legend {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      fill: #1f2328;
    }
  </style>
"""


def build_stats_section(data: dict, y_offset: int) -> str:
    repos = data["repositories"]["nodes"]
    contributions = data["contributionsCollection"]
    languages = aggregate_languages(repos)

    commits = contributions.get("totalCommitContributions", 0)
    prs = contributions.get("totalPullRequestContributions", 0)
    issues = contributions.get("totalIssueContributions", 0)
    stars = sum(repo.get("stargazerCount", 0) for repo in repos)
    repo_count = data["repositories"].get("totalCount", len(repos))

    cards = [
        stat_card(32, 86, 152, short_num(commits), "Commits"),
        stat_card(198, 86, 152, short_num(stars), "Stars"),
        stat_card(364, 86, 152, short_num(prs), "Pull Requests"),
        stat_card(530, 86, 152, short_num(issues), "Issues"),
        stat_card(696, 86, 152, short_num(repo_count), "Repos"),
    ]

    return f"""
  <g transform="translate(0,{y_offset})">
    <line x1="40" y1="0" x2="860" y2="0" stroke="#e2e6ea"/>

    <text x="40" y="44" class="prompt">
      <tspan class="green">{esc(TERMINAL_NAME)}@github</tspan><tspan class="blue">:~/stats</tspan><tspan class="muted">$</tspan><tspan class="cmd"> git log --summary</tspan>
    </text>

    {''.join(cards)}

    {language_section(languages, 32, 230)}
  </g>
"""


def build_footer(y: int) -> str:
    return f"""
  <line x1="40" y1="{y - 34}" x2="860" y2="{y - 34}" stroke="#f0f2f4"/>
  <text x="40" y="{y}" font-size="15" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">
    <tspan fill="#1a7f37">yejingksdpwls@github</tspan><tspan fill="#0969da"> ~&gt;</tspan><tspan fill="#afb8c1"> # Thanks for stopping by :)</tspan>
  </text>
"""


def generate_svg(data: dict) -> str:
    if not BASE_PROFILE_PATH.exists():
        fail("assets/profile-card-base.svg not found.")

    base_svg = BASE_PROFILE_PATH.read_text(encoding="utf-8")

    final_height = 1010
    stats_y = 650
    footer_y = 980

    base_svg = remove_existing_footer(base_svg)
    base_svg = resize_svg(base_svg, final_height)

    base_svg = base_svg.replace("</svg>", "")

    return f"""{base_svg}

{stats_style()}

{build_stats_section(data, stats_y)}

{build_footer(footer_y)}

</svg>
"""


def main() -> None:
    data = fetch_data()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(generate_svg(data), encoding="utf-8")
    print(f"Generated {OUT_PATH}")


if __name__ == "__main__":
    main()
