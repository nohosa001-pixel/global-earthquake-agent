"""
Unit & Integration Tests for Global Earthquake Physics-ML Agent
"""

import os
import sys
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.physics import SeismicityPhysics
from core.zones import MAJOR_SEISMIC_ZONES, SpatialZoneFilter
from core.commercial_oracle import (
    ParametricInsuranceOracle,
    SupplyChainRiskSentinel,
    CommodityHedgeSignaler,
    TradeSupplyChainOracle,
)
from models.risk_predictor import SeismicityRiskPredictor, SeismicityBacktester


def _make_catalog(mags, start_dt=None, freq_hours=6, lat=37.5, lon=142.0, depth_km=20.0, status="reviewed"):
    if start_dt is None:
        start_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = [start_dt + timedelta(hours=i * freq_hours) for i in range(len(mags))]
    df = pd.DataFrame(
        {
            "id": [f"evt_{i}" for i in range(len(mags))],
            "place": ["Test Region"] * len(mags),
            "mag": mags,
            "depth_km": [depth_km] * len(mags),
            "latitude": [lat] * len(mags),
            "longitude": [lon] * len(mags),
            "tsunami": [0] * len(mags),
            "status": [status] * len(mags),
        },
        index=pd.DatetimeIndex(times, name="time"),
    )
    return df


# ---------------------------------------------------------------------------
# 1. Physics Core Tests
# ---------------------------------------------------------------------------

def test_aki_b_value_synthetic_gr():
    rng = np.random.default_rng(42)
    # Exponentially distributed magnitudes with true b = 1.0, 0.1-binned from Mc = 2.5
    beta = np.log(10) * 1.0
    mags = 2.5 + rng.exponential(scale=1.0 / beta, size=1000)
    mags = np.floor(mags * 10) / 10.0

    b_val, std_err, n = SeismicityPhysics.calculate_b_value_aki(mags, mc=2.5)
    assert n == 1000
    assert 0.90 <= b_val <= 1.10
    assert 0.01 <= std_err <= 0.05


def test_b_value_delta_aic_significance():
    rng = np.random.default_rng(7)
    mags_normal = np.round(2.5 + rng.exponential(scale=1.0 / (np.log(10) * 1.1), size=200), 1)
    mags_drop = np.round(2.5 + rng.exponential(scale=1.0 / (np.log(10) * 0.6), size=80), 1)

    daic_same, p_same = SeismicityPhysics.calculate_b_value_delta_aic(mags_normal, mags_normal, mc=2.5)
    assert daic_same < 0
    assert p_same > 0.05

    daic_diff, p_diff = SeismicityPhysics.calculate_b_value_delta_aic(mags_normal, mags_drop, mc=2.5)
    assert daic_diff >= 2.0
    assert p_diff <= 0.05


def test_timeseries_cumulative_strain_monotonic():
    mags = [3.0 + (i % 5) * 0.3 for i in range(60)]
    df = _make_catalog(mags)
    ts = SeismicityPhysics.compute_b_value_timeseries(df, window_size=20, step=5, mc=2.5)
    assert len(ts) > 0
    cum_vals = [row["cumulative_strain"] for row in ts]
    assert cum_vals == sorted(cum_vals)
    for row in ts:
        assert row["window_strain"] <= row["cumulative_strain"]


# ---------------------------------------------------------------------------
# 2. Spatial Zones Tests
# ---------------------------------------------------------------------------

def test_new_zones_classify_assets():
    assert SpatialZoneFilter.classify_zone(24.78, 120.99) == "taiwan_ryukyu"
    assert SpatialZoneFilter.classify_zone(-4.05, 137.11) == "new_guinea_banda"
    assert SpatialZoneFilter.classify_zone(19.30, -92.20) == "central_america_trench"


def test_filter_by_radius():
    df = pd.DataFrame(
        {
            "latitude": [24.78, 25.10, 35.68],
            "longitude": [120.99, 121.50, 139.69],
            "mag": [3.5, 4.0, 4.2],
        }
    )
    near_tsmc = SpatialZoneFilter.filter_by_radius(df, 24.78, 120.99, radius_km=100.0)
    assert len(near_tsmc) == 2


