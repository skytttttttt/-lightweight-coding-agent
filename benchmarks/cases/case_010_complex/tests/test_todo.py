import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import os
import tempfile
from todoapp.storage import load, save
from todoapp.tasks import add_task, pending, completed

def test_load_missing_returns_empty():
    path = os.path.join(tempfile.mkdtemp(), 'nope.json')
    assert load(path) == []

def test_save_and_load_roundtrip():
    path = os.path.join(tempfile.mkdtemp(), 't.json')
    save(path, [{'title': '中文任务', 'done': False}])
    with open(path, encoding='utf-8') as f:
        raw = f.read()
    assert '中' in raw  # ensure_ascii=False 可读中文
    assert load(path) == [{'title': '中文任务', 'done': False}]

def test_add_and_pending():
    tasks = []
    add_task(tasks, 'a')
    add_task(tasks, 'b', done=True)
    assert pending(tasks) == [{'title': 'a', 'done': False}]

def test_completed_order():
    tasks = [{'title': 'x', 'done': True}, {'title': 'y', 'done': False},
             {'title': 'z', 'done': True}]
    assert completed(tasks) == [{'title': 'x', 'done': True}, {'title': 'z', 'done': True}]
