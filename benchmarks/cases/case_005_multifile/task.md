项目位于 workspace/bench_case_005，是一个 calculator 包，需要修复多处：
1) calc_pkg/operations.py 的 divide 在除数为 0 时应抛出 ValueError，当前返回 0；
2) calc_pkg/__init__.py 应正确导出 add/subtract/multiply/divide 四个函数；
3) 各函数在收到非数字输入（如字符串）时应抛出 TypeError（validate.py 提供校验）。
可能需要修改多个文件。请修复后运行 tests/test_calc.py 验证。禁止修改测试文件。
