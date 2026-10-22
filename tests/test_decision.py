"""
Apex Scout - Decision Engine Tests
"""

import pytest
from datetime import datetime, timezone
from scanner.models import TokenData, TokenFilterCriteria
from config.constants import TokenSource, DecisionAction
from decision.criteria import ScoringCriteria
from decision.engine import DecisionEngine
from decision.models import DecisionResult


class TestScoringCriteria:
    """Scoring criteria tests"""

    @pytest.fixture
    def criteria(self):
        return ScoringCriteria()

    @pytest.fixture
    def sample_token(self):
        return TokenData(
            address="So11111111111111111111111111111111111111112",
            name="Test Token",
            symbol="TEST",
            price_usd=0.001,
            liquidity_usd=25000,
            market_cap=50000,
            volume_24h=15000,
            age_seconds=1800,  # 30 min
            mint_authority="",
            freeze_authority="",
            mint_renounced=True,
            freeze_renounced=True,
            holder_count=500,
            top_10_holder_pct=25.0,
            source=TokenSource.DEXSCREENER,
        )

    def test_score_liquidity(self, criteria, sample_token):
        """Likidite skoru"""
        score = criteria._score_liquidity(sample_token)
        assert 0 <= score <= 100
        # 25k likidite -> ~50 puan
        assert 40 < score < 60

    def test_score_volume(self, criteria, sample_token):
        """Hacim skoru"""
        score = criteria._score_volume(sample_token)
        assert 0 <= score <= 100
        # 15k/25k = 0.6 ratio -> ~20-40 puan
        assert score > 0

    def test_score_age(self, criteria, sample_token):
        """Yaş skoru"""
        score = criteria._score_age(sample_token)
        assert 0 <= score <= 100
        # 30 min -> 90 puan
        assert score >= 90

    def test_score_mcap(self, criteria, sample_token):
        """Market cap skoru"""
        score = criteria._score_mcap(sample_token)
        assert 0 <= score <= 100
        # 50k -> sweet spot, yüksek skor
        assert score >= 80

    def test_score_mint_freeze(self, criteria, sample_token):
        """Mint/Freeze skoru"""
        # sample_token'da mint_authority ve freeze_authority None olduğu için
        # kod nötr (50.0) döndürür
        # Test token'ını düzgün ayarla
        sample_token.mint_authority = ""
        sample_token.freeze_authority = ""
        sample_token.mint_renounced = True
        sample_token.freeze_renounced = True
        score = criteria._score_mint_freeze(sample_token)
        assert score == 100.0  # Her ikisi de renounced

    def test_score_mint_freeze_unknown_is_neutral(self, criteria):
        """Mint/Freeze bilgisi yoksa nötr (50) puan - 0 değil"""
        token = TokenData(
            address="So11111111111111111111111111111111111111112",
            name="Unknown",
            symbol="UNK",
            mint_authority=None,
            freeze_authority=None,
            source=TokenSource.DEXSCREENER,
        )
        score = criteria._score_mint_freeze(token)
        assert score == 50.0, "Bilinmiyor bilgi tehlikeli gibi puanlanmamalı"

    def test_score_mint_freeze_pumpfun_assumed_renounced(self, criteria):
        """Pump.fun token'larında 80 (genelde renounced)"""
        token = TokenData(
            address="So11111111111111111111111111111111111111112",
            name="Pump",
            symbol="PUMP",
            mint_authority=None,
            freeze_authority=None,
            source=TokenSource.PUMPFUN,
        )
        score = criteria._score_mint_freeze(token)
        assert score == 80.0

    def test_score_volume_unknown_is_neutral(self, criteria):
        """Hacim bilgisi yoksa (Pump.fun) nötr (50) puan - 0 değil"""
        token = TokenData(
            address="So11111111111111111111111111111111111111112",
            name="NoVol",
            symbol="NOVOL",
            liquidity_usd=50000,
            volume_24h=0,  # bilgi yok
            source=TokenSource.PUMPFUN,
        )
        score = criteria._score_volume(token)
        assert score == 50.0, "Hacim bilgisi yoksa token haksız yere elenmemeli"

    def test_score_volume_real_low_is_zero(self, criteria):
        """Gerçek düşük hacim 0 puan alır (bilgi yok ile karıştırılmamalı)"""
        token = TokenData(
            address="So11111111111111111111111111111111111111112",
            name="LowVol",
            symbol="LOWVOL",
            liquidity_usd=100000,
            volume_24h=1000,  # ratio = 0.01 -> gerçek düşük
            source=TokenSource.DEXSCREENER,
        )
        score = criteria._score_volume(token)
        assert score == 0.0

    def test_score_mint_freeze_not_renounced(self, criteria):
        """Mint/Freeze renounced değil"""
        token = TokenData(
            address="So11111111111111111111111111111111111111112",
            name="Test",
            symbol="TEST",
            mint_renounced=False,
            freeze_renounced=False,
            mint_authority="auth123",
            freeze_authority="auth123",
            source=TokenSource.DEXSCREENER,
        )
        score = criteria._score_mint_freeze(token)
        assert score == 0.0

    def test_score_holder_dist(self, criteria, sample_token):
        """Holder dağılımı skoru"""
        score = criteria._score_holder_dist(sample_token)
        assert 0 <= score <= 100
        # Top 10 = 25% -> 60 puan
        assert 50 < score < 70

    def test_calculate_score(self, criteria, sample_token):
        """Toplu skor hesaplama"""
        breakdown = criteria.calculate_score(sample_token)
        assert isinstance(breakdown.liquidity, float)
        assert isinstance(breakdown.volume, float)
        assert isinstance(breakdown.age, float)
        assert isinstance(breakdown.mcap, float)
        assert isinstance(breakdown.mint_freeze, float)
        assert isinstance(breakdown.holder_dist, float)

    def test_get_total_score(self, criteria, sample_token):
        """Ağırlıklı toplam skor"""
        breakdown = criteria.calculate_score(sample_token)
        total = criteria.get_total_score(breakdown)
        assert 0 <= total <= 100
        # Bu token'un skoru ~58.6 (volume ratio düşük)
        assert total > 55


