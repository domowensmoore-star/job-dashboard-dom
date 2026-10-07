#!/usr/bin/env python3
"""
Daily Job Bot for Dominique Owens-Moore
---------------------------------------
Pulls marketing ops / MarTech jobs from free sources, scores each one against
your resume, drops duplicates and jobs you've already seen, and writes a ranked
HTML report + CSV. Run it once a day (see SCHEDULING at the bottom).

Uses only the Python standard library (Python 3.8+). No pip installs needed.

Sources:
  - Remotive        (no key)  remote jobs
  - Greenhouse      (no key)  company boards you list below
  - Lever           (no key)  company boards you list below
  - Adzuna          (free key) broad US coverage incl. LA/Orange County + salary
                    Get a free key at https://developer.adzuna.com/
                    then set env vars ADZUNA_APP_ID and ADZUNA_APP_KEY.
"""
import csv
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ----------------------------------------------------------------------------
# CONFIG - edit this section
# ----------------------------------------------------------------------------
OUTPUT_DIR = Path(os.environ.get("JOBBOT_DIR", Path.home() / "job_bot_output"))
TOP_N = 40                    # jobs shown in the HTML report
MIN_SCORE = 35                # hide anything scoring below this
MAX_AGE_DAYS = 14             # ignore postings older than this
SALARY_FLOOR = 65000          # drop jobs that DISCLOSE a max salary below this

SEARCH_TERMS = [
    "marketing operations",
    "marketing automation",
    "campaign operations",
    "email marketing operations",
    "marketing technology",
    "martech",
    "content operations",
    "marketing program manager",
]

ADZUNA_LOCATIONS = ["Los Angeles, CA", "Irvine, CA", "Orange County, CA"]

# Company boards. Slugs are the name in the careers URL, e.g.
# boards.greenhouse.io/<slug>  or  jobs.lever.co/<slug>
# Bad slugs are skipped with a warning, so just add/remove freely.
GREENHOUSE_BOARDS = ["airbnb", "stripe", "twilio", "figma", "discord", "databricks"]
LEVER_BOARDS = ["palantir", "plaid"]

# Title scoring (checked against lowercase title)
STRONG_TITLES = [
    "marketing operations", "marketing ops", "marketing automation",
    "campaign operations", "campaign manager", "email operations",
    "martech", "marketing technology", "marketing systems",
    "demand generation operations", "lifecycle marketing operations",
]
MEDIUM_TITLES = [
    "marketing program", "marketing project", "content operations",
    "web production", "digital operations", "email marketing",
    "marketing analyst", "campaign", "ad operations", "ad ops",
    "production manager", "workflow",
]
LEVEL_OK = ["specialist", "analyst", "manager", "coordinator", "associate", "senior"]
LEVEL_TOO_HIGH = ["director", "vp ", "vice president", "head of", "principal",
                  "chief", "svp", "evp"]
EXCLUDE_TITLES = ["intern", "internship", "sales representative", "account executive",
                  "sdr", "bdr", "software engineer", "recruiter", "nurse"]

# Skills from your resume. Each one found in the description adds points.
SKILLS = [
    "marketo", "salesforce marketing cloud", "sfmc", "hubspot", "pardot",
    "eloqua", "sql", "jira", "asana", "qa", "uat", "a/b test",
    "google analytics", "html", "aem", "adobe experience manager",
    "sharepoint", "campaign", "lead routing", "segmentation", "sla",
    "workflow", "intake", "salesforce",
]

# Location preferences
LOCAL_KEYWORDS = ["los angeles", "irvine", "orange county", "santa monica",
                  "culver city", "pasadena", "long beach", "costa mesa",
                  "newport beach", "burbank", "glendale", "anaheim", "el segundo",
                  "california", "ca,", ", ca"]
REMOTE_KEYWORDS = ["remote", "anywhere", "work from home", "united states", "usa", "us-"]

HEADERS = {"User-Agent": "Mozilla/5.0 (personal job search script)"}
TIMEOUT = 25

