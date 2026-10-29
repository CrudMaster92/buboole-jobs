import json,time,traceback,httpx
from pathlib import Path
from bs4 import BeautifulSoup
import bs4,soupsieve
from server.public_jobs.catalog import load_monitors
from server.public_jobs.collector import PublicClient,HostLimiter
from server.scrapers import run_scraper
from server.scrapers.http import bounded_request
print('VERSIONS',bs4.__version__,soupsieve.__version__,flush=True)
ids={'armatures-bois-francs','groupe-morin','laser-amp','laser-amp-en','laserax','laserax-en','laserax-de'}
lock=json.loads(Path('catalog-lock.json').read_text());lock['monitors']=[s for s in lock['monitors'] if s['id'] in ids]
monitors=load_monitors(Path('.catalog'),lock)
print('SPEC TYPE',type(monitors),flush=True)
for m,r in monitors:
 print('MONITOR',m['id'],flush=True)
 for sel in r.selectors.values():
  try:soupsieve.compile(sel)
  except Exception:traceback.print_exc()
 try:
  resp=httpx.get(r.request.url,params=r.request.params,timeout=35,follow_redirects=True);print('RAW',resp.status_code,resp.url,'redirects',[(h.status_code,h.url,h.headers.get('Location')) for h in resp.history], 'title',str(BeautifulSoup(resp.content,'html.parser').title),flush=True)
 except Exception:traceback.print_exc()
 try:
  with PublicClient(HostLimiter(),time.monotonic()+120) as client:
   raw=bounded_request(r.request,r.allowed_hosts,client=client);print('BOUNDED',raw.status_code,raw.url,flush=True)
 except Exception:traceback.print_exc()
 try:
  with PublicClient(HostLimiter(),time.monotonic()+150) as client:out=run_scraper(r,client=client,detail_cache={})
  print('RESULT',len(out.jobs),out.complete,out.warnings,flush=True)
 except Exception:traceback.print_exc()
