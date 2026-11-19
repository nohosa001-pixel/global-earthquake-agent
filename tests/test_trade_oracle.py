import os
import sys
from datetime import datetime, timedelta, timezone
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from core.trade_oracle import TradeSeismicOracle, UNIFIED_TRADE_HAZARD_SCHEMA
from app.main import app


def _make_seismic_catalog(mags, lat, lng, depth_km=12.0, status="reviewed"):
    start_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = [start_dt + timedelta(hours=i * 6) for i in range(len(mags))]
    return pd.DataFrame(
        {
            "id": [f"eq_{i}" for i in range(len(mags))],
            "place": ["Test Seismic Zone"] * len(mags),
            "mag": mags,
            "depth_km": [depth_km] * len(mags),
            "latitude": [lat] * len(mags),
            "longitude": [lng] * len(mags),
            "tsunami": [0] * len(mags),
            "status": [status] * len(mags),
        },
        index=pd.DatetimeIndex(times, name="time"),
    )


def test_trade_seismic_oracle_asset_clear_and_schema():
    oracle = TradeSeismicOracle()
    res = oracle.assess_asset(
        asset_id="MINE-CL-ATACAMA",
        lat=-23.50,
        lng=-68.25,
        asset_type="MINE",
        commodity="LITHIUM",
        use_live_feed=False,
    )
    for field in UNIFIED_TRADE_HAZARD_SCHEMA["required_fields"]:
        assert field in res
    assert res["subsystem"] == "SEISMIC_ORACLE"
    assert res["schema_version"] == "trade-hazard-oracle/1.0"
    assert res["trade_action"] in UNIFIED_TRADE_HAZARD_SCHEMA["trade_actions"]
    assert res["eudr_compliant"] is True
    assert res["bft_verified"] is True


def test_trade_seismic_oracle_eudr_hold_compliance():
    oracle = TradeSeismicOracle()
    res = oracle.assess_asset(
        asset_id="FARM-BR-9999",
        lat=-12.54,
        lng=-55.72,
        asset_type="FARM",
        commodity="SOYBEAN",
        region_id="BRAZIL_MATO_GROSSO_SOY",
        polygon_id="FARM-BR-9999",
        canopy_loss_pct=4.5,
        use_live_feed=False,
    )
    assert res["eudr_compliant"] is False
    assert res["hazard_type"] == "DEFORESTATION"
    assert res["trade_action"] == "HOLD_COMPLIANCE"
    assert res["severity_score"] >= 85.0


def test_trade_seismic_oracle_strong_shaking_reroute_and_force_majeure():
    oracle = TradeSeismicOracle()
    df_quake = _make_seismic_catalog([6.7], lat=3.72, lng=98.65, depth_km=10.0, status="reviewed")
    res = oracle.assess_asset(
        asset_id="PORT-ID-BELAWAN",
        lat=3.78,
        lng=98.68,
        asset_type="PORT",
        commodity="PALM_OIL",
        use_live_feed=False,
        catalog_df=df_quake,
    )
    assert res["hazard_type"] == "SEISMIC"
    assert res["severity_score"] >= 75.0
    assert res["trade_action"] == "REROUTE"
    assert res["force_majeure_eligible"] is True
    assert res["bft_verified"] is True


def test_trade_seismic_oracle_route_assessment():
    oracle = TradeSeismicOracle()
    route = oracle.assess_route(
        waypoints=[
            {"asset_id": "MINE-CL-ATACAMA", "lat": -23.50, "lng": -68.25, "asset_type": "MINE", "commodity": "LITHIUM"},
            {"asset_id": "PORT-PA-PANAMA", "lat": 9.10, "lng": -79.92, "asset_type": "PORT", "commodity": "MARITIME_CORRIDOR"},
        ],
        use_live_feed=False,
    )
    assert route["subsystem"] == "SEISMIC_ORACLE"
    assert route["waypoint_count"] == 2
    assert route["route_trade_action"] in UNIFIED_TRADE_HAZARD_SCHEMA["trade_actions"]
    assert len(route["waypoints"]) == 2


