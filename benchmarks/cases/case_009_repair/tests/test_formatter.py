import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from formatter import format_name

def test_full_name():
    assert format_name('Ada', 'Lovelace') == 'Ada Lovelace'

def test_empty_last_no_trailing_space():
    assert format_name('Ada', '') == 'Ada'

def test_single_letter():
    assert format_name('L', 'Lee') == 'L Lee'
