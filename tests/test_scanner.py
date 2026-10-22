"""
Apex Scout - Scanner Filter Tests
"""

import pytest
from datetime import datetime, timezone
from scanner.models import TokenData, TokenFilterCriteria
from scanner.filters import TokenFilter
from config.constants import TokenSource


class TestTokenFilterCriteria:
    """Token filter criteria tests"""

    @pytest.fixture
    def criteria(self):
        return TokenFilterCriteria(
            min_liquidity_usd=5000,
            max_age_hours=2,
            min_volume_24h=1000,
            min_holder_count=10,
            max_top_10_holder_pct=80.0,
        )

    @pytest.fixture
    def good_token(self):
        return TokenData(
            address="So11111111111111111111111111111111111111112",
            name="Good Token",
            symbol="GOOD",
            price_usd=0.001,
            liquidity_usd=25000,
            market_cap=50000,
            volume_24h=15000,
            age_seconds=3600,  # 1 hour
            mint_renounced=True,
            freeze_renounced=True,
            holder_count=500,
            top_10_holder_pct=25.0,
            source=TokenSource.DEXSCREENER,
        )

    @pytest.fixture
    def bad_liquidity_token(self):
        return TokenData(
            address="So11111111111111111111111111111111111111113",
            name="Low Liquidity",
            symbol="LOWL",
            price_usd=0.001,
            liquidity_usd=1000,  # Below minimum
            market_cap=50000,
            volume_24h=15000,
            age_seconds=3600,
            mint_renounced=True,
            freeze_renounced=True,
            holder_count=500,
            top_10_holder_pct=25.0,
            source=TokenSource.DEXSCREENER,
        )

    @pytest.fixture
    def old_token(self):
        return TokenData(
            address="So11111111111111111111111111111111111111114",
            name="Old Token",
            symbol="OLD",
            price_usd=0.001,
            liquidity_usd=25000,
            market_cap=50000,
            volume_24h=15000,
            age_seconds=10800,  # 3 hours > 2h max
            mint_renounced=True,
            freeze_renounced=True,
            holder_count=500,
            top_10_holder_pct=25.0,
            source=TokenSource.DEXSCREENER,
        )

    def test_check_good_token(self, criteria, good_token):
        """İyi token geçmeli"""
        passed, reasons = criteria.check(good_token)
        assert passed is True
        assert len(reasons) == 0

    def test_check_low_liquidity(self, criteria, bad_liquidity_token):
        """Düşük likidite reddedilmeli"""
        passed, reasons = criteria.check(bad_liquidity_token)
        assert passed is False
        assert any("Likidite çok düşük" in r for r in reasons)

    def test_check_old_token(self, criteria, old_token):
        """Eski token reddedilmeli"""
        passed, reasons = criteria.check(old_token)
        assert passed is False
        assert any("Token çok eski" in r for r in reasons)

    def test_check_low_volume(self, criteria):
        """Düşük hacim reddedilmeli"""
        token = TokenData(
            address="So11111111111111111111111111111111111111115",
            name="Low Vol",
            symbol="LOWV",
            price_usd=0.001,
            liquidity_usd=25000,
            market_cap=50000,
            volume_24h=100,  # Below minimum
            age_seconds=3600,
            mint_renounced=True,
            freeze_renounced=True,
            holder_count=500,
            top_10_holder_pct=25.0,
            source=TokenSource.DEXSCREENER,
        )
        passed, reasons = criteria.check(token)
        assert passed is False
        assert any("Hacim çok düşük" in r for r in reasons)

    def test_check_low_holders(self, criteria):
        """Az holder reddedilmeli"""
        token = TokenData(
            address="So11111111111111111111111111111111111111116",
            name="Low Holders",
            symbol="LOWH",
            price_usd=0.001,
            liquidity_usd=25000,
            market_cap=50000,
            volume_24h=15000,
            age_seconds=3600,
            mint_renounced=True,
            freeze_renounced=True,
            holder_count=5,  # Below minimum
            top_10_holder_pct=25.0,
            source=TokenSource.DEXSCREENER,
        )
        passed, reasons = criteria.check(token)
        assert passed is False
        assert any("Holder sayısı az" in r for r in reasons)

    def test_check_concentrated_holders(self, criteria):
        """Konsantre holder reddedilmeli"""
        token = TokenData(
            address="So11111111111111111111111111111111111111117",
            name="Concentrated",
            symbol="CONC",
            price_usd=0.001,
            liquidity_usd=25000,
            market_cap=50000,
            volume_24h=15000,
            age_seconds=3600,
            mint_renounced=True,
            freeze_renounced=True,
            holder_count=500,
            top_10_holder_pct=90.0,  # Above maximum
            source=TokenSource.DEXSCREENER,
        )
        passed, reasons = criteria.check(token)
        assert passed is False
        assert any("Top 10 holder çok yoğun" in r for r in reasons)

    def test_excluded_symbols(self, criteria):
        """Dışlanmış semboller"""
        criteria.excluded_symbols = ["SCAM", "RUG"]
        token = TokenData(
            address="So11111111111111111111111111111111111111118",
            name="Scam Token",
            symbol="SCAM",
            price_usd=0.001,
            liquidity_usd=25000,
            market_cap=50000,
            volume_24h=15000,
            age_seconds=3600,
            mint_renounced=True,
            freeze_renounced=True,
            holder_count=500,
            top_10_holder_pct=25.0,
            source=TokenSource.DEXSCREENER,
        )
        passed, reasons = criteria.check(token)
        assert passed is False
        assert any("Sembol dışlanmış" in r for r in reasons)

    def test_excluded_addresses(self, criteria):
        """Dışlanmış adresler"""
        criteria.excluded_addresses = ["So11111111111111111111111111111111111111119"]
        token = TokenData(
            address="So11111111111111111111111111111111111111119",
            name="Blacklisted",
            symbol="BLACK",
            price_usd=0.001,
            liquidity_usd=25000,
            market_cap=50000,
            volume_24h=15000,
            age_seconds=3600,
            mint_renounced=True,
            freeze_renounced=True,
            holder_count=500,
            top_10_holder_pct=25.0,
            source=TokenSource.DEXSCREENER,
        )
        passed, reasons = criteria.check(token)
        assert passed is False
        assert any("Adres blacklist" in r for r in reasons)


