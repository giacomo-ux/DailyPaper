#!/usr/bin/env python3
"""Daily Paper generator.

Builds a newspaper-style grayscale PNG (news + weather + today's calendar)
sized for a Kindle screen.

Usage:
    python generate.py                  # uses config.json, writes out/paper.png
    python generate.py --demo           # fake data, no network needed
    python generate.py -o my.png        # custom output path

Environment overrides (handy for GitHub Actions secrets):
    CALENDAR_ICS_URLS   comma-separated iCal URLs (overrides config.json)
    PAPER_NAME          output file name (default paper.png)
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

WMO = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Drizzle",
    55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain",
    67: "Freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Rain showers", 81: "Rain showers",
    82: "Violent showers", 85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm, hail", 99: "Thunderstorm, hail",
}


# ----------------------------------------------------------------- helpers
def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "DailyPaper/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def find_font(names, size, font_dir=None):
    dirs = [font_dir] if font_dir else []
    dirs += [
        os.path.join(HERE, "fonts"),
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/liberation",
        "/usr/share/fonts/dejavu",
        "/Library/Fonts",
        "/System/Library/Fonts/Supplemental",
        "C:\\Windows\\Fonts",
    ]
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


# -------------------------------------------------------------------- data
def get_news(cfg):
    per_feed = cfg.get("items_per_feed", 4)
    columns = []
    for feed in cfg["news_feeds"]:
        items = []
        try:
            root = ET.fromstring(http_get(feed["url"]))
            nodes = root.findall(".//item") or root.findall(
                ".//{http://www.w3.org/2005/Atom}entry")
            for n in nodes[:per_feed]:
                def g(tag):
                    e = n.find(tag)
                    if e is None:
                        e = n.find("{http://www.w3.org/2005/Atom}" + tag)
                    return clean(e.text) if e is not None and e.text else ""
                title = g("title")
                summary = g("description") or g("summary")
                if title:
                    items.append({"source": feed["name"], "title": title,
                                  "summary": summary})
        except Exception as e:  # keep going if one feed is down
            print(f"[warn] feed {feed['name']} failed: {e}", file=sys.stderr)
        columns.append(items)
    # round-robin so every source gets a slot near the top
    merged = []
    for i in range(per_feed):
        for col in columns:
            if i < len(col):
                merged.append(col[i])
    return merged


def get_weather(cfg):
    w = cfg["weather"]
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={w['latitude']}&longitude={w['longitude']}"
        "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max,precipitation_sum,sunrise,sunset"
        f"&timezone={cfg['timezone']}&forecast_days=1&wind_speed_unit=ms"
    )
    try:
        d = json.loads(http_get(url))
        cur, day = d["current"], d["daily"]
        return {
            "place": w["name"],
            "now": round(cur["temperature_2m"]),
            "feels": round(cur["apparent_temperature"]),
            "wind": round(cur["wind_speed_10m"]),
            "desc": WMO.get(day["weather_code"][0], "—"),
            "hi": round(day["temperature_2m_max"][0]),
            "lo": round(day["temperature_2m_min"][0]),
            "rain_p": day["precipitation_probability_max"][0],
            "rain_mm": day["precipitation_sum"][0],
            "sunrise": day["sunrise"][0][11:16],
            "sunset": day["sunset"][0][11:16],
        }
    except Exception as e:
        print(f"[warn] weather failed: {e}", file=sys.stderr)
        return None


def get_events(cfg, today):
    urls = os.environ.get("CALENDAR_ICS_URLS")
    urls = [u.strip() for u in urls.split(",")] if urls else cfg.get(
        "calendar_ics_urls", [])
    urls = [u for u in urls if u]
    if not urls:
        return None  # not configured
    import icalendar
    import recurring_ical_events

    tz = ZoneInfo(cfg["timezone"])
    events = []
    for url in urls:
        try:
            cal = icalendar.Calendar.from_ical(http_get(url, 30))
            for ev in recurring_ical_events.of(cal).at(today):
                start, end = ev.get("DTSTART").dt, ev.get("DTEND")
                end = end.dt if end else None
                title = str(ev.get("SUMMARY", "(no title)"))
                loc = str(ev.get("LOCATION", "") or "")
                if isinstance(start, dt.datetime):
                    s = start.astimezone(tz) if start.tzinfo else start
                    e = end.astimezone(tz) if isinstance(end, dt.datetime) and end.tzinfo else end
                    when = s.strftime("%H:%M")
                    if isinstance(e, dt.datetime):
                        when += "–" + e.strftime("%H:%M")
                    key = s.replace(tzinfo=None)
                else:
                    when, key = "All day", dt.datetime.combine(start, dt.time())
                events.append((key, when, title, loc))
        except Exception as e:
            print(f"[warn] calendar failed: {e}", file=sys.stderr)
    events.sort(key=lambda x: x[0])
    return [(w, t, l) for _, w, t, l in events]


def demo_data():
    news = [
        {"source": "Demo Wire", "title": "Parliament passes long-debated transport bill after late-night session",
         "summary": "The bill, which funds new rail links and cheaper regional fares, passed with a comfortable majority after more than ten hours of debate."},
        {"source": "Demo World", "title": "Climate talks open with pledge to speed up emissions cuts",
         "summary": "Delegates from more than 150 countries gathered on Friday, with several large economies promising earlier targets."},
        {"source": "Demo Wire", "title": "Central bank holds rates steady, signals cautious outlook",
         "summary": "Policymakers said inflation is easing but warned that wage growth and energy prices remain a risk for the coming months."},
        {"source": "Demo World", "title": "Scientists report breakthrough in battery recycling process",
         "summary": "A new method recovers over 95 percent of lithium and cobalt, researchers said, and could cut costs for electric vehicles."},
        {"source": "Demo Wire", "title": "Local derby ends in dramatic 3-2 win with stoppage-time goal",
         "summary": "The home side came from behind twice before a late header decided one of the season's most talked-about matches."},
        {"source": "Demo World", "title": "Storm warning issued for western coast over the weekend",
         "summary": "Meteorologists expect strong gusts and heavy rain from Saturday afternoon; ferry services may be disrupted."},
    ]
    weather = {"place": "Copenhagen", "now": 9, "feels": 6, "wind": 7,
               "desc": "Partly cloudy", "hi": 11, "lo": 5, "rain_p": 40,
               "rain_mm": 0.8, "sunrise": "07:40", "sunset": "17:55"}
    events = [("09:00–09:30", "Team stand-up", "Teams"),
              ("12:00–13:00", "Lunch with Maria", "Café Norden"),
              ("15:30–16:30", "Dentist", "Vesterbrogade 12"),
              ("19:00–20:00", "Piano lesson", "")]
    return news, weather, events


# ------------------------------------------------------------------ render
def render(cfg, news, weather, events, now):
    W, H = cfg["screen"]["width"], cfg["screen"]["height"]
    s = W / 1072.0  # scale all sizes relative to a 1072px-wide screen
    fd = cfg.get("font_dir")
    serif_b = ["DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf"]
    serif = ["DejaVuSerif.ttf", "LiberationSerif-Regular.ttf"]
    sans = ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"]
    sans_b = ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"]
    F = lambda names, px: find_font(names, max(8, int(px * s)), fd)

    f_mast = F(serif_b, 92)
    f_date = F(serif, 26)
    f_sec = F(sans_b, 22)
    f_big = F(serif_b, 64)
    f_txt = F(sans, 26)
    f_txt_b = F(sans_b, 26)
    f_small = F(sans, 21)
    f_head = F(serif_b, 33)
    f_body = F(serif, 25)

    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    M = int(48 * s)
    cw = W - 2 * M

    def rule(y, w=2, x0=M, x1=W - M):
        d.line([(x0, y), (x1, y)], fill=0, width=max(1, int(w * s)))

    # Masthead
    y = int(30 * s)
    title = cfg.get("title", "THE DAILY PAPER")
    d.text((W / 2, y), title, font=f_mast, fill=0, anchor="mt")
    y += int(108 * s)
    rule(y, 4)
    y += int(8 * s)
    rule(y, 1)
    y += int(10 * s)
    datestr = now.strftime("%A, %d %B %Y")
    d.text((M, y), datestr, font=f_date, fill=0)
    d.text((W - M, y), f"Edition {now.strftime('%H:%M')}", font=f_date,
           fill=0, anchor="ra")
    y += int(40 * s)
    rule(y, 1)
    y += int(18 * s)

    # Weather (left) + Agenda (right)
    col_gap = int(36 * s)
    lw = int(cw * 0.42)
    rx = M + lw + col_gap
    rw = W - M - rx
    top = y

    # -- weather
    wy = top
    d.text((M, wy), "WEATHER", font=f_sec, fill=0)
    wy += int(32 * s)
    if weather:
        d.text((M, wy), f"{weather['now']}°", font=f_big, fill=0)
        d.text((M + int(150 * s), wy + int(8 * s)), weather["desc"],
               font=f_txt_b, fill=0)
        d.text((M + int(150 * s), wy + int(42 * s)), weather["place"],
               font=f_small, fill=0)
        wy += int(84 * s)
        rows = [
            f"High {weather['hi']}°  Low {weather['lo']}°",
            f"Feels like {weather['feels']}°, wind {weather['wind']} m/s",
            f"Rain {weather['rain_p']}%  ({weather['rain_mm']} mm)",
            f"Sun {weather['sunrise']} – {weather['sunset']}",
        ]
        for r in rows:
            d.text((M, wy), r, font=f_txt, fill=0)
            wy += int(34 * s)
    else:
        d.text((M, wy), "Weather unavailable", font=f_txt, fill=90)
        wy += int(34 * s)

    # -- agenda
    ay = top
    d.text((rx, ay), "TODAY'S AGENDA", font=f_sec, fill=0)
    ay += int(32 * s)
    if events is None:
        d.text((rx, ay), "No calendar configured", font=f_txt, fill=90)
        ay += int(34 * s)
    elif not events:
        d.text((rx, ay), "Nothing scheduled. Enjoy the day!", font=f_txt, fill=0)
        ay += int(34 * s)
    else:
        limit = top + int(330 * s)
        for i, (when, t, loc) in enumerate(events):
            lines = wrap(d, t, f_txt_b, rw)[:2]
            need = int(26 * s) + len(lines) * int(32 * s) + (int(26 * s) if loc else 0)
            if ay + need > limit and i > 0:
                d.text((rx, ay), f"+ {len(events) - i} more", font=f_small, fill=0)
                ay += int(28 * s)
                break
            d.text((rx, ay), when, font=f_small, fill=0)
            ay += int(26 * s)
            for ln in lines:
                d.text((rx, ay), ln, font=f_txt_b, fill=0)
                ay += int(32 * s)
            if loc:
                d.text((rx, ay), loc[:50], font=f_small, fill=90)
                ay += int(26 * s)
            ay += int(8 * s)

    # vertical divider
    block_bottom = max(wy, ay)
    d.line([(M + lw + col_gap // 2, top), (M + lw + col_gap // 2, block_bottom)],
           fill=0, width=max(1, int(1 * s)))
    y = block_bottom + int(12 * s)
    rule(y, 3)
    y += int(8 * s)
    d.text((M, y), "TOP STORIES", font=f_sec, fill=0)
    y += int(36 * s)
    rule(y, 1)
    y += int(16 * s)

    # News
    bottom = H - int(44 * s)
    shown = 0
    for item in news:
        h_lines = wrap(d, item["title"], f_head, cw)[:3]
        b_lines = wrap(d, item["summary"], f_body, cw) if item["summary"] else []
        max_b = 3
        if len(b_lines) > max_b:
            b_lines = b_lines[:max_b]
            b_lines[-1] = b_lines[-1].rstrip(" .,;") + "…"
        block = (int(22 * s) + len(h_lines) * int(40 * s)
                 + len(b_lines) * int(32 * s) + int(24 * s))
        if y + block > bottom:
            # try a version without summary before giving up
            block2 = int(22 * s) + len(h_lines) * int(40 * s) + int(20 * s)
            if y + block2 > bottom:
                break
            b_lines = []
        d.text((M, y), item["source"].upper(), font=f_small, fill=90)
        y += int(24 * s)
        for ln in h_lines:
            d.text((M, y), ln, font=f_head, fill=0)
            y += int(40 * s)
        for ln in b_lines:
            d.text((M, y), ln, font=f_body, fill=40)
            y += int(32 * s)
        y += int(8 * s)
        rule(y, 1, x0=M, x1=W - M)
        y += int(14 * s)
        shown += 1

    d.text((W / 2, H - int(30 * s)),
           f"Generated {now.strftime('%d %b %Y %H:%M')}  ·  {shown} stories",
           font=f_small, fill=90, anchor="mm")
    return img


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--demo", action="store_true", help="use fake data")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    tz = ZoneInfo(cfg["timezone"])
    now = dt.datetime.now(tz)

    if args.demo:
        news, weather, events = demo_data()
    else:
        news = get_news(cfg)
        weather = get_weather(cfg)
        events = get_events(cfg, now.date())

    img = render(cfg, news, weather, events, now)

    out = args.out or os.path.join(
        HERE, "out", os.environ.get("PAPER_NAME", "paper.png"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out, "PNG", optimize=True)  # 8-bit grayscale, non-interlaced
    print(f"Wrote {out} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
