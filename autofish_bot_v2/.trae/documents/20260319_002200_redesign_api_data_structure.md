# 重新设计 API 返回数据结构计划

## 目标
将用例相关的信息放入独立的 `test_case` 字典中，使数据结构更清晰。

## 当前数据结构
```json
{
    "data": {
        "amplitude": {...},
        "entry": {...},
        "id": 4,
        "market": {...},
        "name": "ETHUSDT震荡策略测试",
        "status": "active",
        "symbol": "ETHUSDT",
        "test_type": "market_aware",
        "timeout": {...},
        "updated_at": "..."
    },
    "success": true
}
```

## 目标数据结构
```json
{
    "data": {
        "test_case": {
            "case_id": "...",
            "name": "ETHUSDT震荡策略测试",
            "status": "active",
            "symbol": "ETHUSDT",
            "test_type": "market_aware",
            "date_start": "20200101",
            "date_end": "20201231",
            "description": "...",
            "created_at": "...",
            "updated_at": "...",
            "success": true
        },
        "amplitude": {...},
        "market": {...},
        "entry": {...},
        "timeout": {...}
    }
}
```

## 实施步骤

### 1. 修改后端 API
修改 `test_manager.py` 中的 `get_case` API 返回结构：
- 将用例基本信息放入 `test_case` 字段
- 将 `success` 字段也放入 `test_case` 中
- 保持 `amplitude`, `market`, `entry`, `timeout` 作为独立字段

### 2. 修改数据库查询
修改 `database/test_results_db.py` 中的 `get_case` 方法：
- 分离用例基本信息和配置参数

### 3. 修改前端代码
修改 `web/test_results/index.html` 中的相关函数：
- `showEditCaseForm` 函数：从 `data.test_case` 读取用例基本信息
- `showCaseDetail` 函数：适配新的数据结构
- 其他使用用例数据的地方

## 涉及文件
1. `test_manager.py` - API 返回结构
2. `database/test_results_db.py` - 数据库查询方法
3. `web/test_results/index.html` - 前端数据处理
