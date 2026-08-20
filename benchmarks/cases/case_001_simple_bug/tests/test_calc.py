import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calc import average

def test_average_float():
    assert average([1, 2, 3, 4]) == 2.5

def test_average_empty():
    assert average([]) == 0

def test_average_single():
    assert average([7]) == 7.0
