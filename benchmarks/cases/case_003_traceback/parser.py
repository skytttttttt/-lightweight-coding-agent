def parse_config(text):
    cfg = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, value = line.split('=', 1)
        cfg[key.strip()] = int(value.strip())  # BUG: 非数字值抛 ValueError
    return cfg
