from utils.helpers import sort_items

def test_ascending():
    assert sort_items([3, 1, 2]) == [1, 2, 3]

def test_negative():
    assert sort_items([-1, 5, 0, 3]) == [-1, 0, 3, 5]

def test_duplicates():
    assert sort_items([2, 2, 1]) == [1, 2, 2]
