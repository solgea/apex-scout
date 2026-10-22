"""
Apex Scout - Skorlama Kriterleri
Her kriter 0-100 arası skor verir, ağırlıklı toplam alınır.
"""

from typing import Dict, Optional
from config.settings import settings
from scanner.models import TokenData
from decision.models import ScoreBreakdown


class ScoringCriteria:
    """
    Jev-style skorlama kriterleri.
    Her alt kriter 0-100 arası normalize skor verir.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or settings.scoring_weights_dict
        self._validate_weights()

    def _validate_weights(self):
        """Ağırlıkları doğrula"""
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Skor ağırlıkları toplamı 1.0 olmalı, şu an: {total:.3f}")

    def calculate_score(self, token: TokenData) -> ScoreBreakdown:
        """
        Token için tüm kriterleri hesapla ve ScoreBreakdown döndür.
        """
        breakdown = ScoreBreakdown(
            liquidity=self._score_liquidity(token),
            volume=self._score_volume(token),
            age=self._score_age(token),
            mcap=self._score_mcap(token),
            mint_freeze=self._score_mint_freeze(token),
            holder_dist=self._score_holder_dist(token),
        )
        return breakdown

    def get_total_score(self, breakdown: ScoreBreakdown) -> float:
        """Ağırlıklı toplam skoru hesapla"""
        return breakdown.total(self.weights)

    # ============ INDIVIDUAL SCORING FUNCTIONS ============

    def _score_liquidity(self, token: TokenData) -> float:
        """
        Likidite skoru (0-100):
        - $5k: 0
        - $10k: 20
        - $25k: 50
        - $50k: 75
        - $100k+: 100
        """
        liq = token.liquidity_usd
        if liq < 5_000:
            return 0.0
        elif liq < 10_000:
            return 20.0
        elif liq < 25_000:
            return 20 + 30 * (liq - 10_000) / 15_000
        elif liq < 50_000:
            return 50 + 25 * (liq - 25_000) / 25_000
        elif liq < 100_000:
            return 75 + 25 * (liq - 50_000) / 50_000
        else:
            return 100.0

    def _score_volume(self, token: TokenData) -> float:
        """
        24h Hacim skoru (0-100):
        Likiditeye göre normalize edilir.
        Volume/Liquidity oranı:
        - < 0.5: 0
        - 1.0: 40
        - 2.0: 70
        - 5.0+: 100

        NOT: volume_24h == 0 => "bilgi yok" (Pump.fun hacim vermez).
        Bilgi yok 0 puan DEĞİLDİR - nötr (50) puan verilir.
        """
        if token.liquidity_usd <= 0:
            return 0.0

        # Hacim bilgisi yok -> nötr skor (token'lar haksız yere elenmesin)
        if token.volume_24h <= 0:
            return 50.0

        vol_liq_ratio = token.volume_24h / token.liquidity_usd

        if vol_liq_ratio < 0.5:
            return 0.0
        elif vol_liq_ratio < 1.0:
            return 40 * (vol_liq_ratio - 0.5) / 0.5
        elif vol_liq_ratio < 2.0:
            return 40 + 30 * (vol_liq_ratio - 1.0) / 1.0
        elif vol_liq_ratio < 5.0:
            return 70 + 30 * (vol_liq_ratio - 2.0) / 3.0
        else:
            return 100.0

    def _score_age(self, token: TokenData) -> float:
        """
        Token yaşı skoru (0-100):
        Yeni token'lar avantajlı (momentum için).
        - 0-15 min: 100
        - 30 min: 90
        - 1 hour: 75
        - 2 hours: 50
        - 4 hours: 25
        - 8+ hours: 0
        """
        age_hours = token.age_seconds / 3600

        if age_hours <= 0.25:  # 15 min
            return 100.0
        elif age_hours <= 0.5:  # 30 min
            return 90.0
        elif age_hours <= 1.0:  # 1 hour
            return 75.0
        elif age_hours <= 2.0:  # 2 hours
            return 50.0
        elif age_hours <= 4.0:  # 4 hours
            return 25.0
        elif age_hours <= 8.0:  # 8 hours
            return 10.0
        else:
            return 0.0

    def _score_mcap(self, token: TokenData) -> float:
        """
        Market Cap skoru (0-100):
        Çok düşük = risky, çok yüksek = pump sonrası olabilir.
        Sweet spot: $10k - $500k
        - < $1k: 0
        - $5k: 20
        - $10k: 50
        - $50k: 80
        - $100k: 100
        - $500k: 80
        - $1M: 50
        - $5M+: 20
        """
        mcap = token.market_cap

        if mcap < 1_000:
            return 0.0
        elif mcap < 5_000:
            return 20.0
        elif mcap < 10_000:
            return 20 + 30 * (mcap - 5_000) / 5_000
        elif mcap < 50_000:
            return 50 + 30 * (mcap - 10_000) / 40_000
        elif mcap < 100_000:
            return 80 + 20 * (mcap - 50_000) / 50_000
        elif mcap < 500_000:
            return 100 - 20 * (mcap - 100_000) / 400_000
        elif mcap < 1_000_000:
            return 80 - 30 * (mcap - 500_000) / 500_000
        elif mcap < 5_000_000:
            return 50 - 30 * (mcap - 1_000_000) / 4_000_000
        else:
            return max(20.0, 20 - 10 * (mcap - 5_000_000) / 5_000_000)

    def _score_mint_freeze(self, token: TokenData) -> float:
        """
        Mint/Freeze authority skoru (0-100):
        - Her ikisi de renounced: 100
        - Sadece mint renounced: 70
        - Sadece freeze renounced: 50
        - Hiçbiri: 0
        - Bilgi yok: 50 (nötr - bilinmiyor ≠ tehlikeli)
        """
        mint_renounced = token.mint_renounced
        freeze_renounced = token.freeze_renounced

        # Bilgi yoksa (None/False varsayılan)
        if token.mint_authority is None and token.freeze_authority is None:
            # Pump.fun token'lar genelde renounced
            if token.source.value == "pumpfun":
                return 80.0
            # DexScreener holder/mint bilgisi vermez -> nötr skor
            return 50.0

        if mint_renounced and freeze_renounced:
            return 100.0
        elif mint_renounced:
            return 70.0
        elif freeze_renounced:
            return 50.0
        else:
            return 0.0

    def _score_holder_dist(self, token: TokenData) -> float:
        """
        Holder dağılımı skoru (0-100):
        Top 10 holder yüzdesi:
        - < 10%: 100 (çok dağıtık)
        - 20%: 80
        - 30%: 60
        - 40%: 40
        - 50%: 20
        - > 60%: 0 (çok konsantre)
        """
        pct = token.top_10_holder_pct

        if pct <= 0:
            return 50.0  # Veri yoksa orta

        if pct <= 10:
            return 100.0
        elif pct <= 20:
            return 80.0
        elif pct <= 30:
            return 60.0
        elif pct <= 40:
            return 40.0
        elif pct <= 50:
            return 20.0
        elif pct <= 60:
            return 10.0
        else:
            return 0.0