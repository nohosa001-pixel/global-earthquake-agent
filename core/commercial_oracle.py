"""
B2B Commercial Oracles & Monetization Engine
1. Parametric Catastrophe Insurance Oracle (Cat-Bond Smart Contract Trigger)
2. Global Semiconductor / Precision Manufacturing Supply Chain Risk Sentinel
3. Commodity / Freight Futures Quantitative Hedge Signaler
"""

import hashlib
import json
from typing import Dict, List, Optional
import pandas as pd
from datetime import datetime, timezone
from core.physics import SeismicityPhysics
from core.zones import MAJOR_SEISMIC_ZONES, SpatialZoneFilter
from models.risk_predictor import SeismicityRiskPredictor


# 1. 글로벌 반도체/정밀 팹 및 항만 핵심 인프라 자산 위치 DB
CRITICAL_SUPPLY_CHAIN_ASSETS = [
    {
        "id": "tsmc_hsinchu",
        "name": "TSMC 팹 단지 (신주/타이난, 대만)",
        "category": "SEMICONDUCTOR",
        "lat": 24.78, "lon": 120.99,
        "radius_km": 300.0,
        "zone_id": "taiwan_ryukyu",
        "criticality": "EXTREME",
        "exposure_market": "글로벌 파운드리 공급 점유율 60%+",
        "fault_zone": "대만 서부/동부 단층대"
    },
    {
        "id": "sony_kumamoto",
        "name": "소니 이미지센서 / JASM 팹 (구마모토, 일본)",
        "category": "SEMICONDUCTOR",
        "lat": 32.88, "lon": 130.85,
        "radius_km": 300.0,
        "zone_id": "nankai_trough",
        "criticality": "HIGH",
        "exposure_market": "글로벌 CMOS 이미지 센서 시장 50%",
        "fault_zone": "일본 규슈 후타가와 단층대"
    },
    {
        "id": "renesas_naka",
        "name": "르네사스 나카 차량용 반도체 팹 (이바라키, 일본)",
        "category": "AUTOMOTIVE_CHIPS",
        "lat": 36.42, "lon": 140.53,
        "radius_km": 300.0,
        "zone_id": "japan_trench",
        "criticality": "HIGH",
        "exposure_market": "글로벌 MCU 차량용 반도체",
        "fault_zone": "일본 도호쿠/관동 해구"
    },
    {
        "id": "port_yokohama",
        "name": "요코하마 / 도쿄항 컨테이너 터미널",
        "category": "LOGISTICS_PORT",
        "lat": 35.44, "lon": 139.64,
        "radius_km": 300.0,
        "zone_id": "japan_trench",
        "criticality": "HIGH",
        "exposure_market": "동아시아 주요 해상 물류 허브",
        "fault_zone": "도쿄 수도권 직하 단층"
    }
]

