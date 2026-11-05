import requests
for s in ["THREEFYTP10","THREEFYTP5"]:
    r=requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={s}&cosd=2003-01-01",timeout=60)
    print("##",s,r.status_code);print(r.text.strip())
