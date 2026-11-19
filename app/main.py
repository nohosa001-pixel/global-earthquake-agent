"""
FastAPI Server & REST API / B2B Oracle Backend
"""

import asyncio
from contextlib import asynccontextmanager
import os
import sys
import time

# 프로젝트 루트 디렉터리를 sys.path에 추가하여 직접 실행(python app/main.py) 지원
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, List
import pandas as pd
import numpy as np

from services.usgs_client import USGSEarthquakeCollector
from core.zones import MAJOR_SEISMIC_ZONES, SpatialZoneFilter
from core.physics import SeismicityPhysics
from models.risk_predictor import SeismicityRiskPredictor
from core.commercial_oracle import (
    ParametricInsuranceOracle,
    SupplyChainRiskSentinel,
    CommodityHedgeSignaler,
    TradeSupplyChainOracle,
    CRITICAL_SUPPLY_CHAIN_ASSETS,
    CRITICAL_COMMODITY_ASSETS
)
from core.security_gate import SeismicSecurityGate
from core.storage import OracleStateStore
from core.trade_oracle import (
    TradeSeismicOracle,
    TRADE_HUB_PRESETS,
    UNIFIED_TRADE_HAZARD_SCHEMA,
)

state_store = OracleStateStore()
collector = USGSEarthquakeCollector()
predictor = SeismicityRiskPredictor(default_mc=2.8)
security_gate = SeismicSecurityGate(state_store=state_store)
trade_oracle = TradeSeismicOracle(
    security_gate=security_gate,
    collector=collector,
    predictor=predictor,
    state_store=state_store,
)

MONITOR_INTERVAL_SECONDS = 180


