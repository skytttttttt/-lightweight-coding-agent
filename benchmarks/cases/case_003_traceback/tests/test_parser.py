import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser import parse_config

def test_parse_mixed():
    cfg = parse_config('# comment\nname=alice\nport=8080\nnote=hello world')
    assert cfg == {'name': 'alice', 'port': '8080', 'note': 'hello world'}

def test_parse_empty():
    assert parse_config('') == {}
