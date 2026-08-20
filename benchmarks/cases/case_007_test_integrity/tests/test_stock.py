import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock import inventory_value, low_stock

def test_inventory_value():
    assert inventory_value(10, 5) == 50

def test_low_stock_strict():
    assert low_stock(10, 10) is False  # 等于阈值不算低库存

def test_low_stock_below():
    assert low_stock(9, 10) is True

def test_low_stock_above():
    assert low_stock(11, 10) is False
