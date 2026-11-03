import requests, json, time
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
def t(name, url, ua=True, n=300):
    try:
        r=requests.get(url, headers={"User-Agent":UA} if ua else {}, timeout=(10,40))
        txt=r.text
        print(f"## {name} {r.status_code} len={len(txt)}\n{txt[:n]}\n...{txt[-n:]}\n")
    except Exception as e: print(f"## {name} ERR {e}\n")
t("treas real 2003","https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2003/all?type=daily_treasury_real_yield_curve&field_tdr_date_value=2003&page&_format=csv")
t("fred multi","https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDTARMDLR,GDP,A091RC1Q027SBEA,IRLTLT01JPM156N&cosd=2000-01-01",ua=False)
t("fred dxy cpi","https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS,CPIAUCSL,DFII5,DFII10,T5YIFR&cosd=2024-01-01",ua=False)
t("fred jp policy","https://fred.stlouisfed.org/graph/fredgraph.csv?id=IRSTCI01JPM156N,INTDSRJPM193N&cosd=2020-01-01",ua=False)
for s in ["GC%3DF","DX-Y.NYB","BTC-USD","%5ETNX"]:
    t("yahoo "+s,f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=max&interval=1mo",n=200)
t("yahoo2 GC","https://query2.finance.yahoo.com/v8/finance/chart/GC%3DF?range=max&interval=1mo",n=200)
t("stooq xau","https://stooq.com/q/d/l/?s=xauusd&i=m",n=200)
t("cnbc all gold","https://ts-api.cnbc.com/harmony/app/charts/ALL.json?symbol=@GC.1",n=200)
t("cnbc 10y dxy",".".join([""]) or "https://ts-api.cnbc.com/harmony/app/charts/10Y.json?symbol=.DXY",n=200)
t("cnbc 10y dxy2","https://ts-api.cnbc.com/harmony/app/charts/10Y.json?symbol=.DXY",n=200)
t("cnbc 10y btc","https://ts-api.cnbc.com/harmony/app/charts/10Y.json?symbol=BTC.CM%3D",n=200)
t("boj","https://www.stat-search.boj.or.jp/ssi/mtshtml/fm02_m_1.html",n=200)
t("mof jgb","https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv",n=200)
t("mof jgb cur","https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv",n=200)
t("nyfed acm","https://www.newyorkfed.org/medialibrary/media/research/data_indicators/ACMTermPremium.xls",n=100)
t("fred tga walcl","https://fred.stlouisfed.org/graph/fredgraph.csv?id=WTREGEN,WALCL,WRESBAL,RRPONTSYD&cosd=2025-06-01",ua=False)
