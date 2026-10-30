import requests, time, re
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
def t(name,fn):
    t0=time.time()
    try: out=fn()
    except Exception as e: out=f"ERR {type(e).__name__} {e}"[:300]
    print(f"== {name} ({time.time()-t0:.1f}s)\n{out}\n",flush=True)
def get(u,**k):
    r=requests.get(u,headers={"User-Agent":UA},timeout=(15,120),**k); return f"{r.status_code} len={len(r.text)}\n"+"\n".join(r.text.strip().splitlines()[-6:])
t("fredgraph oas", lambda: get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2,BAMLC0A0CM&cosd=2026-10-01"))
t("fredgraph oas noUA", lambda: (lambda r: f"{r.status_code}\n{r.text[-300:]}")(requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2&cosd=2026-10-01",timeout=(15,120))))
t("fred data txt", lambda: get("https://fred.stlouisfed.org/data/BAMLH0A0HYM2.txt"))
t("fredgraph icsa", lambda: get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=ICSA,CCSA&cosd=2026-09-01"))
t("fred api nokey", lambda: get("https://api.stlouisfed.org/fred/series/observations?series_id=BAMLH0A0HYM2&file_type=json"))
t("fred series page", lambda: (lambda r: f"{r.status_code} "+str(re.findall(r'series-meta-observation-value[^>]*>([^<]+)',r.text)[:3])+str(re.findall(r'(\d{4}-\d\d-\d\d):',r.text)[:3]))(requests.get("https://fred.stlouisfed.org/series/BAMLH0A0HYM2",headers={"User-Agent":UA},timeout=(15,120))))
def dol():
    y=2026; form={"level":"nation","strtdate":str(y-1),"enddate":str(y),"filetype":"html","final":"Submit"}
    r=requests.post("https://oui.doleta.gov/unemploy/wkclaims/report.asp",data=form,headers={"User-Agent":UA,"Referer":"https://oui.doleta.gov/unemploy/claims.asp"},timeout=60)
    ds=sorted(set(re.findall(r'<td headers="(\d\d/\d\d/\d{4}) ',r.text)),key=lambda d:d[6:]+d[:2]+d[3:5])
    return f"{r.status_code} len={len(r.text)} last={ds[-4:]}"
t("dol claims", dol)
t("dol weekly pdf", lambda: get("https://www.dol.gov/ui/data.pdf").split("\n")[0])
t("dol csv", lambda: get("https://oui.doleta.gov/unemploy/csv/ar539.csv"))
