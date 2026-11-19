# Trade-Enabling Seismic Hazard Oracle Subsystem

> **Role:** Physical Seismic Hazard, Ground-Motion (PGA/MMI) & Supply-Chain Disruption Oracle Subsystem  
> **Sibling Subsystem:** `climate-insurance-agent` (`CLIMATE_ORACLE`)  
> **Primary Consumers:** EUDR Compliance Engine, Minerals Oracle, Trade Finance & Maritime Logistics  
> **Unified Schema:** `trade-hazard-oracle/1.0`

---

## System Identity

This subsystem provides verified seismic hazard scoring (Gutenberg-Richter $b$-value, Utsu $\Delta\text{AIC}$, Benioff Strain, GMPE PGA/MMI ground-motion estimation) and EUDR deforestation-free / circuit-breaker compliance gates so external trade systems can clear, caution, reroute, or hold shipments using the exact same contract as `climate-insurance-agent`.

---

## Trade Oracle API Specification

### 1. Unified Trade Hazard Schema
- **Method:** `GET`
- **Endpoint:** `/api/trade-oracle/schema`
- **Purpose:** Returns the standardized `trade-hazard-oracle/1.0` contract shared with `climate-insurance-agent` (`trade_actions`: `CLEAR | CAUTION | REROUTE | HOLD_COMPLIANCE`).

### 2. Global Trade Hub Presets
- **Method:** `GET`
- **Endpoint:** `/api/trade-oracle/presets`
- **Purpose:** Returns shared Minerals Oracle mines, maritime corridors, EUDR agricultural polygons, and semiconductor hubs.

### 3. Single Asset / Polygon Risk Assessment
- **Method:** `POST`
- **Endpoint:** `/api/trade-oracle/assess`
- **Payload:**
```json
{
  "asset_id": "MINE-ID-MOROWALI",
  "lat": -2.82,
  "lng": 122.15,
  "asset_type": "MINE",
  "commodity": "NICKEL",
  "region_id": "SE_ASIA_SULAWESI",
  "canopy_loss_pct": 0.3,
  "use_live_feed": true
}
```

### 4. End-to-End Trade Route Assessment
- **Method:** `POST`
- **Endpoint:** `/api/trade-oracle/assess-route`
- **Payload:**
```json
{
  "waypoints": [
    {"asset_id": "MINE-CL-ATACAMA", "lat": -23.5, "lng": -68.25, "asset_type": "MINE", "commodity": "LITHIUM"},
    {"asset_id": "PORT-PA-PANAMA", "lat": 9.1, "lng": -79.92, "asset_type": "PORT", "commodity": "MARITIME_CORRIDOR"}
  ],
  "use_live_feed": true
}
```

### 5. Security Gate & EUDR Audit
- `GET /api/security-gate/status` — Circuit breaker & audit telemetry
- `POST /api/security-gate/trip-circuit-breaker` — Emergency kill-switch
- `POST /api/security-gate/reset-circuit-breaker` — Restore operational state
- `POST /api/security/eudr/audit` — Direct EUDR polygon compliance check