def test_api_unified_trade_oracle_endpoints_and_validation():
    client = TestClient(app)

    root_resp = client.get("/")
    assert root_resp.status_code == 200
    assert root_resp.json()["subsystem"] == "SEISMIC_ORACLE"
    assert root_resp.json()["schema_version"] == "trade-hazard-oracle/1.0"
    assert root_resp.json()["status"] == "OPERATIONAL"

    assert client.get("/api/health").json()["subsystem"] == "SEISMIC_ORACLE"
    assert client.get("/api/trade-oracle/schema").json()["schema_version"] == "trade-hazard-oracle/1.0"
    assert len(client.get("/api/trade-oracle/presets").json()["presets"]) >= 6

    # Invalid coordinates / empty route should fail Pydantic validation (422)
    bad_coord = client.post(
        "/api/trade-oracle/assess",
        json={"asset_id": "BAD", "lat": 95.0, "lng": 200.0, "use_live_feed": False},
    )
    assert bad_coord.status_code == 422

    empty_route = client.post(
        "/api/trade-oracle/assess-route",
        json={"waypoints": [], "use_live_feed": False},
    )
    assert empty_route.status_code == 422

    assess_resp = client.post(
        "/api/trade-oracle/assess",
        json={
            "asset_id": "MINE-ID-MOROWALI",
            "lat": -2.82,
            "lng": 122.15,
            "asset_type": "MINE",
            "commodity": "NICKEL",
            "use_live_feed": False,
        },
    )
    assert assess_resp.status_code == 200
    assert assess_resp.json()["asset_id"] == "MINE-ID-MOROWALI"
    assert assess_resp.json()["subsystem"] == "SEISMIC_ORACLE"

    route_resp = client.post(
        "/api/trade-oracle/assess-route",
        json={
            "waypoints": [
                {"asset_id": "FARM-BR-8891", "lat": -12.54, "lng": -55.72, "asset_type": "FARM", "commodity": "SOYBEAN", "canopy_loss_pct": 0.4},
                {"asset_id": "PORT-BR-SANTOS", "lat": -23.96, "lng": -46.33, "asset_type": "PORT", "commodity": "GRAIN_EXPORT"},
            ],
            "use_live_feed": False,
        },
    )
    assert route_resp.status_code == 200
    assert route_resp.json()["all_eudr_compliant"] is True


def test_circuit_breaker_and_eudr_audit_flow():
    client = TestClient(app)

    trip = client.post("/api/security-gate/trip-circuit-breaker?reason=Test+Halt")
    assert trip.status_code == 200
    assert trip.json()["gate"]["circuit_breaker_active"] is True

    halted = client.post(
        "/api/trade-oracle/assess",
        json={"asset_id": "PORT-BR-SANTOS", "lat": -23.96, "lng": -46.33, "use_live_feed": False},
    )
    assert halted.status_code == 200
    assert halted.json()["trade_action"] == "HOLD_COMPLIANCE"
    assert halted.json()["bft_verified"] is False

    reset = client.post("/api/security-gate/reset-circuit-breaker")
    assert reset.status_code == 200
    assert reset.json()["gate"]["circuit_breaker_active"] is False

    eudr = client.post(
        "/api/security/eudr/audit",
        json={"region_id": "BRAZIL_MATO_GROSSO_SOY", "polygon_id": "FARM-BR-01", "canopy_loss_pct": 0.2},
    )
    assert eudr.status_code == 200
    assert eudr.json()["is_compliant"] is True


def test_assess_route_offline_calls_collector_once():
    call_count = 0

    class DummyCollector:
        def fetch_recent_earthquakes(self, **kwargs):
            nonlocal call_count
            call_count += 1
            return pd.DataFrame()

    oracle = TradeSeismicOracle(collector=DummyCollector())
    route = oracle.assess_route(
        waypoints=[
            {"asset_id": "WP-1", "lat": -23.5, "lng": -68.25, "asset_type": "MINE", "commodity": "LITHIUM"},
            {"asset_id": "WP-2", "lat": 9.1, "lng": -79.92, "asset_type": "PORT", "commodity": "MARITIME_CORRIDOR"},
            {"asset_id": "WP-3", "lat": 3.78, "lng": 98.68, "asset_type": "PORT", "commodity": "PALM_OIL"},
        ],
        use_live_feed=True,
    )
    assert call_count == 1
    assert route["waypoint_count"] == 3
    assert all(wp["source_mode"] == "SYNTHETIC_FALLBACK" for wp in route["waypoints"])