# 2. 글로벌 원자재 및 에너지 핵심 생산 기지 DB
CRITICAL_COMMODITY_ASSETS = [
    {
        "id": "escondida_copper",
        "name": "에스콘디다 구리 광산 (칠레 아타카마)",
        "commodity": "COPPER (구리)",
        "lat": -24.27, "lon": -69.07,
        "radius_km": 350.0,
        "zone_id": "chile_peru_trench",
        "exposure": "전 세계 구리 공급량의 약 5~7%",
        "futures_ticker": "HG (COMEX Copper)",
        "fault_zone": "칠레-페루 해구 (Chile-Peru Trench)"
    },
    {
        "id": "grasberg_copper_gold",
        "name": "그라스버그 구리/금광 (인도네시아 파푸아)",
        "commodity": "COPPER / GOLD",
        "lat": -4.05, "lon": 137.11,
        "radius_km": 350.0,
        "zone_id": "new_guinea_banda",
        "exposure": "세계 2위 구리 광산",
        "futures_ticker": "HG / GC (Gold)",
        "fault_zone": "뉴기니 섭입대"
    },
    {
        "id": "pemex_gulf",
        "name": "멕시코만 해상 유전 단지 (페멕스)",
        "commodity": "CRUDE OIL (원유)",
        "lat": 19.30, "lon": -92.20,
        "radius_km": 400.0,
        "zone_id": "central_america_trench",
        "exposure": "중미 원유 수출 공급망",
        "futures_ticker": "CL (WTI Crude)",
        "fault_zone": "중미 해구 인접대"
    },
    {
        "id": "morowali_nickel",
        "name": "모로왈리 니켈 산업단지 (인도네시아 술라웨시)",
        "commodity": "NICKEL (니켈 - 배터리 핵심광물)",
        "lat": -2.83, "lon": 122.15,
        "radius_km": 350.0,
        "zone_id": "new_guinea_banda",
        "exposure": "글로벌 배터리급 니켈 정련 핵심 거점",
        "futures_ticker": "LME Nickel",
        "fault_zone": "술라웨시-반다해 복합 단층대"
    },
    {
        "id": "atacama_lithium",
        "name": "살라르 데 아타카마 리튬 & 안토파가스타항 (칠레)",
        "commodity": "LITHIUM (리튬 - 배터리 핵심광물)",
        "lat": -23.65, "lon": -70.40,
        "radius_km": 350.0,
        "zone_id": "chile_peru_trench",
        "exposure": "글로벌 리튬 탄산염 주요 수출 루트",
        "futures_ticker": "LTH (Lithium Carbonate)",
        "fault_zone": "칠레-페루 해구 (Chile-Peru Trench)"
    },
    {
        "id": "belawan_palm_rubber_eudr",
        "name": "수마트라 벨라완 수출항 (인도네시아 EUDR 허브)",
        "commodity": "PALM_OIL / RUBBER (EUDR)",
        "lat": 3.78, "lon": 98.68,
        "radius_km": 350.0,
        "zone_id": "sunda_trench",
        "exposure": "EUDR 대상 팜유·천연고무 주요 선적항",
        "futures_ticker": "FCPO / TSR20",
        "fault_zone": "수마트라 순다 해구 (Sunda Trench)"
    },
    {
        "id": "callao_copper_eudr",
        "name": "페루 카야오 수출항 (광물·EUDR 복합 허브)",
        "commodity": "COPPER / COFFEE (EUDR)",
        "lat": -12.05, "lon": -77.14,
        "radius_km": 350.0,
        "zone_id": "chile_peru_trench",
        "exposure": "남미 구리 정광 및 EUDR 커피·카카오 수출항",
        "futures_ticker": "HG / KC",
        "fault_zone": "칠레-페루 해구 (Chile-Peru Trench)"
    }
]


class ParametricInsuranceOracle:
    """
    파라메트릭 재해 보험 (Parametric Cat-Bond) 오라클
    - 사전에 합의된 트리거 조건(규모 M >= X, 진원 깊이 <= Y km, 반경 <= Z km) 충족 시 
      손해사정 절차 없이 즉각적인 스마트 컨트랙트 정산/지급 검증 데이터 제공
    """

    @classmethod
    def evaluate_cat_bond_triggers(
        cls, 
        df_recent_events: pd.DataFrame, 
        trigger_mag: float = 6.8, 
        max_depth_km: float = 50.0,
        require_reviewed: bool = True,
    ) -> List[Dict]:
        triggered_contracts = []
        if df_recent_events.empty:
            return triggered_contracts

        qualifying = df_recent_events[
            (df_recent_events["mag"] >= trigger_mag) & 
            (df_recent_events["depth_km"] <= max_depth_km)
        ]

        for idx, row in qualifying.iterrows():
            event_status = str(row.get("status", "automatic")).lower()
            is_reviewed = event_status == "reviewed"

            if require_reviewed and not is_reviewed:
                oracle_status = "PRELIMINARY_HOLD"
                action = "AWAITING_USGS_REVIEWED_CONFIRMATION"
            else:
                oracle_status = "TRIGGERED"
                action = "AUTOMATIC_PAYOUT_DISPATCH"

            trigger_event = {
                "event_id": row.get("id", ""),
                "magnitude": row.get("mag"),
                "depth_km": row.get("depth_km"),
                "coordinates": [row.get("latitude"), row.get("longitude")],
                "place": row.get("place"),
                "usgs_status": event_status,
                "timestamp": idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
            }
            payload_bytes = json.dumps(trigger_event, sort_keys=True, ensure_ascii=False).encode("utf-8")
            payload_hash = hashlib.sha256(payload_bytes).hexdigest()

            triggered_contracts.append({
                "contract_id": f"CATBOND-USGS-{row.get('id', idx)}",
                "oracle_status": oracle_status,
                "verified_reviewed": is_reviewed,
                "trigger_event": trigger_event,
                "payout_factor": 1.0 if row.get("mag") >= 7.5 else 0.5,
                "cryptographic_proof": f"SHA256:{payload_hash}",
                "action": action
            })

        return triggered_contracts


