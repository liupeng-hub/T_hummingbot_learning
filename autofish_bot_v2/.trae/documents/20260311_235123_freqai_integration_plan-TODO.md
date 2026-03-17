# Autofish Bot V2 与 FreqAI 整合计划

## 目标
整合 Freqtrade 的 FreqAI 模块到 Autofish Bot V2，以提升市场状态（震荡 vs 趋势）的判断能力。FreqAI 将作为“信号提供者”，分析市场并输出状态，供 Autofish Bot V2（“消费者”）读取，从而决定是否进行交易。

## 架构设计

1.  **Freqtrade (信号提供者)**:
    *   运行专用的 FreqAI 策略。
    *   利用机器学习（如 XGBoost/LightGBM）预测市场趋势或波动率。
    *   实时将推断结果（市场状态）写入共享的 JSON 文件。
2.  **共享存储**:
    *   位于 `autofish_bot_v2/market_status.json` 的 JSON 文件。
3.  **Autofish Bot V2 (消费者)**:
    *   在 `market_status_detector.py` 中新增 `FreqAIAlgorithm` 类。
    *   读取 JSON 文件。
    *   将 FreqAI 的预测转换为 `MarketStatus`（RANGING 震荡, TRENDING_UP 上涨趋势, TRENDING_DOWN 下跌趋势）。
    *   若信号过期或缺失，则回退到内部逻辑或保持原有状态。

## 详细步骤

### 第一阶段：环境与配置 (Freqtrade)
1.  **验证 Freqtrade 安装**:
    *   使用现有的 `T_freqtrade` 目录。
    *   确保已安装 FreqAI 依赖（通过 `pip install -r requirements-freqai.txt` 或 `uv`）。
2.  **创建 FreqAI 配置**:
    *   创建 `T_freqtrade/user_data/config_freqai_provider.json`。
    *   启用 `freqai` 部分。
    *   配置 `exchange`、`pair_whitelist`（需与 Autofish 目标交易对一致）和 `timeframe`。
    *   设置 `runmode` 为 `dry_run`（仅需信号，无需实际交易）。

### 第二阶段：FreqAI 策略实现
1.  **创建策略文件**:
    *   创建 `T_freqtrade/user_data/strategies/FreqaiTrendProvider.py`。
2.  **实现逻辑**:
    *   继承 `IStrategy`。
    *   定义 `populate_indicators`:
        *   调用 `self.freqai.start(dataframe, metadata)`。
    *   定义 `populate_entry_trend`:
        *   提取预测结果（例如 `&s-up_or_down`, `&s-volatility`）。
        *   根据预测阈值确定市场状态。
        *   **输出到文件**: 将状态、置信度和时间戳写入 `market_status.json`。
        *   目标路径: `/Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/market_status.json`。

### 第三阶段：Autofish 整合
1.  **创建 FreqAI 算法类**:
    *   修改 `autofish_bot_v2/market_status_detector.py`。
    *   添加 `FreqAIAlgorithm(StatusAlgorithm)` 类。
    *   实现 `calculate` 方法:
        *   读取 `market_status.json`。
        *   检查时间戳有效性（例如 < 5 分钟）。
        *   根据文件内容返回 `StatusResult`。
        *   处理错误（文件缺失、数据过期），返回 `UNKNOWN` 或回退。
2.  **注册算法**:
    *   将 `freqai` 添加到 `MarketStatusDetector.ALGORITHMS`。

### 第四阶段：执行与验证
1.  **启动 Freqtrade**:
    *   运行 `freqtrade trade --config user_data/config_freqai_provider.json --strategy FreqaiTrendProvider`。
2.  **启动 Autofish 分析**:
    *   运行 `python market_status_detector.py --algorithm freqai --symbol BTCUSDT`。
3.  **验证**:
    *   检查 `market_status.json` 是否在更新。
    *   检查 Autofish 是否正确读取并显示状态。

## 文件位置
*   **Freqtrade 根目录**: `/Users/liupeng/Documents/trae_projects/T_freqtrade`
*   **Autofish 根目录**: `/Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2`
*   **共享信号文件**: `/Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/market_status.json`
