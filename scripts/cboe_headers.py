"""Cboe's API (cdn.cboe.com redirects to cdn-api.cboe.com since 2026-11-20) answers 403 unless the request
looks like it comes from cboe.com's own pages. Importing this module adds those headers to every requests
call to a cboe.com URL, in whichever script imports it."""
import requests

CBOE = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.cboe.com",
    "Referer": "https://www.cboe.com/",
}
_request = requests.Session.request


def _with_cboe_headers(self, method, url, *args, **kw):
    if "cboe.com" in str(url):
        kw["headers"] = {**CBOE, **(kw.get("headers") or {})}
        kw["headers"]["User-Agent"] = CBOE["User-Agent"]
    return _request(self, method, url, *args, **kw)


requests.Session.request = _with_cboe_headers