# ---------------------------------------------------------------------------
# 3. Risk Predictor & Backtester Tests
# ---------------------------------------------------------------------------

def test_predictor_insufficient_data():
    df_small = _make_catalog([3.0, 3.2, 3.5])
    predictor = SeismicityRiskPredictor()
    res = predictor.analyze_region(df_small, zone_id="test", zone_name="Test")
    assert res["status"] == "INSUFFICIENT_DATA"
    assert res["risk_level"] == "NORMAL"


def test_predictor_warning_on_b_drop_and_surge():
    rng = np.random.default_rng(123)
    baseline = list(np.round(2.8 + rng.exponential(scale=1.0 / (np.log(10) * 1.15), size=80), 1))
    # Recent surge of larger magnitudes -> sharp b-value drop
    recent = [4.6, 4.8, 5.1, 4.5, 4.9, 5.2, 4.7, 5.0, 4.6, 4.8,
              5.3, 4.9, 4.7, 5.1, 4.8, 4.6, 5.0, 5.4, 4.9, 4.7]
    df = _make_catalog(baseline + recent, freq_hours=3)
    predictor = SeismicityRiskPredictor()
    res = predictor.analyze_region(df, zone_id="test_warn", zone_name="Warn Zone", mc=2.8)
    assert res["status"] == "SUCCESS"
    assert res["b_value_recent"] < res["b_value_historical"]
    assert res["risk_score"] >= 0.45
    assert res["risk_level"] in ("WATCH", "WARNING")
    assert "b_delta_aic" in res


def test_backtester_evaluate_catalog():
    rng = np.random.default_rng(99)
    mags = list(np.round(2.8 + rng.exponential(scale=1.0 / (np.log(10) * 1.0), size=180), 1))
    # Inject a M6.2 target event near the end
    mags[150] = 6.2
    df = _make_catalog(mags, freq_hours=18)  # ~135 days
    report = SeismicityBacktester.evaluate_catalog(
        df, lookback_days=60, horizon_days=30, step_days=10, target_mag=6.0
    )
    assert report["status"] == "SUCCESS"
    assert report["windows_evaluated"] > 0
    assert report["positive_events"] >= 1
    assert 0.0 <= report["brier_score"] <= 1.0


# ---------------------------------------------------------------------------
# 4. B2B Commercial Oracles Tests
# ---------------------------------------------------------------------------

def test_catbond_oracle_sha256_proof():
    df_rev = _make_catalog([6.8, 4.0], depth_km=25.0, status="reviewed")
    triggers = ParametricInsuranceOracle.evaluate_cat_bond_triggers(df_rev, trigger_mag=6.5, max_depth_km=50.0)
    assert len(triggers) == 1
    assert triggers[0]["oracle_status"] == "TRIGGERED"
    assert triggers[0]["verified_reviewed"] is True
    proof = triggers[0]["cryptographic_proof"]
    assert proof.startswith("SHA256:")
    assert len(proof.split(":")[1]) == 64  # valid SHA256 hex digest

    df_auto = _make_catalog([6.8], depth_km=25.0, status="automatic")
    held = ParametricInsuranceOracle.evaluate_cat_bond_triggers(df_auto, trigger_mag=6.5, require_reviewed=True)
    assert held[0]["oracle_status"] == "PRELIMINARY_HOLD"
    assert held[0]["action"] == "AWAITING_USGS_REVIEWED_CONFIRMATION"


def test_ground_motion_and_trade_route_oracle():
    near_gm = SeismicityPhysics.estimate_ground_motion(magnitude=6.5, distance_km=15.0, depth_km=10.0)
    far_gm = SeismicityPhysics.estimate_ground_motion(magnitude=6.5, distance_km=300.0, depth_km=100.0)
    assert near_gm["estimated_mmi"] >= 6.0
    assert near_gm["pga_g"] > far_gm["pga_g"]
    assert far_gm["estimated_mmi"] < 4.5

    # Strong shaking near an EUDR palm-oil origin in Sumatra
    df_quake = _make_catalog([6.6], lat=3.70, lon=98.60, depth_km=12.0, status="reviewed")
    res = TradeSupplyChainOracle.assess_trade_route(
        origin_lat=3.78,
        origin_lon=98.68,
        port_lat=3.80,
        port_lon=98.70,
        commodity="PALM_OIL",
        zone_risk_map={},
        global_df=df_quake,
        is_eudr_regulated=True,
    )
    assert res["route_status"] == "FORCE_MAJEURE_VERIFICATION_REQUIRED"
    assert res["peak_estimated_mmi"] >= 6.0
    assert res["eudr_compliance_impact"]["applicable"] is True
    assert res["eudr_compliance_impact"]["landslide_or_access_risk"] is True
    assert res["origin_assessment"]["reviewed_events_ratio"] == 1.0


