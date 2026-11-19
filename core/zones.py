"""
Global Fault Zones & Spatial Filtering Module
"""

from typing import Dict, List, Tuple, Optional
import numpy as np
import pandas as pd


# 글로벌 주요 활성 단층대 및 서브덕션 존 정의
# [min_lat, min_lon, max_lat, max_lon, center_lat, center_lon, description, tectonic_setting]
MAJOR_SEISMIC_ZONES: Dict[str, Dict] = {
    "japan_trench": {
        "id": "japan_trench",
        "name": "일본 도호쿠/관동 해구 (Japan Trench)",
        "bbox": (33.0, 138.0, 42.5, 146.0),
        "center": (37.5, 142.0),
        "tectonic_setting": "태평양판-북미판 섭입대 (Subduction Zone)",
        "typical_b_value": 0.95,
        "hazard_rating": "EXTREME"
    },
    "nankai_trough": {
        "id": "nankai_trough",
        "name": "일본 난카이 트러프 (Nankai Trough)",
        "bbox": (30.0, 130.0, 35.5, 139.0),
        "center": (32.8, 134.5),
        "tectonic_setting": "필리핀해판-유라시아판 섭입대 (Mega-thrust)",
        "typical_b_value": 0.90,
        "hazard_rating": "EXTREME"
    },
    "san_andreas": {
        "id": "san_andreas",
        "name": "미국 캘리포니아 산안드레아스 단층계",
        "bbox": (32.0, -125.0, 41.5, -114.0),
        "center": (36.5, -119.5),
        "tectonic_setting": "태평양판-북미판 주향이동단층 (Transform Fault)",
        "typical_b_value": 1.02,
        "hazard_rating": "HIGH"
    },
    "turkey_anatolian": {
        "id": "turkey_anatolian",
        "name": "튀르키예 아나톨리아 단층대 (East/North Anatolian)",
        "bbox": (35.0, 26.0, 42.0, 44.0),
        "center": (38.5, 36.0),
        "tectonic_setting": "아나톨리아 미소판-아라비아판 충돌대",
        "typical_b_value": 0.98,
        "hazard_rating": "EXTREME"
    },
    "sunda_trench": {
        "id": "sunda_trench",
        "name": "인도네시아 수마트라/자바 순다 해구",
        "bbox": (-11.0, 93.0, 6.0, 122.0),
        "center": (-3.0, 105.0),
        "tectonic_setting": "인도-호주판 섭입대 (Ring of Fire)",
        "typical_b_value": 0.92,
        "hazard_rating": "HIGH"
    },
    "chile_peru_trench": {
        "id": "chile_peru_trench",
        "name": "남미 칠레-페루 해구 (Chile-Peru Trench)",
        "bbox": (-45.0, -78.0, -15.0, -68.0),
        "center": (-30.0, -72.0),
        "tectonic_setting": "나스카판-남미판 섭입대 (Megathrust)",
        "typical_b_value": 0.94,
        "hazard_rating": "HIGH"
    },
    "korea_vicinity": {
        "id": "korea_vicinity",
        "name": "한반도 및 주변 해역 (Korea & Vicinity)",
        "bbox": (32.0, 122.0, 41.0, 132.0),
        "center": (36.0, 128.0),
        "tectonic_setting": "유라시아판 내부 (Intraplate Seismicity)",
        "typical_b_value": 0.88,
        "hazard_rating": "MODERATE"
    },
    "taiwan_ryukyu": {
        "id": "taiwan_ryukyu",
        "name": "대만 및 류큐 해구 (Taiwan-Ryukyu Trench)",
        "bbox": (21.5, 119.5, 26.5, 124.5),
        "center": (24.0, 121.8),
        "tectonic_setting": "필리핀해판-유라시아판 충돌 및 섭입대",
        "typical_b_value": 0.93,
        "hazard_rating": "EXTREME"
    },
    "new_guinea_banda": {
        "id": "new_guinea_banda",
        "name": "뉴기니 및 반다해 섭입대 (New Guinea / Banda)",
        "bbox": (-7.0, 130.0, 0.0, 145.0),
        "center": (-4.0, 137.0),
        "tectonic_setting": "태평양판-호주판 복합 수렴 경계",
        "typical_b_value": 0.91,
        "hazard_rating": "HIGH"
    },
    "central_america_trench": {
        "id": "central_america_trench",
        "name": "중미 해구 및 멕시코만 인접대 (Middle America Trench)",
        "bbox": (13.0, -105.0, 22.0, -88.0),
        "center": (17.5, -96.0),
        "tectonic_setting": "코코스판-북미판 섭입대",
        "typical_b_value": 0.95,
        "hazard_rating": "HIGH"
    }
}


class SpatialZoneFilter:
    """지리공간 필터링 및 단층대 매핑 유틸리티"""

    @staticmethod
    def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """두 위경도 좌표 간의 구면 대권 거리(km) 계산"""
        R = 6371.0  # 지구 반경 (km)
        dlat = np.radians(lat2 - lat1)
        dlon = np.radians(lon2 - lon1)
        a = (
            np.sin(dlat / 2.0) ** 2
            + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2.0) ** 2
        )
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
        return float(R * c)

    @classmethod
    def filter_by_bbox(
        cls, 
        df: pd.DataFrame, 
        bbox: Tuple[float, float, float, float]
    ) -> pd.DataFrame:
        """
        bbox: (min_lat, min_lon, max_lat, max_lon)
        """
        if df.empty:
            return df

        min_lat, min_lon, max_lat, max_lon = bbox
        mask = (
            (df["latitude"] >= min_lat)
            & (df["latitude"] <= max_lat)
            & (df["longitude"] >= min_lon)
            & (df["longitude"] <= max_lon)
        )
        return df[mask].copy()

    @classmethod
    def filter_by_radius(
        cls, 
        df: pd.DataFrame, 
        center_lat: float, 
        center_lon: float, 
        radius_km: float = 300.0
    ) -> pd.DataFrame:
        """특정 진앙 중심 반경 R km 이내 지진 필터링"""
        if df.empty:
            return df

        distances = [
            cls.haversine_distance_km(center_lat, center_lon, lat, lon)
            for lat, lon in zip(df["latitude"], df["longitude"])
        ]
        df_copy = df.copy()
        df_copy["dist_from_center_km"] = distances
        return df_copy[df_copy["dist_from_center_km"] <= radius_km].copy()

    @classmethod
    def classify_zone(cls, lat: float, lon: float) -> Optional[str]:
        """주어진 위경도가 어느 주요 단층대에 속하는지 분류"""
        for zone_id, info in MAJOR_SEISMIC_ZONES.items():
            min_lat, min_lon, max_lat, max_lon = info["bbox"]
            if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
                return zone_id
        return None
