def read_lines(path):
    with open(path) as f:
        return [ln.rstrip('\n') for ln in f]
