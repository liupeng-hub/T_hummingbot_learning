# FreqAI 集成方案分析与计划

## 1. 核心问题：如何运行 FreqAI？

在将 FreqAI 集成到 Autofish Bot V2 时，我们面临两种架构选择：

### 方案 A：作为“后台服务”运行 (推荐)
*   **运行方式**：启动一个独立的 Freqtrade 进程，配置为 `dry_run` (模拟盘) 模式。
*   **工作流**：该进程负责连接交易所、下载 K 线、计算技术指标、清洗数据、训练模型并生成预测。它将最终结果（如“趋势向上”或“震荡”）实时写入一个共享文件（JSON），Autofish Bot V2 只需读取该文件。
*   **优点**：
    1.  **解耦**：Autofish 不需要安装 Freqtrade 庞大的依赖库（TensorFlow, Torch, Scikit-learn 等），保持轻量。
    2.  **稳定**：利用 Freqtrade 成熟的数据清洗和特征工程管道，无需在 Autofish 中重写复杂的预处理逻辑。
    3.  **可视化**：可直接利用 FreqUI 网页查看 AI 的训练状态和特征重要性。
*   **缺点**：需要额外维护一个进程。

### 方案 B：作为“Python 库”引用 (Library Mode)
*   **运行方式**：在 Autofish 代码中直接 `import freqtrade.freqai`，实例化 AI 引擎。
*   **工作流**：Autofish 内部直接调用 AI 模型进行预测。
*   **缺点**：
    1.  **依赖复杂**：Autofish 环境必须安装所有 AI 相关库，且版本需与 Freqtrade 兼容。
    2.  **重复造轮子**：需要自己实现“数据下载 -> 指标计算 -> 数据归一化”的全套流程来喂给 AI，成本极高且易错。
    3.  **维护困难**：Freqtrade 内部 API 变动频繁，作为库调用容易在升级时失效。

### 结论
**我们坚持采用方案 A (后台服务模式)**。我们将 Freqtrade 视为一个**“高级行情预言机”**，它只负责输出信号，Autofish 负责执行策略。

---

## 2. 实现计划 (基于 Spec)

根据 [FreqAI Integration Spec](../../.trae/specs/freqai-integration/spec.md)，我们将按照以下步骤实施优化：

### 第一阶段：Freqtrade 端配置 (信号生产)
1.  **环境准备**：验证 FreqAI 依赖安装。
2.  **配置创建**：建立 `config_freqai_provider.json`，配置 Dry-run 模式和目标交易对。
3.  **策略开发**：编写 `FreqaiTrendProvider` 策略，专门用于输出信号而不执行交易。
    - **离线模式**：利用 FreqAI 回测生成的 `feather` 文件进行后续分析。
    - **在线模式**：实时将推断结果写入 `market_status.json`。

### 第二阶段：离线验证工作流
1.  **数据生成**：运行 Freqtrade 回测生成历史预测数据。
2.  **转换工具**：开发 `freqai_result_converter.py`，将 FreqAI 的 `feather` 结果转换为 Autofish 可读的 JSON 格式。
3.  **Autofish 回测**：修改 Autofish 回测系统，使其能加载这些历史信号文件，验证 AI 判断在策略中的实际效果。

### 第三阶段：Autofish 集成 (信号消费)
1.  **算法实现**：在 `market_status_detector.py` 中新增 `FreqAIAlgorithm` 类。
2.  **逻辑处理**：
    - 读取信号文件（实盘读 `market_status.json`，回测读转换后的历史文件）。
    - 校验信号时效性（防止使用过期数据）。
    - 实现回退机制（当 AI 信号缺失时使用备用算法）。
3.  **可视化**：更新报告生成功能，将 AI 信号叠加在 K 线图上，便于人工审查和调优。

### 第四阶段：实盘部署
1.  **实时测试**：启动 Freqtrade Dry-run 进程，验证信号写入的实时性。
2.  **延迟监控**：确保 Autofish 读取信号的延迟在可接受范围内。

详细的任务清单请参考 [Tasks](../../.trae/specs/freqai-integration/tasks.md)。
