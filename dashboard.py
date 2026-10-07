#!/usr/bin/env python3
"""Runs the job bot, merges new jobs into docs/jobs.json (30-day history),
and writes docs/index.html, a filterable dashboard. Meant for GitHub Actions."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import job_bot as b

DOCS = Path("docs")
DATA = DOCS / "jobs.json"
KEEP_DAYS = 30
MAX_NEW_PER_RUN = 60

TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Job Dashboard</title>
<style>
:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#e3e3e3;--card:#f7f7f8;--acc:#2563eb;--ok:#0a7a2f;--warn:#a15c00}
@media(prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#eee;--mut:#9aa3ad;--line:#2b2f36;--card:#1e2127;--acc:#6ea0ff;--ok:#5fd38a;--warn:#e8a24a}}
body{margin:0;font:15px system-ui,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:16px 20px;border-bottom:1px solid var(--line)}h1{margin:0;font-size:20px}.mut{color:var(--mut);font-size:13px}
.bar{display:flex;flex-wrap:wrap;gap:8px;padding:12px 20px;background:var(--card);border-bottom:1px solid var(--line)}
input,select{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
label{display:flex;align-items:center;gap:4px;font-size:14px}
.stats{padding:10px 20px}.list{padding:0 20px 40px}
.job{display:grid;grid-template-columns:48px 1fr auto;gap:12px;padding:12px 0;border-bottom:1px solid var(--line)}
.sc{font-weight:700;font-size:22px;text-align:center}.t{font-weight:600;color:var(--acc);text-decoration:none}
.tag{font-size:12px;margin-right:8px}.ok{color:var(--ok)}.warn{color:var(--warn)}
.new{background:var(--acc);color:#fff;border-radius:4px;padding:1px 6px;font-size:11px;margin-left:6px}
.done{opacity:.45}
</style></head><body>
<header><h1>Job Dashboard</h1><div class="mut" id="upd"></div></header>
<div class="bar">
<input id="q" placeholder="Search title or company" size="26">
<select id="min"><option value="0">Any score</option><option value="50">50+</option><option value="65" selected>65+</option><option value="80">80+</option></select>
<select id="stat"><option value="open" selected>Not applied/skipped</option><option value="all">All</option><option value="to">To apply</option><option value="applied">Applied</option><option value="skip">Skipped</option></select>
<select id="region"><option value="all" selected>US + International</option><option value="us">US only</option><option value="intl">International only</option></select>
<select id="sort"><option value="score">Sort: best match</option><option value="posted">Sort: newest posted</option><option value="seen">Sort: newest found</option></select>
<label><input type="checkbox" id="direct"> Company site only</label>
<label><input type="checkbox" id="recent"> Posted in last 3 days</label>
<label><input type="checkbox" id="fresh"> Found in last 24h</label>
</div>
<div class="stats mut" id="stats"></div><div class="list" id="list"></div>
<script>
const JOBS=__DATA__,UPDATED="__UPDATED__";
let st={};try{st=JSON.parse(localStorage.getItem("jobstatus")||"{}")}catch(e){}
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const safe=u=>/^https?:\/\//.test(u)?u:"#";
const cutoff=new Date(new Date(UPDATED)-864e5);
function ago(j){if(!j.posted)return "posted date unknown";const h=(Date.now()-new Date(j.posted))/36e5;
  if(h<24)return "posted today";const d=Math.floor(h/24);return "posted "+d+(d===1?" day":" days")+" ago";}
$("upd").textContent="Last updated "+new Date(UPDATED).toLocaleString()+" - updates automatically every day";
function render(){
  const q=$("q").value.toLowerCase(),min=+$("min").value,sf=$("stat").value,rg=$("region").value;
  let r=JOBS.filter(j=>{const s=st[j.key]||"";
    if(j.score<min)return false;
    if(rg==="us"&&j.intl)return false;
    if(rg==="intl"&&!j.intl)return false;
    if(q&&!(j.title+" "+j.company).toLowerCase().includes(q))return false;
    if($("direct").checked&&!j.direct)return false;
    if($("fresh").checked&&new Date(j.first_seen)<cutoff)return false;
    if($("recent").checked&&(!j.posted||Date.now()-new Date(j.posted)>3*864e5))return false;
    if(sf==="open")return s!=="applied"&&s!=="skip";
    if(sf==="to")return s==="to";if(sf==="applied")return s==="applied";if(sf==="skip")return s==="skip";return true;});
  const so=$("sort").value;
  r.sort(so==="seen"?(a,b)=>b.first_seen.localeCompare(a.first_seen)
    :so==="posted"?(a,b)=>(b.posted||"").localeCompare(a.posted||"")
    :(a,b)=>b.score-a.score);
  const ap=JOBS.filter(j=>st[j.key]==="applied").length;
  $("stats").textContent=r.length+" shown of "+JOBS.length+" tracked - "+ap+" applied";
  $("list").innerHTML=r.map(j=>{const s=st[j.key]||"";
    const pay=(j.salary_min||j.salary_max)?" - $"+Math.round((j.salary_min||0)/1000)+"K-$"+Math.round((j.salary_max||0)/1000)+"K":"";
    const link=j.direct?'<span class="tag ok">&#10003; company site</span>':'<span class="tag warn">via job board</span><a class="tag" target="_blank" rel="noopener" href="'+esc(safe(j.search_url))+'">find on company site</a>';
    return '<div class="job '+(s==="applied"||s==="skip"?"done":"")+'"><div class="sc">'+j.score+'</div><div>'
    +'<a class="t" target="_blank" rel="noopener" href="'+esc(safe(j.url))+'">'+esc(j.title)+'</a>'+(new Date(j.first_seen)>=cutoff?'<span class="new">NEW</span>':'')
    +'<div class="mut">'+(j.intl?'<b>INTL '+esc(j.country)+'</b> - ':'')+esc(j.company)+" - "+esc(j.location)+pay+" - "+ago(j)+'</div><div class="mut">'+esc(j.why)+'</div><div>'+link+'</div></div>'
    +'<select data-k="'+esc(j.key)+'"><option value="">Status</option><option value="to"'+(s==="to"?" selected":"")+'>To apply</option><option value="applied"'+(s==="applied"?" selected":"")+'>Applied</option><option value="skip"'+(s==="skip"?" selected":"")+'>Skip</option></select></div>';}).join("")||'<p class="mut">No jobs match these filters.</p>';
}
$("list").addEventListener("change",e=>{const k=e.target.dataset.k;if(!k)return;st[k]=e.target.value;try{localStorage.setItem("jobstatus",JSON.stringify(st))}catch(x){}render();});
["q","min","stat","region","sort","direct","recent","fresh"].forEach(i=>$(i).addEventListener("input",render));
render();
</script></body></html>"""