class TestTokenFilter:
    """TokenFilter integration tests"""

    @pytest.fixture
    def token_filter(self):
        return TokenFilter()

    def test_filter_tokens_empty(self, token_filter):
        """Boş liste"""
        result = token_filter.filter_tokens([])
        assert result == []

    def test_filter_tokens_mixed(self, token_filter):
        """Karma liste filtreleme"""
        tokens = [
            TokenData(
                address="So11111111111111111111111111111111111111112",
                name="Good",
                symbol="GOOD",
                price_usd=0.001,
                liquidity_usd=25000,
                market_cap=50000,
                volume_24h=15000,
                age_seconds=3600,
                mint_renounced=True,
                freeze_renounced=True,
                holder_count=500,
                top_10_holder_pct=25.0,
                source=TokenSource.DEXSCREENER,
            ),
            TokenData(
                address="So11111111111111111111111111111111111111113",
                name="Bad",
                symbol="BAD",
                price_usd=0.001,
                liquidity_usd=1000,
                market_cap=50000,
                volume_24h=15000,
                age_seconds=3600,
                mint_renounced=True,
                freeze_renounced=True,
                holder_count=500,
                top_10_holder_pct=25.0,
                source=TokenSource.DEXSCREENER,
            ),
        ]
        result = token_filter.filter_tokens(tokens)
        assert len(result) == 1
        assert result[0].symbol == "GOOD"

    def test_check_token(self, token_filter):
        """Tek token kontrolü"""
        token = TokenData(
            address="So11111111111111111111111111111111111111112",
            name="Good",
            symbol="GOOD",
            price_usd=0.001,
            liquidity_usd=25000,
            market_cap=50000,
            volume_24h=15000,
            age_seconds=3600,
            mint_renounced=True,
            freeze_renounced=True,
            holder_count=500,
            top_10_holder_pct=25.0,
            source=TokenSource.DEXSCREENER,
        )
        passed, reasons = token_filter.check_token(token)
        assert passed is True
        assert len(reasons) == 0
