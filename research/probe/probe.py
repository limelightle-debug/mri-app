import requests,re
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
t=requests.get("https://www.nbcnews.com/politics/2026-elections/house-results",headers={"User-Agent":UA},timeout=30).text
print(re.search(r'"seatsByParty":\{[^}]*\}',t).group(0) if re.search(r'"seatsByParty":\{[^}]*\}',t) else "no seatsByParty", len(t))
m=re.search(r'"S":\{"officeCode":"S".{0,400}',t);print(m.group(0)[:400] if m else "no S")
m=re.search(r'"lastModified":"[^"]*"',t);print(m.group(0) if m else "")