class TestDecisionEngine:
    """Decision engine tests"""

    @pytest.fixture
    def engine(self):
        return DecisionEngine(min_score_to_trade=70, watch_threshold=50)

    @pytest.fixture
    def good_token(self):
        return TokenData(
            address="So11111111111111111111111111111111111111112",
            name="Good Token",
            symbol="GOOD",
            price_usd=0.001,
            liquidity_usd=50000,
            market_cap=100000,
            volume_24h=50000,
            age_seconds=900,  # 15 min
            mint_renounced=True,
            freeze_renounced=True,
            holder_count=1000,
            top_10_holder_pct=15.0,
            source=TokenSource.DEXSCREENER,
        )

    @pytest.fixture
    def bad_token(self):
        return TokenData(
            address="So11111111111111111111111111111111111111113",
            name="Bad Token",
            symbol="BAD",
            price_usd=0.000001,
            liquidity_usd=1000,  # Minimum altı
            market_cap=500,
            volume_24h=100,
            age_seconds=7200,  # 2 saat
            mint_renounced=False,
            freeze_renounced=False,
            holder_count=5,
            top_10_holder_pct=80.0,
            source=TokenSource.DEXSCREENER,
        )

    def test_evaluate_good_token(self, engine, good_token):
        """İyi token PASS almalı"""
        result = engine.evaluate(good_token)
        assert isinstance(result, DecisionResult)
        assert result.action == DecisionAction.PASS
        assert result.score >= 70
        assert len(result.reasons) > 0

    def test_evaluate_bad_token(self, engine, bad_token):
        """Kötü token SKIP almalı"""
        result = engine.evaluate(bad_token)
        assert result.action == DecisionAction.SKIP
        assert result.score < 50

    def test_evaluate_batch(self, engine, good_token, bad_token):
        """Toplu değerlendirme"""
        batch = engine.evaluate_batch([good_token, bad_token])
        assert batch.pass_count == 1
        assert batch.skip_count == 1
        assert batch.watch_count == 0

    def test_critical_issues_override(self, engine):
        """Kritik sorun PASS'i SKIP'e çevirmeli"""
        # Skor yüksek (PASS) ama likidite minimumun altında
        token = TokenData(
            address="So11111111111111111111111111111111111111114",
            name="Critical Token",
            symbol="CRIT",
            price_usd=0.01,
            liquidity_usd=1000,  # 5000 min altı
            market_cap=200000,   # Yüksek MCAP için yüksek skor
            volume_24h=100000,   # Yüksek volume
            age_seconds=300,     # Çok yeni (5 dk)
            mint_authority="",
            freeze_authority="",
            mint_renounced=True,
            freeze_renounced=True,
            holder_count=2000,
            top_10_holder_pct=10.0,
            source=TokenSource.DEXSCREENER,
        )
        result = engine.evaluate(token)
        # Skor yüksek olabilir (PASS) ama kritik likidite hatası -> SKIP
        assert result.action == DecisionAction.SKIP
        assert any("Kritik" in r for r in result.reasons)