def main():
    now = datetime.now(timezone.utc)
    DOCS.mkdir(exist_ok=True)
    store = json.loads(DATA.read_text()) if DATA.exists() else {}

    raw = b.fetch_remotive() + b.fetch_greenhouse() + b.fetch_lever() + b.fetch_adzuna() + b.fetch_adzuna_intl()
    print(f"Pulled {len(raw)} postings")

    fresh = {}
    for job in raw:
        k = b.job_key(job)
        if k in store or k in fresh:
            continue
        s, reasons = b.score_job(job, now)
        if s is None or s < b.MIN_SCORE:
            continue
        job.update(score=s, why="; ".join(reasons), key=k)
        fresh[k] = job

    top = sorted(fresh.values(), key=lambda j: -j["score"])[:MAX_NEW_PER_RUN]
    b.finalize_links(top)
    for j in top:
        store[j["key"]] = {
            "key": j["key"], "title": j["title"], "company": j["company"],
            "location": j["location"], "url": j["url"], "direct": j["direct"],
            "search_url": j["search_url"], "score": j["score"], "why": j["why"],
            "source": j["source"], "intl": bool(j.get("intl")),
            "country": j.get("country", "US"), "salary_min": j["salary_min"],
            "salary_max": j["salary_max"], "first_seen": now.isoformat(),
            "posted": j["posted"].isoformat() if j["posted"] else None,
        }

    cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
    store = {k: v for k, v in store.items() if v["first_seen"] >= cutoff}
    DATA.write_text(json.dumps(store))

    data = json.dumps(list(store.values())).replace("</", "<\\/")
    page = TEMPLATE.replace("__DATA__", data).replace("__UPDATED__", now.isoformat())
    (DOCS / "index.html").write_text(page, encoding="utf-8")
    print(f"Added {len(top)} new jobs; dashboard tracks {len(store)}")


if __name__ == "__main__":
    main()