def test_rupture_adjusted_ground_motion_and_tsunami_aftermath():
    from core.physics import SeismicityPhysics

    rupture_m75 = SeismicityPhysics.estimate_rupture_length_km(7.5)
    assert rupture_m75 > 80.0
    gm_m75 = SeismicityPhysics.estimate_ground_motion(magnitude=7.5, distance_km=50.0, depth_km=15.0)
    assert gm_m75["rupture_length_km"] == rupture_m75
    assert gm_m75["estimated_mmi"] >= 7.5

    # Tsunami + PAGER orange aftermath at port
    df_tsunami = _make_seismic_catalog([7.3, 5.1, 4.8], lat=3.70, lng=98.60, depth_km=18.0, status="reviewed")
    df_tsunami["tsunami"] = [1, 0, 0]
    df_tsunami["alert"] = ["orange", "green", None]

    oracle = TradeSeismicOracle()
    res = oracle.assess_asset(
        asset_id="PORT-ID-BELAWAN",
        lat=3.78,
        lng=98.68,
        asset_type="PORT",
        commodity="PALM_OIL",
        use_live_feed=False,
        catalog_df=df_tsunami,
    )
    assert res["telemetry"]["tsunami_warning"] is True
    assert res["telemetry"]["pager_alert"] == "orange"
    assert res["telemetry"]["aftershock_count_72h"] == 3
    assert res["telemetry"]["estimated_disruption_days"] == 14
    assert res["trade_action"] == "REROUTE"
    assert res["force_majeure_eligible"] is True


def test_multi_source_usgs_emsc_cross_verification_and_divergence():
    from services.usgs_client import USGSEarthquakeCollector

    df_usgs = _make_seismic_catalog([6.4], lat=-23.50, lng=-68.25, status="automatic")
    df_emsc_agree = _make_seismic_catalog([6.3], lat=-23.55, lng=-68.20, status="reviewed")
    cv_ok = USGSEarthquakeCollector.cross_verify_catalogs(df_usgs, df_emsc_agree)
    assert cv_ok["confirmed_events"] == 1
    assert cv_ok["confirmed_ratio"] == 1.0
    assert cv_ok["max_mag_diff"] <= 0.2

    # Even if USGS status is automatic, EMSC confirmation passes BFT gate
    oracle = TradeSeismicOracle()
    res_ok = oracle.assess_asset(
        asset_id="MINE-CL-ATACAMA",
        lat=-23.50,
        lng=-68.25,
        asset_type="MINE",
        commodity="LITHIUM",
        use_live_feed=False,
        catalog_df=df_usgs,
        secondary_df=df_emsc_agree,
    )
    assert res_ok["bft_verified"] is True

    # Large divergence (ΔM = 1.0) between USGS and EMSC must fail BFT gate
    df_emsc_diverge = _make_seismic_catalog([5.4], lat=-23.55, lng=-68.20, status="reviewed")
    res_bad = oracle.assess_asset(
        asset_id="MINE-CL-ATACAMA",
        lat=-23.50,
        lng=-68.25,
        asset_type="MINE",
        commodity="LITHIUM",
        use_live_feed=False,
        catalog_df=df_usgs,
        secondary_df=df_emsc_diverge,
    )
    assert res_bad["bft_verified"] is False
    assert "divergence" in res_bad["bft_verdict"].lower()


