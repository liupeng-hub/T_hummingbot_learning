# 测试框架输出目录统一管理方案

## 1. 问题分析

### 1.1 当前问题

**测试框架定义的目录结构**：
```
out/
├── test_results/
│   ├── backtest/TP001/         # 按计划ID组织
│   ├── market_aware/TP002/
│   ├── visualizer/TP003/
│   └── optimization/TP004/
```

**各脚本实际输出目录**：
| 脚本 | 输出目录 | 文件 |
|------|----------|------|
| binance_backtest.py | out/autofish/ | binance_BTCUSDT_backtest_report.md |
| market_aware_backtest.py | out/market_backtest/ | binance_BTCUSDT_market_aware_backtest.md |
| market_status_visualizer.py | out/market_visualizer/ | market_visualizer_*.md/png/html |
| optuna_*.py | out/market_optimization/ | optimization_result.csv/md |

**问题**：
1. 目录不一致：测试框架定义的目录 vs 脚本实际输出目录
2. 结果分散：无法按测试计划ID统一管理
3. 数据格式不统一：各脚本输出格式不同，难以统一收集

### 1.2 目标

1. **测试计划执行时**：结果输出到测试框架目录 `test_results/{type}/{plan_id}/`
2. **单独执行脚本时**：结果输出到脚本原有目录
3. **数据统一管理**：测试框架能收集各脚本的输出数据

## 2. 解决方案

### 2.1 方案概述

**核心思路**：通过参数控制输出目录

```
测试计划执行 → 传递 --output-dir 参数 → 输出到测试框架目录
单独执行脚本 → 不传递参数 → 输出到脚本默认目录
```

### 2.2 目录结构设计

```
out/
├── test_results/                          # 测试框架管理目录
│   ├── backtest/
│   │   └── TP001/                         # 按计划ID组织
│   │       ├── TP001_S001_result.md       # 标准化结果报告
│   │       ├── TP001_S001_raw/            # 原始输出文件
│   │       │   └── binance_BTCUSDT_backtest_report.md
│   │       └── TP001_summary.md
│   ├── market_aware/
│   │   └── TP002/
│   │       ├── TP002_S001_result.md
│   │       ├── TP002_S001_raw/
│   │       │   └── binance_BTCUSDT_market_aware_backtest.md
│   │       └── TP002_summary.md
│   └── visualizer/
│       └── TP003/
│           ├── TP003_S001_result.md
│           └── TP003_S001_raw/
│               ├── market_visualizer.md
│               ├── market_visualizer.png
│               └── market_visualizer.html
│
├── autofish/                              # 脚本默认输出目录（单独执行时）
├── market_backtest/
├── market_visualizer/
└── market_optimization/
```

### 2.3 实现方案

#### 方案A：参数传递方式

**修改各测试脚本，支持 `--output-dir` 参数**：

```python
# binance_backtest.py
parser.add_argument("--output-dir", type=str, default=None, help="输出目录（测试框架使用）")

# save_report 方法
def save_report(self, symbol: str, days: int = None, date_range: str = None, output_dir: str = None):
    if output_dir:
        # 测试框架模式：输出到指定目录
        filepath = os.path.join(output_dir, f"binance_{symbol}_backtest_report.md")
    else:
        # 默认模式：输出到脚本默认目录
        filepath = os.path.join(os.path.dirname(__file__), "out/autofish", f"binance_{symbol}_backtest_report.md")
```

**测试计划命令模板**：

```json
{
  "execution": {
    "command_template": "python binance_backtest.py --symbol {symbol} --output-dir {output_dir}"
  }
}
```

**test_manager.py 执行时传递目录**：

```python
def run_plan(self, plan_id: str, scenario_id: str = None):
    results_dir = self.get_results_dir(plan.test_type) / plan.plan_id
    raw_dir = results_dir / f"{plan.plan_id}_{scenario['scenario_id']}_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    # 替换 output_dir 参数
    command = command.replace("{output_dir}", str(raw_dir))
```

#### 方案B：结果收集器方式

**定义统一的结果格式**：

```python
# test_manager.py
class TestResultCollector:
    """测试结果收集器"""
    
    RESULT_SCHEMA = {
        "test_id": str,           # TP001_S001
        "plan_id": str,           # TP001
        "scenario_id": str,       # S001
        "test_type": str,         # backtest
        "executed_at": str,       # 2026-03-14T17:00:00
        "command": str,           # 执行的命令
        "status": str,            # success/failed
        "metrics": dict,          # 核心指标
        "output_files": list,     # 输出文件列表
        "raw_output": str,        # 原始输出目录
    }
    
    def collect_from_backtest(self, report_file: str) -> dict:
        """从 binance_backtest 报告收集结果"""
        with open(report_file, 'r') as f:
            content = f.read()
        
        # 解析报告提取指标
        metrics = self._parse_backtest_report(content)
        return {
            "test_id": "...",
            "metrics": metrics,
            "output_files": [report_file],
        }
    
    def _parse_backtest_report(self, content: str) -> dict:
        """解析回测报告提取指标"""
        import re
        metrics = {}
        
        # 提取总交易次数
        match = re.search(r'\| 总交易次数 \| (\d+) \|', content)
        if match:
            metrics['total_trades'] = int(match.group(1))
        
        # 提取胜率
        match = re.search(r'\| 胜率 \| ([\d.]+)% \|', content)
        if match:
            metrics['win_rate'] = float(match.group(1))
        
        # 提取净收益
        match = re.search(r'\| 净收益 \| ([\d.]+) USDT \|', content)
        if match:
            metrics['net_profit'] = float(match.group(1))
        
        # 提取标的涨跌幅
        match = re.search(r'\| 标的涨跌幅 \| ([\d.]+)% \|', content)
        if match:
            metrics['price_change'] = float(match.group(1))
        
        return metrics
```

