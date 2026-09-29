from datetime import datetime, timedelta
from html import escape
from html.parser import HTMLParser
import math
import os
import re
from urllib.request import Request, urlopen
from pathlib import Path


class ContributionCalendarParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells = {}
        self.counts = {}
        self.current_tooltip = None
        self.tooltip_text = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "td" and "data-date" in attributes:
            classes = attributes.get("class", "").split()
            if "ContributionCalendar-day" in classes:
                self.cells[attributes.get("id", "")] = attributes["data-date"]
        elif tag == "tool-tip" and attributes.get("for"):
            self.current_tooltip = attributes["for"]
            self.tooltip_text = []

    def handle_data(self, data):
        if self.current_tooltip:
            self.tooltip_text.append(data)

    def handle_endtag(self, tag):
        if tag == "tool-tip" and self.current_tooltip:
            text = " ".join(" ".join(self.tooltip_text).split())
            match = re.search(r"([\d,]+)\s+contributions?\b", text, re.IGNORECASE)
            if match:
                self.counts[self.current_tooltip] = int(match.group(1).replace(",", ""))
            elif "no contributions" in text.lower():
                self.counts[self.current_tooltip] = 0
            self.current_tooltip = None
            self.tooltip_text = []


def fetch_contributions(username):
    url = f"https://github.com/users/{username}/contributions"
    request = Request(url, headers={"User-Agent": "profile-contribution-graph/1.0"})
    with urlopen(request, timeout=30) as response:
        page = response.read().decode("utf-8", errors="replace")

    parser = ContributionCalendarParser()
    parser.feed(page)
    points = [
        (datetime.strptime(day, "%Y-%m-%d").date(), parser.counts.get(cell_id))
        for cell_id, day in parser.cells.items()
        if cell_id in parser.counts
    ]
    points.sort(key=lambda item: item[0])
    if len(points) < 300:
        raise RuntimeError(f"Expected a year of contribution data, found only {len(points)} days")
    latest_day = points[-1][0]
    first_day = latest_day - timedelta(days=364)
    points = [point for point in points if point[0] >= first_day]
    if len(points) != 365:
        raise RuntimeError(f"Expected 365 contribution days, found {len(points)}")
    return points


def smooth_path(points):
    path = [f"M {points[0][0]:.2f},{points[0][1]:.2f}"]
    for index in range(len(points) - 1):
        x0, y0 = points[max(0, index - 1)]
        x1, y1 = points[index]
        x2, y2 = points[index + 1]
        x3, y3 = points[min(len(points) - 1, index + 2)]
        control1 = (x1 + (x2 - x0) / 6, y1 + (y2 - y0) / 6)
        control2 = (x2 - (x3 - x1) / 6, y2 - (y3 - y1) / 6)
        path.append(
            f"C {control1[0]:.2f},{control1[1]:.2f} "
            f"{control2[0]:.2f},{control2[1]:.2f} {x2:.2f},{y2:.2f}"
        )
    return " ".join(path)


def make_svg(username, contributions):
    width, height = 960, 300
    left, right, top, bottom = 52, 24, 60, 238
    plot_width, plot_height = width - left - right, bottom - top
    raw_counts = [count for _, count in contributions]
    total = sum(raw_counts)
    window_days = 15
    smoothed_counts = []
    for index in range(len(raw_counts)):
        window_start = max(0, index - window_days // 2)
        window_end = min(len(raw_counts), index + window_days // 2 + 1)
        smoothed_counts.append(sum(raw_counts[window_start:window_end]) / (window_end - window_start))

    maximum = max(1, max(smoothed_counts))
    x_step = plot_width / (len(contributions) - 1)

    points = []
    for index, count in enumerate(smoothed_counts):
        scaled = math.sqrt(count / maximum)
        points.append((left + index * x_step, bottom - scaled * plot_height))

    line = smooth_path(points)
    area = f"{line} L {points[-1][0]:.2f},{bottom} L {points[0][0]:.2f},{bottom} Z"
    grid = []
    for fraction in (0, 0.25, 0.5, 0.75, 1):
        y = bottom - fraction * plot_height
        grid.append(f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}"/>')

    month_labels = []
    first_day = contributions[0][0]
    for index, (day, _) in enumerate(contributions):
        if day.day == 1:
            x = left + index * x_step
            month_labels.append(f'<text x="{x:.2f}" y="276">{day.strftime("%b")}</text>')

    start_label = contributions[0][0].strftime("%b %d, %Y")
    end_label = contributions[-1][0].strftime("%b %d, %Y")
    title = escape(f"{username}’s GitHub contribution activity")
    description = escape(f"{total} contributions from {start_label} to {end_label}, shown as a 15-day smoothed curve.")
    last_x, last_y = points[-1]
    output = Path("profile/activity-graph.svg")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">
  <title id="title">{title}</title>
  <desc id="description">{description}</desc>
  <defs>
    <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#7aa2f7" stop-opacity="0.34"/>
      <stop offset="100%" stop-color="#7aa2f7" stop-opacity="0.015"/>
    </linearGradient>
  </defs>
  <style>
    text {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; fill: #64748b; }}
    .title {{ font-size: 17px; font-weight: 600; fill: #334155; }}
    .summary {{ font-size: 12px; }}
    .month {{ font-size: 11px; }}
    .grid {{ stroke: #cbd5e1; stroke-opacity: 0.55; stroke-width: 1; }}
  </style>
  <text class="title" x="{left}" y="27">Contribution activity</text>
  <text class="summary" x="{width-right}" y="27" text-anchor="end">{total:,} contributions · 15-day smooth</text>
  <g class="grid">{''.join(grid)}</g>
  <path d="{area}" fill="url(#area)"/>
  <path d="{line}" fill="none" stroke="#7aa2f7" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="{last_x:.2f}" cy="{last_y:.2f}" r="4.5" fill="#bb9af7" stroke="#ffffff" stroke-width="2"/>
  <g class="month">{''.join(month_labels)}</g>
</svg>
''',
        encoding="utf-8",
    )
    print(f"Generated {output} with {total} contributions across {len(contributions)} days")


if __name__ == "__main__":
    username = os.environ.get("GITHUB_USERNAME", "YYousabFouad")
    if not re.fullmatch(r"[A-Za-z0-9-]+", username):
        raise ValueError("Invalid GitHub username")
    make_svg(username, fetch_contributions(username))
