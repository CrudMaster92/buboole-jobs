"""Anonymous, bounded diagnostics for one reviewed browser source; never production state."""
import json,os,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from server.public_jobs.catalog import load_monitors
from server.public_jobs.browser import BrowserBudget,eligible
from server.scrapers import runtime
lock=json.loads((root/'catalog-lock.json').read_text());selected=[p for p in lock['monitors'] if p['id']=='super-c-lachute'];assert len(selected)==1
monitor,recipe=load_monitors(root/'.catalog',{**lock,'monitors':selected})[0];assert eligible(recipe)
keys={'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','HOME','USERPROFILE','LOCALAPPDATA','PLAYWRIGHT_BROWSERS_PATH'}
clean={k:v for k,v in os.environ.items() if k.upper() in keys};os.environ.clear();os.environ.update(clean)
original=runtime._read_browser_json
def diagnostic(response,selected):
 payload=json.loads(response.body());collections=runtime._browser_json_path_values(payload,selected.mapping['items']);rows=collections[0] if len(collections)==1 and isinstance(collections[0],list) else []
 body=response.request.post_data_json or {}
 allowed={'must','should','must_not','match','term','terms','bool','filter','brandname','city','province','region','jobtype','jobcategories','department'}
 def filters(value):
  if isinstance(value,dict):return {k:filters(v) if k in allowed else '[omitted]' for k,v in value.items()}
  if isinstance(value,list):return [filters(v) for v in value[:20]]
  return value if isinstance(value,(str,int,float,bool,type(None))) else '[omitted]'
 print(json.dumps({'diagnostic':'public_request_scope','index':body.get('index_name'),'offset':body.get('offset'),'limit':body.get('limit'),'search':body.get('search'),'filters':filters((body.get('query') or {}).get('filter_query'))},ensure_ascii=True)[:3000],flush=True)
 summary={'diagnostic':'public_listing_shape','keys':list(payload)[:30] if isinstance(payload,dict) else [],'raw_count':len(rows),'samples':[{k:r[k] for k in ('title','city','brandname','locations') if k in r} for r in rows[:2] if isinstance(r,dict)]}
 print(json.dumps(summary,ensure_ascii=True)[:5000],flush=True)
 return original(response,selected)
runtime._read_browser_json=diagnostic
result=runtime.run_scraper(recipe,browser_policy=BrowserBudget(90));print(json.dumps({'diagnostic':'normalized_public_rows','jobs':len(result.jobs),'pages':result.pages_fetched}),flush=True)