### 2.4 推荐方案：参数传递 + 结果收集

**结合两种方式**：

1. **参数传递**：控制输出目录
2. **结果收集**：解析输出文件，生成标准化报告

**执行流程**：

```
1. test_manager.py 执行测试计划
   ↓
2. 创建目录 test_results/{type}/{plan_id}/{scenario_id}_raw/
   ↓
3. 传递 --output-dir 参数给测试脚本
   ↓
4. 测试脚本输出到指定目录
   ↓
5. test_manager.py 收集结果，生成标准化报告
   ↓
6. 更新测试历史记录
```

## 3. 实现细节

### 3.1 修改测试脚本

**需要修改的脚本**：

| 脚本 | 需要添加的参数 |
|------|----------------|
| binance_backtest.py | --output-dir |
| market_aware_backtest.py | --output-dir |
| market_status_visualizer.py | --output-dir |
| optuna_dual_thrust_optimizer.py | --output-dir |
| optuna_improved_strategy_optimizer.py | --output-dir |

### 3.2 修改 test_manager.py

```python
class TestManager:
    def run_plan(self, plan_id: str, scenario_id: str = None, dry_run: bool = False):
        # ... 现有代码 ...
        
        for scenario in scenarios:
            # 创建输出目录
            results_dir = self.get_results_dir(plan.test_type) / plan.plan_id
            raw_dir = results_dir / f"{plan.plan_id}_{scenario['scenario_id']}_raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            
            # 添加 output_dir 参数
            params['output_dir'] = str(raw_dir)
            
            # 执行命令
            command = self._build_command(plan, scenario, params)
            
            if not dry_run:
                result = subprocess.run(command, shell=True, cwd=str(self.base_dir))
                
                # 收集结果
                collector = TestResultCollector()
                result_data = collector.collect(plan.test_type, raw_dir)
                
                # 生成标准化报告
                self._save_result_report(results_dir, scenario, result_data)
                
                # 更新历史
                self._update_history(plan, scenario, result_data)
```

### 3.3 结果收集器

```python
class TestResultCollector:
    COLLECTORS = {
        'backtest': '_collect_backtest',
        'market_aware': '_collect_market_aware',
        'visualizer': '_collect_visualizer',
        'optimization': '_collect_optimization',
    }
    
    def collect(self, test_type: str, raw_dir: Path) -> dict:
        collector_method = self.COLLECTORS.get(test_type)
        if collector_method:
            return getattr(self, collector_method)(raw_dir)
        return {}
    
    def _collect_backtest(self, raw_dir: Path) -> dict:
        """收集回测结果"""
        report_file = raw_dir / "binance_BTCUSDT_backtest_report.md"
        if not report_file.exists():
            # 查找其他可能的文件
            report_files = list(raw_dir.glob("*.md"))
            if report_files:
                report_file = report_files[0]
        
        if report_file.exists():
            return self._parse_backtest_report(report_file)
        return {}
    
    def _parse_backtest_report(self, report_file: Path) -> dict:
        """解析回测报告"""
        with open(report_file, 'r') as f:
            content = f.read()
        
        return {
            'total_trades': self._extract_value(content, r'\| 总交易次数 \| (\d+) \|', int),
            'win_rate': self._extract_value(content, r'\| 胜率 \| ([\d.]+)% \|', float),
            'net_profit': self._extract_value(content, r'\| 净收益 \| ([\d.]+) USDT \|', float),
            'price_change': self._extract_value(content, r'\| 标的涨跌幅 \| ([\d.]+)% \|', float),
            'roi': self._extract_value(content, r'\| 收益率 \| ([\d.]+)% \|', float),
        }
    
    def _extract_value(self, content: str, pattern: str, value_type: type):
        import re
        match = re.search(pattern, content)
        if match:
            return value_type(match.group(1))
        return None
```

## 4. 执行步骤

### 阶段1：修改测试脚本支持 --output-dir 参数

1. 修改 binance_backtest.py
2. 修改 market_aware_backtest.py
3. 修改 market_status_visualizer.py
4. 修改 optuna_*.py

### 阶段2：修改 test_manager.py

1. 添加 output_dir 参数传递
2. 添加 TestResultCollector 类
3. 添加结果收集和报告生成逻辑

### 阶段3：更新测试计划

1. 更新 command_template 添加 --output-dir {output_dir}
2. 测试验证

## 5. 兼容性

### 5.1 向后兼容

- 单独执行脚本时，不传 --output-dir，输出到原有目录
- 测试框架执行时，传递 --output-dir，输出到测试框架目录

### 5.2 数据迁移

- 现有测试结果保留在原目录
- 新测试结果按新方案管理

## 6. 验收标准

1. ✅ 测试计划执行时，结果输出到 test_results/{type}/{plan_id}/
2. ✅ 单独执行脚本时，结果输出到脚本默认目录
3. ✅ 测试框架能收集各脚本的输出数据
4. ✅ 生成标准化测试结果报告
5. ✅ 更新测试历史记录
