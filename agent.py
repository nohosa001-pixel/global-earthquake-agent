import sys
import io

# Windows PowerShell Unicode Encoding Fix
if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import pandas as pd
from datetime import datetime, timezone
from services.usgs_client import USGSEarthquakeCollector
from core.zones import MAJOR_SEISMIC_ZONES, SpatialZoneFilter
from core.physics import SeismicityPhysics
from models.risk_predictor import SeismicityRiskPredictor
from core.commercial_oracle import (
    ParametricInsuranceOracle,
    SupplyChainRiskSentinel,
    CommodityHedgeSignaler,
    CRITICAL_SUPPLY_CHAIN_ASSETS,
    CRITICAL_COMMODITY_ASSETS
)


def run_agent():
    print("=" * 95)
    print(" 🌐 [GLOBAL EARTHQUAKE PHYSICS-ML EARLY WARNING & B2B ORACLE AGENT] ")
    print(f" ⏱️ 실행 시각(UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 95)

    collector = USGSEarthquakeCollector()
    predictor = SeismicityRiskPredictor(default_mc=2.8)

    print("\n📡 [1/4] 글로벌 USGS 실시간 지진 카탈로그 수집 중 (최근 60일, 전 세계 M2.5+)...")
    global_df = collector.fetch_recent_earthquakes(min_magnitude=2.5, days_back=60)
    
    if global_df.empty:
        print("   ⚠️ USGS API로부터 데이터를 수집하지 못했습니다. 네트워크를 확인하세요.")
        return

    print(f"   ✅ 총 {len(global_df):,}건의 글로벌 지진 이벤트 수집 완료 (최대 규모: M{global_df['mag'].max():.1f})")

    # 1. 단층대별 통계물리학 & 위험도 분석
    print("\n🔬 [2/4] 글로벌 주요 단층대(Fault Zones) 통계물리 역학 및 b값 이상 징후 분석")
    print("-" * 95)

    zone_risk_results = {}

    for zone_id, zone_info in MAJOR_SEISMIC_ZONES.items():
        zone_name = zone_info["name"]
        bbox = zone_info["bbox"]
        
        # 공간 필터링
        df_zone = SpatialZoneFilter.filter_by_bbox(global_df, bbox)
        result = predictor.analyze_region(df_zone, zone_id=zone_id, zone_name=zone_name)
        zone_risk_results[zone_id] = result

        status_icon = "🟢"
        if result["risk_level"] == "WARNING":
            status_icon = "🔴"
        elif result["risk_level"] == "WATCH":
            status_icon = "🟠"
        elif result["risk_level"] == "ADVISORY":
            status_icon = "🟡"

        print(f"\n{status_icon} [{zone_name}] - {zone_info['tectonic_setting']}")
        print(f"   📊 관측 이벤트: {result['events_count']}건 | 추정 완결규모(Mc): M{result['mc']}")
        print(f"   📉 장기 b값: {result['b_value_historical']:.3f} ──► 최근 윈도우 b값: {result['b_value_recent']:.3f} (변화율: -{result['b_drop_pct']}%)")
        print(f"   ⚡ 최근 10일 일평균 빈도: {result['recent_10d_daily_frequency']:.1f} 회/일 | 누적 변형률 지수: {result['cumulative_strain_log10']}")
        print(f"   🚨 위험 지수: {result['risk_score']*100:.0f}/100 | 향후 30일 M6.0+ 확률: {result['prob_m6_30d_pct']}% ──► [{result['risk_level_kr']}]")
        
        if result["indicators"]:
            for ind in result["indicators"]:
                print(f"      • ⚠️ {ind}")

    # 2. B2B 파라메트릭 보험 오라클 평가
    print("\n" + "=" * 95)
    print(" 💼 [3/4] B2B 수익화 모델 #1: 파라메트릭 재해 보험 (Cat-Bond) 오라클 상태")
    print("-" * 95)
    
    cat_triggers = ParametricInsuranceOracle.evaluate_cat_bond_triggers(global_df, trigger_mag=6.5)
    if cat_triggers:
        for trig in cat_triggers:
            evt = trig["trigger_event"]
            print(f"   🚨 [SMART CONTRACT TRIGGERED] {trig['contract_id']}")
            print(f"      • 지진: M{evt['magnitude']} ({evt['place']}) | 깊이: {evt['depth_km']}km")
            print(f"      • 오라클 서명 증명: {trig['cryptographic_proof']}")
            print(f"      • 조치: {trig['action']} (지급 비율: {trig['payout_factor']*100:.0f}%)")
    else:
        print("   ✅ 최근 60일간 Cat-Bond 즉각 트리거 조건(M6.5+ 천발 지진) 미발생 (정상)")

    # 3. 글로벌 반도체 공급망 센티널 & 원자재 퀀트 시그널
    print("\n" + "=" * 95)
    print(" 🏭 [4/4] B2B 수익화 모델 #2 & #3: 공급망 리스크 센티널 & 원자재 퀀트 시그널")
    print("-" * 95)

    fab_alerts = SupplyChainRiskSentinel.audit_facilities(
        zone_risk_results, global_df=global_df, predictor=predictor
    )
    print("   [글로벌 반도체 팹 및 핵심 물류 항만 모니터링]")
    for fab in fab_alerts:
        print(f"   • [{fab['category']}] {fab['facility_name']} ({fab['associated_fault_zone']})")
        print(f"     상태: [{fab['facility_status']}] (위험 스코어: {fab['local_risk_score']*100:.0f}점 | 분석범위: {fab['analysis_scope']})")
        print(f"     조치 권고: {fab['actionable_recommendation']}")

    commodity_signals = CommodityHedgeSignaler.generate_quant_signals(
        zone_risk_results, global_df=global_df, predictor=predictor
    )
    print("\n   [글로벌 원자재/에너지 선물 퀀트 헷지 포지션]")
    for sig in commodity_signals:
        print(f"   • [{sig['commodity']}] {sig['asset_name']} -> 티커: {sig['futures_ticker']}")
        print(f"     시그널: {sig['quant_signal']} (신뢰도: {sig['signal_confidence']} | 분석범위: {sig['analysis_scope']})")
        print(f"     물리적 근거: {sig['physics_rationale']}")

    print("\n" + "=" * 95)
    print(" 🚀 [에이전트 실행 완료] 웹 대시보드 기동은 'python app/main.py' 를 실행하세요.")
    print("=" * 95)


if __name__ == "__main__":
    run_agent()
