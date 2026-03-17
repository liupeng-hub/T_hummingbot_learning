# market_status_visualizer.py CLI 参数改造计划

## 背景

参考 `market_status_detector.py` 的 CLI 参数改造，对 `market_status_visualizer.py` 进行类似改造。

## 当前参数

```python
parser.add_argument('--server', action='store_true', help='启动Web服务器模式')
parser.add_argument('--port', type=int, default=5001, help='Web服务器端口 (默认: 5001)')

parser.add_argument('--symbol', default='BTCUSDT', help='交易对')
parser.add_argument('--date-range', help='时间范围 (格式: yyyymmdd-yyyymmdd)')
parser.add_argument('--interval', default='1d', help='K线周期 (默认: 1d)')
parser.add_argument('--algorithm', default='dual_thrust', 
                    choices=['dual_thrust', 'improved', 'always_ranging'],
                    help='行情判断算法')
parser.add_argument('--output-dir', default='out/market_visualizer', help='输出目录')

parser.add_argument('--generate-md', action='store_true', help='生成MD报告文件')
parser.add_argument('--generate-png', action='store_true', help='生成PNG图表文件')
parser.add_argument('--generate-html', action='store_true', help='生成HTML可视化文件')
parser.add_argument('--generate-all', action='store_true', help='生成所有文件(MD+PNG+HTML)')

parser.add_argument('--n-days', type=int, help='Dual Thrust 参数: 回看天数')
parser.add_argument('--k1', type=float, help='Dual Thrust 参数: 上轨系数')
parser.add_argument('--k2', type=float, help='Dual Thrust 参数: 下轨系数')
parser.add_argument('--k2-down-factor', type=float, help='Dual Thrust 参数: 下跌敏感系数')
parser.add_argument('--down-confirm-days', type=int, help='Dual Thrust 参数: 下跌确认天数')
parser.add_argument('--cooldown-days', type=int, help='Dual Thrust 参数: 状态切换冷却期')
```

## 改造后参数

保留的参数：
```python
parser.add_argument('--server', action='store_true', help='启动Web服务器模式')
parser.add_argument('--port', type=int, default=5001, help='Web服务器端口 (默认: 5001)')
parser.add_argument('--symbol', default='BTCUSDT', help='交易对')
parser.add_argument('--date-range', required=True, help='时间范围 (格式: yyyymmdd-yyyymmdd)（必选）')
parser.add_argument('--interval', default='1d', help='K线周期 (默认: 1d)')
parser.add_argument('--algorithm', default='dual_thrust', 
                    choices=['dual_thrust', 'improved', 'always_ranging', 'composite', 'adx', 'realtime'],
                    help='行情判断算法')
parser.add_argument('--output-dir', default='out/market_visualizer', help='输出目录')
parser.add_argument('--generate-all', action='store_true', help='生成所有文件(MD+PNG+HTML)')
```

新增参数：
```python
parser.add_argument('--algorithm-params', type=str, default=None, help='算法参数 (JSON格式)')
```

移除的参数：
- `--generate-md`
- `--generate-png`
- `--generate-html`
- `--n-days`
- `--k1`
- `--k2`
- `--k2-down-factor`
- `--down-confirm-days`
- `--cooldown-days`

## 实施步骤

### Step 1: 更新 CLI 参数定义

修改 `main()` 函数中的 `argparse` 参数定义。

### Step 2: 更新算法参数解析逻辑

修改 `_build_algorithm_config()` 方法：
- 优先从 `--algorithm-params` 读取 JSON 参数
- 兼容旧格式参数（通过 argparse 获取的参数）

### Step 3: 算法选项更新

将算法选项更新为完整列表：
- `dual_thrust`
- `improved`
- `always_ranging`
- `composite`
- `adx`
- `realtime`

## 验证清单

- [x] CLI 参数已更新
- [x] 算法参数解析逻辑已更新
- [x] 算法选项已更新
- [x] 功能测试通过
