import requests,json
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
URL="https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols={}"       "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
r=requests.get(URL.format("@VX.1|@SP.1|@ND.1|.VIX|@VX.2"),headers={"User-Agent":UA},timeout=30)
d=r.json()
for q in d["FormattedQuoteResult"]["FormattedQuote"]:
    print({k:q.get(k) for k in ["symbol","name","last","change","change_pct","previous_day_closing","last_time","ExtendedMktQuote"]})
