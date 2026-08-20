def average(nums):
    if not nums:
        return 0
    total = 0
    for n in nums:
        total += n
    return total // len(nums)  # BUG: 整除丢失精度
