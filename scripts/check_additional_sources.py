import json,time,concurrent.futures as cf
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlsplit
from server.scrapers import ScraperRecipe,run_scraper
from server.public_jobs.collector import PublicClient,HostLimiter
specs=json.loads(Path('scripts/additional-source-candidates.json').read_text());limiter=HostLimiter()
def one(s):
 r=ScraperRecipe.model_validate(s['recipe']);cache={}
 for attempt in range(10):
  with PublicClient(limiter,time.monotonic()+180) as client:out=run_scraper(r,client=client,detail_cache=cache)
  if not out.continuation_ready:break
 assert out.complete and out.jobs and not out.continuation_ready,(s['id'],out.complete,out.warnings)
 assert all(urlsplit(j.source_url).hostname in r.allowed_hosts for j in out.jobs)
 row={'id':s['id'],'checked_at':datetime.now(timezone.utc).isoformat(),'complete':out.complete,'job_count':len(out.jobs),'pages':out.pages_fetched,'warnings':out.warnings,'titles':[j.title for j in out.jobs],'source_urls':[j.source_url for j in out.jobs]}
 print('VERIFIED_SOURCE '+json.dumps(row,ensure_ascii=False),flush=True);return row
with cf.ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(one,specs))
Path('additional-source-results.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False)+'\n')
print('ALL_CANDIDATES_COMPLETE',len(rows),sum(r['job_count'] for r in rows))