async def _proactive_monitor_loop():
    """주기적으로 글로벌 무역 허브 프리셋을 선제 스캔하여 고위험 시 웹훅 경보 발송"""
    while True:
        try:
            await asyncio.sleep(MONITOR_INTERVAL_SECONDS)
            await asyncio.to_thread(trade_oracle.scan_presets_for_alerts, True)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            print(f"[Proactive Monitor] Scan error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_proactive_monitor_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(
    title="Global Earthquake Physics-ML Early Warning Agent API",
    description="Statistical Physics (b-value, Benioff Strain) & B2B Commercial Oracle API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 구역 분석 결과 인메모리 TTL 캐시 (중복 연산 방지)
_zone_bundle_cache: Dict[int, tuple] = {}
ZONE_CACHE_TTL_SECONDS = 120


def _get_zone_analysis_bundle(days_back: int = 60):
    """글로벌 지진 데이터와 모든 주요 단층대 분석 결과를 TTL 캐싱하여 반환"""
    now = time.time()
    cached = _zone_bundle_cache.get(days_back)
    if cached and (now - cached[0] < ZONE_CACHE_TTL_SECONDS):
        return cached[1], cached[2]

    global_df = collector.fetch_recent_earthquakes(min_magnitude=2.5, days_back=days_back)
    zone_results_map = {}
    for zone_id, zone_info in MAJOR_SEISMIC_ZONES.items():
        df_zone = SpatialZoneFilter.filter_by_bbox(global_df, zone_info["bbox"])
        zone_results_map[zone_id] = predictor.analyze_region(
            df_zone, zone_id=zone_id, zone_name=zone_info["name"]
        )

    _zone_bundle_cache[days_back] = (now, global_df, zone_results_map)
    return global_df, zone_results_map


@app.get("/")
def service_root():
    return {
        "system": "Trade-Enabling Seismic Hazard Oracle Subsystem",
        "subsystem": TradeSeismicOracle.SUBSYSTEM_ID,
        "schema_version": UNIFIED_TRADE_HAZARD_SCHEMA["schema_version"],
        "status": "OPERATIONAL",
        "docs": "/docs",
    }


@app.get("/api/health")
def health():
    return {
        "status": "HEALTHY",
        "service": "Earthquake Physics-ML Agent",
        "subsystem": TradeSeismicOracle.SUBSYSTEM_ID,
        "schema_version": UNIFIED_TRADE_HAZARD_SCHEMA["schema_version"],
        "circuit_breaker_active": security_gate.circuit_breaker_active,
    }


@app.get("/api/earthquakes/realtime")
def get_realtime_earthquakes(feed: str = Query("4.5_month", description="USGS Feed type (e.g., 2.5_day, 4.5_week, 4.5_month)")):
    """실시간 글로벌 지진 이벤트 목록 (Leaflet 지도 시각화용)"""
    df = collector.fetch_feed(feed)
    if df.empty:
        df = collector.fetch_recent_earthquakes(min_magnitude=3.0, days_back=30)
    
    events = []
    for idx, row in df.iterrows():
        events.append({
            "id": row.get("id", str(idx)),
            "time": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
            "mag": row.get("mag"),
            "depth_km": row.get("depth_km"),
            "place": row.get("place"),
            "lat": row.get("latitude"),
            "lon": row.get("longitude"),
            "tsunami": row.get("tsunami", 0)
        })
    return {"count": len(events), "events": events}


@app.get("/api/zones/summary")
def get_zones_summary(days_back: int = 60):
    """전 세계 주요 단층대별 실시간 통계물리 지표 및 위험도 요약"""
    _, zone_results_map = _get_zone_analysis_bundle(days_back=days_back)
    summary_list = []

    for zone_id, zone_info in MAJOR_SEISMIC_ZONES.items():
        analysis = zone_results_map[zone_id]

        summary_list.append({
            "zone_id": zone_id,
            "name": zone_info["name"],
            "center": zone_info["center"],
            "bbox": zone_info["bbox"],
            "tectonic_setting": zone_info["tectonic_setting"],
            "events_count": analysis["events_count"],
            "b_value_historical": analysis["b_value_historical"],
            "b_value_recent": analysis["b_value_recent"],
            "b_drop_pct": analysis["b_drop_pct"],
            "risk_score": analysis["risk_score"],
            "prob_m6_30d_pct": analysis["prob_m6_30d_pct"],
            "risk_level": analysis["risk_level"],
            "risk_level_kr": analysis["risk_level_kr"],
            "max_magnitude": analysis["max_magnitude"]
        })

    return {
        "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "zones_count": len(summary_list),
        "zones": summary_list
    }


@app.get("/api/zones/{zone_id}/detail")
def get_zone_detail(zone_id: str, days_back: int = 90):
    """특정 단층대의 정밀 통계물리 시계열, FMD, 변형률 데이터"""
    if zone_id not in MAJOR_SEISMIC_ZONES:
        raise HTTPException(status_code=404, detail="Zone not found")

    zone_info = MAJOR_SEISMIC_ZONES[zone_id]
    global_df = collector.fetch_recent_earthquakes(min_magnitude=2.2, days_back=days_back)
    df_zone = SpatialZoneFilter.filter_by_bbox(global_df, zone_info["bbox"])
    
    analysis = predictor.analyze_region(df_zone, zone_id=zone_id, zone_name=zone_info["name"])
    return {
        "zone_info": zone_info,
        "analysis": analysis
    }


@app.get("/api/oracle/catbonds")
def get_catbond_oracle(require_reviewed: bool = Query(True, description="Require USGS reviewed status for payout dispatch")):
    """파라메트릭 재해 보험(Cat-Bond) 오라클 트리거 상태"""
    df = collector.fetch_recent_earthquakes(min_magnitude=6.0, days_back=60)
    triggers = ParametricInsuranceOracle.evaluate_cat_bond_triggers(
        df, trigger_mag=6.5, require_reviewed=require_reviewed
    )
    return {
        "oracle_type": "PARAMETRIC_CAT_BOND_EARTHQUAKE",
        "verified_provider": "USGS Real-time Seismic Stream / Aki-Utsu Physics Agent",
        "require_reviewed": require_reviewed,
        "active_triggers_count": len(triggers),
        "triggers": triggers
    }


@app.get("/api/b2b/supply-chain")
def get_supply_chain_sentinel():
    """글로벌 반도체 팹 및 주요 항만 리스크 센티널"""
    global_df, zone_results_map = _get_zone_analysis_bundle(days_back=60)
    audits = SupplyChainRiskSentinel.audit_facilities(
        zone_results_map, global_df=global_df, predictor=predictor
    )
    return {
        "assets_monitored": len(audits),
        "assets": audits
    }


@app.get("/api/b2b/commodity-hedge")
def get_commodity_hedge_signals():
    """글로벌 원자재/운송 선물 퀀트 헷지 시그널"""
    global_df, zone_results_map = _get_zone_analysis_bundle(days_back=60)
    signals = CommodityHedgeSignaler.generate_quant_signals(
        zone_results_map, global_df=global_df, predictor=predictor
    )
    return {
        "signals_count": len(signals),
        "signals": signals
    }


class TradeRouteRiskRequest(BaseModel):
    origin_lat: float = Field(..., ge=-90, le=90)
    origin_lon: float = Field(..., ge=-180, le=180)
    port_lat: float = Field(..., ge=-90, le=90)
    port_lon: float = Field(..., ge=-180, le=180)
    commodity: str = Field(..., min_length=1, max_length=64)
    is_eudr_regulated: bool = False
    radius_km: float = Field(300.0, gt=10, le=1000)


@app.post("/api/b2b/trade-route-risk", deprecated=True)
def assess_trade_route_risk(req: TradeRouteRiskRequest):
    """[Deprecated: /api/trade-oracle/assess-route 사용 권장] EUDR 및 핵심 광물 무역 경로 지진 리스크 평가"""
    global_df, zone_results_map = _get_zone_analysis_bundle(days_back=60)
    return TradeSupplyChainOracle.assess_trade_route(
        origin_lat=req.origin_lat,
        origin_lon=req.origin_lon,
        port_lat=req.port_lat,
        port_lon=req.port_lon,
        commodity=req.commodity,
        zone_risk_map=zone_results_map,
        global_df=global_df,
        predictor=predictor,
        is_eudr_regulated=req.is_eudr_regulated,
        radius_km=req.radius_km,
    )


# --- Unified Trade Hazard Oracle Endpoints (trade-hazard-oracle/1.0) ---
class TradeAssetAssessRequest(BaseModel):
    asset_id: str = Field(..., min_length=1)
    lat: float = Field(..., ge=-90.0, le=90.0)
    lng: float = Field(..., ge=-180.0, le=180.0)
    asset_type: str = "PORT"
    commodity: str = "GENERAL"
    region_id: Optional[str] = None
    polygon_id: Optional[str] = None
    canopy_loss_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    use_live_feed: bool = True


class TradeRouteAssessRequest(BaseModel):
    waypoints: List[TradeAssetAssessRequest] = Field(..., min_length=1)
    use_live_feed: bool = True


class EudrAuditRequest(BaseModel):
    region_id: str = Field(..., min_length=1)
    polygon_id: str = Field(..., min_length=1)
    canopy_loss_pct: float = Field(..., ge=0.0, le=100.0)


@app.get("/api/trade-oracle/schema")
def get_trade_oracle_schema():
    """Returns unified Trade Hazard Oracle schema shared with climate-insurance-agent"""
    return UNIFIED_TRADE_HAZARD_SCHEMA


@app.get("/api/trade-oracle/presets")
def get_trade_oracle_presets():
    """Returns global Minerals Oracle mines, maritime corridors, and EUDR export presets"""
    return {"presets": TRADE_HUB_PRESETS}


@app.post("/api/trade-oracle/assess")
def assess_trade_asset(req: TradeAssetAssessRequest):
    """Evaluates seismic disruption, USGS consensus, and EUDR compliance for a trade asset"""
    return trade_oracle.assess_asset(
        asset_id=req.asset_id,
        lat=req.lat,
        lng=req.lng,
        asset_type=req.asset_type,
        commodity=req.commodity,
        region_id=req.region_id,
        polygon_id=req.polygon_id,
        canopy_loss_pct=req.canopy_loss_pct,
        use_live_feed=req.use_live_feed,
    )


@app.post("/api/trade-oracle/assess-route")
def assess_trade_route(req: TradeRouteAssessRequest):
    """Evaluates an end-to-end multi-waypoint supply chain route (e.g., Mine -> Port -> Port)"""
    return trade_oracle.assess_route(
        waypoints=[wp.model_dump() for wp in req.waypoints],
        use_live_feed=req.use_live_feed,
    )


class WebhookRegisterRequest(BaseModel):
    url: str = Field(..., min_length=8)


@app.get("/api/trade-oracle/alerts")
def get_trade_oracle_alerts():
    """Returns recently dispatched high-priority trade warning alerts"""
    return {
        "alerts_count": len(trade_oracle.alert_history),
        "registered_webhooks": len(trade_oracle.webhook_urls),
        "alerts": trade_oracle.alert_history,
    }


@app.post("/api/trade-oracle/alerts/webhook")
def register_trade_oracle_webhook(req: WebhookRegisterRequest):
    """Registers a webhook URL for immediate push notifications on REROUTE / HOLD_COMPLIANCE"""
    hooks = trade_oracle.register_webhook(req.url)
    return {"registered_webhooks": hooks}


@app.post("/api/trade-oracle/monitor/scan-now")
def trigger_preset_scan_now(use_live_feed: bool = True):
    """Triggers an immediate proactive scan across all global trade hub presets"""
    return trade_oracle.scan_presets_for_alerts(use_live_feed=use_live_feed)


# --- Security Gate & EUDR Compliance Endpoints ---
@app.get("/api/security-gate/status")
def get_security_gate_status():
    """Returns real-time Security Gate telemetry, audit log, and circuit breaker state"""
    return security_gate.get_security_status()


@app.post("/api/security-gate/trip-circuit-breaker")
def trip_circuit_breaker(reason: Optional[str] = "Manual Operator Emergency Kill-Switch"):
    """Emergency kill-switch to freeze automated oracle approvals"""
    security_gate.trip_circuit_breaker(reason)
    return {"status": "CIRCUIT_BREAKER_TRIPPED", "gate": security_gate.get_security_status()}


@app.post("/api/security-gate/reset-circuit-breaker")
def reset_circuit_breaker():
    """Restores system to operational status after operator review"""
    security_gate.reset_circuit_breaker()
    return {"status": "CIRCUIT_BREAKER_RESET", "gate": security_gate.get_security_status()}


@app.post("/api/security/eudr/audit")
def audit_eudr_polygon(req: EudrAuditRequest):
    """Audits farm polygon for EUDR deforestation-free compliance"""
    passed, risk, verdict = security_gate.audit_eudr_compliance(
        region_id=req.region_id,
        farm_polygon_id=req.polygon_id,
        canopy_cover_loss_pct=req.canopy_loss_pct,
    )
    return {
        "is_compliant": passed,
        "risk_score": risk,
        "verdict": verdict,
        "gate_status": security_gate.get_security_status(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
