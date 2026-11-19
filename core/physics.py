"""
Statistical Seismology Physics Core
- Gutenberg-Richter Law: log10(N) = a - bM
- Aki-Utsu Maximum Likelihood Estimation (MLE) for b-value
- Dynamic Completeness Magnitude (Mc) estimation (MAXC)
- Gutenberg-Richter Seismic Energy: log10(E) = 4.8 + 1.5 * M (Joules)
- Benioff Strain Release: S = sqrt(E) = 10^(2.4 + 0.75 * M)
- Spatio-temporal rolling b-value time series & anomaly scoring
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional


class SeismicityPhysics:
    """통계물리학 기반 지진 응력 및 이상 징후 분석 엔진"""

    @staticmethod
    def estimate_mc_maxc(magnitudes: np.ndarray, bin_size: float = 0.1) -> float:
        """
        MAXC (Maximum Curvature) 알고리즘을 통한 완결성 규모(Mc) 자동 추정
        규모-빈도 분포(FMD)의 1차 미분(곡률)이 최대인 지점
        """
        if len(magnitudes) < 15:
            return 2.5
        
        bins = np.arange(np.min(magnitudes), np.max(magnitudes) + bin_size, bin_size)
        counts, bin_edges = np.histogram(magnitudes, bins=bins)
        if len(counts) == 0:
            return 2.5
            
        max_idx = np.argmax(counts)
        mc = bin_edges[max_idx]
        return round(float(mc), 1)

    @classmethod
    def calculate_b_value_aki(
        cls, 
        magnitudes: np.ndarray, 
        mc: Optional[float] = None, 
        bin_size: float = 0.1
    ) -> Tuple[float, float, int]:
        """
        Aki-Utsu 최대우도법(MLE) 기반 b값 및 표준오차 계산
        b = log10(e) / (mean(M) - (Mc - bin_size/2))
        sigma_b = b / sqrt(N)
        Returns: (b_value, std_error, sample_count)
        """
        if len(magnitudes) == 0:
            return 1.0, 0.0, 0

        if mc is None:
            mc = cls.estimate_mc_maxc(magnitudes, bin_size)

        m_filtered = magnitudes[magnitudes >= (mc - 1e-5)]
        n = len(m_filtered)

        if n < 15:
            return 1.0, 0.25, n

        mean_m = np.mean(m_filtered)
        denominator = mean_m - (mc - (bin_size / 2.0))
        
        if denominator <= 1e-4:
            return 1.0, 0.25, n

        b = (np.log10(np.e)) / denominator
        b = round(float(b), 3)
        std_err = round(float(b / np.sqrt(n)), 3)
        return b, std_err, n

    @classmethod
    def calculate_b_value_delta_aic(
        cls,
        mags_1: np.ndarray,
        mags_2: np.ndarray,
        mc: float,
        bin_size: float = 0.1,
    ) -> Tuple[float, float]:
        """
        Utsu (1992) ΔAIC 검정: 두 지진 표본(장기 vs 최근)의 b값 차이가
        통계적으로 유의미한지 판정.
        Returns: (delta_aic, p_value)
          - delta_aic >= 2.0 (p <= ~0.05) 이면 유의미한 b값 변화
        """
        b1, _, n1 = cls.calculate_b_value_aki(mags_1, mc=mc, bin_size=bin_size)
        b2, _, n2 = cls.calculate_b_value_aki(mags_2, mc=mc, bin_size=bin_size)

        if n1 < 15 or n2 < 15 or b1 <= 0 or b2 <= 0:
            return 0.0, 1.0

        delta_aic = (
            -2.0 * (n1 + n2) * np.log(n1 + n2)
            + 2.0 * n1 * np.log(n1 + n2 * (b1 / b2))
            + 2.0 * n2 * np.log(n1 * (b2 / b1) + n2)
            - 2.0
        )
        p_value = float(np.exp(-delta_aic / 2.0 - 2.0))
        p_value = min(1.0, max(0.0, p_value))
        return round(float(delta_aic), 3), round(p_value, 4)

    @staticmethod
    def calculate_seismic_energy_joules(magnitude: float) -> float:
        """
        지진 에너지 방출량 (Gutenberg-Richter 1956):
        log10(E) = 4.8 + 1.5 * M (Joules)
        E = 10^(4.8 + 1.5 * M)
        """
        return float(10.0 ** (4.8 + 1.5 * magnitude))

    @staticmethod
    def calculate_benioff_strain(magnitude: float) -> float:
        """
        베니오프 변형 방출량 (Benioff Strain Release):
        S proportional to sqrt(E) = 10^(2.4 + 0.75 * M)
        단층면의 누적 변위 및 비탄성 변형 해소 척도
        """
        return float(10.0 ** (2.4 + 0.75 * magnitude))

    @staticmethod
    def estimate_rupture_length_km(magnitude: float) -> float:
        """
        Wells & Coppersmith (1994) 경험식 기반 단층 파열 길이(km) 추정:
        log10(SRL) = -2.44 + 0.59 * M (M >= 5.5 에서 유의미)
        """
        if magnitude < 5.5:
            return 0.0
        return round(float(10.0 ** (-2.44 + 0.59 * magnitude)), 2)

    SITE_AMPLIFICATION_FACTORS: Dict[str, float] = {
        "HARD_ROCK": 0.85,      # 내륙 암반 광산
        "STIFF_SOIL": 1.00,     # 일반 경질 지반 / 공단
        "SOFT_ALLUVIAL": 1.35,  # 충적층 / 농지 / 하천 유역
        "COASTAL_FILL": 1.55,   # 해안 매립지 / 항만 (액상화 취약)
    }

    DEFAULT_SOIL_BY_ASSET: Dict[str, str] = {
        "PORT": "COASTAL_FILL",
        "FARM": "SOFT_ALLUVIAL",
        "SMELTER": "STIFF_SOIL",
        "WAREHOUSE": "STIFF_SOIL",
        "MINE": "HARD_ROCK",
    }

    @classmethod
    def estimate_ground_motion(
        cls,
        magnitude: float,
        distance_km: float,
        depth_km: float = 15.0,
        site_soil_type: str = "STIFF_SOIL",
    ) -> Dict[str, float]:
        """
        단층 파열 길이 보정(Wells & Coppersmith 1994) + 지반 증폭(Site Amplification) +
        간이 거리감쇠식(GMPE) 기반 예상 최대지반가속도(PGA, g) 및 수정 메르칼리 진도(MMI) 추정.
        """
        rupture_len = cls.estimate_rupture_length_km(magnitude)
        effective_epi_dist = max(0.0, float(distance_km) - (rupture_len * 0.5))
        r_hyp = float(np.sqrt(effective_epi_dist ** 2 + max(1.0, depth_km) ** 2))
        log10_pga_g = 0.45 * magnitude - 1.55 * np.log10(r_hyp + 10.0) - 1.20
        amp = cls.SITE_AMPLIFICATION_FACTORS.get(site_soil_type.upper(), 1.0)
        pga_g = float((10.0 ** log10_pga_g) * amp)
        pga_cms2 = max(1e-3, pga_g * 980.665)

        if pga_cms2 >= 18.0:
            mmi = 3.66 * np.log10(pga_cms2) - 1.66
        else:
            mmi = 2.20 * np.log10(pga_cms2) + 1.00
        mmi = min(10.0, max(1.0, float(mmi)))

        return {
            "hypocentral_distance_km": round(r_hyp, 1),
            "rupture_length_km": rupture_len,
            "site_soil_type": site_soil_type.upper(),
            "pga_g": round(pga_g, 4),
            "estimated_mmi": round(mmi, 1),
        }

    @classmethod
    def assess_aftermath_impact(
        cls,
        local_df: pd.DataFrame,
        asset_type: str = "PORT",
        default_radius_km: float = 300.0,
        site_soil_type: Optional[str] = None,
    ) -> Dict:
        """
        국소 반경 내 지진 카탈로그로부터 자산 특성·지반 증폭을 반영한 실질 무역 여파(Aftermath) 산출:
        - 단층 파열 + 지반 증폭 보정 최대 MMI / PGA
        - USGS PAGER 최고 경보 단계 (green/yellow/orange/red)
        - 쓰나미 위험 여부 (PORT 자산 및 해안)
        - 최근 72시간 여진(Aftershock) 빈도
        - 자산 유형별 예상 공급 손실률(%), 물류 병목 요인, 복구 소요 일수
        """
        soil = (site_soil_type or cls.DEFAULT_SOIL_BY_ASSET.get(asset_type.upper(), "STIFF_SOIL")).upper()

        if local_df.empty:
            return {
                "site_soil_type": soil,
                "max_estimated_mmi": 1.0,
                "max_pga_g": 0.0,
                "pager_alert": "none",
                "tsunami_warning": False,
                "aftershock_count_72h": 0,
                "operational_status": "NORMAL",
                "supply_capacity_loss_pct": 0.0,
                "estimated_disruption_days": 0,
                "logistics_bottlenecks": [],
            }

        alert_rank = {"none": 0, "green": 1, "yellow": 2, "orange": 3, "red": 4}
        best_alert = "none"
        max_mmi = 1.0
        max_pga_g = 0.0
        tsunami_warning = False

        for _, row in local_df[local_df["mag"] >= 4.0].iterrows():
            mag = float(row["mag"])
            depth = float(row.get("depth_km", 15.0))
            dist = float(row.get("dist_from_center_km", default_radius_km))

            gm = cls.estimate_ground_motion(
                magnitude=mag, distance_km=dist, depth_km=depth, site_soil_type=soil
            )
            max_mmi = max(max_mmi, gm["estimated_mmi"])
            max_pga_g = max(max_pga_g, gm["pga_g"])

            raw_alert = str(row.get("alert") or "none").lower()
            if alert_rank.get(raw_alert, 0) > alert_rank.get(best_alert, 0):
                best_alert = raw_alert

            if int(row.get("tsunami", 0) or 0) == 1 and (asset_type.upper() == "PORT" or dist <= 150.0):
                tsunami_warning = True

        latest_ts = local_df.index.max()
        cutoff_72h = latest_ts - pd.Timedelta(hours=72)
        aftershock_72h = int((local_df.index >= cutoff_72h).sum())

        # 자산 유형별 취약성 기반 무역 여파(공급 손실률, 병목 요인, 복구 일수) 산출
        atype = asset_type.upper()
        bottlenecks: List[str] = []
        capacity_loss = 0.0
        disruption_days = 0

        if tsunami_warning:
            bottlenecks.append("TSUNAMI_PORT_CLOSURE_AND_BERTH_EVACUATION")
            capacity_loss = max(capacity_loss, 95.0)
            disruption_days = max(disruption_days, 14)

        if atype == "PORT":
            if max_mmi >= 6.5 or best_alert in ("orange", "red"):
                bottlenecks.append("CRANE_AND_QUAY_LIQUEFACTION_DAMAGE")
                capacity_loss = max(capacity_loss, 75.0)
                disruption_days = max(disruption_days, 10)
            elif max_mmi >= 5.5 or best_alert == "yellow":
                bottlenecks.append("PORT_CONGESTION_AND_BERTH_INSPECTION")
                capacity_loss = max(capacity_loss, 35.0)
                disruption_days = max(disruption_days, 3)
        elif atype == "SMELTER":
            if max_mmi >= 6.0 or best_alert in ("orange", "red"):
                bottlenecks.append("FURNACE_OR_CLEANROOM_EMERGENCY_SHUTDOWN")
                capacity_loss = max(capacity_loss, 80.0)
                disruption_days = max(disruption_days, 10)
            elif max_mmi >= 5.0:
                bottlenecks.append("PRECISION_EQUIPMENT_RECALIBRATION_HOLD")
                capacity_loss = max(capacity_loss, 30.0)
                disruption_days = max(disruption_days, 3)
        elif atype == "MINE":
            if max_mmi >= 6.5 or best_alert in ("orange", "red"):
                bottlenecks.append("MINE_SHAFT_SAFETY_LOCK_AND_RAIL_DISRUPTION")
                capacity_loss = max(capacity_loss, 70.0)
                disruption_days = max(disruption_days, 7)
            elif max_mmi >= 5.5:
                bottlenecks.append("INLAND_HAUL_ROAD_LANDSLIDE_INSPECTION")
                capacity_loss = max(capacity_loss, 25.0)
                disruption_days = max(disruption_days, 2)
        else:  # FARM / WAREHOUSE / GENERAL
            if max_mmi >= 6.0 or best_alert in ("orange", "red"):
                bottlenecks.append("INLAND_LOGISTICS_AND_LANDSLIDE_BLOCKAGE")
                capacity_loss = max(capacity_loss, 60.0)
                disruption_days = max(disruption_days, 7)
            elif max_mmi >= 5.0:
                bottlenecks.append("RURAL_FEEDER_ROAD_DELAY")
                capacity_loss = max(capacity_loss, 20.0)
                disruption_days = max(disruption_days, 2)

        if best_alert == "red":
            capacity_loss = max(capacity_loss, 90.0)
            disruption_days = max(disruption_days, 14)

        if aftershock_72h >= 10 and disruption_days > 0:
            bottlenecks.append("PERSISTENT_AFTERSHOCK_SWARM_DELAYING_RECOVERY")
            disruption_days += 2

        if capacity_loss >= 70.0:
            op_status = "SEVERE_OUTAGE"
        elif capacity_loss >= 25.0:
            op_status = "PARTIAL_DISRUPTION"
        elif max_mmi >= 4.5:
            op_status = "INSPECTION_HOLD"
            disruption_days = max(disruption_days, 1)
        else:
            op_status = "NORMAL"

        return {
            "site_soil_type": soil,
            "max_estimated_mmi": round(max_mmi, 1),
            "max_pga_g": round(max_pga_g, 4),
            "pager_alert": best_alert,
            "tsunami_warning": tsunami_warning,
            "aftershock_count_72h": aftershock_72h,
            "operational_status": op_status,
            "supply_capacity_loss_pct": round(capacity_loss, 1),
            "estimated_disruption_days": disruption_days,
            "logistics_bottlenecks": bottlenecks,
        }

    @classmethod
    def compute_b_value_timeseries(
        cls, 
        df_events: pd.DataFrame, 
        window_size: int = 40, 
        step: int = 5,
        mc: Optional[float] = None
    ) -> List[Dict]:
        """
        이벤트 기반 슬라이딩 윈도우로 시간 경과에 따른 b-value 및 변형률 시계열 산출
        """
        if len(df_events) < window_size:
            return []

        ts_results = []
        magnitudes = df_events["mag"].values
        timestamps = df_events.index

        if mc is None:
            mc = cls.estimate_mc_maxc(magnitudes)

        all_strains = np.array([cls.calculate_benioff_strain(m) for m in magnitudes])
        running_cum_strains = np.cumsum(all_strains)

        for i in range(window_size, len(df_events) + 1, step):
            sub_mags = magnitudes[i - window_size:i]
            b_val, std_err, cnt = cls.calculate_b_value_aki(sub_mags, mc=mc)
            end_time = timestamps[i - 1]

            win_strain = float(np.sum(all_strains[i - window_size:i]))
            cum_strain = float(running_cum_strains[i - 1])

            ts_results.append({
                "time": end_time.isoformat() if hasattr(end_time, "isoformat") else str(end_time),
                "b_value": b_val,
                "std_err": std_err,
                "sample_count": cnt,
                "window_strain": round(win_strain, 2),
                "cumulative_strain": round(cum_strain, 2),
                "max_mag_in_window": round(float(np.max(sub_mags)), 1)
            })

        return ts_results

    @classmethod
    def calculate_fmd(cls, magnitudes: np.ndarray, bin_size: float = 0.1) -> Dict:
        """
        규모-빈도 분포 (Frequency-Magnitude Distribution, FMD) 히스토그램 & 누적 카운트
        G-R 관계식 곡선 피팅용
        """
        if len(magnitudes) == 0:
            return {"bins": [], "non_cum": [], "cum": []}

        min_m = np.floor(np.min(magnitudes) * 10) / 10
        max_m = np.ceil(np.max(magnitudes) * 10) / 10
        bins = np.arange(min_m, max_m + bin_size, bin_size)
        
        counts, bin_edges = np.histogram(magnitudes, bins=bins)
        cum_counts = [int(np.sum(magnitudes >= edge)) for edge in bin_edges[:-1]]

        return {
            "bins": [round(float(b), 1) for b in bin_edges[:-1]],
            "non_cumulative": [int(c) for c in counts],
            "cumulative": cum_counts
        }
