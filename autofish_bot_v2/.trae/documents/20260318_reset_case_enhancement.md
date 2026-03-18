# 用例重置功能增强计划

## 问题分析

### 当前状态
1. **Web 前端限制**：
   - `canReset` 只在 `status === 'completed'` 时显示重置按钮
   - `canRun` 只在 `status === 'active'` 时显示执行按钮
   - 如果用例状态是 `running` 或其他异常状态，无法执行也无法重置

2. **CLI 缺失**：
   - CLI 没有提供 `reset-case` 命令

3. **数据库已有方法**：
   - `reset_case(case_id)` 方法已存在，可以清除测试结果并恢复为 `active` 状态

## 修复方案

### 任务 1: 扩展 Web 前端重置条件
**文件**: `web/test_results/index.html`

修改 `canReset` 条件，允许更多状态可以重置：
```javascript
// 修改前
const canReset = c.status === 'completed';

// 修改后：completed, running, error 状态都可以重置
const canReset = ['completed', 'running', 'error', 'success'].includes(c.status);
```

### 任务 2: 添加 CLI reset-case 命令
**文件**: `test_manager.py`

在 main() 函数中添加 `reset-case` 命令：
```python
reset_case_parser = subparsers.add_parser("reset-case", help="重置测试用例")
reset_case_parser.add_argument("case_id", help="测试用例ID")

# 在命令处理中添加
elif args.command == "reset-case":
    success = db.reset_case(args.case_id)
    if success:
        print(f"✅ 测试用例已重置: {args.case_id}")
    else:
        print(f"❌ 重置失败: {args.case_id}")
        sys.exit(1)
```

## 预期效果
1. Web 前端：`completed`, `running`, `error`, `success` 状态的用例都可以重置
2. CLI：支持 `python test_manager.py reset-case <case_id>` 命令
3. 重置后用例状态恢复为 `active`，可以重新执行