# Try to turn job-board links into the employer's own application page.
RESOLVE_LINKS = True
JOB_BOARD_DOMAINS = ["adzuna", "indeed", "linkedin", "ziprecruiter", "glassdoor",
                     "jooble", "talent.com", "simplyhired", "careerbuilder",
                     "monster", "learn4good", "jobrapido", "lensa", "remotive",
                     "snagajob", "jobsora", "recruit.net"]

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_date(value):
    """Return an aware datetime from ISO string or epoch ms, else None."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        v = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def make_job(source, title, company, location, url, posted, desc, smin=None, smax=None):
    return {
        "source": source,
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "location": (location or "").strip(),
        "url": url or "",
        "posted": posted,
        "desc": strip_html(desc)[:6000],
        "salary_min": smin,
        "salary_max": smax,
    }


# ----------------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------------
def fetch_remotive():
    jobs = []
    for term in SEARCH_TERMS:
        url = "https://remotive.com/api/remote-jobs?" + urllib.parse.urlencode(
            {"search": term, "limit": 50})
        try:
            for j in get_json(url).get("jobs", []):
                jobs.append(make_job(
                    "Remotive", j.get("title"), j.get("company_name"),
                    "Remote - " + (j.get("candidate_required_location") or ""),
                    j.get("url"), parse_date(j.get("publication_date")),
                    j.get("description")))
        except Exception as e:
            print(f"[warn] Remotive '{term}': {e}")
    return jobs


def fetch_greenhouse():
    jobs = []
    for slug in GREENHOUSE_BOARDS:
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        try:
            for j in get_json(url).get("jobs", []):
                title = j.get("title", "")
                if not looks_relevant(title):
                    continue
                jobs.append(make_job(
                    f"Greenhouse:{slug}", title, slug.title(),
                    (j.get("location") or {}).get("name"),
                    j.get("absolute_url"), parse_date(j.get("updated_at")),
                    j.get("content")))
        except Exception as e:
            print(f"[warn] Greenhouse '{slug}' skipped: {e}")
    return jobs


def fetch_lever():
    jobs = []
    for slug in LEVER_BOARDS:
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        try:
            for j in get_json(url):
                title = j.get("text", "")
                if not looks_relevant(title):
                    continue
                jobs.append(make_job(
                    f"Lever:{slug}", title, slug.title(),
                    (j.get("categories") or {}).get("location"),
                    j.get("hostedUrl"), parse_date(j.get("createdAt")),
                    j.get("descriptionPlain") or j.get("description")))
        except Exception as e:
            print(f"[warn] Lever '{slug}' skipped: {e}")
    return jobs


def fetch_adzuna():
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        print("[info] Adzuna skipped (set ADZUNA_APP_ID / ADZUNA_APP_KEY to enable)")
        return []
    jobs = []
    combos = [(t, loc) for t in SEARCH_TERMS[:5] for loc in ADZUNA_LOCATIONS]
    combos += [(t, None) for t in SEARCH_TERMS[:5]]  # nationwide; remote hits scored later
    for term, loc in combos:
        params = {"app_id": app_id, "app_key": app_key, "what": term,
                  "results_per_page": 50, "sort_by": "date",
                  "max_days_old": MAX_AGE_DAYS, "content-type": "application/json"}
        if loc:
            params["where"] = loc
            params["distance"] = 40
        url = "https://api.adzuna.com/v1/api/jobs/us/search/1?" + urllib.parse.urlencode(params)
        try:
            for j in get_json(url).get("results", []):
                jobs.append(make_job(
                    "Adzuna", j.get("title"), (j.get("company") or {}).get("display_name"),
                    (j.get("location") or {}).get("display_name"),
                    j.get("redirect_url"), parse_date(j.get("created")),
                    j.get("description"), j.get("salary_min"), j.get("salary_max")))
        except Exception as e:
            print(f"[warn] Adzuna '{term}' / {loc}: {e}")
    return jobs


def looks_relevant(title):
    t = title.lower()
    return any(k in t for k in STRONG_TITLES + MEDIUM_TITLES) or (
        "marketing" in t and any(k in t for k in LEVEL_OK))


# ----------------------------------------------------------------------------
# Scoring: 0-100. Higher = better odds for YOUR background.
#   title fit 40 + skill overlap 25 + freshness 15 + location 10 + pay/level 10
# ----------------------------------------------------------------------------
def score_job(job, now):
    title = job["title"].lower()
    desc = job["desc"].lower()
    loc = job["location"].lower()
    reasons = []

    if any(x in title for x in EXCLUDE_TITLES):
        return None, ["excluded title"]
    if any(x in (title + " ") for x in LEVEL_TOO_HIGH):
        return None, ["too senior"]
    if job["salary_max"] and job["salary_max"] < SALARY_FLOOR:
        return None, ["pay below floor"]

    score = 0

    # Title fit (40)
    if any(k in title for k in STRONG_TITLES):
        score += 40; reasons.append("strong title match")
    elif any(k in title for k in MEDIUM_TITLES):
        score += 25; reasons.append("related title")
    elif "marketing" in title:
        score += 10

    # Skill overlap (25): 5 pts per distinct skill, capped
    hits = sorted({s for s in SKILLS if s in desc or s in title})
    score += min(25, 5 * len(hits))
    if hits:
        reasons.append("skills: " + ", ".join(hits[:6]))

    # Freshness (15): earlier applicants get most interviews
    if job["posted"]:
        age = (now - job["posted"]).total_seconds() / 86400
        if age > MAX_AGE_DAYS:
            return None, ["too old"]
        if age <= 1:
            score += 15; reasons.append("posted <24h: APPLY NOW")
        elif age <= 3:
            score += 10; reasons.append("posted <3d")
        elif age <= 7:
            score += 5
    else:
        score += 3

    # Location (10)
    if any(k in loc for k in REMOTE_KEYWORDS) or "remote" in desc[:400]:
        score += 10; reasons.append("remote")
    elif any(k in loc for k in LOCAL_KEYWORDS):
        score += 10; reasons.append("local")
    else:
        score -= 10  # not remote and not near you

    # Level / pay (10)
    if any(x in title for x in LEVEL_OK):
        score += 5
    if job["salary_min"] and job["salary_min"] >= SALARY_FLOOR:
        score += 5; reasons.append("pay disclosed")

    return max(0, min(100, score)), reasons


# ----------------------------------------------------------------------------
# Pipeline
# ----------------------------------------------------------------------------
def resolve_link(url):
    """Follow redirects (e.g. Adzuna tracking links) to the final page."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.geturl()
    except Exception:
        return url  # keep the original link if the site blocks us


