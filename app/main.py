from __future__ import annotations

import csv
import io
import json
import threading
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from .scraper import SearchCancelled, scrape

app = FastAPI(title="Local Amazon Jobs Scraper", version="1.0.0")
active_searches: dict[str, threading.Event] = {}
active_searches_lock = threading.Lock()


class SearchInput(BaseModel):
    searchKeyword: str = ""
    location: str = ""
    requestId: str = ""
    searchUrls: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    jobTypes: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    sortBy: str = "relevant"
    maxResults: int = Field(default=100, ge=0, le=10_000)


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(PAGE)


@app.post("/api/search")
def search(data: SearchInput):
    cancel_event = threading.Event()
    if data.requestId:
        with active_searches_lock:
            active_searches[data.requestId] = cancel_event
    try:
        jobs, total = scrape(data.model_dump(), cancel_event=cancel_event)
    except SearchCancelled:
        raise HTTPException(status_code=409, detail="Search cancelled.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Amazon jobs search failed: {exc}") from exc
    finally:
        if data.requestId:
            with active_searches_lock:
                if active_searches.get(data.requestId) is cancel_event:
                    active_searches.pop(data.requestId, None)
    return {"totalHits": total, "returned": len(jobs), "jobs": jobs}


@app.post("/api/search/{request_id}/cancel")
def cancel_search(request_id: str):
    with active_searches_lock:
        event = active_searches.get(request_id)
        if event:
            event.set()
    return {"cancelled": event is not None}


