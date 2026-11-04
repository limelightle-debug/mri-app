import requests,io,csv
for s in ["A191RL1Q225SBEA","PCEPILFE"]:
    r=requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={s}",timeout=60)
    print("##",s,r.status_code)
    print(r.text.strip())