def is_direct(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    return bool(host) and not any(d in host for d in JOB_BOARD_DOMAINS)


def finalize_links(jobs):
    """Resolve links for the jobs we'll actually show, and add a fallback search link."""
    for j in jobs:
        if RESOLVE_LINKS and not is_direct(j["url"]):
            j["url"] = resolve_link(j["url"])
        j["direct"] = is_direct(j["url"])
        q = urllib.parse.quote_plus(f'{j["company"]} careers {j["title"]}')
        j["search_url"] = "https://www.google.com/search?q=" + q


def job_key(job):
    base = (job["title"] + "|" + job["company"]).lower()
    return re.sub(r"[^a-z0-9|]", "", base)


def run():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    seen_path = OUTPUT_DIR / "seen.json"
    seen = set(json.loads(seen_path.read_text())) if seen_path.exists() else set()

    print("Fetching jobs...")
    raw = fetch_remotive() + fetch_greenhouse() + fetch_lever() + fetch_adzuna()
    print(f"Pulled {len(raw)} postings")

    scored, batch_keys = [], set()
    for job in raw:
        k = job_key(job)
        if k in seen or k in batch_keys:
            continue
        s, reasons = score_job(job, now)
        if s is None or s < MIN_SCORE:
            continue
        batch_keys.add(k)
        job["score"], job["why"], job["key"] = s, "; ".join(reasons), k
        scored.append(job)

    scored.sort(key=lambda j: j["score"], reverse=True)
    top = scored[:TOP_N]
    print(f"{len(scored)} new matches; resolving links for top {len(top)}...")
    finalize_links(top)
    print(f"{sum(j['direct'] for j in top)} of {len(top)} link straight to a company site")

    stamp = now.astimezone().strftime("%Y-%m-%d")
    write_html(top, OUTPUT_DIR / f"jobs_{stamp}.html", stamp)
    append_csv(scored, OUTPUT_DIR / "jobs_master.csv", stamp)

    seen.update(j["key"] for j in scored)
    seen_path.write_text(json.dumps(sorted(seen)))
    print(f"Done. Open: {OUTPUT_DIR / f'jobs_{stamp}.html'}")


def write_html(jobs, path, stamp):
    rows = []
    for j in jobs:
        posted = j["posted"].strftime("%b %d") if j["posted"] else "?"
        pay = ""
        if j["salary_min"] or j["salary_max"]:
            pay = f"${int(j['salary_min'] or 0):,} - ${int(j['salary_max'] or 0):,}"
        rows.append(
            f"<tr><td class='s'>{j['score']}</td>"
            f"<td><a href='{html.escape(j['url'])}' target='_blank'>{html.escape(j['title'])}</a>"
            f"<br><small>{html.escape(j['why'])}</small><br>"
            + (f"<small class='ok'>&#10003; company site</small>" if j.get("direct")
               else f"<small class='board'>via job board</small> &middot; "
                    f"<small><a href='{html.escape(j.get('search_url', ''))}' target='_blank'>"
                    f"find on company site</a></small>")
            + "</td>"
            f"<td>{html.escape(j['company'])}</td><td>{html.escape(j['location'])}</td>"
            f"<td>{posted}</td><td>{pay}</td><td>{html.escape(j['source'])}</td></tr>")
    page = f"""<!doctype html><meta charset=utf-8><title>Jobs {stamp}</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;max-width:1200px}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}}
th{{background:#f4f4f4}}.s{{font-weight:700;font-size:1.2em}}small{{color:#666}}.ok{{color:#0a7a2f;font-weight:600}}.board{{color:#a15c00}}</style>
<h2>Top job matches - {stamp}</h2>
<p>Score = title fit + skill overlap + freshness + location + level/pay. Apply to the top ones first, especially anything posted under 24 hours ago.</p>
<table><tr><th>Score</th><th>Role</th><th>Company</th><th>Location</th><th>Posted</th><th>Pay</th><th>Source</th></tr>
{''.join(rows) or '<tr><td colspan=7>No new matches today.</td></tr>'}</table>"""
    path.write_text(page, encoding="utf-8")


def append_csv(jobs, path, stamp):
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date_found", "score", "title", "company", "location",
                        "posted", "salary_min", "salary_max", "url", "source",
                        "why", "status"])
        for j in jobs:
            w.writerow([stamp, j["score"], j["title"], j["company"], j["location"],
                        j["posted"].date() if j["posted"] else "", j["salary_min"] or "",
                        j["salary_max"] or "", j["url"], j["source"], j["why"], "to apply"])


if __name__ == "__main__":
    run()

# ----------------------------------------------------------------------------
# SCHEDULING (run once a day, e.g. 7:00 AM)
#   Mac/Linux:  crontab -e   then add:
#       0 7 * * * /usr/bin/python3 /path/to/job_bot.py
#   Windows:    Task Scheduler > Create Basic Task > Daily > Start a program
#       Program: python    Arguments: C:\path\to\job_bot.py
#   Free cloud option: a GitHub Actions workflow with a daily cron trigger.
# ----------------------------------------------------------------------------
