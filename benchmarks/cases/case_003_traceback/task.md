项目位于 workspace/bench_case_003。parser.py 的 parse_config 函数对包含非数字值（如 name=alice、note=hello world）的配置行会抛出 ValueError。配置解析应把所有值作为字符串保留，不得抛异常。请修复 parser.py 使 tests/test_parser.py 通过，并运行测试验证。禁止修改测试文件。
