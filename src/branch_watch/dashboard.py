"""Local multi-repository release dashboard."""

import json
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from .ai import AIError, analyze_release_risk
from .github import GitHubClient, GitHubError, parse_repo


HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Branch Watch / Release Control</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Space+Grotesk:wght@400;500;600;700&display=swap');
:root{--ink:#17211f;--muted:#71807c;--paper:#f4f1e9;--panel:#fffdf8;--line:#d9ded6;--mint:#bce4d0;--green:#21845f;--orange:#d87535;--red:#c84d45;--navy:#24484b}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:radial-gradient(circle at 82% 0,#e1eee2 0,transparent 34%),var(--paper);font-family:'Space Grotesk',sans-serif}header{display:flex;justify-content:space-between;align-items:center;padding:28px 5vw;border-bottom:1px solid var(--line)}.brand{font-weight:700;font-size:20px}.refresh,.action{border:1px solid var(--line);background:var(--panel);padding:10px 14px;border-radius:6px;font:500 12px 'DM Mono',monospace;cursor:pointer}.action{background:var(--navy);color:white;border:0}main{max-width:1440px;margin:auto;padding:54px 5vw 80px}.eyebrow{color:var(--orange);font:500 12px 'DM Mono',monospace;text-transform:uppercase;letter-spacing:.12em}h1{max-width:720px;margin:12px 0 10px;font-size:clamp(38px,5vw,68px);line-height:.98;letter-spacing:-.07em}.lede{max-width:610px;color:var(--muted);line-height:1.6;margin:0 0 40px}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:44px}.metric,.repo{background:var(--panel);border:1px solid var(--line)}.metric{padding:18px 20px;min-height:102px}.metric strong{display:block;font-size:35px;letter-spacing:-.06em;margin-top:9px}.metric span,.label{color:var(--muted);font:11px 'DM Mono',monospace;text-transform:uppercase}.section-head{display:flex;justify-content:space-between;margin-bottom:15px}h2{margin:0;font-size:21px}.updated{color:var(--muted);font:11px 'DM Mono',monospace}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px}.repo{padding:22px;position:relative}.repo:before{content:'';position:absolute;width:5px;inset:0 auto 0 0;background:var(--green)}.repo.behind:before{background:var(--orange)}.repo.hotfix-missing:before{background:var(--red)}.top,.deploy,.actions{display:flex;justify-content:space-between;gap:12px}.repo-name{font-size:20px;font-weight:600}.badge{padding:6px 9px;background:#e5f2e8;color:var(--green);font:500 10px 'DM Mono',monospace;text-transform:uppercase}.behind .badge{background:#fff0e2;color:var(--orange)}.hotfix-missing .badge{background:#fbe7e3;color:var(--red)}.branches{display:flex;gap:10px;margin:22px 0 18px;font:12px 'DM Mono',monospace}.branch{background:#eef1ea;padding:7px 8px}.counts{display:flex;gap:18px;padding:14px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);font:12px 'DM Mono',monospace}.counts b{font-size:18px}.warn{color:var(--orange)}.danger{color:var(--red)}.commit{padding-top:17px}.commit+.commit{margin-top:14px;padding-top:14px;border-top:1px dashed var(--line)}.commit-title{margin:6px 0;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.meta{color:var(--muted);font:11px 'DM Mono',monospace}.deploy{margin-top:20px;background:#f1f4ee;padding:11px 12px;color:var(--muted);font:11px 'DM Mono',monospace}.deploy b{color:var(--green);font-weight:500}.actions{align-items:center;margin-top:18px}.empty,.error{border:1px dashed var(--line);padding:28px;color:var(--muted)}@media(max-width:700px){header{padding:20px}main{padding:38px 20px 60px}.summary{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}h1{font-size:46px}}
</style></head><body><header><div class="brand">● branch watch <span style="color:#9aa6a0;font:11px monospace">/ control room</span></div><button class="refresh" id="refresh">REFRESH DATA</button></header><main><div class="eyebrow">Release confidence · multi-repository</div><h1>Find the hotfix before it finds production.</h1><p class="lede">A single view of production and release branches, with the commit trail and deployment context your release decision needs.</p><section class="summary" id="summary"></section><div class="section-head"><h2>Repository watchlist</h2><span class="updated" id="updated">Loading...</span></div><section class="grid" id="repos"><div class="empty">Connecting to GitHub...</div></section></main><script>
const $=id=>document.getElementById(id), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])), date=v=>v?new Date(v).toLocaleString([], {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'time unavailable';
function commit(c,label){return `<div class="commit"><div class="label">${label} · ${esc(c.sha)}</div><div class="commit-title">${esc(c.message)}</div><div class="meta">${esc(c.author)} · ${esc(date(c.timestamp))}</div></div>`}
function comparisonUrl(row){const repo=row.repo.split('/').map(encodeURIComponent).join('/');return `https://github.com/${repo}/compare/${encodeURIComponent(row.production)}...${encodeURIComponent(row.release)}`}
function render(data){let rows=data.repositories||[], n={synced:0,behind:0,'hotfix-missing':0};rows.forEach(r=>n[r.status]++);$('summary').innerHTML=[['synced','Synced'],['behind','Behind'],['hotfix-missing','Hotfix missing'],['total','Repositories']].map(([k,l])=>`<div class="metric"><span>${l}</span><strong>${k==='total'?rows.length:n[k]}</strong></div>`).join('');$('updated').textContent='Updated '+new Date().toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});$('repos').innerHTML=rows.length?rows.map(r=>`<article class="repo ${esc(r.status)}"><div class="top"><div class="repo-name">${esc(r.repo)}</div><div class="badge">${esc({synced:'Synced',behind:'Behind','hotfix-missing':'Hotfix missing'}[r.status])}</div></div><div class="branches"><span class="branch">${esc(r.production)}</span>→<span class="branch">${esc(r.release)}</span></div><div class="counts"><span class="${r.behind?'warn':''}"><b>${r.behind}</b> behind</span><span class="${r.ahead?'danger':''}"><b>${r.ahead}</b> ahead</span></div>${commit(r.production_commit,'Latest production commit')}${commit(r.release_commit,'Release commit')}<div class="deploy"><span>Last production deploy</span><b>${esc(r.deployment.timestamp?date(r.deployment.timestamp):r.deployment.state)}</b></div><div class="actions"><button class="action ai-action">Analyze with AI</button><button class="action" ${r.status==='synced'?'disabled':''}>Create Back-Merge PR</button><a class="meta compare" href="${comparisonUrl(r)}" target="_blank" rel="noopener noreferrer">View comparison ↗</a></div><div class="ai-result"></div></article>`).join(''):'<div class="empty">No repository data returned.</div>';if(data.errors?.length)$('repos').insertAdjacentHTML('beforeend',`<div class="error">${data.errors.map(esc).join('<br>')}</div>`)}
async function backMerge(button){button.disabled=true;button.textContent='Creating...';try{const response=await fetch('/api/back-merge',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({repo:button.dataset.repo,production:button.dataset.production,release:button.dataset.release})});const result=await response.json();if(!response.ok)throw new Error(result.error||'Could not create PR');button.textContent='PR created';button.title=result.url;window.open(result.url,'_blank')}catch(error){button.disabled=false;button.textContent='Create Back-Merge PR';alert(error.message)}}
function wireButtons(){document.querySelectorAll('.repo').forEach(card=>{const button=card.querySelector('.action');if(!button||button.disabled)return;const branches=card.querySelectorAll('.branch');button.dataset.repo=card.querySelector('.repo-name').textContent.trim();button.dataset.production=branches[0].textContent.trim();button.dataset.release=branches[1].textContent.trim();button.onclick=()=>backMerge(button)})}
async function analyze(button){const card=button.closest('.repo'), result=card.querySelector('.ai-result');button.disabled=true;button.textContent='Analyzing...';try{const response=await fetch('/api/ai/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({repo:card.querySelector('.repo-name').textContent.trim(),production:card.querySelectorAll('.branch')[0].textContent.trim(),release:card.querySelectorAll('.branch')[1].textContent.trim()})});const data=await response.json();if(!response.ok)throw new Error(data.error||'AI analysis failed');result.innerHTML=`<strong>AI risk: ${esc(data.risk.toUpperCase())}</strong><p>${esc(data.summary)}</p><p><b>Impact:</b> ${esc(data.impact)}</p><p><b>Recommendation:</b> ${esc(data.recommendation)}</p><p><b>Suggested tests:</b> ${data.tests.map(esc).join(' · ')}</p>`;button.textContent='AI analysis ready'}catch(error){result.textContent=error.message;button.textContent='Analyze with AI';button.disabled=false}}
function wireAiButtons(){document.querySelectorAll('.ai-action').forEach(button=>button.onclick=()=>analyze(button))}
async function load(){$('refresh').disabled=true;try{render(await fetch('/api/overview').then(r=>r.json()));wireButtons();wireAiButtons()}catch(e){$('repos').innerHTML='<div class="error">Could not load dashboard data.</div>'}finally{$('refresh').disabled=false}}$('refresh').onclick=load;load();
</script></body></html>"""


def _commit(value: Dict[str, Any]) -> Dict[str, str]:
    commit = value.get("commit", {})
    author = value.get("author") or {}
    commit_author = commit.get("author") or {}
    sha = value.get("sha", "unknown")
    return {
        "sha": sha[:9],
        "message": (commit.get("message") or "No commit message").splitlines()[0],
        "author": author.get("login") or commit_author.get("name") or "Unknown",
        "timestamp": commit_author.get("date", ""),
    }


def inspect(client: GitHubClient, repo: str, release_branch: Optional[str] = None) -> Dict[str, Any]:
    parse_repo(repo)
    production = client.repository(repo).get("default_branch", "main")
    branches = client.branches(repo)
    names = [branch.get("name", "") for branch in branches]
    release = release_branch or ("release" if "release" in names else next((name for name in names if name.startswith("release/")), None))
    if release is None:
        raise ValueError(
            "no release branch found; create a `release` or `release/*` branch "
            "before adding this repository to the dashboard"
        )
    comparison = client.compare(repo, production, release)
    production_commit = comparison.get("base_commit", {})
    release_commit = client.branch_commit(repo, release)
    deployments = client.deployments(repo)
    deployment = deployments[0] if deployments else {}
    behind = comparison.get("behind_by", 0)
    ahead = comparison.get("ahead_by", 0)
    status = "synced" if not behind else "hotfix-missing" if ahead else "behind"
    commits = [
        {
            "sha": item.get("sha", "")[:9],
            "message": (item.get("commit", {}).get("message") or "").splitlines()[0],
        }
        for item in comparison.get("commits", [])
    ]
    return {
        "repo": repo, "production": production, "release": release, "status": status,
        "behind": behind, "ahead": ahead,
        "production_commit": _commit(production_commit),
        "release_commit": _commit(release_commit),
        "commits": commits,
        "changed_files": [item.get("filename", "") for item in comparison.get("files", [])],
        "deployment": {"environment": "production", "state": "deployed" if deployment else "not recorded", "timestamp": deployment.get("created_at", "")},
    }


def overview(client: GitHubClient, repos: List[str], release_branch: Optional[str] = None) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    errors: List[str] = []
    for repo in repos:
        try:
            results.append(inspect(client, repo, release_branch))
        except (GitHubError, ValueError) as error:
            errors.append("{}: {}".format(repo, error))
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "repositories": results, "errors": errors}


def serve(client: GitHubClient, repos: List[str], host: str, port: int, release_branch: Optional[str] = None, open_browser: bool = True) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                body = HTML.encode("utf-8")
                content_type = "text/html; charset=utf-8"
            elif parsed.path == "/api/overview":
                requested = parse_qs(parsed.query).get("repos", [None])[0]
                selected = [item.strip() for item in requested.split(",") if item.strip()] if requested else repos
                body = json.dumps(overview(client, selected, release_branch)).encode("utf-8")
                content_type = "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path not in {"/api/back-merge", "/api/ai/analyze"}:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                repo = payload["repo"]
                production = payload["production"]
                release = payload["release"]
                if path == "/api/ai/analyze":
                    analysis = analyze_release_risk(inspect(client, repo, release))
                    body = json.dumps(analysis).encode("utf-8")
                    status = 200
                else:
                    result = client.create_pull(
                        repo,
                        "Back-merge {} into {}".format(production, release),
                        production,
                        release,
                        "Back-merge production hotfixes into the release branch.\n\nCreated by branch-watch.",
                    )
                    body = json.dumps({"url": result.get("html_url", ""), "number": result.get("number")}).encode("utf-8")
                    status = 201
            except (AIError, KeyError, json.JSONDecodeError, GitHubError, ValueError) as error:
                body = json.dumps({"error": str(error)}).encode("utf-8")
                status = 400 if isinstance(error, (KeyError, json.JSONDecodeError, ValueError)) else 502
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format_string: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    address = "http://{}:{}".format(host, port)
    print("Branch Watch dashboard: " + address)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(address)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