def _resolve_asset_risk(
    asset: Dict,
    zone_risk_map: Dict[str, Dict],
    global_df: Optional[pd.DataFrame],
    predictor: Optional[SeismicityRiskPredictor],
    default_risk: float = 0.2,
    default_b: float = 1.0,
) -> Dict:
    """
    자산 좌표 반경 내 지진 데이터가 충분하면 국소 반경 분석을 우선 사용하고,
    부족할 경우 해당 자산에 매핑된 광역 단층대(zone_id) 분석 결과를 반환.
    """
    radius_km = float(asset.get("radius_km", 300.0))
    if global_df is not None and not global_df.empty:
        local_df = SpatialZoneFilter.filter_by_radius(
            global_df, asset["lat"], asset["lon"], radius_km=radius_km
        )
        if len(local_df) >= 15:
            eng = predictor or SeismicityRiskPredictor()
            local_analysis = eng.analyze_region(
                local_df, zone_id=asset["id"], zone_name=asset["name"]
            )
            local_analysis["analysis_scope"] = f"LOCAL_RADIUS_{int(radius_km)}KM"
            return local_analysis

    zone_id = asset.get("zone_id") or SpatialZoneFilter.classify_zone(asset["lat"], asset["lon"])
    zone_stat = dict(zone_risk_map.get(zone_id, {})) if zone_id else {}
    zone_stat.setdefault("risk_score", default_risk)
    zone_stat.setdefault("risk_level", "NORMAL")
    zone_stat.setdefault("b_value_recent", default_b)
    zone_stat.setdefault("events_count", 0)
    zone_stat["analysis_scope"] = f"REGIONAL_ZONE:{zone_id}"
    return zone_stat


class SupplyChainRiskSentinel:
    """
    글로벌 반도체/정밀 제조 공급망 조기 경보 모니터링 B2B 서비스
    """

    @classmethod
    def audit_facilities(
        cls,
        zone_risk_map: Dict[str, Dict],
        global_df: Optional[pd.DataFrame] = None,
        predictor: Optional[SeismicityRiskPredictor] = None,
    ) -> List[Dict]:
        alerts = []
        for asset in CRITICAL_SUPPLY_CHAIN_ASSETS:
            zone_stat = _resolve_asset_risk(
                asset, zone_risk_map, global_df, predictor, default_risk=0.2, default_b=1.0
            )
            risk_score = zone_stat["risk_score"]
            b_val = zone_stat["b_value_recent"]

            # 사업장 위험도 산출
            status = "OPERATIONAL_STABLE"
            recommendation = "정상 가동"
            if risk_score >= 0.65 or b_val <= 0.70:
                status = "CRITICAL_FACILITY_WARNING"
                recommendation = "클린룸 진동 차단 시스템 사전 점검 및 웨이퍼 이송 장비 완충 모드 가동 권고"
            elif risk_score >= 0.40:
                status = "ELEVATED_STRESS_ADVISORY"
                recommendation = "단층 응력 집중 감지. 비상 백업 전력망 및 가스 라인 점검"

            alerts.append({
                "facility_id": asset["id"],
                "facility_name": asset["name"],
                "category": asset["category"],
                "exposure_market": asset["exposure_market"],
                "associated_fault_zone": asset["fault_zone"],
                "analysis_scope": zone_stat["analysis_scope"],
                "local_events_count": zone_stat.get("events_count", 0),
                "local_risk_score": risk_score,
                "facility_status": status,
                "b_value_status": b_val,
                "actionable_recommendation": recommendation
            })
        return alerts


