"""
Apex Scout - Decision Engine
Token'ları skorlar, PASS/WATCH/SKIP kararı verir.
"""

import time
from typing import List, Optional
from datetime import datetime

from shared.logger import get_logger
from shared.exceptions import DecisionError
from config.settings import settings
from config.constants import DecisionAction
from scanner.models import TokenData
from decision.criteria import ScoringCriteria
from decision.models import DecisionResult, DecisionBatch, ScoreBreakdown

log = get_logger(__name__)


class DecisionEngine:
    """
    Jev-style karar motoru.
    Token'ları 0-100 skorlar, eşik değerlere göre aksiyon belirler.
    """

    def __init__(
        self,
        min_score_to_trade: int = None,
        watch_threshold: int = None,
        scoring_criteria: Optional[ScoringCriteria] = None,
    ):
        self.min_score_to_trade = min_score_to_trade or settings.min_score_to_trade
        self.watch_threshold = watch_threshold or settings.watch_threshold
        self.criteria = scoring_criteria or ScoringCriteria()
        self.decision_count = 0

    def evaluate(self, token: TokenData) -> DecisionResult:
        """
        Tek bir token'ı değerlendir.
        """
        start = time.perf_counter()

        try:
            # 1. Skor bileşenlerini hesapla
            breakdown = self.criteria.calculate_score(token)

            # 2. Ağırlıklı toplam skor
            total_score = self.criteria.get_total_score(breakdown)
            total_score = round(max(0.0, min(100.0, total_score)), 2)

            # 3. Aksiyon belirle
            action, reasons = self._determine_action(token, total_score, breakdown)

            # 4. Sonuç oluştur
            result = DecisionResult(
                token=token,
                score=total_score,
                action=action,
                breakdown=breakdown,
                reasons=reasons,
                timestamp=datetime.utcnow(),
            )

            self.decision_count += 1
            elapsed_ms = (time.perf_counter() - start) * 1000
            log.debug(f"[Decision] {token.symbol}: {action.value} ({total_score:.1f}) in {elapsed_ms:.1f}ms")

            return result

        except Exception as e:
            log.error(f"[Decision] Evaluation error for {token.symbol}: {e}")
            raise DecisionError(f"Decision failed for {token.symbol}", {"error": str(e)}) from e

    def evaluate_batch(self, tokens: List[TokenData]) -> DecisionBatch:
        """
        Token listesi değerlendir.
        """
        start = time.perf_counter()
        results = []

        for token in tokens:
            try:
                result = self.evaluate(token)
                results.append(result)
            except DecisionError:
                # Hatalı token'ı atla, SKIP olarak ekle
                results.append(DecisionResult(
                    token=token,
                    score=0.0,
                    action=DecisionAction.SKIP,
                    reasons=["Evaluation error"],
                ))

        elapsed_ms = (time.perf_counter() - start) * 1000

        batch = DecisionBatch(
            results=results,
            scan_duration_ms=elapsed_ms,
            timestamp=datetime.utcnow(),
        )

        log.info(
            f"[Decision] Batch complete: "
            f"PASS={batch.pass_count}, WATCH={batch.watch_count}, SKIP={batch.skip_count} "
            f"in {elapsed_ms:.1f}ms"
        )

        return batch

    def _determine_action(
        self,
        token: TokenData,
        score: float,
        breakdown: ScoreBreakdown
    ) -> tuple[DecisionAction, List[str]]:
        """
        Skora ve bileşenlere göre aksiyon belirle.
        """
        reasons = []

        # Temel eşik kontrolleri
        if score >= self.min_score_to_trade:
            action = DecisionAction.PASS
            reasons.append(f"Skor ≥ {self.min_score_to_trade} ({score:.1f})")
        elif score >= self.watch_threshold:
            action = DecisionAction.WATCH
            reasons.append(f"Skor ≥ {self.watch_threshold} ({score:.1f}) - İzleme modu")
        else:
            action = DecisionAction.SKIP
            reasons.append(f"Skor < {self.watch_threshold} ({score:.1f})")

        # Detaylı nedenler ekle
        self._add_detailed_reasons(token, breakdown, reasons)

        # Kritik red nedenleri (PASS olsa bile)
        if action == DecisionAction.PASS:
            critical_issues = self._check_critical_issues(token)
            if critical_issues:
                action = DecisionAction.SKIP
                reasons = critical_issues  # Override reasons

        return action, reasons

    def _add_detailed_reasons(self, token: TokenData, breakdown: ScoreBreakdown, reasons: List[str]):
        """Detaylı skor nedenlerini ekle"""
        # Güçlü yönler
        if breakdown.liquidity >= 70:
            reasons.append(f"Güçlü likidite: ${token.liquidity_usd:,.0f}")
        if breakdown.volume >= 70:
            reasons.append(f"Yüksek hacim/likidite oranı")
        if breakdown.age >= 70:
            reasons.append(f"Yeni token ({token.age_seconds/60:.0f} dk)")
        if breakdown.mcap >= 70:
            reasons.append(f"İdeal market cap: ${token.market_cap:,.0f}")
        if breakdown.mint_freeze >= 70:
            reasons.append("Mint/Freeze yetkileri terk edilmiş")
        if breakdown.holder_dist >= 70:
            reasons.append(f"Sağlıklı holder dağılımı (%{token.top_10_holder_pct:.0f} top10)")

        # Zayıf yönler
        if breakdown.liquidity < 30:
            reasons.append(f"Düşük likidite: ${token.liquidity_usd:,.0f}")
        if breakdown.volume < 30:
            reasons.append("Düşük hacim aktivitesi")
        if breakdown.age < 30:
            reasons.append(f"Token yaşlı ({token.age_seconds/3600:.1f} saat)")
        if breakdown.mcap < 30:
            reasons.append(f"Riskli market cap: ${token.market_cap:,.0f}")
        if breakdown.mint_freeze < 30:
            reasons.append("Mint/Freeze yetkileri aktif (rug riski)")
        if breakdown.holder_dist < 30:
            reasons.append(f"Konsantre holder dağılımı (%{token.top_10_holder_pct:.0f} top10)")

    def _check_critical_issues(self, token: TokenData) -> List[str]:
        """
        PASS skoru alsa bile engelleyen kritik sorunlar.
        Returns: Boş liste = sorun yok, dolu = SKIP nedenleri

        NOT: "bilgi yok" değerleri (0) kritik sayılmaz.
        Pump.fun hacim/holder bilgisi vermez, DexScreener da vermez.
        """
        issues = []
        from config.constants import TokenSource

        # Likidite minimum altındaysa (config'de zaten filtrelenmeli ama double-check)
        if token.liquidity_usd < settings.min_liquidity_usd:
            issues.append(f"Kritik: Likidite minimumun altına düştü (${token.liquidity_usd:,.0f})")

        # Yaş limiti aşıldıysa
        age_hours = token.age_seconds / 3600
        if age_hours > settings.max_token_age_hours:
            issues.append(f"Kritik: Token yaşı limit aşıldı ({age_hours:.1f}h)")

        # Hacim minimum altındaysa - ANCAK hacim bilgisi varsa
        if token.volume_24h > 0 and token.volume_24h < settings.min_volume_24h:
            issues.append(f"Kritik: Hacim minimumun altındaydı (${token.volume_24h:,.0f})")

        # Mint/Freeze her ikisi de aktif ve renounced değilse
        if not token.mint_renounced and not token.freeze_renounced:
            # Sadece bilgi varsa kritik say (bilgi yoksa nötr)
            if token.mint_authority or token.freeze_authority:
                issues.append("Kritik: Hem mint hem freeze yetkisi aktif")

        return issues

    def get_stats(self) -> dict:
        return {
            "total_decisions": self.decision_count,
            "min_score_to_trade": self.min_score_to_trade,
            "watch_threshold": self.watch_threshold,
            "weights": self.criteria.weights,
        }