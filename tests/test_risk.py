"""
Apex Scout - Risk Manager Tests
"""

import pytest

from config.constants import OrderSide, PositionStatus
from trading.models import Position
from trading.risk_manager import RiskManager, TPTier


class TestRiskManager:
    """Risk manager tests"""

    @pytest.fixture
    def risk_manager(self):
        return RiskManager()

    def test_calculate_position_size(self, risk_manager):
        """Pozisyon boyutu hesaplama"""
        qty, value = risk_manager.calculate_position_size(1000.0, 0.001)
        # 1000 * 10% = 100 USD / 0.001 = 100,000 token
        assert value == 100.0
        assert qty == 100000.0

    def test_calculate_position_size_min(self, risk_manager):
        """Minimum pozisyon boyutu"""
        qty, value = risk_manager.calculate_position_size(50.0, 0.001)
        # 50 * 10% = 5 USD < 10 min -> 10 USD kullan
        assert value == 10.0
        assert qty == 10000.0

    def test_check_position_size_ok(self, risk_manager):
        """Pozisyon boyutu kontrolü - OK"""
        result = risk_manager.check_position_size(50.0, 1000.0)
        assert result.allowed is True

    def test_check_position_size_exceed(self, risk_manager):
        """Pozisyon boyutu kontrolü - Aşım"""
        # 1000 * 10% * 1.1 = 110 max, 200 verildi
        result = risk_manager.check_position_size(200.0, 1000.0)
        assert result.allowed is False
        assert abs(result.max_size_usd - 110.0) < 0.01

    def test_check_portfolio_risk_ok(self, risk_manager):
        """Portföy risk kontrolü - OK"""
        positions = []
        result = risk_manager.check_portfolio_risk(positions, 100.0, 1000.0)
        # 100/1000 = 10% < 35%
        assert result.allowed is True

    def test_check_portfolio_risk_exceed(self, risk_manager):
        """Portföy risk kontrolü - Aşım"""

        # Mevcut pozisyonlar 300 USD, yeni 100 USD = 400/1000 = 40% > 35%
        class MockPos:
            entry_value_usd = 300.0
            status = "OPEN"

        positions = [MockPos()]
        result = risk_manager.check_portfolio_risk(positions, 100.0, 1000.0)
        assert result.allowed is False

    def test_check_max_positions_ok(self, risk_manager):
        """Max pozisyon kontrolü - OK"""
        positions = [type("P", (), {"status": "OPEN"})() for _ in range(3)]
        result = risk_manager.check_max_positions(positions)
        assert result.allowed is True

    def test_check_max_positions_exceed(self, risk_manager):
        """Max pozisyon kontrolü - Aşım"""
        positions = [type("P", (), {"status": "OPEN"})() for _ in range(4)]
        result = risk_manager.check_max_positions(positions)
        assert result.allowed is False
        assert "Max open positions" in result.reason

    def test_create_stop_loss_price_buy(self, risk_manager):
        """Stop-Loss fiyatı - ALIŞ"""
        sl = risk_manager.create_stop_loss_price(100.0, OrderSide.BUY)
        # 100 * (1 - 15%) = 85
        assert sl == 85.0

    def test_create_stop_loss_price_sell(self, risk_manager):
        """Stop-Loss fiyatı - SATIŞ"""
        sl = risk_manager.create_stop_loss_price(100.0, OrderSide.SELL)
        # 100 * (1 + 15%) = 115
        assert abs(sl - 115.0) < 0.01

    def test_create_take_profit_tiers(self, risk_manager):
        """TP katmanları oluşturma"""
        tiers = risk_manager.create_take_profit_tiers(100.0, OrderSide.BUY)
        assert len(tiers) == 3
        assert all(isinstance(t, TPTier) for t in tiers)
        # İlk tier: 100 * 1.25 = 125
        assert tiers[0].profit_pct == 25.0
        assert tiers[0].sell_pct == 40.0
        assert tiers[0].triggered is False

    def test_get_tp_trigger_prices(self, risk_manager):
        """TP tetikleme fiyatları"""
        prices = risk_manager.get_tp_trigger_prices(100.0, OrderSide.BUY)
        assert len(prices) == 3
        assert prices[0] == 125.0  # +25%
        assert prices[1] == 145.0  # +45%
        assert prices[2] == 170.0  # +70%

    def test_check_exit_conditions_stop_loss(self, risk_manager):
        """Stop-Loss çıkış kontrolü"""
        position = Position(
            inst_id="TEST-USDT",
            side=OrderSide.BUY,
            entry_price=100.0,
            quantity=1000.0,
            entry_value_usd=100000.0,
            stop_loss_price=85.0,
            take_profit_tiers=[
                {"profit_pct": 25, "sell_pct": 40, "triggered": False},
            ],
            trailing_activated=False,
        )

        # Fiyat SL altına düştü
        action, price, tier = risk_manager.check_exit_conditions(position, 84.0)
        assert action == "STOP_LOSS"
        assert price == 85.0

    def test_check_exit_conditions_take_profit(self, risk_manager):
        """Take-Profit çıkış kontrolü"""
        position = Position(
            inst_id="TEST-USDT",
            side=OrderSide.BUY,
            entry_price=100.0,
            quantity=1000.0,
            entry_value_usd=100000.0,
            stop_loss_price=85.0,
            take_profit_tiers=[
                {"profit_pct": 25, "sell_pct": 40, "triggered": False},
                {"profit_pct": 45, "sell_pct": 40, "triggered": False},
            ],
            trailing_activated=False,
        )

        # Fiyat ilk TP'yi geçti
        action, price, tier = risk_manager.check_exit_conditions(position, 126.0)
        assert action == "TAKE_PROFIT"
        assert tier == 0
        assert price == 125.0

    def test_check_exit_conditions_trailing_stop(self, risk_manager):
        """Trailing Stop çıkış kontrolü"""
        position = Position(
            inst_id="TEST-USDT",
            side=OrderSide.BUY,
            entry_price=100.0,
            quantity=1000.0,
            entry_value_usd=100000.0,
            stop_loss_price=85.0,
            take_profit_tiers=[
                {"profit_pct": 25, "sell_pct": 40, "triggered": True},  # TP1 tetiklendi
            ],
            trailing_activated=True,
            trailing_stop_price=135.0,  # 150 * 0.9 = 135
        )

        # Fiyat trailing'in altına düştü
        action, price, tier = risk_manager.check_exit_conditions(position, 134.0)
        assert action == "TRAILING_STOP"
        assert price == 135.0

    def test_update_position_after_tp(self, risk_manager):
        """TP fill sonrası pozisyon güncelleme"""
        position = Position(
            inst_id="TEST-USDT",
            side=OrderSide.BUY,
            entry_price=100.0,
            quantity=1000.0,
            entry_value_usd=100000.0,
            stop_loss_price=85.0,
            take_profit_tiers=[
                {"profit_pct": 25, "sell_pct": 40, "triggered": False},
            ],
            current_tp_tier=0,
        )

        risk_manager.update_position_after_tp(position, 0, 125.0, 400.0)

        assert position.take_profit_tiers[0]["triggered"] is True
        assert position.current_tp_tier == 1
        assert position.quantity == 600.0  # 1000 - 400
        assert position.realized_pnl == 10000.0  # (125-100) * 400
        assert position.status == PositionStatus.PARTIAL

    def test_update_position_after_sl(self, risk_manager):
        """SL fill sonrası pozisyon güncelleme"""
        position = Position(
            inst_id="TEST-USDT",
            side=OrderSide.BUY,
            entry_price=100.0,
            quantity=1000.0,
            entry_value_usd=100000.0,
            stop_loss_price=85.0,
            take_profit_tiers=[],
        )

        risk_manager.update_position_after_sl(position, 85.0, 1000.0)

        assert position.quantity == 0.0
        assert position.realized_pnl == -15000.0  # (85-100) * 1000
        assert position.status == PositionStatus.STOPPED_OUT

    def test_update_position_after_trailing(self, risk_manager):
        """Trailing fill sonrası pozisyon güncelleme"""
        position = Position(
            inst_id="TEST-USDT",
            side=OrderSide.BUY,
            entry_price=100.0,
            quantity=600.0,
            entry_value_usd=100000.0,
            stop_loss_price=85.0,
            take_profit_tiers=[{"profit_pct": 25, "sell_pct": 40, "triggered": True}],
            trailing_activated=True,
            trailing_stop_price=135.0,
        )

        risk_manager.update_position_after_trailing(position, 135.0, 600.0)

        assert position.quantity == 0.0
        assert position.status == PositionStatus.TRAILING_CLOSED

    def test_create_tp_order(self, risk_manager):
        """TP emri oluşturma"""
        position = Position(
            inst_id="TEST-USDT",
            side=OrderSide.BUY,
            entry_price=100.0,
            quantity=1000.0,
            entry_value_usd=100000.0,
            stop_loss_price=85.0,
            take_profit_tiers=[
                {"profit_pct": 25, "sell_pct": 40, "triggered": False},
            ],
        )

        order = risk_manager.create_tp_order(position, 0, 400.0)

        assert order.inst_id == "TEST-USDT"
        assert order.side == OrderSide.SELL
        assert order.size == 400.0
        assert order.is_take_profit is True
        assert order.tp_tier_index == 0

    def test_create_sl_order(self, risk_manager):
        """SL emri oluşturma"""
        position = Position(
            inst_id="TEST-USDT",
            side=OrderSide.BUY,
            entry_price=100.0,
            quantity=1000.0,
            entry_value_usd=100000.0,
            stop_loss_price=85.0,
            take_profit_tiers=[],
        )

        order = risk_manager.create_sl_order(position, 1000.0)

        assert order.inst_id == "TEST-USDT"
        assert order.side == OrderSide.SELL
        assert order.size == 1000.0
        assert order.is_stop_loss is True
        assert order.price == 85.0

    def test_get_risk_summary(self, risk_manager):
        """Risk özeti"""
        positions = [
            type(
                "P",
                (),
                {
                    "entry_value_usd": 5000.0,
                    "status": "OPEN",
                    "unrealized_pnl": 100.0,
                },
            )(),
        ]
        summary = risk_manager.get_risk_summary(positions, 10000.0)

        assert summary["open_positions"] == 1
        assert summary["total_exposure_usd"] == 5000.0
        assert summary["exposure_pct"] == 50.0
