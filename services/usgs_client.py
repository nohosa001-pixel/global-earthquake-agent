"""
USGS Real-time & Historical Earthquake Catalog Collector
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional
import time
from concurrent.futures import ThreadPoolExecutor


class USGSEarthquakeCollector:
    """USGS FDSN/GeoJSON & EMSC SeismicPortal 다중 소스 지진 데이터 수집 및 교차 검증기"""
    
    BASE_QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    FEED_SUMMARY_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary"
    EMSC_QUERY_URL = "https://www.seismicportal.eu/fdsnws/event/1/query"

    _cache: Dict[str, Tuple[float, pd.DataFrame]] = {}
    CACHE_TTL_SECONDS = 120  # 2분 캐싱

    @classmethod
    def fetch_feed(cls, feed_type: str = "4.5_month") -> pd.DataFrame:
        """
        USGS 사전 생성 실시간 GeoJSON 피드 수집:
        - 1.0_hour, all_hour
        - 2.5_day, all_day
        - 4.5_week, all_week
        - 4.5_month, 2.5_month, all_month
        """
        cache_key = f"feed_{feed_type}"
        now = time.time()
        if cache_key in cls._cache:
            ts, cached_df = cls._cache[cache_key]
            if now - ts < cls.CACHE_TTL_SECONDS:
                return cached_df.copy()

        url = f"{cls.FEED_SUMMARY_URL}/{feed_type}.geojson"
        try:
            resp = requests.get(url, timeout=12)
            resp.raise_for_status()
            data = resp.json()
            df = cls._parse_geojson(data)
            cls._cache[cache_key] = (now, df)
            return df
        except Exception as e:
            print(f"[USGS Collector] Feed fetch error ({url}): {e}")
            return pd.DataFrame()

    @classmethod
    def fetch_recent_earthquakes(
        cls, 
        min_magnitude: float = 2.5, 
        days_back: int = 60,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        limit: int = 20000,
        timeout: float = 10.0,
    ) -> pd.DataFrame:
        """
        USGS FDSN 쿼리 API를 통해 지정 기간/영역/규모별 지진 수집
        bbox: (min_lat, min_lon, max_lat, max_lon)
        """
        cache_key = f"query_{min_magnitude}_{days_back}_{bbox}_{limit}"
        now = time.time()
        if cache_key in cls._cache:
            ts, cached_df = cls._cache[cache_key]
            if now - ts < cls.CACHE_TTL_SECONDS:
                return cached_df.copy()

        start_time = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        
        params = {
            "format": "geojson",
            "starttime": start_time,
            "minmagnitude": min_magnitude,
            "orderby": "time-desc",
            "limit": limit
        }
        if bbox:
            params["minlatitude"] = bbox[0]
            params["minlongitude"] = bbox[1]
            params["maxlatitude"] = bbox[2]
            params["maxlongitude"] = bbox[3]

        try:
            response = requests.get(cls.BASE_QUERY_URL, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            df = cls._parse_geojson(data)
            cls._cache[cache_key] = (now, df)
            return df
        except Exception as e:
            print(f"[USGS Collector] Query error: {e}")
            return pd.DataFrame()

    @classmethod
    def _parse_geojson(cls, data: dict) -> pd.DataFrame:
        features = data.get("features", [])
        events = []
        for feature in features:
            props = feature.get("properties", {})
            geom = feature.get("geometry", {})
            coords = geom.get("coordinates", [0.0, 0.0, 0.0])
            
            raw_time = props.get("time")
            event_time = pd.to_datetime(raw_time, unit="ms", utc=True) if raw_time else datetime.now(timezone.utc)
            
            mag = props.get("mag")
            events.append({
                "id": feature.get("id", ""),
                "time": event_time,
                "place": props.get("place", "Unknown Location"),
                "mag": float(mag) if mag is not None else 0.0,
                "mag_type": props.get("magType", "ml"),
                "depth_km": float(coords[2]) if len(coords) > 2 else 10.0,
                "longitude": float(coords[0]),
                "latitude": float(coords[1]),
                "significance": props.get("sig", 0),
                "tsunami": props.get("tsunami", 0),
                "status": props.get("status", "automatic"),
                "mmi": float(props["mmi"]) if props.get("mmi") is not None else None,
                "alert": props.get("alert"),
                "url": props.get("url", "")
            })

        df = pd.DataFrame(events)
        if not df.empty:
            df.set_index("time", inplace=True)
            df.sort_index(inplace=True)
        return df

    @classmethod
    def fetch_emsc_recent(
        cls,
        min_magnitude: float = 4.0,
        days_back: int = 14,
        limit: int = 2000,
        timeout: float = 4.0,
    ) -> pd.DataFrame:
        """
        유럽-지중해 지진센터(EMSC SeismicPortal FDSN) 독립 피드 수집 (교차 검증 및 페일오버용)
        """
        cache_key = f"emsc_{min_magnitude}_{days_back}_{limit}"
        now = time.time()
        if cache_key in cls._cache:
            ts, cached_df = cls._cache[cache_key]
            if now - ts < cls.CACHE_TTL_SECONDS:
                return cached_df.copy()

        start_time = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S")
        params = {
            "format": "json",
            "start": start_time,
            "minmag": min_magnitude,
            "limit": limit,
        }
        try:
            resp = requests.get(cls.EMSC_QUERY_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            df = cls._parse_emsc_json(data)
            cls._cache[cache_key] = (now, df)
            return df
        except Exception as e:
            print(f"[EMSC Collector] Query error: {e}")
            return pd.DataFrame()

    @classmethod
    def _parse_emsc_json(cls, data: dict) -> pd.DataFrame:
        features = data.get("features", [])
        events = []
        for feature in features:
            props = feature.get("properties", {})
            geom = feature.get("geometry", {})
            coords = geom.get("coordinates", [0.0, 0.0, 0.0])

            raw_time = props.get("time")
            event_time = pd.to_datetime(raw_time, utc=True) if raw_time else datetime.now(timezone.utc)
            mag = props.get("mag")
            events.append({
                "id": str(feature.get("id", props.get("unid", ""))),
                "time": event_time,
                "place": props.get("flynn_region", "EMSC Region"),
                "mag": float(mag) if mag is not None else 0.0,
                "mag_type": props.get("magtype", "m"),
                "depth_km": abs(float(coords[2])) if len(coords) > 2 else 10.0,
                "longitude": float(coords[0]),
                "latitude": float(coords[1]),
                "significance": 0,
                "tsunami": 0,
                "status": "reviewed",
                "mmi": None,
                "alert": None,
                "url": "",
            })

        df = pd.DataFrame(events)
        if not df.empty:
            df.set_index("time", inplace=True)
            df.sort_index(inplace=True)
        return df

    @classmethod
    def cross_verify_catalogs(
        cls,
        primary_df: pd.DataFrame,
        secondary_df: pd.DataFrame,
        min_mag: float = 4.5,
        time_window_sec: float = 180.0,
        max_dist_km: float = 120.0,
    ) -> Dict:
        """
        USGS(1차)와 EMSC(2차) 지진 카탈로그를 시공간·규모 기준으로 교차 검증.
        """
        if primary_df.empty:
            return {"checked_events": 0, "confirmed_events": 0, "confirmed_ratio": 1.0, "max_mag_diff": 0.0}

        major_primary = primary_df[primary_df["mag"] >= min_mag]
        if major_primary.empty:
            return {"checked_events": 0, "confirmed_events": 0, "confirmed_ratio": 1.0, "max_mag_diff": 0.0}
        if secondary_df.empty:
            return {"checked_events": len(major_primary), "confirmed_events": 0, "confirmed_ratio": 0.0, "max_mag_diff": 0.0}

        confirmed = 0
        max_mag_diff = 0.0
        for ts, row in major_primary.iterrows():
            dt_sec = np.abs((secondary_df.index - ts).total_seconds())
            candidates = secondary_df[dt_sec <= time_window_sec]
            if candidates.empty:
                continue

            dlat = np.radians(candidates["latitude"].values - float(row["latitude"]))
            dlon = np.radians(candidates["longitude"].values - float(row["longitude"]))
            lat1 = np.radians(float(row["latitude"]))
            lat2 = np.radians(candidates["latitude"].values)
            a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
            dists = 6371.0 * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))

            matched = candidates[dists <= max_dist_km]
            if not matched.empty:
                mag_diff = float(np.min(np.abs(matched["mag"].values - float(row["mag"]))))
                max_mag_diff = max(max_mag_diff, mag_diff)
                if mag_diff <= 0.5:
                    confirmed += 1

        checked = len(major_primary)
        return {
            "checked_events": checked,
            "confirmed_events": confirmed,
            "confirmed_ratio": round(confirmed / checked, 3) if checked > 0 else 1.0,
            "max_mag_diff": round(max_mag_diff, 2),
        }

    @classmethod
    def fetch_with_failover(
        cls,
        min_magnitude: float = 2.5,
        days_back: int = 60,
        timeout: float = 4.0,
    ) -> Tuple[str, pd.DataFrame]:
        """USGS 우선 수집 후 장애 시 EMSC로 자동 페일오버"""
        df_usgs = cls.fetch_recent_earthquakes(min_magnitude=min_magnitude, days_back=days_back, timeout=timeout)
        if not df_usgs.empty:
            return "LIVE_USGS_FDSN", df_usgs
        df_emsc = cls.fetch_emsc_recent(min_magnitude=max(3.5, min_magnitude), days_back=min(30, days_back), timeout=timeout)
        if not df_emsc.empty:
            return "FAILOVER_EMSC_FDSN", df_emsc
        return "OFFLINE_EMPTY", pd.DataFrame()

    @classmethod
    def fetch_with_cross_verification(
        cls,
        min_magnitude: float = 2.5,
        days_back: int = 60,
        timeout: float = 4.0,
    ) -> Tuple[str, pd.DataFrame, pd.DataFrame]:
        """
        USGS와 EMSC를 병렬 수집하여 상시 다중 기관 교차 검증용 데이터 반환.
        USGS 장애 시 EMSC로 자동 페일오버.
        """
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_usgs = pool.submit(
                cls.fetch_recent_earthquakes,
                min_magnitude=min_magnitude,
                days_back=days_back,
                timeout=timeout,
            )
            fut_emsc = pool.submit(
                cls.fetch_emsc_recent,
                min_magnitude=max(4.0, min_magnitude),
                days_back=min(14, days_back),
                timeout=timeout,
            )
            df_usgs = fut_usgs.result()
            df_emsc = fut_emsc.result()

        if not df_usgs.empty:
            mode = "LIVE_USGS_EMSC_CROSS_VERIFIED" if not df_emsc.empty else "LIVE_USGS_FDSN"
            return mode, df_usgs, df_emsc
        if not df_emsc.empty:
            return "FAILOVER_EMSC_FDSN", df_emsc, pd.DataFrame()
        return "OFFLINE_EMPTY", pd.DataFrame(), pd.DataFrame()
