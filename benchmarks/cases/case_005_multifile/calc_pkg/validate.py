def validate_inputs(*args):
    for a in args:
        if not isinstance(a, (int, float)):
            raise TypeError(f'不支持的数值类型: {type(a).__name__}')
