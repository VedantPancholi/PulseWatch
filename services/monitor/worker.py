import os, time, asyncio
from typing import Dict, Any, List, Tuple
import httpx

API_URL = os.getenv("API_URL", "http://api:8000")

def in_expected(status: int, spec: str) -> bool:
    """
    spec like '200-399' or '200,201,204' (you can extend later)
    """
    parts = [p.strip() for p in spec.split(",")]
    for p in parts:
        if "-" in p:
            a, b = p.split("-", 1)
            if a.isdigit() and b.isdigit() and int(a) <= status <= int(b):
                return True
        elif p.isdigit() and int(p) == status:
            return True
    return False

async def check_once(client: httpx.AsyncClient, mon: Dict[str, Any]) -> None:
    url = mon["url"]
    timeout = mon.get("timeout_ms", 5000) / 1000.0
    method = mon.get("method", "GET").upper()
    ok = False
    status_code = None
    err = None
    start = time.perf_counter()
    try:
        resp = await client.request(method, url, timeout=timeout)
        status_code = resp.status_code
        ok = in_expected(status_code, mon.get("expected_statuses", "200-399"))
    except Exception as e:
        err = str(e)[:300]
    latency_ms = (time.perf_counter() - start) * 1000.0
    await client.post(f"{API_URL}/checks", json={
        "monitor_id": mon["id"],
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
        "ok": bool(ok),
        "error_reason": err,
    })

async def runner():
    async with httpx.AsyncClient() as client:
        while True:
            try:
                r = await client.get(f"{API_URL}/public/monitors")
                r.raise_for_status()
                monitors: List[Dict[str, Any]] = r.json()
                tasks = [check_once(client, m) for m in monitors if m.get("is_enabled", True)]
                if tasks:
                    await asyncio.gather(*tasks)
            except Exception as e:
                print("worker loop error:", e)
            # simple global interval; later: schedule per monitor.interval_sec
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(runner())
