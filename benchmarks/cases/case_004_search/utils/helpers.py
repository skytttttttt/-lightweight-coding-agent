def sort_items(items):
    # BUG: 不应按模 3 排序
    return sorted(items, key=lambda x: x % 3)
