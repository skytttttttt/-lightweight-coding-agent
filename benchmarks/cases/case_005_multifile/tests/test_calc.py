import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import calc_pkg
from calc_pkg import add, subtract, multiply, divide

def test_exports():
    assert set(['add', 'subtract', 'multiply', 'divide']) <= set(calc_pkg.__all__)

def test_basic():
    assert add(2, 3) == 5
    assert subtract(5, 2) == 3
    assert multiply(3, 4) == 12
    assert divide(10, 2) == 5.0

def test_divide_by_zero():
    with pytest.raises(ValueError):
        divide(1, 0)

def test_type_error():
    with pytest.raises(TypeError):
        add('a', 1)
