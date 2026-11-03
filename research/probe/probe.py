import requests, time, json
for s in ["_VIX","_SKEW","_SPX"]:
    r=requests.get(f"https://cdn.cboe.com/api/global/delayed_quotes/quotes/{s}.json?_={int(time.time())}",headers={"Cache-Control":"no-cache"},timeout=30)
    j=r.json();d=j.get("data",{});print(s,j.get("timestamp"),{k:d.get(k) for k in ["current_price","close","last_trade_time","prev_day_close","price_change"]})
r=requests.get(f"https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json?_={int(time.time())}",headers={"Cache-Control":"no-cache"},timeout=60)
j=r.json();print("chain",j.get("timestamp"),len(j.get("data",{}).get("options",[])))
o=j["data"]["options"][:3];print([ (x.get("option"),x.get("bid"),x.get("ask"),x.get("last_trade_time")) for x in o])
r=requests.get(f"https://cdn.cboe.com/api/global/delayed_quotes/options/_VIX.json?_={int(time.time())}",headers={"Cache-Control":"no-cache"},timeout=60)
print("vixchain",r.json().get("timestamp"))
