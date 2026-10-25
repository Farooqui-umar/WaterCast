from __future__ import annotations

from datetime import datetime

from flask import current_app

from ..extensions import cache, db
from ..models import Vote
from ..timeutil import iso, utcnow
from . import http

RAIN_DAY_MM = 1.0

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Violent showers", 85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail",
}


def fetch_forecast(lat: float, lon: float) -> dict:
    cfg = current_app.config
    key = f"wx:{round(lat, 2)}:{round(lon, 2)}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    params = {
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max",
        "past_days": 30, "forecast_days": 7, "timezone": "auto",
    }
    if cfg["OPEN_METEO_API_KEY"]:
        params["apikey"] = cfg["OPEN_METEO_API_KEY"]
    data = http.fetch_json(cfg["OPEN_METEO_FORECAST_URL"], params=params)
    cache.set(key, data, timeout=600)
    return data


def _num(v, default=0.0):
    return default if v is None else v


def summarise(data: dict) -> dict:
    d = data.get("daily") or {}
    times = d.get("time") or []
    n = len(times)
    if not n:
        raise ValueError("no daily data")

    def col(name):
        arr = d.get(name) or []
        return arr + [None] * (n - len(arr))

    psum = [_num(x) for x in col("precipitation_sum")]
    pprob, tmax, tmin, wcode = (col("precipitation_probability_max"), col("temperature_2m_max"),
                                col("temperature_2m_min"), col("weather_code"))
    cur = data.get("current") or {}
    today = (cur.get("time") or "")[:10]
    ti = times.index(today) if today in times else max(0, n - 7)

    if _num(cur.get("precipitation")) >= 0.1:
        dsr, capped = 0, False
    else:
        dsr, capped = ti, True
        for k, i in enumerate(range(ti - 1, -1, -1), start=1):
            if psum[i] >= RAIN_DAY_MM:
                dsr, capped = k, False
                break
    rain_7d = sum(psum[max(0, ti - 7):ti])
    rain_30d = sum(psum[max(0, ti - 30):ti])
    next7 = sum(psum[ti:ti + 7])
    next3 = sum(psum[ti:ti + 3])

    status = "Recently Wet" if dsr <= 5 else "Drying Out" if dsr <= 15 else "Confirmed Dry"
    if dsr >= 16 and next7 < 10:
        tier = "critical"
    elif dsr >= 10 or (dsr >= 6 and next7 < 5):
        tier = "warning"
    else:
        tier = "watch"
    if next3 >= 200:
        tier = "critical"
    elif next3 >= 100 and tier == "watch":
        tier = "warning"
    score = round(min(10.0, min(dsr, 30) / 30 * 5 + (1 - min(rain_30d, 150) / 150) * 5), 1)

    daily = []
    for i in range(ti, min(ti + 7, n)):
        daily.append({"date": times[i], "weekday": datetime.strptime(times[i], "%Y-%m-%d").strftime("%a").upper(),
                      "precip_prob": pprob[i], "precip_mm": round(psum[i], 1), "tmax": tmax[i], "tmin": tmin[i],
                      "condition": WMO_CODES.get(wcode[i], "")})
    return {
        "current": {"temp_c": cur.get("temperature_2m"), "feels_like_c": cur.get("apparent_temperature"),
                    "humidity": cur.get("relative_humidity_2m"), "wind_kmh": cur.get("wind_speed_10m"),
                    "precip_mm": cur.get("precipitation"), "is_day": cur.get("is_day"),
                    "condition": WMO_CODES.get(cur.get("weather_code"), ""), "time": cur.get("time")},
        "daily": daily,
        "past": {"rain_7d_mm": round(rain_7d, 1), "rain_30d_mm": round(rain_30d, 1), "days_since_rain": dsr,
                 "capped": capped, "window_days": ti + 1},
        "next7_mm": round(next7, 1), "next3_mm": round(next3, 1),
        "derived": {"status_label": status, "risk_tier": tier, "scarcity_score": score},
        "elevation_m": data.get("elevation"),
    }


def place_summary(lat: float, lon: float, name: str, state: str = "", country: str = "") -> dict:
    summary = summarise(fetch_forecast(lat, lon))
    reports = 0
    if name:
        reports = Vote.query.filter(db.func.lower(Vote.locality_name) == name.lower()).count()
    summary.update({"name": name, "state": state, "country": country, "lat": lat, "lon": lon,
                    "citizen_reports": reports, "updated_at": iso(utcnow()),
                    "sources": {"weather": "Open-Meteo", "places": "OpenStreetMap contributors"}})
    return summary
