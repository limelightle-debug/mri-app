import requests,re
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
for u in ["https://www.nbcnews.com/politics/2026-elections/house-results","https://www.nbcnews.com/politics/2026-elections/senate-results"]:
    t=requests.get(u,headers={"User-Agent":UA},timeout=30).text
    print("==",u,len(t))
    for k in ["seatsByParty","bopData","notUpForElection","leading","Leading","lastUpdated","updatedAt","asOf"]:
        for m in list(re.finditer(re.escape(k),t))[:3]:
            print(k,"::",re.sub(r'\s+',' ',t[max(0,m.start()-150):m.start()+450]).replace("\\u002F","/"));print()
