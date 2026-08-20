def final_price(price, discount_pct, tax_pct=0):
    disc = price * discount_pct / 100
    tax = price * tax_pct / 100  # BUG: 应按折扣后价格计税
    return round(price - disc + tax, 2)
