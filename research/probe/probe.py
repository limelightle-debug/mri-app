import requests, io, openpyxl
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
B="https://www.newyorkfed.org/medialibrary/media/research/economists/williams/data/"
for f in ["Holston_Laubach_Williams_current_estimates.xlsx","Laubach_Williams_current_estimates.xlsx"]:
    for ua in (UA,None):
        try:
            r=requests.get(B+f,headers={"User-Agent":ua} if ua else {},timeout=60)
            print("==",f,"ua" if ua else "noua",r.status_code,len(r.content),flush=True)
            if r.ok and r.content[:2]==b"PK":
                wb=openpyxl.load_workbook(io.BytesIO(r.content),data_only=True)
                for ws in wb.worksheets:
                    rows=list(ws.iter_rows(values_only=True))
                    print("  sheet",ws.title,len(rows))
                    for row in rows[:8]: print("   ",row[:12])
                    for row in rows[-4:]: print("   ",row[:12])
                break
        except Exception as e: print("ERR",f,e)
