import requests,re
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
for u in ["https://www.nbcnews.com/politics/2026-elections/senate-results","https://www.nbcnews.com/politics/2026-elections/house-results"]:
    t=requests.get(u,headers={"User-Agent":UA},timeout=30).text
    print("==",u)
    for m in list(re.finditer(r'"S":\{"officeCode":"S"',t))[:2]:
        print(t[m.start():m.start()+700]);print()
    for m in list(re.finditer(r'"seatsByParty"',t))[:2]:
        print(t[m.start():m.start()+120]);print()
    for k in ['"lastUpdated"','"updatedAt"','"timestamp"','"lastModified"','dateModified']:
        m=re.search(k+r'.{0,60}',t)
        if m:print(m.group(0))
