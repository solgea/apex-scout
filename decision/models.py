"""
Apex Scout - Decision Modelleri (Pydantic)
Karar motoru girdi/çıktı modelleri.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime
from config.constants import DecisionAction
from scanner.models import TokenData


class ScoreBreakdown(BaseModel):
    """Skor bileşenleri detayı"""

    liquidity: float = Field(default=0.0, ge=0, le=100, description="Likidite skoru (0-100)")
    volume: float = Field(default=0.0, ge=0, le=100, description="Hacim skoru (0-100)")
    age: float = Field(default=0.0, ge=0, le=100, description="Yaş skoru (0-100)")
    mcap: float = Field(default=0.0, ge=0, le=100, description="Market cap skoru (0-100)")
    mint_freeze: float = Field(default=0.0, ge=0, le=100, description="Mint/Freeze skoru (0-100)")
    holder_dist: float = Field(
        default=0.0, ge=0, le=100, description="Holder dağılımı skoru (0-100)"
    )

    def total(self, weights: Dict[str, float]) -> float:
        """Ağırlıklı toplam skor"""
        return (
            self.liquidity * weights.get("liquidity", 0)
            + self.volume * weights.get("volume", 0)
            + self.age * weights.get("age", 0)
            + self.mcap * weights.get("mcap", 0)
            + self.mint_freeze * weights.get("mint_freeze", 0)
            + self.holder_dist * weights.get("holder_dist", 0)
        )


class DecisionResult(BaseModel):
    """Karar motoru sonucu"""

    token: TokenData
    score: float = Field(default=0.0, ge=0, le=100, description="Toplam skor (0-100)")
    action: DecisionAction = Field(default=DecisionAction.SKIP, description="PASS/WATCH/SKIP")
    breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    reasons: List[str] = Field(default_factory=list, description="Karar nedenleri")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Dict'e çevir"""
        return {
            "token": self.token.to_dict(),
            "score": round(self.score, 2),
            "action": self.action.value,
            "breakdown": self.breakdown.model_dump(),
            "reasons": self.reasons,
            "timestamp": self.timestamp.isoformat(),
        }

    def __str__(self) -> str:
        return f"Decision({self.token.symbol}: {self.action.value} | Score: {self.score:.1f})"


class DecisionBatch(BaseModel):
    """Toplu karar sonucu"""

    results: List[DecisionResult] = Field(default_factory=list)
    scan_duration_ms: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.action == DecisionAction.PASS)

    @property
    def watch_count(self) -> int:
        return sum(1 for r in self.results if r.action == DecisionAction.WATCH)

    @property
    def skip_count(self) -> int:
        return sum(1 for r in self.results if r.action == DecisionAction.SKIP)

    def get_pass_tokens(self) -> List[TokenData]:
        return [r.token for r in self.results if r.action == DecisionAction.PASS]
