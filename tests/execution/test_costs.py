import pytest

from tradebot.domain import Side
from tradebot.execution import PRESETS, CostModel


def test_zero_preset_is_free() -> None:
    zero = PRESETS["zero"]
    assert zero.commission(10, 100) == 0
    assert zero.apply_slippage(Side.BUY, 100) == 100


def test_ibkr_fixed_minimum_hurts_small_orders() -> None:
    ibkr = PRESETS["ibkr_fixed"]
    # 0,2 action à 500 $ = 100 $ : 0,001 $ au tarif par action, mais minimum 1 $,
    # plafonné à 1 % du montant -> 1 $.
    assert ibkr.commission(0.2, 500) == pytest.approx(1.0)
    # 1000 actions à 50 $ : 5 $ (au-dessus du minimum).
    assert ibkr.commission(1000, 50) == pytest.approx(5.0)
    # Très petit montant : plafond de 1 % (20 $ -> 0,20 $).
    assert ibkr.commission(1, 20) == pytest.approx(0.20)


def test_percentage_commission() -> None:
    model = CostModel(commission_pct=0.001, slippage_bps=0)
    assert model.commission(10, 100) == pytest.approx(1.0)


def test_slippage_is_always_adverse() -> None:
    model = CostModel(slippage_bps=10)
    assert model.apply_slippage(Side.BUY, 100) == pytest.approx(100.1)
    assert model.apply_slippage(Side.SELL, 100) == pytest.approx(99.9)


def test_negative_values_rejected() -> None:
    with pytest.raises(ValueError):
        CostModel(slippage_bps=-1)
