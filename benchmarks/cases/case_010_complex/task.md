项目位于 workspace/bench_case_010，是一个简易 Todo 存储工具，需要完成以下工作：
1) todoapp/storage.py 的 load 在文件不存在时应返回空列表，当前会抛异常；
2) save 写入时应使用 ensure_ascii=False，方便阅读中文内容；
3) 在 todoapp/tasks.py 中新增函数 completed(tasks)，返回 done 为 True 的任务列表，保持原顺序；
4) pending(tasks) 应只返回未完成（done 为 False）的任务，保持顺序。
可能需要修改多个文件。运行 tests/test_todo.py 验证所有功能。禁止修改测试文件。