def test_supply_chain_and_commodity_local_radius_vs_fallback():
    # Create 20 earthquakes right around TSMC (24.78, 120.99)
    df_tsmc = _make_catalog([3.2 + (i % 4) * 0.3 for i in range(20)], lat=24.80, lon=121.00)
    zone_map = {
        "taiwan_ryukyu": {"risk_score": 0.3, "risk_level": "ADVISORY", "b_value_recent": 0.85, "events_count": 20},
        "chile_peru_trench": {"risk_score": 0.65, "risk_level": "WATCH", "b_value_recent": 0.70, "events_count": 40},
        "new_guinea_banda": {"risk_score": 0.2, "risk_level": "NORMAL", "b_value_recent": 0.95, "events_count": 10},
        "central_america_trench": {"risk_score": 0.15, "risk_level": "NORMAL", "b_value_recent": 1.0, "events_count": 10},
    }

    audits = SupplyChainRiskSentinel.audit_facilities(zone_map, global_df=df_tsmc)
    tsmc = next(a for a in audits if a["facility_id"] == "tsmc_hsinchu")
    yokohama = next(a for a in audits if a["facility_id"] == "port_yokohama")
    assert tsmc["analysis_scope"].startswith("LOCAL_RADIUS_")
    assert tsmc["local_events_count"] == 20
    assert yokohama["analysis_scope"] == "REGIONAL_ZONE:japan_trench"

    signals = CommodityHedgeSignaler.generate_quant_signals(zone_map, global_df=df_tsmc)
    escondida = next(s for s in signals if s["asset_id"] == "escondida_copper")
    pemex = next(s for s in signals if s["asset_id"] == "pemex_gulf")
    assert escondida["analysis_scope"] == "REGIONAL_ZONE:chile_peru_trench"
    assert escondida["signal_confidence"] == "HIGH"
    assert pemex["analysis_scope"] == "REGIONAL_ZONE:central_america_trench"
    assert pemex["signal_confidence"] == "LOW"


# ---------------------------------------------------------------------------
# 5. FastAPI Endpoints Test (Mocked USGS Collector)
# ---------------------------------------------------------------------------

def test_fastapi_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as app_main

    sample_df = _make_catalog([3.1, 3.4, 4.0, 4.5, 3.2] * 5, lat=37.5, lon=142.0)
    monkeypatch.setattr(app_main.collector, "fetch_recent_earthquakes", lambda **kwargs: sample_df)
    monkeypatch.setattr(app_main.collector, "fetch_feed", lambda feed_type="4.5_month": sample_df)
    app_main._zone_bundle_cache.clear()

    client = TestClient(app_main.app)

    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "HEALTHY"

    r_zones = client.get("/api/zones/summary")
    assert r_zones.status_code == 200
    assert r_zones.json()["zones_count"] == len(MAJOR_SEISMIC_ZONES)

    r_sup = client.get("/api/b2b/supply-chain")
    assert r_sup.status_code == 200
    assert r_sup.json()["assets_monitored"] == 4

    r_com = client.get("/api/b2b/commodity-hedge")
    assert r_com.status_code == 200
    assert r_com.json()["signals_count"] == 7

    r_trade = client.post(
        "/api/b2b/trade-route-risk",
        json={
            "origin_lat": -23.65,
            "origin_lon": -70.40,
            "port_lat": -23.65,
            "port_lon": -70.40,
            "commodity": "LITHIUM",
            "is_eudr_regulated": False,
        },
    )
    assert r_trade.status_code == 200
    assert "route_status" in r_trade.json()
    assert "origin_assessment" in r_trade.json()
