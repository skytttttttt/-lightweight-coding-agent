def load_cfg(text):
    return dict(line.split('=') for line in text.splitlines() if line)
