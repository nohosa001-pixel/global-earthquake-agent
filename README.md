# 🌐 Global Earthquake Physics & Trade Hazard Oracle (`SEISMIC_ORACLE`)

USGS(미국 지질조사국) 실시간 글로벌 지진 스트림을 기반으로 **구텐베르크-리히터(Gutenberg-Richter) $b$-value 붕괴 역학**, **Utsu $\Delta\text{AIC}$ 유의성 검정**, **베니오프 변형률(Benioff Strain)**, **GMPE 기반 예상 진도(PGA/MMI)**를 산출하는 **Headless B2B 지진 인텔리전스 및 무역 오라클 서브시스템**입니다.

형제 서브시스템인 `climate-insurance-agent`(`CLIMATE_ORACLE`)와 동일한 **`trade-hazard-oracle/1.0`** 통합 계약을 공유하여, **EUDR 컴플라이언스 엔진 · Minerals Oracle · 무역 금융 · 파라메트릭 보험(Cat-Bond)**에 표준화된 JSON 리스크 판정을 제공합니다.

---

## 📐 1. 핵심 통계물리학 수식 체계

1. **Aki-Utsu MLE $b$-value & Utsu $\Delta\text{AIC}$ 유의성 검정**
   $$b = \frac{\log_{10}(e)}{\langle M \rangle - \left(M_c - \frac{\Delta M}{2}\right)}, \quad \sigma_b = \frac{b}{\sqrt{N}}$$
   * $b \approx 1.0$: 정상 응력 해소 상태 / $b \le 0.75 \sim 0.65$: 단층 임계 응력 고착
   * $\Delta\text{AIC} \ge 2.0$: 장기 대비 최근 $b$-value 하락의 통계적 유의성 검증
2. **지진 에너지 & 누적 베니오프 변형률 (Benioff Strain)**
   $$\log_{10} E = 4.8 + 1.5M \ (\text{Joules}), \quad S = \sqrt{E} = 10^{2.4 + 0.75M}$$
3. **간이 거리감쇠식(GMPE) 기반 PGA / MMI 진도 추정**
   * 진앙 거리 및 진원 깊이로부터 광산·항만·EUDR 원산지 지점의 실질 타격 진도(`estimated_mmi`, `pga_g`) 산출

---

## 📁 2. 프로젝트 아키텍처 (Headless API & CLI)

```text
global-earthquake-agent/
├── AGENTS.md                  # SEISMIC_ORACLE 서브시스템 및 trade-hazard-oracle/1.0 명세
├── agent.py                   # CLI 글로벌 단층대 & B2B 오라클 분석 리포트
├── requirements.txt           # 패키지 의존성
├── core/
│   ├── physics.py             # Aki-Utsu MLE b-value, ΔAIC, Benioff Strain, GMPE PGA/MMI
│   ├── zones.py               # 글로벌 10대 단층대 바운딩박스 & 반경 필터링
│   ├── trade_oracle.py        # trade-hazard-oracle/1.0 통합 무역 오라클 (SEISMIC_ORACLE)
│   ├── security_gate.py       # USGS reviewed 합의 검증, EUDR 감사, 서킷 브레이커
│   └── commercial_oracle.py   # Cat-Bond(reviewed 검증), 반도체 공급망, 원자재 퀀트 시그널
├── services/
│   └── usgs_client.py         # USGS FDSN/GeoJSON 수집기 (time-desc, 120초 TTL 캐시)
├── models/
│   └── risk_predictor.py      # 물리기반 위험도 스코어러 & SeismicityBacktester
├── app/
│   └── main.py                # FastAPI Headless REST API 서버 (/docs 지원)
└── tests/
    ├── test_earthquake_agent.py
    └── test_trade_oracle.py
```

---

## 🚀 3. 실행 및 테스트 가이드

### (1) 의존성 설치
```bash
pip install -r requirements.txt
```

### (2) Headless Oracle API 서버 기동
```bash
python app/main.py
```
* 서비스 메타데이터: `http://localhost:8000/`
* Swagger API 문서: `http://localhost:8000/docs`
* 통합 무역 오라클: `GET /api/trade-oracle/schema`, `GET /api/trade-oracle/presets`, `POST /api/trade-oracle/assess`, `POST /api/trade-oracle/assess-route`
* 보안 게이트 & EUDR: `GET /api/security-gate/status`, `POST /api/security/eudr/audit`

### (3) CLI 리포트 실행
```bash
python agent.py
```

### (4) 테스트 실행
```bash
python -m pytest -v
```
