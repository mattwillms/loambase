import json
import logging
from typing import Optional

import httpx
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

SSURGO_URL = "https://SDMDataAccess.sc.egov.usda.gov/Tabular/post.rest"
CACHE_TTL = 604800  # 7 days
_NONE_SENTINEL = "none"

_QUERY = """
SELECT
    co.compname AS soil_series_name,
    ctg.texdesc AS texture_class,
    co.drainagecl AS drainage_class,
    ch.ph1to1h2o_r AS ph_water,
    ch.om_r AS organic_matter_pct
FROM component co
LEFT JOIN chorizon ch ON ch.cokey = co.cokey AND ch.hzdept_r = 0
LEFT JOIN chtexturegrp ctg ON ctg.chkey = ch.chkey AND ctg.rvindicator = 'Yes'
WHERE co.mukey IN (
    SELECT DISTINCT mukey
    FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('POINT({lon} {lat})')
)
AND co.majcompflag = 'Yes'
ORDER BY co.comppct_r DESC
"""


async def get_soil_data(lat: float, lon: float, redis: aioredis.Redis) -> Optional[dict]:
    cache_key = f"soil:{lat:.4f}:{lon:.4f}"

    cached = await redis.get(cache_key)
    if cached is not None:
        if cached == _NONE_SENTINEL:
            return None
        return json.loads(cached)

    try:
        query = _QUERY.format(lat=lat, lon=lon)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                SSURGO_URL,
                data={"query": query, "format": "JSON"},
            )
            response.raise_for_status()
            payload = response.json()

        rows = payload.get("Table", [])
        if not rows:
            await redis.set(cache_key, _NONE_SENTINEL, ex=CACHE_TTL)
            return None

        row = rows[0]
        data = {
            "soil_series_name": row[0] if row[0] else None,
            "texture_class": row[1] if row[1] else None,
            "drainage_class": row[2] if row[2] else None,
            "ph_water": float(row[3]) if row[3] is not None else None,
            "organic_matter_pct": float(row[4]) if row[4] is not None else None,
        }
        await redis.set(cache_key, json.dumps(data), ex=CACHE_TTL)
        return data

    except Exception as exc:
        logger.warning("SSURGO soil data fetch failed for (%s, %s): %s", lat, lon, exc)
        return None
