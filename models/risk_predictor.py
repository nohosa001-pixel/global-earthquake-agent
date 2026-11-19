"""
Physics-Informed Seismicity Risk Predictor & Early Warning Scorer
- Integrates Gutenberg-Richter b-value decay dynamics
- Benioff strain acceleration
- Seismic energy surge detection
- Probability estimation for M6.0+ earthquake within 7~30 days
"""

from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from core.physics import SeismicityPhysics


class SeismicityRiskPredictor:
    """통계물리 피처 융합 기반 위험도 및 대형 지진(M6.0+) 예측 엔진"""

    def __init__(self, default_mc: float = 2.8):
        self.default_mc = default_mc

    def analyze_region(
        self, 
        df_region: pd.DataFrame, 
        zone_id: str = "custom",
        zone_name: str = "Custom Region",
        mc: Optional[float] = None
    ) -> Dict:
        """
        특정 단층대/지역의 지진 카탈로그를 분석하여 물리 지표 및 조기 경보 산출
        """
        if len(df_region) < 15:
            return {
                "zone_id": zone_id,
                "zone_name": zone_name,
                "status": "INSUFFICIENT_DATA",
                "events_count": len(df_region),
                "risk_score": 0.10,
                "prob_m6_30d_pct": 5.0,
                "risk_level": "NORMAL",
                "risk_level_kr": "정상 해소 상태 (데이터 부족)",
                "b_value_historical": 1.0,
                "b_value_historical_err": 0.0,
                "b_value_recent": 1.0,
                "b_value_recent_err": 0.0,
                "b_drop_pct": 0.0,
                "b_delta_aic": 0.0,
                "b_drop_p_value": 1.0,
                "b_drop_significant": False,
                "mc": 2.5,
                "recent_10d_daily_frequency": 0.0,
                "max_magnitude": float(df_region["mag"].max()) if not df_region.empty else 0.0,
                "cumulative_strain_log10": 0.0,
                "energy_surge_pct": 0.0,
                "indicators": [],
                "timeseries": [],
                "fmd": {"bins": [], "non_cumulative": [], "cumulative": []},
                "explanation": "관측된 유효 지진 수가 적어 지각이 안정적이거나 완결성 규모 미만입니다."
            }

        magnitudes = df_region["mag"].values

        # 1. 완결성 규모(Mc) 추정
        if mc is None:
            mc = SeismicityPhysics.estimate_mc_maxc(magnitudes)

        # 2. 장기(Historical) b값 vs 최근(Recent) b값 비교
        b_hist, b_hist_err, n_hist = SeismicityPhysics.calculate_b_value_aki(magnitudes, mc=mc)
        
        # 최근 30개 (또는 전체의 30%) 이벤트 윈도우
        recent_window_size = min(35, max(15, int(len(magnitudes) * 0.35)))
        recent_mags = magnitudes[-recent_window_size:]
        b_recent, b_recent_err, n_recent = SeismicityPhysics.calculate_b_value_aki(recent_mags, mc=mc)

        # b값 하락률 계산
        if b_hist > 0:
            b_drop_ratio = (b_hist - b_recent) / b_hist
        else:
            b_drop_ratio = 0.0
        b_drop_pct = round(max(0.0, b_drop_ratio * 100), 1)

        # Utsu (1992) ΔAIC 유의성 검정 (비중첩 기준선 대비 최근 윈도우 비교)
        baseline_mags = magnitudes[:-recent_window_size]
        if len(baseline_mags) < 15:
            baseline_mags = magnitudes
        b_delta_aic, b_drop_p_value = SeismicityPhysics.calculate_b_value_delta_aic(
            baseline_mags, recent_mags, mc=mc
        )
        b_drop_significant = bool(b_delta_aic >= 2.0 and b_drop_pct > 0)

        # 3. 누적 에너지 및 베니오프 변형률 (Benioff Strain)
        strains = [SeismicityPhysics.calculate_benioff_strain(m) for m in magnitudes]
        total_strain = sum(strains)
        recent_strain = sum(strains[-recent_window_size:])
        strain_surge_ratio = (recent_strain / total_strain) if total_strain > 0 else 0.0

        energies = [SeismicityPhysics.calculate_seismic_energy_joules(m) for m in magnitudes]
        total_energy = sum(energies)
        recent_energy = sum(energies[-recent_window_size:])
        energy_surge_ratio = (recent_energy / total_energy) if total_energy > 0 else 0.0

        # 4. 최근 10일간 발생 빈도 가속도
        latest_time = df_region.index.max()
        cutoff_10d = latest_time - timedelta(days=10)
        recent_10d_events = df_region[df_region.index >= cutoff_10d]
        count_10d = len(recent_10d_events)
        freq_rate_10d = count_10d / 10.0

        # 최근 M4.5+ 중대형 지진 수
        m45_count = int(np.sum(magnitudes >= 4.5))
        m45_recent = int(np.sum(recent_mags >= 4.5))

        # 5. 물리기반 종합 위험도 지수 산출 (0.0 ~ 1.0)
        risk_score = 0.05
        indicators = []

        # (a) b-value 임계치 판정
        if b_recent <= 0.65:
            risk_score += 0.45
            indicators.append(f"b값 극단적 급락 ({b_recent:.2f} <= 0.65, 단층 임계 응력 고착)")
        elif b_recent <= 0.75:
            risk_score += 0.30
            indicators.append(f"b값 저하 경고 ({b_recent:.2f} <= 0.75, 응력 집중 진행)")
        elif b_recent <= 0.85:
            risk_score += 0.15
            indicators.append(f"b값 경계 ({b_recent:.2f} <= 0.85)")

        # (b) b값 상대적 하락 폭 (Utsu ΔAIC 유의성 반영)
        if b_drop_pct >= 25.0:
            risk_score += 0.25 if b_drop_significant else 0.15
            sig_label = f"ΔAIC={b_delta_aic}, p={b_drop_p_value}" if b_drop_significant else "표본 유의성 경계"
            indicators.append(f"장기 대비 b값 {b_drop_pct}% 급락 ({sig_label})")
        elif b_drop_pct >= 15.0:
            risk_score += 0.15 if b_drop_significant else 0.08
            indicators.append(f"장기 대비 b값 {b_drop_pct}% 하락세")

        # (c) 지진 발생 빈도 가속도
        if freq_rate_10d >= 4.0:
            risk_score += 0.20
            indicators.append(f"최근 10일간 일평균 {freq_rate_10d:.1f}회 빈발 (군발지진 징후)")
        elif freq_rate_10d >= 2.0:
            risk_score += 0.10
            indicators.append(f"최근 10일간 발생 빈도 증가 (일평균 {freq_rate_10d:.1f}회)")

        # (d) 에너지/변형률 급증 모멘텀
        if energy_surge_ratio >= 0.50:
            risk_score += 0.15
            indicators.append(f"최근 윈도우에 총 방출 에너지의 {energy_surge_ratio*100:.0f}% 집중")
        elif strain_surge_ratio >= 0.40:
            risk_score += 0.10
            indicators.append("베니오프 변형률 가속 방출 포착")

        # (e) 최근 M4.5+ 군집
        if m45_recent >= 3:
            risk_score += 0.10
            indicators.append(f"최근 M4.5+ 중형 지진 {m45_recent}회 군집 발생")

        risk_score = min(1.0, round(risk_score, 2))

        # 6. 향후 30일 이내 M6.0+ 발생 확률 추정 (로지스틱 변환 모델)
        # P(M6.0+ | risk_score) = 1 / (1 + exp(-k*(score - x0)))
        k = 6.5
        x0 = 0.50
        prob_m6 = 1.0 / (1.0 + np.exp(-k * (risk_score - x0)))
        prob_m6_pct = round(float(prob_m6 * 100), 1)

        # 7. 경보 레벨 판정 (4단계)
        if risk_score >= 0.70 or b_recent <= 0.65:
            risk_level = "WARNING"
            risk_level_kr = "CRITICAL (대형 지진 임박 고위험)"
        elif risk_score >= 0.45 or b_recent <= 0.75:
            risk_level = "WATCH"
            risk_level_kr = "WATCH (단층 응력 집중 주의)"
        elif risk_score >= 0.25:
            risk_level = "ADVISORY"
            risk_level_kr = "ADVISORY (모니터링 강화 권고)"
        else:
            risk_level = "NORMAL"
            risk_level_kr = "NORMAL (정상 응력 해소 상태)"

        # 시계열 b-value 트렌드 생성
        timeseries = SeismicityPhysics.compute_b_value_timeseries(
            df_region, 
            window_size=min(40, max(20, len(df_region)//2)), 
            step=max(2, len(df_region)//30),
            mc=mc
        )

        # 규모-빈도 분포(FMD)
        fmd = SeismicityPhysics.calculate_fmd(magnitudes)

        return {
            "zone_id": zone_id,
            "zone_name": zone_name,
            "status": "SUCCESS",
            "events_count": len(df_region),
            "mc": mc,
            "b_value_historical": b_hist,
            "b_value_historical_err": b_hist_err,
            "b_value_recent": b_recent,
            "b_value_recent_err": b_recent_err,
            "b_drop_pct": b_drop_pct,
            "b_delta_aic": b_delta_aic,
            "b_drop_p_value": b_drop_p_value,
            "b_drop_significant": b_drop_significant,
            "recent_10d_daily_frequency": round(freq_rate_10d, 1),
            "max_magnitude": round(float(np.max(magnitudes)), 1),
            "cumulative_strain_log10": round(float(np.log10(total_strain + 1.0)), 2),
            "energy_surge_pct": round(energy_surge_ratio * 100, 1),
            "risk_score": risk_score,
            "prob_m6_30d_pct": prob_m6_pct,
            "risk_level": risk_level,
            "risk_level_kr": risk_level_kr,
            "indicators": indicators,
            "timeseries": timeseries,
            "fmd": fmd
        }


class SeismicityBacktester:
    """과거 지진 카탈로그를 이용한 롤링 윈도우 백테스트 및 확률 교정 평가기"""

    @staticmethod
    def evaluate_catalog(
        df_catalog: pd.DataFrame,
        predictor: Optional[SeismicityRiskPredictor] = None,
        lookback_days: int = 60,
        horizon_days: int = 30,
        step_days: int = 10,
        target_mag: float = 6.0,
        alert_threshold: float = 0.45,
    ) -> Dict:
        """
        시계열 지진 카탈로그(DatetimeIndex)를 슬라이딩하며 향후 horizon_days 내
        target_mag 이상 지진 발생 여부를 예측 성능(Precision, Recall, F1, Brier Score)으로 평가
        """
        if predictor is None:
            predictor = SeismicityRiskPredictor()

        if df_catalog.empty or len(df_catalog) < 30:
            return {"status": "INSUFFICIENT_DATA", "windows_evaluated": 0}

        df_sorted = df_catalog.sort_index()
        start_ts = df_sorted.index.min() + timedelta(days=lookback_days)
        end_ts = df_sorted.index.max() - timedelta(days=horizon_days)

        if start_ts >= end_ts:
            return {"status": "INSUFFICIENT_TIMESPAN", "windows_evaluated": 0}

        y_true: List[int] = []
        y_prob: List[float] = []
        y_pred: List[int] = []

        cursor = start_ts
        while cursor <= end_ts:
            hist_slice = df_sorted[(df_sorted.index > cursor - timedelta(days=lookback_days)) & (df_sorted.index <= cursor)]
            future_slice = df_sorted[(df_sorted.index > cursor) & (df_sorted.index <= cursor + timedelta(days=horizon_days))]

            result = predictor.analyze_region(hist_slice, zone_id="backtest", zone_name="Backtest")
            actual_event = int(not future_slice.empty and (future_slice["mag"] >= target_mag).any())
            prob = float(result["prob_m6_30d_pct"]) / 100.0
            pred = int(float(result["risk_score"]) >= alert_threshold)

            y_true.append(actual_event)
            y_prob.append(prob)
            y_pred.append(pred)

            cursor += timedelta(days=step_days)

        n = len(y_true)
        if n == 0:
            return {"status": "NO_WINDOWS", "windows_evaluated": 0}

        tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)

        precision = round(tp / (tp + fp), 3) if (tp + fp) > 0 else 0.0
        recall = round(tp / (tp + fn), 3) if (tp + fn) > 0 else 0.0
        f1 = round(2 * precision * recall / (precision + recall), 3) if (precision + recall) > 0 else 0.0
        brier_score = round(float(np.mean([(p - t) ** 2 for p, t in zip(y_prob, y_true)])), 4)

        return {
            "status": "SUCCESS",
            "windows_evaluated": n,
            "positive_events": sum(y_true),
            "alerts_triggered": sum(y_pred),
            "precision": precision,
            "recall": recall,
            "f1_score": f1,
            "brier_score": brier_score,
        }
