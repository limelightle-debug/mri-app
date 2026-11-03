import requests, json, sys, subprocess
r=requests.get("https://data.financialresearch.gov/v1/series/timeseries",params={"mnemonic":"MMF-MMF_TOT-M"},timeout=60)
print(r.status_code,r.text[:600])
