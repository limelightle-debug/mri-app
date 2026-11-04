import requests
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
URL="https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols={}&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
d=requests.get(URL.format("@SP.1|@ND.1|@DJ.1|.N225|.DXY|JPY=|US10Y|US2Y|@GC.1|@CL.1|.VIX|@VX.1"),headers={"User-Agent":UA},timeout=30).json()
for q in d["FormattedQuoteResult"]["FormattedQuote"]:
    print({k:q.get(k) for k in ["symbol","last","change","change_pct","previous_day_closing","high","low","open","last_time"]})
