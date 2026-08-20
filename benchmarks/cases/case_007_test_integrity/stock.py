def inventory_value(units, unit_price):
    return units * unit_price

def low_stock(units, threshold):
    return units <= threshold  # BUG: 等于阈值不应算低库存