class CommodityHedgeSignaler:
    """
    글로벌 원자재 선물 퀀트 헷지 시그널 생성기
    - 광산/유전 지역 단층대 응력 이상치 감지 시 공급 차질(Supply Disruption) 롱/헷지 시그널 발행
    """

    @classmethod
    def generate_quant_signals(
        cls,
        zone_risk_map: Dict[str, Dict],
        global_df: Optional[pd.DataFrame] = None,
        predictor: Optional[SeismicityRiskPredictor] = None,
    ) -> List[Dict]:
        signals = []
        for asset in CRITICAL_COMMODITY_ASSETS:
            zone_stat = _resolve_asset_risk(
                asset, zone_risk_map, global_df, predictor, default_risk=0.15, default_b=0.95
            )
            risk_score = zone_stat["risk_score"]
            b_val = zone_stat["b_value_recent"]

            # 시그널 산출
            if risk_score >= 0.60 or b_val <= 0.72:
                position = "STRONG_BUY / LONG_HEDGE (공급 차질 프리미엄 발생 예상)"
                confidence = "HIGH"
                rationale = f"해당 광산 인근 단층대 b값 급락({b_val:.2f})으로 강진에 의한 채굴/항만 마비 리스크 급증."
            elif risk_score >= 0.40:
                position = "TACTICAL_CALL_OPTION_BUY (변동성 헷지)"
                confidence = "MEDIUM"
                rationale = "국소 지진 활동 가속화 포착."
            else:
                position = "NEUTRAL / FLAT (정상 공급 상태)"
                confidence = "LOW"
                rationale = "광산 주변 지진 응력 안정 상태 유지."

            signals.append({
                "asset_id": asset["id"],
                "asset_name": asset["name"],
                "commodity": asset["commodity"],
                "futures_ticker": asset["futures_ticker"],
                "market_exposure": asset["exposure"],
                "analysis_scope": zone_stat["analysis_scope"],
                "local_events_count": zone_stat.get("events_count", 0),
                "risk_score": risk_score,
                "quant_signal": position,
                "signal_confidence": confidence,
                "physics_rationale": rationale
            })
        return signals


