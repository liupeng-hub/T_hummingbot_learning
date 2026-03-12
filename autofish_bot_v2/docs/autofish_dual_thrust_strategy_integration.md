# Dual Thrust 策略深度解析与 Autofish 集成方案

## 1. 策略概述

**Dual Thrust** 是由 Michael Chalek 在 20 世纪 80 年代开发的经典日内突破策略。与 R-Breaker 的“攻守兼备”不同，Dual Thrust 是一种**纯粹的趋势追踪策略**。它以逻辑简单、参数少、适应性强而著称，广泛应用于期货、外汇和加密货币市场。

该策略的核心思想是利用前 N 日的历史波动幅度（Range），在当日开盘价（Open）的基础上构建一个非对称的突破区间。一旦价格突破该区间，即视为趋势确立，顺势开仓。

## 2. 核心逻辑与计算公式

Dual Thrust 的计算过程非常简洁，主要分为两步：计算波动幅度（Range）和确定上下轨。

### 第一步：计算波动幅度 (Range)
选取前 $N$ 日（通常 $N$ 取 1 到 4）的四个价差中的最大值：

$$Range = \max(HH - LC, HC - LL)$$

其中：
- $HH$: 前 $N$ 日的最高价 (Highest High)
- $LC$: 前 $N$ 日的最低收盘价 (Lowest Close)
- $HC$: 前 $N$ 日的最高收盘价 (Highest Close)
- $LL$: 前 $N$ 日的最低价 (Lowest Low)

这种计算方式综合考虑了日内波动和隔夜跳空缺口，比单纯的 High - Low 更能反映市场的真实波动率。

### 第二步：确定上下轨 (Upper/Lower Bands)
基于当日开盘价 ($Open_{day}$) 和波动幅度 ($Range$)，引入两个系数 $K_1$ 和 $K_2$：

- **上轨 (Upper Buy)**: $Buy_{trigger} = Open_{day} + K_1 \times Range$
- **下轨 (Lower Sell)**: $Sell_{trigger} = Open_{day} - K_2 \times Range$

当价格突破上轨时做多，跌破下轨时做空。

## 3. 策略特点：非对称性 (Asymmetry)

Dual Thrust 的最大亮点在于 $K_1$ 和 $K_2$ 可以**不相等**。

- **多头市场**: 设置 $K_1 < K_2$，使得向上突破更容易触发（做多门槛低），向下突破更难触发（做空门槛高）。
- **空头市场**: 设置 $K_1 > K_2$，使得向下突破更容易触发，向上突破更难触发。
- **震荡市场**: 设置较大的 $K_1$ 和 $K_2$，过滤掉窄幅震荡的假信号。

这种设计让策略能够通过调整参数，天然适应不同市场的长期偏向性（Bias）。

## 4. 加密货币市场适应性分析

### 优点
1.  **捕捉爆发性行情**: 加密货币经常出现单边暴涨暴跌，Dual Thrust 一旦触发突破，通常能抓住完整的日内大趋势。
2.  **抗震荡干扰**: 在波动率极低的日子里，Range 变小，轨道收窄；在高波动后的整理期，Range 变大，轨道变宽。这种动态调整天然过滤了许多震荡噪音。
3.  **鲁棒性高**: 核心参数仅有 $N$（回看天数）和 $K$（触发系数），不易过拟合，在不同币种（BTC/ETH/SOL）上通用性好。

### 缺点
1.  **假突破风险**: 加密货币常见的“插针”行情会导致价格短暂突破轨道后迅速回落，造成高位接盘止损。
2.  **无明确止盈**: 原始策略通常持有到收盘或反向信号触发，这在波动剧烈的币圈容易导致大幅利润回撤。
3.  **开盘价定义**: 24/7 交易没有明确的“开盘价”，通常使用 UTC 00:00，但该时间点的价格具有一定随机性。

## 5. Autofish 集成方案

Autofish Bot V2 本质上是一个震荡策略（网格/马丁），而 Dual Thrust 是趋势策略。两者的结合点在于利用 Dual Thrust 划定**震荡的安全边界**。

### 方案 A: 状态过滤器 (State Filter) - 推荐
将 Dual Thrust 的轨道作为 Autofish 运行的“安全区”。

- **逻辑**:
    - **价格在轨道内 ($Sell_{trigger} < P < Buy_{trigger}$)**: 市场处于震荡或弱趋势，**Autofish 正常运行**。
    - **价格突破轨道 ($P > Buy_{trigger}$ 或 $P < Sell_{trigger}$)**: 市场进入强趋势，**Autofish 暂停开新单**，甚至平仓止损。
- **优势**: 简单有效，避免了震荡策略最害怕的单边突破行情。

### 方案 B: 顺势网格 (Trend Grid)
利用 Dual Thrust 的方向性指导网格交易的方向。

- **逻辑**:
    - **突破上轨**: 市场看多，Autofish 切换为**仅做多 (Long Only)** 网格，禁止开空单。
    - **跌破下轨**: 市场看空，Autofish 切换为**仅做空 (Short Only)** 网格，禁止开多单。
- **优势**: 在趋势行情中也能获利，而不是完全停止交易。

### 方案 C: 动态网格参数 (Dynamic Parameters)
利用 Dual Thrust 的 $Range$ 来动态调整网格间距。

- **逻辑**:
    - $Range$ 反映了近期的波动率。
    - 当 $Range$ 较大时，说明市场波动剧烈，Autofish 应**增大网格间距**，防止被轻易穿仓。
    - 当 $Range$ 较小时，说明市场窄幅震荡，Autofish 应**减小网格间距**，增加套利频率。

### 方案 D: 结合 FreqAI
利用 FreqAI 预测波动率来动态调整 $K$ 值。

- **逻辑**:
    - FreqAI 预测未来高波动 -> 调大 $K$ 值（让突破更难触发，过滤假动作）。
    - FreqAI 预测未来低波动 -> 调小 $K$ 值（更敏感地捕捉趋势）。

## 6. 实施建议

在 Autofish Bot V2 中，建议优先实施 **方案 A (状态过滤器)**。这不需要修改核心网格逻辑，只需在 `MarketStatusDetector` 中增加一个 `DualThrustAlgorithm` 即可。

```python
class DualThrustAlgorithm(StatusAlgorithm):
    def calculate(self, klines):
        # ... 计算 Range 和 上下轨 ...
        if price > upper_band:
            return MarketStatus.TRENDING_UP
        elif price < lower_band:
            return MarketStatus.TRENDING_DOWN
        else:
            return MarketStatus.RANGING
```
