import requests,re
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
U=["https://www.nbcnews.com/politics/2026-elections/house-results",
"https://www.nbcnews.com/politics/2026-elections/senate-results",
"https://www.politico.com/2026-election/results/house/",
"https://www.cnn.com/election/2026/results/house",
"https://www.foxnews.com/elections/2026/midterm-results/house",
"https://www.nytimes.com/interactive/2026/11/03/us/elections/results-house.html",
"https://www.cbsnews.com/elections/2026/house/",
"https://abcnews.go.com/Elections/2026-us-house-election-results",
"https://www.reuters.com/graphics/USA-ELECTION/RESULTS/2026/",
"https://www.bloomberg.com/graphics/2026-us-election-results/house/",
"https://www.npr.org/2026/11/03/g-s1-election-results-house"]
pat=re.compile(r'.{0,120}(?:Republicans?|GOP|"rep[a-zA-Z_]*"|"R")\W{0,20}\d{1,3}.{0,120}',re.I)
for u in U:
    try:
        r=requests.get(u,headers={"User-Agent":UA,"Accept-Language":"en-US"},timeout=25)
        t=r.text;print("==",u,r.status_code,len(t))
        hits=[m.group(0) for m in pat.finditer(t)]
        hits=[h for h in hits if re.search(r'won|seats|called|total|count|majority|balance|win',h,re.I)]
        for h in hits[:12]:print("  ",re.sub(r'\s+',' ',h)[:260])
    except Exception as e:print("==",u,"ERR",e)
