# 测试用例复制功能计划

## 需求概述

增加测试用例复制功能，在用例的操作栏中添加"复制"按钮，点击后复制源用例的所有配置内容，生成新的用例ID，并在数据库中新增一条数据。

## 实现步骤

### 1. 后端实现 (test_manager.py)

**1.1 新增 API 接口**
- 路径: `/api/cases/<case_id>/copy`
- 方法: `POST`
- 功能: 复制指定用例
- 返回: 新用例的 case_id

**1.2 实现逻辑**
```python
@app.route('/api/cases/<case_id>/copy', methods=['POST'])
def copy_case(case_id):
    # 1. 获取源用例数据
    # 2. 生成新的 case_id
    # 3. 修改 name 为 "源名称-复制"
    # 4. 状态设为 draft
    # 5. 调用 create_case 创建新用例
    # 6. 返回新用例 ID
```

### 2. 数据库层 (test_results_db.py)

**2.1 新增复制方法**
```python
def copy_case(self, source_case_id: str) -> str:
    """复制测试用例
    
    Args:
        source_case_id: 源用例ID
        
    Returns:
        新用例ID
    """
    # 1. 获取源用例数据
    # 2. 生成新 case_id
    # 3. 修改 name 添加 "-复制" 后缀
    # 4. 重置状态为 draft
    # 5. 重置 created_at 和 updated_at
    # 6. 插入新记录
    # 7. 返回新 case_id
```

### 3. 前端实现 (index.html)

**3.1 在用例列表操作栏添加复制按钮**
- 位置: 在用例操作栏中，"详情"按钮旁边
- 样式: `btn-outline-secondary`
- 文本: "复制"
- 点击事件: `copyCase('${c.case_id}')`

**3.2 实现复制功能 JavaScript 函数**
```javascript
async function copyCase(caseId) {
    // 1. 确认对话框
    // 2. 调用 API POST /api/cases/${caseId}/copy
    // 3. 成功后提示用户
    // 4. 刷新用例列表
}
```

**3.3 更新操作栏渲染逻辑**
- 复制按钮对所有状态的用例都可用（无状态限制）
- 按钮顺序: 删除 | 详情 | 复制 | 编辑 | 执行 | 重置

## 文件修改清单

| 文件 | 修改内容 |
|------|----------|
| `database/test_results_db.py` | 新增 `copy_case` 方法 |
| `test_manager.py` | 新增 `/api/cases/<case_id>/copy` 接口 |
| `web/test_results/index.html` | 添加复制按钮和 `copyCase` 函数 |

## 命名规则

- 复制后的用例名称格式: `"{原名称}-复制"`
- 如果原名称已包含 "-复制"，则改为: `"{原名称}-复制2"`、`"{原名称}-复制3"` 等

## 数据复制规则

复制以下内容（与源用例相同）:
- symbol, interval
- date_start, date_end
- test_type, description
- amplitude, market, entry, timeout, capital

重置以下内容:
- case_id: 新生成 UUID
- status: 设为 "draft"
- created_at, updated_at: 设为当前时间

## 验收标准

1. 用例列表中每个用例都显示"复制"按钮
2. 点击复制后，数据库中新增一条用例记录
3. 新用例ID与源用例不同
4. 新用例状态为 draft
5. 新用例名称为"源名称-复制"
6. 新用例的配置参数与源用例完全一致
7. 复制成功后刷新列表，显示新用例
8. 用户收到复制成功的提示
