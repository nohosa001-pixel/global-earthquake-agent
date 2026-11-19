"""
Security Gate for Trade-Enabling Seismic Hazard Oracle Subsystem
Provides institutional validation across:
1. Gate 0: USGS Seismic Feed Verification (Reviewed vs Automatic Divergence Guard)
2. Gate 1: EUDR (EU Deforestation Regulation) Satellite Geofence Compliance Audit
3. Gate 2: Emergency Circuit Breaker & Audit Trail
"""

import datetime
import uuid
from typing import Any, Dict, List, Optional, Tuple
from core.storage import OracleStateStore


class SeismicSecurityGate:
    """Validates seismic oracle feed quality, EUDR compliance, and emergency kill-switch state."""

    def __init__(self, max_audit_log: int = 40, state_store: Optional[OracleStateStore] = None):
        self.max_audit_log = max_audit_log
        self.state_store = state_store

        if self.state_store is not None:
            cb = self.state_store.get_circuit_breaker()
            self.circuit_breaker_active = cb["active"]
            self.circuit_breaker_reason = cb["reason"]
            self.circuit_breaker_tripped_at = cb["tripped_at"]
            self.audit_log = self.state_store.list_audits(limit=max_audit_log)
        else:
            self.circuit_breaker_active = False
            self.circuit_breaker_reason = ""
            self.circuit_breaker_tripped_at = None
            self.audit_log: List[Dict[str, Any]] = []

        self.total_blocked_actions = 0
        self.total_verified_actions = 0

    def trip_circuit_breaker(self, reason: str) -> None:
        """Immediately halts automated trade clearance approvals."""
        self.circuit_breaker_active = True
        self.circuit_breaker_reason = reason
        self.circuit_breaker_tripped_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if self.state_store is not None:
            self.state_store.set_circuit_breaker(True, reason, self.circuit_breaker_tripped_at)
        self._record_audit(
            action_type="CIRCUIT_BREAKER_TRIP",
            is_approved=False,
            risk_score=1.0,
            verdict=f"EMERGENCY KILL-SWITCH TRIPPED: {reason}",
            details={"reason": reason},
        )

    def reset_circuit_breaker(self, admin_key: str = "ADMIN_OVERRIDE") -> None:
        """Restores system to operational state after manual operator review."""
        self.circuit_breaker_active = False
        self.circuit_breaker_reason = ""
        self.circuit_breaker_tripped_at = None
        if self.state_store is not None:
            self.state_store.set_circuit_breaker(False, "", None)
        self._record_audit(
            action_type="CIRCUIT_BREAKER_RESET",
            is_approved=True,
            risk_score=0.0,
            verdict="System reset to normal operational status by operator override",
            details={"admin_key": admin_key},
        )

    def verify_seismic_consensus(
        self,
        asset_id: str,
        reviewed_ratio: float,
        events_count: int,
        peak_mmi: float,
        cross_verified_ratio: Optional[float] = None,
        max_mag_diff: float = 0.0,
    ) -> Tuple[bool, float, str]:
        """
        Gate 0: Validates whether seismic telemetry has sufficient USGS reviewed confirmation
        and multi-source (USGS + EMSC) agreement when high-impact shaking is detected.
        """
        if max_mag_diff > 0.6:
            verdict = f"REJECTED: Multi-source magnitude divergence (ΔM={max_mag_diff:.2f} > 0.60)"
            self._record_audit("SEISMIC_ORACLE", False, 0.90, verdict, {"asset_id": asset_id, "max_mag_diff": max_mag_diff})
            self.total_blocked_actions += 1
            return False, 0.90, verdict

        if peak_mmi >= 6.0 and events_count > 0 and reviewed_ratio < 0.5 and (cross_verified_ratio is None or cross_verified_ratio < 0.5):
            verdict = (
                f"REJECTED: High seismic impact (MMI {peak_mmi:.1f}) relies on unreviewed "
                f"automatic feeds without secondary confirmation (reviewed={reviewed_ratio:.0%})"
            )
            self._record_audit("SEISMIC_ORACLE", False, 0.85, verdict, {"asset_id": asset_id})
            self.total_blocked_actions += 1
            return False, 0.85, verdict

        cross_str = f", cross_verified={cross_verified_ratio:.0%}" if cross_verified_ratio is not None else ""
        verdict = f"PASSED: Seismic telemetry verified (events={events_count}, reviewed={reviewed_ratio:.0%}{cross_str})"
        self._record_audit("SEISMIC_ORACLE", True, 0.04, verdict, {"asset_id": asset_id})
        self.total_verified_actions += 1
        return True, 0.04, verdict

    def audit_eudr_compliance(
        self,
        region_id: str,
        farm_polygon_id: str,
        canopy_cover_loss_pct: float,
    ) -> Tuple[bool, float, str]:
        """
        Gate 1: EUDR (EU Deforestation Regulation) Satellite Geofence Audit.
        Verifies deforestation-free compliance (canopy loss <= 1.0% since Dec 2020).
        """
        if canopy_cover_loss_pct > 1.0:
            verdict = (
                f"REJECTED: EUDR Non-Compliant! Forest canopy loss "
                f"{canopy_cover_loss_pct:.2f}% exceeds 1.0% threshold"
            )
            self._record_audit(
                "EUDR_AUDIT",
                False,
                0.95,
                verdict,
                {"region_id": region_id, "polygon_id": farm_polygon_id, "canopy_loss_pct": canopy_cover_loss_pct},
            )
            self.total_blocked_actions += 1
            return False, 0.95, verdict

        verdict = f"PASSED: EUDR Compliant (Canopy loss {canopy_cover_loss_pct:.2f}% <= 1.0%)"
        self._record_audit(
            "EUDR_AUDIT",
            True,
            0.05,
            verdict,
            {"region_id": region_id, "polygon_id": farm_polygon_id},
        )
        self.total_verified_actions += 1
        return True, 0.05, verdict

    def _record_audit(
        self,
        action_type: str,
        is_approved: bool,
        risk_score: float,
        verdict: str,
        details: Dict[str, Any],
    ) -> None:
        record = {
            "audit_id": f"SEC-{str(uuid.uuid4())[:8].upper()}",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "action_type": action_type,
            "is_approved": is_approved,
            "risk_score": round(risk_score, 3),
            "verdict": verdict,
            "details": details,
        }
        self.audit_log.insert(0, record)
        if len(self.audit_log) > self.max_audit_log:
            self.audit_log.pop()
        if self.state_store is not None:
            self.state_store.save_audit(record)

    def get_security_status(self) -> Dict[str, Any]:
        return {
            "circuit_breaker_active": self.circuit_breaker_active,
            "circuit_breaker_reason": self.circuit_breaker_reason,
            "circuit_breaker_tripped_at": self.circuit_breaker_tripped_at,
            "total_verified_actions": self.total_verified_actions,
            "total_blocked_actions": self.total_blocked_actions,
            "recent_audits": self.audit_log[:12],
        }
