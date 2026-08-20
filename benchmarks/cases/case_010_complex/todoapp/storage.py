import json

def load(path):
    # BUG: 文件不存在时抛异常，应返回空列表
    with open(path) as f:
        return json.load(f)

def save(path, data):
    with open(path, 'w') as f:
        json.dump(data, f)