@app.post("/api/export")
def export(data: SearchInput, format: str = Query("json", pattern="^(json|csv)$")):
    try:
        jobs, _ = scrape(data.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Amazon jobs search failed: {exc}") from exc
    if format == "json":
        return Response(json.dumps(jobs, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": "attachment; filename=amazon-jobs.json"})
    output = io.StringIO()
    fields = list(jobs[0].keys()) if jobs else []
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    if fields:
        writer.writeheader()
        for job in jobs:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in job.items()})
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=amazon-jobs.csv"})


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Amazon Jobs Scraper</title>
<style>
:root{color-scheme:dark;font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#e5e7eb;background:#111318;--surface:#191b22;--line:#30343e;--muted:#9ca3af;--accent:#a3e635;--accent-hover:#bef264}*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 50% -260px,#292d38 0,transparent 760px),#111318;min-height:100vh}.shell{width:100%;max-width:none;margin:0 auto;padding:28px clamp(16px,2.4vw,40px) 56px}.head{padding:0 0 20px;border-bottom:1px solid var(--line);margin-bottom:24px;display:grid;grid-template-columns:76px 1fr;grid-template-rows:auto auto;align-items:center;column-gap:14px}.brand-logo{grid-column:1;grid-row:1/3;width:76px;height:42px;display:block}h1{grid-column:2;grid-row:1}.head .sub{grid-column:2;grid-row:2}h1{font-size:23px;letter-spacing:-.035em;margin:0;font-weight:650}.sub{color:var(--muted);margin:2px 0 0}.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:22px;margin-bottom:18px;box-shadow:0 8px 24px #0002}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px 16px}label{display:block;font-weight:600;font-size:12px;color:#d1d5db;margin-bottom:6px}input,select,textarea{width:100%;padding:10px 12px;border:1px solid #3a3f4a;border-radius:6px;background:#14161b;color:#f3f4f6;font:inherit;outline:none;transition:border-color .15s,box-shadow .15s}input:focus,select:focus,textarea:focus,.multi[open] summary{border-color:#84cc16;box-shadow:0 0 0 2px #84cc1622}input::placeholder,textarea::placeholder{color:#727987}input[type=checkbox]{accent-color:#a3e635}textarea{min-height:76px;resize:vertical}.multi{position:relative}.multi summary{padding:10px 12px;border:1px solid #3a3f4a;border-radius:6px;background:#14161b;cursor:pointer;list-style:none;color:#e5e7eb}.multi summary::-webkit-details-marker{display:none}.multi summary:after{content:'⌄';float:right;color:#9ca3af;font-size:16px;line-height:1.2}.multi[open] summary{border-radius:6px 6px 0 0}.options{position:absolute;z-index:5;top:100%;left:0;right:0;max-height:260px;overflow:auto;padding:8px;background:#20232b;border:1px solid #3a3f4a;border-top:0;border-radius:0 0 6px 6px;box-shadow:0 12px 26px #0008}.options label{display:flex;align-items:center;gap:9px;padding:6px 5px;font-weight:450;font-size:13px;margin:0;border-radius:4px}.options label:hover{background:#2b303a}.options input{width:auto;margin:0}.wide{grid-column:1/-1}.actions{display:flex;gap:9px;margin-top:20px;padding-top:16px;border-top:1px solid var(--line);align-items:center;flex-wrap:wrap}button{border:1px solid #a3e635;border-radius:6px;padding:9px 15px;background:var(--accent);color:#171a12;font-weight:700;cursor:pointer;transition:background .15s,transform .15s}button:hover{background:var(--accent-hover)}button:active{transform:translateY(1px)}button.secondary{background:#252932;border-color:#3a3f4a;color:#e5e7eb}button.secondary:hover{background:#303540}.status{color:var(--muted);margin-left:auto;align-self:center;font-size:13px}h2{font-size:16px;font-weight:650;letter-spacing:-.01em;margin:0 0 14px}.tablewrap{width:100%;overflow-x:hidden;border:1px solid var(--line);border-radius:7px}table{border-collapse:collapse;width:100%;table-layout:fixed;background:#17191f}th:nth-child(1){width:20%}th:nth-child(2){width:16%}th:nth-child(3){width:17%}th:nth-child(4){width:14%}th:nth-child(5){width:10%}th:nth-child(6){width:23%}th,td{text-align:left;padding:11px 12px;border-bottom:1px solid #2a2e37;vertical-align:top;overflow-wrap:anywhere;word-break:normal}th{color:#9ca3af;font-size:11px;letter-spacing:.055em;text-transform:uppercase;background:#1e2128;white-space:nowrap}tbody tr:last-child td{border-bottom:0}tbody tr:hover{background:#20232a}td a{color:#bef264;text-decoration:none;overflow-wrap:anywhere}td a:hover{text-decoration:underline}pre{white-space:pre-wrap;max-height:440px;overflow:auto;background:#121419;color:#d1d5db;padding:16px;border:1px solid var(--line);border-radius:7px}details>summary{cursor:pointer;color:#c5cad3}.hint{font-size:12px;color:#858c99;margin-top:6px}.shell>p.hint{line-height:1.7;max-width:860px;margin:22px 0 0}@media(max-width:760px){.grid{grid-template-columns:1fr 1fr}.wide{grid-column:1/-1}.shell{padding:20px 15px 40px}.card{padding:17px}.head{align-items:flex-start}.status{width:100%;margin:2px 0 0}}@media(max-width:480px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}.actions button{flex:1}.status{order:5}}
</style></head><body><main class="shell"><header class="head"><svg class="brand-logo" viewBox="0 0 120 56" role="img" aria-label="Amazon"><text x="3" y="34" fill="#f3f4f6" font-family="Arial, sans-serif" font-size="30" font-weight="700" letter-spacing="-1.5">amazon</text><path d="M17 42 C42 55 78 55 103 39" fill="none" stroke="#ff9900" stroke-width="4" stroke-linecap="round"/><path d="M95 38 L105 37 L101 46" fill="none" stroke="#ff9900" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg><h1>Amazon Jobs Scraper</h1><p class="sub">Search Amazon’s public careers listings and export structured results locally.</p></header>
<section class="card"><form id="form"><div class="grid">
<div><label for="keyword">Keyword</label><input id="keyword" value="" placeholder="e.g. data scientist"></div>
<div><label for="location">City</label><input id="location" placeholder="e.g. Seattle"></div>
<div><label for="sort">Sort order</label><select id="sort"><option value="relevant">Relevance</option><option value="recent">Most recent</option></select></div>
<div><label>Categories</label><details class="multi" id="categories"><summary>All categories</summary><div class="options">
<label><input type="checkbox" value="Administrative Support">Administrative Support</label><label><input type="checkbox" value="Applied Science">Applied Science</label><label><input type="checkbox" value="Audio/Video/Photography Production">Audio/Video/Photography Production</label><label><input type="checkbox" value="Business Intelligence">Business Intelligence</label><label><input type="checkbox" value="Business &amp; Merchant Development">Business &amp; Merchant Development</label><label><input type="checkbox" value="Buying, Planning, &amp; Instock Management">Buying, Planning, &amp; Instock Management</label><label><input type="checkbox" value="Corporate Operations">Corporate Operations</label><label><input type="checkbox" value="Customer Service">Customer Service</label><label><input type="checkbox" value="Data Science">Data Science</label><label><input type="checkbox" value="Database Administration">Database Administration</label><label><input type="checkbox" value="Design">Design</label><label><input type="checkbox" value="Economics">Economics</label><label><input type="checkbox" value="Editorial, Writing, &amp; Content Management">Editorial, Writing, &amp; Content Management</label><label><input type="checkbox" value="Facilities, Maintenance, &amp; Real Estate">Facilities, Maintenance, &amp; Real Estate</label><label><input type="checkbox" value="Finance &amp; Accounting">Finance &amp; Accounting</label><label><input type="checkbox" value="Fulfillment Associate">Fulfillment Associate</label><label><input type="checkbox" value="Fulfillment &amp; Operations Management">Fulfillment &amp; Operations Management</label><label><input type="checkbox" value="Fulfillment Warehouse Associate">Fulfillment Warehouse Associate</label><label><input type="checkbox" value="Hardware Development">Hardware Development</label><label><input type="checkbox" value="Human Resources">Human Resources</label><label><input type="checkbox" value="Investigation &amp; Loss Prevention">Investigation &amp; Loss Prevention</label><label><input type="checkbox" value="Leadership Development &amp; Training">Leadership Development &amp; Training</label><label><input type="checkbox" value="Legal">Legal</label><label><input type="checkbox" value="Machine Learning Science">Machine Learning Science</label><label><input type="checkbox" value="Marketing">Marketing</label><label><input type="checkbox" value="Medical, Health, &amp; Safety">Medical, Health, &amp; Safety</label><label><input type="checkbox" value="Operations, IT, &amp; Support Engineering">Operations, IT, &amp; Support Engineering</label><label><input type="checkbox" value="Procurement">Procurement</label><label><input type="checkbox" value="Project/Program/Product Management--Non-Tech">Project/Program/Product Management--Non-Tech</label><label><input type="checkbox" value="Project/Program/Product Management--Technical">Project/Program/Product Management--Technical</label><label><input type="checkbox" value="Public Policy">Public Policy</label><label><input type="checkbox" value="Public Relations">Public Relations</label><label><input type="checkbox" value="Research Science">Research Science</label><label><input type="checkbox" value="Sales, Advertising, &amp; Account Management">Sales, Advertising, &amp; Account Management</label><label><input type="checkbox" value="Software Development">Software Development</label><label><input type="checkbox" value="Solutions Architect">Solutions Architect</label><label><input type="checkbox" value="Supply Chain/Transportation Management">Supply Chain/Transportation Management</label><label><input type="checkbox" value="Systems, Quality, &amp; Security Engineering">Systems, Quality, &amp; Security Engineering</label></div></details><div class="hint">Select one or more Amazon categories</div></div>
<div><label>Countries</label><details class="multi" id="countries"><summary>Worldwide</summary><div class="options"><label><input type="checkbox" value="USA">United States</label><label><input type="checkbox" value="GBR">United Kingdom</label><label><input type="checkbox" value="DEU">Germany</label><label><input type="checkbox" value="IND">India</label><label><input type="checkbox" value="JPN">Japan</label><label><input type="checkbox" value="CAN">Canada</label><label><input type="checkbox" value="BRA">Brazil</label><label><input type="checkbox" value="ARE">United Arab Emirates</label><label><input type="checkbox" value="AUS">Australia</label><label><input type="checkbox" value="FRA">France</label><label><input type="checkbox" value="ITA">Italy</label><label><input type="checkbox" value="ESP">Spain</label><label><input type="checkbox" value="MEX">Mexico</label><label><input type="checkbox" value="SGP">Singapore</label><label><input type="checkbox" value="IRL">Ireland</label><label><input type="checkbox" value="POL">Poland</label><label><input type="checkbox" value="NLD">Netherlands</label><label><input type="checkbox" value="SWE">Sweden</label><label><input type="checkbox" value="TUR">Türkiye</label><label><input type="checkbox" value="ZAF">South Africa</label></div></details><div class="hint">Select one or more countries; leave empty for worldwide</div></div>
<div><label>Job schedule types</label><details class="multi" id="types"><summary>All types</summary><div class="options"><label><input type="checkbox" value="Full-Time">Full-time</label><label><input type="checkbox" value="Part-Time">Part-time</label><label><input type="checkbox" value="Part-Time (20-29 hours)">Part-time (20-29 hours)</label><label><input type="checkbox" value="Reduced-Time (30-39 hours)">Reduced-time (30-39 hours)</label><label><input type="checkbox" value="Flex time">Flex time</label><label><input type="checkbox" value="Flex-time (under 19 hours)">Flex-time (under 19 hours)</label></div></details></div>
<div><label for="max">Maximum results</label><input id="max" type="number" min="0" max="10000" value="100"><div class="hint">0 means the available 10,000-result search window</div></div>
<div class="wide"><label for="urls">Search URLs (optional)</label><textarea id="urls" placeholder="Paste one Amazon Jobs search URL per line"></textarea><div class="hint">Each URL is paginated as a separate search and deduplicated by job ID.</div></div>
</div><div class="actions"><button id="run" type="submit">Search jobs</button><button id="cancel" class="secondary" type="button" hidden>Cancel search</button><button id="json" class="secondary" type="button">Download JSON</button><button id="csv" class="secondary" type="button">Download CSV</button><span class="status" id="status">Ready</span></div></form></section>
<section class="card"><h2 id="summary">Results</h2><div class="tablewrap"><table><thead><tr><th>Title</th><th>Location</th><th>Category</th><th>Schedule</th><th>Posted</th><th>Job URL</th></tr></thead><tbody id="rows"><tr><td colspan="6">Run a search to load live results.</td></tr></tbody></table></div><details style="margin-top:15px"><summary>View raw JSON</summary><pre id="raw">[]</pre></details></section>
<p class="hint">Runs on your PC. Results come from Amazon Jobs’ public search pages; the site may change its undocumented response format or limit automated requests.</p></main>
<script>
const $=id=>document.getElementById(id);let last=[];
function selected(id){return [...$(id).querySelectorAll('input[type=checkbox]:checked')].map(x=>x.value)}
function updateMenu(id,empty){const root=$(id),items=selected(id);root.querySelector('summary').textContent=items.length?`${items.length} selected`:empty}
for(const id of ['categories','countries','types']){$(id).addEventListener('change',()=>updateMenu(id,{categories:'All categories',countries:'Worldwide',types:'All types'}[id]));$(id).addEventListener('toggle',()=>{if($(id).open)for(const other of ['categories','countries','types'])if(other!==id)$(other).open=false})}
document.addEventListener('click',e=>{if(!e.target.closest('.multi'))document.querySelectorAll('.multi[open]').forEach(menu=>menu.open=false)});
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelectorAll('.multi[open]').forEach(menu=>menu.open=false)});
function input(){return {searchKeyword:$('keyword').value.trim(),location:$('location').value.trim(),sortBy:$('sort').value,categories:selected('categories'),countries:selected('countries'),jobTypes:selected('types'),searchUrls:$('urls').value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean),maxResults:Number($('max').value||0)}}
let activeSearch=null;
function cancelCurrent(){if(!activeSearch)return;const current=activeSearch;current.controller.abort();fetch('/api/search/'+encodeURIComponent(current.id)+'/cancel',{method:'POST'}).catch(()=>{});if(activeSearch===current){activeSearch=null;$('cancel').hidden=true;$('status').textContent='Search cancelled';$('run').textContent='Search jobs'}}
async function run(){if(activeSearch)cancelCurrent();const id=(window.crypto?.randomUUID?window.crypto.randomUUID():`${Date.now()}-${Math.random()}`),controller=new AbortController();activeSearch={id,controller};$('cancel').hidden=false;$('run').textContent='Start new search';$('status').textContent='Searching Amazon Jobs…';try{const r=await fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...input(),requestId:id}),signal:controller.signal});const data=await r.json();if(!r.ok)throw Error(data.detail||'Request failed');last=data.jobs;$('summary').textContent=`${data.returned.toLocaleString()} jobs returned${data.totalHits?` · ${data.totalHits.toLocaleString()} reported hits`:''}`;$('raw').textContent=JSON.stringify(last,null,2);$('rows').innerHTML=last.map(j=>`<tr><td>${esc(j.title)}</td><td>${esc(j.normalizedLocation||j.location)}</td><td>${esc(j.jobCategory)}</td><td>${esc(j.jobScheduleType)}</td><td>${esc(j.postedDate)}</td><td><a href="${esc(j.detailUrl)}" target="_blank" rel="noreferrer">${esc(j.detailUrl)}</a></td></tr>`).join('')||'<tr><td colspan="6">No matching jobs.</td></tr>';$('status').textContent='Done'}catch(e){if(e.name!=='AbortError'&&activeSearch?.id===id)$('status').textContent='Error: '+e.message}finally{if(activeSearch?.id===id){activeSearch=null;$('cancel').hidden=true;$('run').textContent='Search jobs'}}}
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
$('form').addEventListener('submit',e=>{e.preventDefault();run()});for(const fmt of ['json','csv'])$(''+fmt).onclick=async()=>{ $('status').textContent='Preparing '+fmt.toUpperCase()+'…';try{const r=await fetch('/api/export?format='+fmt,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(input())});if(!r.ok){let d=await r.json();throw Error(d.detail||'Export failed')}const b=await r.blob(),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='amazon-jobs.'+fmt;a.click();URL.revokeObjectURL(a.href);$('status').textContent='Downloaded'}catch(e){$('status').textContent='Error: '+e.message}};
$('cancel').addEventListener('click',cancelCurrent);
</script></body></html>'''
