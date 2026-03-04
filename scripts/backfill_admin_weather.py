"""
One-time backfill: fetch 365 days of historical weather from Open-Meteo Archive API
for the admin user's coordinates and upsert into WeatherCache.
"""
import asyncio
import sys
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.logs import WeatherCache
from app.models.user import User

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DAYS = 365


async def fetch_historical(lat: float, lon: float, start: date, end: date) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": ",".join([
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "relative_humidity_2m_max",
            "windspeed_10m_max",
            "et0_fao_evapotranspiration",
        ]),
        "timezone": "America/Chicago",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(ARCHIVE_URL, params=params)
        resp.raise_for_status()
        return resp.json()


async def main():
    async with AsyncSessionLocal() as db:
        # Find admin user with coordinates
        result = await db.execute(
            select(User).where(
                User.role == "admin",
                User.latitude.isnot(None),
                User.longitude.isnot(None),
            )
        )
        admin = result.scalars().first()

        if admin is None:
            print("ERROR: No admin user with latitude/longitude set. Set coordinates on the admin profile first.")
            sys.exit(1)

        lat = admin.latitude
        lon = admin.longitude
        print(f"Admin user: {admin.email} (id={admin.id})")
        print(f"Coordinates: lat={lat}, lon={lon}")

        # Fetch historical data — from Jan 1 2025 through yesterday
        start_date = date(2025, 1, 1)
        end_date = date.today() - timedelta(days=1)
        print(f"Fetching {(end_date - start_date).days + 1} days: {start_date} to {end_date}")

        raw = await fetch_historical(lat, lon, start_date, end_date)
        daily = raw.get("daily", {})
        api_lat = raw.get("latitude", lat)
        api_lon = raw.get("longitude", lon)

        dates = daily.get("time", [])
        highs = daily.get("temperature_2m_max", [])
        lows = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_sum", [])
        humidity = daily.get("relative_humidity_2m_max", [])
        wind = daily.get("windspeed_10m_max", [])

        upserted = 0
        now = datetime.now(timezone.utc)

        for i, d_str in enumerate(dates):
            d = date.fromisoformat(d_str)
            high = highs[i] if i < len(highs) else None
            low = lows[i] if i < len(lows) else None
            prec = precip[i] if i < len(precip) else None
            hum = humidity[i] if i < len(humidity) else None
            wnd = wind[i] if i < len(wind) else None

            # Upsert: match on (latitude, longitude, date)
            record = await db.scalar(
                select(WeatherCache).where(
                    WeatherCache.latitude == api_lat,
                    WeatherCache.longitude == api_lon,
                    WeatherCache.date == d,
                )
            )
            if record is None:
                record = WeatherCache(latitude=api_lat, longitude=api_lon, date=d)
                db.add(record)

            record.high_temp_f = high
            record.low_temp_f = low
            record.precip_inches = prec
            record.humidity_pct = hum
            record.wind_mph = wnd
            record.conditions = None
            record.uv_index = None
            record.soil_temp_f = None
            record.frost_warning = bool(low is not None and low < 32.0)
            record.heat_warning = bool(high is not None and high >= 90.0)
            record.fetched_at = now
            upserted += 1

        await db.commit()

        print(f"\nDone: {upserted} rows upserted")
        print(f"Date range: {start_date} to {end_date}")
        print(f"API coordinates (grid-snapped): lat={api_lat}, lon={api_lon}")


if __name__ == "__main__":
    asyncio.run(main())