class TradeSupplyChainOracle:
    """
    EUDR 및 핵심 광물(Minerals) 무역 거래 전용 지진 리스크 오라클
    - 원산지(광산/EUDR 폴리곤 중심점)와 수출 항만(Export Port) 좌표를 각각 평가
    - 단층 응력(b-value) + 최근 강진에 의한 실제 예상 진도(MMI/PGA) + USGS 데이터 검증 비율(reviewed)을 결합
    """

    @staticmethod
    def _evaluate_site(
        site_id: str,
        site_name: str,
        lat: float,
        lon: float,
        radius_km: float,
        zone_risk_map: Dict[str, Dict],
        global_df: Optional[pd.DataFrame],
        predictor: Optional[SeismicityRiskPredictor],
    ) -> Dict:
        asset_stub = {"id": site_id, "name": site_name, "lat": lat, "lon": lon, "radius_km": radius_km}
        stat = _resolve_asset_risk(
            asset_stub, zone_risk_map, global_df, predictor, default_risk=0.10, default_b=1.0
        )

        max_mmi = 1.0
        max_pga_g = 0.0
        reviewed_ratio = 1.0
        preliminary_count = 0

        if global_df is not None and not global_df.empty:
            local_df = SpatialZoneFilter.filter_by_radius(global_df, lat, lon, radius_km=radius_km)
            if not local_df.empty:
                if "status" in local_df.columns:
                    rev_cnt = int((local_df["status"].astype(str).str.lower() == "reviewed").sum())
                    preliminary_count = len(local_df) - rev_cnt
                    reviewed_ratio = round(rev_cnt / len(local_df), 3)

                for _, row in local_df[local_df["mag"] >= 4.0].iterrows():
                    gm = SeismicityPhysics.estimate_ground_motion(
                        magnitude=float(row["mag"]),
                        distance_km=float(row.get("dist_from_center_km", radius_km)),
                        depth_km=float(row.get("depth_km", 15.0)),
                    )
                    if gm["estimated_mmi"] > max_mmi:
                        max_mmi = gm["estimated_mmi"]
                    if gm["pga_g"] > max_pga_g:
                        max_pga_g = gm["pga_g"]

        return {
            "site_name": site_name,
            "coordinates": [lat, lon],
            "analysis_scope": stat["analysis_scope"],
            "risk_score": stat.get("risk_score", 0.10),
            "prob_m6_30d_pct": stat.get("prob_m6_30d_pct", 5.0),
            "b_value_recent": stat.get("b_value_recent", 1.0),
            "max_estimated_mmi": max_mmi,
            "max_pga_g": max_pga_g,
            "reviewed_events_ratio": reviewed_ratio,
            "preliminary_events_count": preliminary_count,
        }

    @classmethod
    def assess_trade_route(
        cls,
        origin_lat: float,
        origin_lon: float,
        port_lat: float,
        port_lon: float,
        commodity: str,
        zone_risk_map: Dict[str, Dict],
        global_df: Optional[pd.DataFrame] = None,
        predictor: Optional[SeismicityRiskPredictor] = None,
        is_eudr_regulated: bool = False,
        radius_km: float = 300.0,
    ) -> Dict:
        origin_eval = cls._evaluate_site(
            "trade_origin", f"{commodity} Origin", origin_lat, origin_lon,
            radius_km, zone_risk_map, global_df, predictor
        )
        port_eval = cls._evaluate_site(
            "export_port", f"{commodity} Export Port", port_lat, port_lon,
            radius_km, zone_risk_map, global_df, predictor
        )

        combined_risk = round(max(origin_eval["risk_score"], port_eval["risk_score"]), 2)
        peak_mmi = max(origin_eval["max_estimated_mmi"], port_eval["max_estimated_mmi"])

        if peak_mmi >= 6.0:
            route_status = "FORCE_MAJEURE_VERIFICATION_REQUIRED"
            trade_action = "강진 진동(MMI 6.0+) 감지. 선적항/광산 설비 안전 점검 및 불가항력(Force Majeure) 증빙 확보 권고"
        elif combined_risk >= 0.65:
            route_status = "REROUTE_TO_PREVERIFIED_HUB"
            trade_action = "고위험 응력 집중(b값 급락). 사전 검증된 대체 공급처/우회 항만으로 물량 분산 권고"
        elif combined_risk >= 0.40 or peak_mmi >= 4.5:
            route_status = "PRE_SHIPMENT_HEDGE_ADVISORY"
            trade_action = "지진 활동 증가 포착. 선적 지연 대비 안전재고 확보 및 원자재/운임 변동성 헷지 권고"
        else:
            route_status = "CLEAR_FOR_SHIPMENT"
            trade_action = "원산지 및 수출항 지진 응력 안정 상태. 정상 무역 거래 진행 가능"

        eudr_impact = {
            "applicable": is_eudr_regulated,
            "landslide_or_access_risk": bool(is_eudr_regulated and origin_eval["max_estimated_mmi"] >= 5.5),
            "recommendation": (
                "원산지 인근 강진으로 산사태·도로 유실 가능성 있음. EUDR 적격 대체 폴리곤 라우팅 및 위성 재검증 권고"
                if (is_eudr_regulated and origin_eval["max_estimated_mmi"] >= 5.5)
                else ("EUDR 원산지 지형 안정 상태" if is_eudr_regulated else "N/A")
            ),
        }

        return {
            "commodity": commodity,
            "route_status": route_status,
            "combined_risk_score": combined_risk,
            "peak_estimated_mmi": peak_mmi,
            "trade_action": trade_action,
            "eudr_compliance_impact": eudr_impact,
            "origin_assessment": origin_eval,
            "port_assessment": port_eval,
            "data_source": "USGS FDSN/GeoJSON Real-time Seismic Stream",
        }