def test_soil_amplification_asset_trade_impact_and_alert_dispatch():
    from core.physics import SeismicityPhysics

    gm_port = SeismicityPhysics.estimate_ground_motion(6.4, distance_km=40.0, depth_km=15.0, site_soil_type="COASTAL_FILL")
    gm_mine = SeismicityPhysics.estimate_ground_motion(6.4, distance_km=40.0, depth_km=15.0, site_soil_type="HARD_ROCK")
    assert gm_port["pga_g"] > gm_mine["pga_g"]
    assert gm_port["estimated_mmi"] >= gm_mine["estimated_mmi"]

    # Smelter (Semiconductor Fab) shutdown impact + immediate alert history dispatch
    oracle = TradeSeismicOracle()
    df_fab = _make_seismic_catalog([6.5], lat=24.70, lng=120.90, depth_km=12.0, status="reviewed")
    res_fab = oracle.assess_asset(
        asset_id="FAB-TW-TSMC",
        lat=24.78,
        lng=120.99,
        asset_type="SMELTER",
        commodity="SEMICONDUCTOR",
        use_live_feed=False,
        catalog_df=df_fab,
    )
    assert res_fab["telemetry"]["site_soil_type"] == "STIFF_SOIL"
    assert res_fab["telemetry"]["operational_status"] == "SEVERE_OUTAGE"
    assert res_fab["telemetry"]["supply_capacity_loss_pct"] >= 80.0
    assert "FURNACE_OR_CLEANROOM_EMERGENCY_SHUTDOWN" in res_fab["telemetry"]["logistics_bottlenecks"]
    assert len(oracle.alert_history) == 1
    assert oracle.alert_history[0]["asset_id"] == "FAB-TW-TSMC"

    # Webhook & alert endpoints
    client = TestClient(app)
    wh = client.post("/api/trade-oracle/alerts/webhook", json={"url": "https://example.com/webhook"})
    assert wh.status_code == 200
    assert "https://example.com/webhook" in wh.json()["registered_webhooks"]

    alerts = client.get("/api/trade-oracle/alerts")
    assert alerts.status_code == 200
    assert alerts.json()["registered_webhooks"] >= 1

    scan_resp = client.post("/api/trade-oracle/monitor/scan-now?use_live_feed=false")
    assert scan_resp.status_code == 200
    assert scan_resp.json()["scanned_count"] >= 6


def test_sqlite_persistence_across_restart_and_suggested_alternates(tmp_path):
    from core.storage import OracleStateStore
    from core.security_gate import SeismicSecurityGate

    db_file = str(tmp_path / "oracle_test.db")
    store1 = OracleStateStore(db_path=db_file)
    gate1 = SeismicSecurityGate(state_store=store1)
    oracle1 = TradeSeismicOracle(security_gate=gate1, state_store=store1)

    oracle1.register_webhook("https://hooks.example.com/trade")
    gate1.trip_circuit_breaker("Persistent Kill-Switch Test")

    df_belawan = _make_seismic_catalog([6.8], lat=3.72, lng=98.65, depth_km=12.0, status="reviewed")
    # Reset circuit breaker to test REROUTE + suggested_alternates
    gate1.reset_circuit_breaker()
    res = oracle1.assess_asset(
        asset_id="PORT-ID-BELAWAN",
        lat=3.78,
        lng=98.68,
        asset_type="PORT",
        commodity="PALM_OIL",
        use_live_feed=False,
        catalog_df=df_belawan,
    )
    assert res["trade_action"] == "REROUTE"
    assert len(res["suggested_alternates"]) >= 1
    assert res["suggested_alternates"][0]["asset_id"] == "PORT-MY-KLANG"

    # Simulate server restart by creating fresh instances on the same SQLite DB
    store2 = OracleStateStore(db_path=db_file)
    gate2 = SeismicSecurityGate(state_store=store2)
    oracle2 = TradeSeismicOracle(security_gate=gate2, state_store=store2)

    assert "https://hooks.example.com/trade" in oracle2.webhook_urls
    assert len(oracle2.alert_history) >= 1
    assert oracle2.alert_history[0]["asset_id"] == "PORT-ID-BELAWAN"
    assert len(gate2.audit_log) >= 2

    # Proactive preset scan with injected quake near TSMC
    df_tsmc = _make_seismic_catalog([6.6], lat=24.72, lng=120.92, depth_km=12.0, status="reviewed")
    scan = oracle2.scan_presets_for_alerts(use_live_feed=False, catalog_df=df_tsmc)
    assert scan["alerts_triggered"] >= 1
    flagged_ids = [item["asset_id"] for item in scan["flagged_assets"]]
    assert "FAB-TW-TSMC" in flagged_ids
