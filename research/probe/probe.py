import requests, json
B="https://data.financialresearch.gov/v1"
def get(u,**p):
    try:
        r=requests.get(B+u,params=p,timeout=60);print("==",u,p,r.status_code,len(r.content),flush=True);return r
    except Exception as e:print("ERR",u,e)
r=get("/metadata/mnemonics",dataset="mmf")
if r is not None and r.ok:
    j=r.json();print(type(j),len(j))
    items=j if isinstance(j,list) else j.get("mnemonics",j)
    for x in (items if isinstance(items,list) else list(items.items()))[:400]:
        s=json.dumps(x,ensure_ascii=False)
        if any(k in s.lower() for k in ["tot","asset","all"]): print(s[:200])
r=get("/metadata/search",query="money market fund total assets")
if r is not None and r.ok: print(r.text[:3000])
