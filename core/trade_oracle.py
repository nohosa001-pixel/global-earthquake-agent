"""
Trade-Enabling Seismic Hazard Oracle Subsystem
Designed to feed EUDR, Minerals Oracle, and global trade/logistics systems
alongside sibling physical-risk subsystems (e.g., climate-insurance-agent).
"""

import datetime
import hashlib
import math
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import requests

from core.physics import SeismicityPhysics
from core.security_gate import SeismicSecurityGate
from core.storage import OracleStateStore
from core.zones import MAJOR_SEISMIC_ZONES, SpatialZoneFilter
from models.risk_predictor import SeismicityRiskPredictor
from services.usgs_client import USGSEarthquakeCollector


TRADE_HUB_PRESETS: List[Dict[str, Any]] = [
    {
        "asset_id": "MINE-CL-ATACAMA",
        "name": "Salar de Atacama Lithium Brine Operations",
        "asset_type": "MINE",
        "commodity": "LITHIUM",
        "region_id": "SOUTH_AMERICA_ANDES",
        "lat": -23.50,
        "lng": -68.25,
        "canopy_loss_pct": 0.0,
    },
    {
        "asset_id": "MINE-ID-MOROWALI",
        "name": "Morowali Nickel Processing & Port",
        "asset_type": "MINE",
        "commodity": "NICKEL",
        "region_id": "SE_ASIA_SULAWESI",
        "lat": -2.82,
        "lng": 122.15,
        "canopy_loss_pct": 0.3,
    },
    {
        "asset_id": "MINE-PE-CERRO",
        "name": "Cerro Verde Copper Mine (Arequipa)",
        "asset_type": "MINE",
        "commodity": "COPPER",
        "region_id": "SOUTH_AMERICA_ANDES",
        "lat": -16.53,
        "lng": -71.58,
        "canopy_loss_pct": 0.0,
    },
    {
        "asset_id": "PORT-PA-PANAMA",
        "name": "Panama Canal (Gatun Lake Transit Corridor)",
        "asset_type": "PORT",
        "commodity": "MARITIME_CORRIDOR",
        "region_id": "CENTRAL_AMERICA",
        "lat": 9.10,
        "lng": -79.92,
        "canopy_loss_pct": 0.1,
    },
    {
        "asset_id": "FARM-BR-8891",
        "name": "Mato Grosso Soy Export Polygon (Sorriso)",
        "asset_type": "FARM",
        "commodity": "SOYBEAN",
        "region_id": "BRAZIL_MATO_GROSSO_SOY",
        "lat": -12.54,
        "lng": -55.72,
        "canopy_loss_pct": 0.4,
    },
    {
        "asset_id": "PORT-BR-SANTOS",
        "name": "Port of Santos Agri & Mineral Terminal",
        "asset_type": "PORT",
        "commodity": "GRAIN_EXPORT",
        "region_id": "BRAZIL_COAST",
        "lat": -23.96,
        "lng": -46.33,
        "canopy_loss_pct": 0.0,
    },
    {
        "asset_id": "FAB-TW-TSMC",
        "name": "TSMC Hsinchu Semiconductor Fab Complex",
        "asset_type": "SMELTER",
        "commodity": "SEMICONDUCTOR",
        "region_id": "TAIWAN_RYUKYU",
        "lat": 24.78,
        "lng": 120.99,
        "canopy_loss_pct": 0.0,
    },
    {
        "asset_id": "PORT-ID-BELAWAN",
        "name": "Port of Belawan Palm Oil & Rubber Hub (Sumatra)",
        "asset_type": "PORT",
        "commodity": "PALM_OIL",
        "region_id": "SE_ASIA_SUMATRA",
        "lat": 3.78,
        "lng": 98.68,
        "canopy_loss_pct": 0.2,
    },
]

UNIFIED_TRADE_HAZARD_SCHEMA: Dict[str, Any] = {
    "schema_version": "trade-hazard-oracle/1.0",
    "subsystems": ["CLIMATE_ORACLE", "SEISMIC_ORACLE"],
    "trade_actions": ["CLEAR", "CAUTION", "REROUTE", "HOLD_COMPLIANCE"],
    "hazard_types": [
        "NOMINAL",
        "HEATWAVE",
        "FLOOD_PRECIP",
        "DROUGHT",
        "DEFORESTATION",
        "SEISMIC",
    ],
    "required_fields": [
        "subsystem",
        "asset_id",
        "asset_type",
        "commodity",
        "location",
        "hazard_type",
        "severity_score",
        "trade_action",
        "force_majeure_eligible",
        "eudr_compliant",
        "bft_verified",
        "oracle_proof",
        "timestamp",
    ],
}


