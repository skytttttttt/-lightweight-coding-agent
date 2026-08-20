import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from price import final_price

def test_discount_only():
    assert final_price(100, 10) == 90.0

def test_with_tax_after_discount():
    assert final_price(100, 10, 8) == 97.2

def test_no_discount():
    assert final_price(50, 0, 10) == 55.0
