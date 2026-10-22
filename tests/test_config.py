"""
Apex Scout - Config Tests
"""

import pytest
from config.settings import Settings, TakeProfitTierModel
from config.constants import DecisionAction, PositionStatus


class TestSettings:
    """Settings validation tests"""

    def test_valid_take_profit_tier(self):
        """Geçerli TP katmanı"""
        tier = TakeProfitTierModel(profit_pct=25.0, sell_pct=40.0)
        assert tier.profit_pct == 25.0
        assert tier.sell_pct == 40.0

    def test_invalid_take_profit_tier_negative(self):
        """Negatif değer hatası"""
        with pytest.raises(ValueError):
            TakeProfitTierModel(profit_pct=-10, sell_pct=40)

    def test_invalid_take_profit_tier_over_100(self):
        """100 üzeri değer hatası"""
        with pytest.raises(ValueError):
            TakeProfitTierModel(profit_pct=25, sell_pct=150)

    def test_settings_weights_sum(self):
        """Ağırlıklar toplamı 1.0 olmalı"""
        # Geçerli ağırlıklar
        settings = Settings(
            okx_api_key="test",
            okx_api_secret="test",
            okx_passphrase="test",
            okx_demo_trading=True,
            scoring_weights_liquidity=0.25,
            scoring_weights_volume=0.20,
            scoring_weights_age=0.15,
            scoring_weights_mcap=0.15,
            scoring_weights_mint_freeze=0.10,
            scoring_weights_holder_dist=0.15,
        )
        assert abs(sum(settings.scoring_weights_dict.values()) - 1.0) < 0.01

    def test_settings_invalid_weights(self):
        """Geçersiz ağırlıklar toplamı"""
        with pytest.raises(ValueError, match="toplamı 1.0 olmalı"):
            Settings(
                okx_api_key="test",
                okx_api_secret="test",
                okx_passphrase="test",
                okx_demo_trading=True,
                scoring_weights_liquidity=0.50,
                scoring_weights_volume=0.50,
                scoring_weights_age=0.15,
                scoring_weights_mcap=0.15,
                scoring_weights_mint_freeze=0.10,
                scoring_weights_holder_dist=0.15,
            )

    def test_take_profit_tiers_validation(self):
        """TP katmanları sıralama ve toplam kontrolü"""
        # Geçerli: artan profit_pct
        settings = Settings(
            okx_api_key="test",
            okx_api_secret="test",
            okx_passphrase="test",
            okx_demo_trading=True,
            take_profit_tiers=[
                {"profit_pct": 25, "sell_pct": 40},
                {"profit_pct": 45, "sell_pct": 40},
                {"profit_pct": 70, "sell_pct": 20},
            ],
        )
        assert len(settings.take_profit_tiers) == 3

    def test_take_profit_tiers_invalid_order(self):
        """TP katmanları sıralı olmalı"""
        with pytest.raises(ValueError, match="artan sırada"):
            Settings(
                okx_api_key="test",
                okx_api_secret="test",
                okx_passphrase="test",
                okx_demo_trading=True,
                take_profit_tiers=[
                    {"profit_pct": 45, "sell_pct": 40},
                    {"profit_pct": 25, "sell_pct": 40},  # Yanlış sıra
                ],
            )

    def test_take_profit_tiers_sell_pct_over_100(self):
        """TP sell_pct toplamı 100 geçemez"""
        with pytest.raises(ValueError, match="100'i geçemez"):
            Settings(
                okx_api_key="test",
                okx_api_secret="test",
                okx_passphrase="test",
                okx_demo_trading=True,
                take_profit_tiers=[
                    {"profit_pct": 25, "sell_pct": 60},
                    {"profit_pct": 45, "sell_pct": 60},
                ],
            )

    def test_demo_trading_required(self):
        """Demo trading zorunlu"""
        with pytest.raises(ValueError, match="OKX_DEMO_TRADING=true olmalı"):
            Settings(
                okx_api_key="test",
                okx_api_secret="test",
                okx_passphrase="test",
                okx_demo_trading=False,  # False olamaz
            )

    def test_scoring_weights_dict(self):
        """Weights dict property"""
        settings = Settings(
            okx_api_key="test",
            okx_api_secret="test",
            okx_passphrase="test",
            okx_demo_trading=True,
        )
        weights = settings.scoring_weights_dict
        assert "liquidity" in weights
        assert "volume" in weights
        assert len(weights) == 6

    def test_get_take_profit_tiers(self):
        """get_take_profit_tiers method"""
        settings = Settings(
            okx_api_key="test",
            okx_api_secret="test",
            okx_passphrase="test",
            okx_demo_trading=True,
        )
        tiers = settings.get_take_profit_tiers()
        assert isinstance(tiers, list)
        assert len(tiers) == 3
        assert all("profit_pct" in t and "sell_pct" in t for t in tiers)


class TestConstants:
    """Constants tests"""

    def test_decision_action_values(self):
        assert DecisionAction.PASS.value == "PASS"
        assert DecisionAction.WATCH.value == "WATCH"
        assert DecisionAction.SKIP.value == "SKIP"

    def test_position_status_values(self):
        assert PositionStatus.OPEN.value == "OPEN"
        assert PositionStatus.CLOSED.value == "CLOSED"
        assert PositionStatus.STOPPED_OUT.value == "STOPPED_OUT"

    def test_okx_demo_header(self):
        from config.constants import OKX_DEMO_HEADER, OKX_DEMO_VALUE
        assert OKX_DEMO_HEADER == "x-simulated-trading"
        assert OKX_DEMO_VALUE == "1"