class TradeSeismicOracle:
    """
    Unified trade-hazard-oracle/1.0 seismic risk & EUDR compliance oracle.
    """

    SUBSYSTEM_ID = "SEISMIC_ORACLE"

    ALTERNATE_TRADE_HUBS: Dict[str, List[Dict[str, str]]] = {
        "COPPER": [
            {"asset_id": "PORT-CL-ANTOFAGASTA", "name": "Port of Antofagasta (Chile)", "role": "ALTERNATE_COPPER_EXPORT"},
            {"asset_id": "MINE-ZM-KANSANSHI", "name": "Kansanshi Copper Belt (Zambia - Low Seismic)", "role": "ALTERNATE_SUPPLY"},
        ],
        "NICKEL": [
            {"asset_id": "PORT-AU-TOWNSVILLE", "name": "Port of Townsville (Australia - Low Seismic)", "role": "ALTERNATE_NICKEL_EXPORT"},
            {"asset_id": "MINE-CA-SUDBURY", "name": "Sudbury Basin Nickel (Canada - Stable Craton)", "role": "ALTERNATE_SUPPLY"},
        ],
        "LITHIUM": [
            {"asset_id": "PORT-AU-FREMANTLE", "name": "Port of Fremantle Spodumene Hub (Australia)", "role": "ALTERNATE_LITHIUM_EXPORT"},
        ],
        "SEMICONDUCTOR": [
            {"asset_id": "PORT-KR-BUSAN", "name": "Port of Busan Logistics Hub (South Korea)", "role": "ALTERNATE_TRANSSHIPMENT"},
            {"asset_id": "FAB-US-ARIZONA", "name": "Arizona Semiconductor Corridor (USA - Low Seismic)", "role": "ALTERNATE_FAB_CAPACITY"},
        ],
        "PALM_OIL": [
            {"asset_id": "PORT-MY-KLANG", "name": "Port Klang EUDR-Verified Hub (Malaysia)", "role": "ALTERNATE_EUDR_PORT"},
        ],
        "CONTAINER_EXPORT": [
            {"asset_id": "PORT-KR-BUSAN", "name": "Port of Busan Transshipment Hub (South Korea)", "role": "ALTERNATE_PORT"},
            {"asset_id": "PORT-JP-HAKATA", "name": "Port of Hakata / Fukuoka (Japan)", "role": "ALTERNATE_PORT"},
        ],
    }

    def __init__(
        self,
        security_gate: Optional[SeismicSecurityGate] = None,
        collector: Optional[USGSEarthquakeCollector] = None,
        predictor: Optional[SeismicityRiskPredictor] = None,
        state_store: Optional[OracleStateStore] = None,
        max_alert_history: int = 50,
        cache_ttl_seconds: int = 900,
        request_timeout_seconds: float = 1.5,
    ):
        self.state_store = state_store
        self.security_gate = security_gate or SeismicSecurityGate(state_store=state_store)
        self.collector = collector or USGSEarthquakeCollector()
        self.predictor = predictor or SeismicityRiskPredictor(default_mc=2.8)
        self.max_alert_history = max_alert_history
        self.cache_ttl_seconds = cache_ttl_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self._catalog_cache: Optional[Tuple[float, str, pd.DataFrame, Optional[pd.DataFrame]]] = None

        if self.state_store is not None:
            self.webhook_urls = self.state_store.list_webhooks()
            self.alert_history = self.state_store.list_alerts(limit=max_alert_history)
        else:
            self.webhook_urls: List[str] = []
            self.alert_history: List[Dict[str, Any]] = []

    def register_webhook(self, url: str) -> List[str]:
        if self.state_store is not None:
            self.webhook_urls = self.state_store.add_webhook(url)
        elif url and url not in self.webhook_urls:
            self.webhook_urls.append(url)
        return list(self.webhook_urls)

    def _suggest_alternates(self, asset_id: str, commodity: str) -> List[Dict[str, str]]:
        c_key = commodity.upper()
        for key, hubs in self.ALTERNATE_TRADE_HUBS.items():
            if key in c_key or c_key in key:
                return [h for h in hubs if h["asset_id"] != asset_id]
        return [{"asset_id": "PORT-KR-BUSAN", "name": "Port of Busan Regional Hub", "role": "GENERAL_ALTERNATE_PORT"}]

    def _dispatch_warning_alert(self, assessment: Dict[str, Any]) -> None:
        """경고 등급(REROUTE/HOLD_COMPLIANCE 또는 Force Majeure) 발생 시 즉시 경보 기록/영속화 및 등록된 웹훅으로 푸시"""
        if assessment["trade_action"] not in ("REROUTE", "HOLD_COMPLIANCE") and not assessment["force_majeure_eligible"]:
            return

        alert_payload = {
            "event": "TRADE_SEISMIC_WARNING",
            "subsystem": self.SUBSYSTEM_ID,
            "asset_id": assessment["asset_id"],
            "asset_type": assessment["asset_type"],
            "commodity": assessment["commodity"],
            "trade_action": assessment["trade_action"],
            "severity_score": assessment["severity_score"],
            "force_majeure_eligible": assessment["force_majeure_eligible"],
            "operational_status": assessment["telemetry"].get("operational_status"),
            "supply_capacity_loss_pct": assessment["telemetry"].get("supply_capacity_loss_pct"),
            "estimated_disruption_days": assessment["telemetry"].get("estimated_disruption_days"),
            "logistics_bottlenecks": assessment["telemetry"].get("logistics_bottlenecks", []),
            "suggested_alternates": assessment.get("suggested_alternates", []),
            "timestamp": assessment["timestamp"],
        }
        self.alert_history.insert(0, alert_payload)
        if len(self.alert_history) > self.max_alert_history:
            self.alert_history.pop()
        if self.state_store is not None:
            self.state_store.save_alert(alert_payload)

        for url in self.webhook_urls:
            try:
                requests.post(url, json=alert_payload, timeout=2.0)
            except Exception:
                pass

    @staticmethod
    def _synthetic_seismic_baseline(lat: float, lng: float, asset_type: str = "PORT") -> Dict[str, Any]:
        """Deterministic geospatial seismic baseline when offline or live feed is disabled."""
        zone_id = SpatialZoneFilter.classify_zone(lat, lng)
        in_ring_of_fire = zone_id is not None
        phase = abs(math.sin(math.radians(lat * 2.1 + lng * 1.3)))
        b_val = round(0.88 + 0.14 * (1.0 - phase) if in_ring_of_fire else 1.05, 3)
        risk_score = round(0.18 + 0.14 * phase if in_ring_of_fire else 0.08, 2)
        soil = SeismicityPhysics.DEFAULT_SOIL_BY_ASSET.get(asset_type.upper(), "STIFF_SOIL")
        return {
            "zone_id": zone_id or "INTRAPLATE_BASELINE",
            "site_soil_type": soil,
            "events_count": 0,
            "b_value_recent": b_val,
            "risk_score": risk_score,
            "prob_m6_30d_pct": round(risk_score * 35.0, 1),
            "max_estimated_mmi": 2.0 if in_ring_of_fire else 1.0,
            "max_pga_g": 0.005 if in_ring_of_fire else 0.001,
            "pager_alert": "none",
            "tsunami_warning": False,
            "aftershock_count_72h": 0,
            "operational_status": "NORMAL",
            "supply_capacity_loss_pct": 0.0,
            "estimated_disruption_days": 0,
            "logistics_bottlenecks": [],
            "reviewed_events_ratio": 1.0,
            "cross_verified_ratio": None,
            "max_mag_diff": 0.0,
        }

    def _get_cached_live_catalog(self) -> Tuple[str, pd.DataFrame, Optional[pd.DataFrame]]:
        """Fetch and cache the live global seismic catalog for 15 minutes with a strict hard timeout."""
        now = time.time()
        if self._catalog_cache is not None:
            ts, mode, df_main, df_sec = self._catalog_cache
            if (now - ts) < self.cache_ttl_seconds:
                return f"{mode}_CACHED", df_main, df_sec

        df_sec: Optional[pd.DataFrame] = None
        t_out = self.request_timeout_seconds
        if hasattr(self.collector, "fetch_with_cross_verification"):
            source_mode, df_live, df_emsc = self.collector.fetch_with_cross_verification(
                min_magnitude=2.5, days_back=60, timeout=t_out
            )
            if not df_emsc.empty:
                df_sec = df_emsc
        elif hasattr(self.collector, "fetch_with_failover"):
            source_mode, df_live = self.collector.fetch_with_failover(
                min_magnitude=2.5, days_back=60, timeout=t_out
            )
        else:
            df_live = self.collector.fetch_recent_earthquakes(
                min_magnitude=2.5, days_back=60, timeout=t_out
            )
            source_mode = "LIVE_USGS_FDSN" if not df_live.empty else "OFFLINE_EMPTY"

        self._catalog_cache = (now, source_mode, df_live, df_sec)
        return source_mode, df_live, df_sec

    def _evaluate_live_seismic(
        self,
        lat: float,
        lng: float,
        global_df: pd.DataFrame,
        asset_type: str = "PORT",
        secondary_df: Optional[pd.DataFrame] = None,
        radius_km: float = 300.0,
    ) -> Dict[str, Any]:
        local_df = SpatialZoneFilter.filter_by_radius(global_df, lat, lng, radius_km=radius_km)
        zone_id = SpatialZoneFilter.classify_zone(lat, lng)

        if len(local_df) >= 15:
            analysis = self.predictor.analyze_region(local_df, zone_id="local_radius", zone_name="Local Radius")
        elif zone_id and zone_id in MAJOR_SEISMIC_ZONES:
            df_zone = SpatialZoneFilter.filter_by_bbox(global_df, MAJOR_SEISMIC_ZONES[zone_id]["bbox"])
            analysis = self.predictor.analyze_region(df_zone, zone_id=zone_id, zone_name=MAJOR_SEISMIC_ZONES[zone_id]["name"])
        else:
            analysis = self.predictor.analyze_region(local_df, zone_id="intraplate", zone_name="Intraplate")

        aftermath = SeismicityPhysics.assess_aftermath_impact(
            local_df, asset_type=asset_type, default_radius_km=radius_km
        )

        reviewed_ratio = 1.0
        if not local_df.empty and "status" in local_df.columns:
            rev_cnt = int((local_df["status"].astype(str).str.lower() == "reviewed").sum())
            reviewed_ratio = round(rev_cnt / len(local_df), 3)

        cross_verified_ratio = None
        max_mag_diff = 0.0
        if secondary_df is not None and not local_df.empty:
            cv = USGSEarthquakeCollector.cross_verify_catalogs(local_df, secondary_df)
            if cv["checked_events"] > 0:
                cross_verified_ratio = cv["confirmed_ratio"]
                max_mag_diff = cv["max_mag_diff"]

        return {
            "zone_id": zone_id or "INTRAPLATE",
            "site_soil_type": aftermath["site_soil_type"],
            "events_count": len(local_df),
            "b_value_recent": analysis["b_value_recent"],
            "risk_score": analysis["risk_score"],
            "prob_m6_30d_pct": analysis["prob_m6_30d_pct"],
            "max_estimated_mmi": aftermath["max_estimated_mmi"],
            "max_pga_g": aftermath["max_pga_g"],
            "pager_alert": aftermath["pager_alert"],
            "tsunami_warning": aftermath["tsunami_warning"],
            "aftershock_count_72h": aftermath["aftershock_count_72h"],
            "operational_status": aftermath["operational_status"],
            "supply_capacity_loss_pct": aftermath["supply_capacity_loss_pct"],
            "estimated_disruption_days": aftermath["estimated_disruption_days"],
            "logistics_bottlenecks": aftermath["logistics_bottlenecks"],
            "reviewed_events_ratio": reviewed_ratio,
            "cross_verified_ratio": cross_verified_ratio,
            "max_mag_diff": max_mag_diff,
        }

    def assess_asset(
        self,
        asset_id: str,
        lat: float,
        lng: float,
        asset_type: str = "PORT",
        commodity: str = "GENERAL",
        region_id: Optional[str] = None,
        polygon_id: Optional[str] = None,
        canopy_loss_pct: float = 0.0,
        use_live_feed: bool = True,
        catalog_df: Optional[pd.DataFrame] = None,
        secondary_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """Evaluate seismic disruption, multi-source consensus, aftermath impact, and EUDR compliance."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if catalog_df is not None:
            if not catalog_df.empty:
                source_mode = "INJECTED_CATALOG"
                telemetry = self._evaluate_live_seismic(
                    lat, lng, catalog_df, asset_type=asset_type, secondary_df=secondary_df
                )
            else:
                source_mode = "SYNTHETIC_FALLBACK"
                telemetry = self._synthetic_seismic_baseline(lat, lng, asset_type=asset_type)
        elif use_live_feed:
            source_mode, df_live, df_emsc = self._get_cached_live_catalog()
            if secondary_df is None and df_emsc is not None and not df_emsc.empty:
                secondary_df = df_emsc

            if not df_live.empty:
                telemetry = self._evaluate_live_seismic(
                    lat, lng, df_live, asset_type=asset_type, secondary_df=secondary_df
                )
            else:
                source_mode = "SYNTHETIC_FALLBACK"
                telemetry = self._synthetic_seismic_baseline(lat, lng, asset_type=asset_type)
        else:
            source_mode = "SYNTHETIC_BASELINE"
            telemetry = self._synthetic_seismic_baseline(lat, lng, asset_type=asset_type)

        # Normalize severity score (0 - 100) from stress risk, ground-motion MMI, PAGER alert & tsunami
        stress_severity = telemetry["risk_score"] * 100.0
        mmi_severity = max(0.0, (telemetry["max_estimated_mmi"] - 2.5) * 20.0)
        pager_boost = {"none": 0.0, "green": 10.0, "yellow": 45.0, "orange": 78.0, "red": 95.0}.get(
            telemetry["pager_alert"], 0.0
        )
        tsunami_boost = 90.0 if telemetry["tsunami_warning"] else 0.0
        severity = round(min(100.0, max(stress_severity, mmi_severity, pager_boost, tsunami_boost)), 1)
        hazard_type = "SEISMIC" if severity >= 15.0 else "NOMINAL"

        # EUDR compliance check when agricultural or polygon audit is supplied
        eudr_compliant = True
        eudr_verdict = "NOT_APPLICABLE"
        if asset_type.upper() == "FARM" or polygon_id or canopy_loss_pct > 0.0:
            eudr_compliant, _, eudr_verdict = self.security_gate.audit_eudr_compliance(
                region_id=region_id or f"GEO_{round(lat, 1)}_{round(lng, 1)}",
                farm_polygon_id=polygon_id or asset_id,
                canopy_cover_loss_pct=canopy_loss_pct,
            )
            if not eudr_compliant:
                hazard_type = "DEFORESTATION"
                severity = max(severity, 85.0)

        bft_ok, _, bft_verdict = self.security_gate.verify_seismic_consensus(
            asset_id=asset_id,
            reviewed_ratio=telemetry["reviewed_events_ratio"],
            events_count=telemetry["events_count"],
            peak_mmi=telemetry["max_estimated_mmi"],
            cross_verified_ratio=telemetry.get("cross_verified_ratio"),
            max_mag_diff=telemetry.get("max_mag_diff", 0.0),
        )

        if self.security_gate.circuit_breaker_active:
            trade_action = "HOLD_COMPLIANCE"
            bft_ok = False
            bft_verdict = f"BLOCKED: Circuit breaker active ({self.security_gate.circuit_breaker_reason})"
        elif not eudr_compliant:
            trade_action = "HOLD_COMPLIANCE"
        elif severity >= 70.0:
            trade_action = "REROUTE"
        elif severity >= 35.0:
            trade_action = "CAUTION"
        else:
            trade_action = "CLEAR"

        force_majeure = severity >= 75.0 and hazard_type == "SEISMIC"
        proof_payload = f"{self.SUBSYSTEM_ID}:{asset_id}:{lat:.4f}:{lng:.4f}:{hazard_type}:{severity}:{now_iso}"
        proof_hash = "0x" + hashlib.sha256(proof_payload.encode()).hexdigest()

        suggested_alternates = (
            self._suggest_alternates(asset_id, commodity) if trade_action == "REROUTE" else []
        )

        result = {
            "subsystem": self.SUBSYSTEM_ID,
            "schema_version": UNIFIED_TRADE_HAZARD_SCHEMA["schema_version"],
            "asset_id": asset_id,
            "asset_type": asset_type.upper(),
            "commodity": commodity.upper(),
            "location": {"lat": lat, "lng": lng, "region_id": region_id or telemetry["zone_id"]},
            "source_mode": source_mode,
            "telemetry": telemetry,
            "hazard_type": hazard_type,
            "severity_score": severity,
            "trade_action": trade_action,
            "force_majeure_eligible": force_majeure,
            "eudr_compliant": eudr_compliant,
            "eudr_verdict": eudr_verdict,
            "bft_verified": bft_ok,
            "bft_verdict": bft_verdict,
            "suggested_alternates": suggested_alternates,
            "oracle_proof": proof_hash,
            "timestamp": now_iso,
        }
        self._dispatch_warning_alert(result)
        return result

    def scan_presets_for_alerts(
        self,
        use_live_feed: bool = True,
        catalog_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """
        선제적 백그라운드 감시 루프: 주요 글로벌 무역 허브 프리셋(TRADE_HUB_PRESETS)을
        일괄 스캔하여 고위험(REROUTE/HOLD_COMPLIANCE) 발생 시 즉시 웹훅 경보 발송.
        """
        route_res = self.assess_route(
            waypoints=TRADE_HUB_PRESETS,
            use_live_feed=use_live_feed,
            catalog_df=catalog_df,
        )
        flagged = [
            {
                "asset_id": wp["asset_id"],
                "trade_action": wp["trade_action"],
                "severity_score": wp["severity_score"],
                "suggested_alternates": wp.get("suggested_alternates", []),
            }
            for wp in route_res["waypoints"]
            if wp["trade_action"] in ("REROUTE", "HOLD_COMPLIANCE")
        ]
        return {
            "scanned_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "scanned_count": route_res["waypoint_count"],
            "alerts_triggered": len(flagged),
            "flagged_assets": flagged,
        }

    def assess_route(
        self,
        waypoints: List[Dict[str, Any]],
        use_live_feed: bool = True,
        catalog_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """Evaluate an end-to-end multi-waypoint trade route (e.g., Mine -> Port -> Port) in parallel."""
        shared_catalog = catalog_df
        shared_secondary = None
        if shared_catalog is None and use_live_feed:
            _, shared_catalog, shared_secondary = self._get_cached_live_catalog()

        def _eval_wp(item: Tuple[int, Dict[str, Any]]) -> Dict[str, Any]:
            idx, wp = item
            return self.assess_asset(
                asset_id=wp.get("asset_id", f"WP-{idx + 1}"),
                lat=wp["lat"],
                lng=wp["lng"],
                asset_type=wp.get("asset_type", "PORT"),
                commodity=wp.get("commodity", "GENERAL"),
                region_id=wp.get("region_id"),
                polygon_id=wp.get("polygon_id"),
                canopy_loss_pct=float(wp.get("canopy_loss_pct", 0.0)),
                use_live_feed=use_live_feed,
                catalog_df=shared_catalog,
                secondary_df=shared_secondary if (shared_secondary is not None and not shared_secondary.empty) else None,
            )

        if len(waypoints) > 1:
            with ThreadPoolExecutor(max_workers=min(8, len(waypoints))) as pool:
                assessments = list(pool.map(_eval_wp, enumerate(waypoints)))
        else:
            assessments = [_eval_wp((idx, wp)) for idx, wp in enumerate(waypoints)]

        max_severity = max((a["severity_score"] for a in assessments), default=0.0)
        any_hold = any(a["trade_action"] == "HOLD_COMPLIANCE" for a in assessments)
        any_reroute = any(a["trade_action"] == "REROUTE" for a in assessments)
        any_caution = any(a["trade_action"] == "CAUTION" for a in assessments)

        if any_hold:
            route_action = "HOLD_COMPLIANCE"
        elif any_reroute:
            route_action = "REROUTE"
        elif any_caution:
            route_action = "CAUTION"
        else:
            route_action = "CLEAR"

        return {
            "subsystem": self.SUBSYSTEM_ID,
            "schema_version": UNIFIED_TRADE_HAZARD_SCHEMA["schema_version"],
            "waypoint_count": len(assessments),
            "route_trade_action": route_action,
            "max_severity_score": max_severity,
            "all_eudr_compliant": all(a["eudr_compliant"] for a in assessments),
            "force_majeure_triggered": any(a["force_majeure_eligible"] for a in assessments),
            "waypoints": assessments,
        }
