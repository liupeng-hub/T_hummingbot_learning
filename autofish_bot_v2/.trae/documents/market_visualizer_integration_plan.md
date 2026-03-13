# 行情可视化系统整合计划

## 任务概述

1. 将 `market_visualizer_db.py` 和 `market_visualizer_server.py` 整合到 `market_status_visualizer.py` 中
2. 整理已完成的行情可视化功能，输出设计文档
3. 提交代码到 GitHub，排除 db 文件

## 当前文件结构

```
autofish_bot_v2/
├── market_status_visualizer.py   # 主程序 - 行情可视化
├── market_visualizer_db.py       # 数据库模块 - 需要整合
├── market_visualizer_server.py   # Web服务器 - 需要整合
├── templates/
│   └── index.html                # Web前端页面
├── market_visualizer_out/        # 输出目录
│   └── market_visualizer.db      # SQLite数据库 - 需要排除
└── docs/
    └── market_visualizer_v2_spec.md
```

## 实施步骤

### 第一阶段：代码整合

#### 步骤 1.1：整合数据库模块
- [ ] 将 `market_visualizer_db.py` 中的类和函数移动到 `market_status_visualizer.py`
- [ ] 保持数据类定义：TestCase, TestResult, DailyStatus
- [ ] 保持 MarketVisualizerDB 类的所有方法
- [ ] 删除原 `market_visualizer_db.py` 文件

#### 步骤 1.2：整合 Web 服务器
- [ ] 将 `market_visualizer_server.py` 中的 Flask 应用整合到 `market_status_visualizer.py`
- [ ] 创建 `MarketVisualizerServer` 类封装服务器逻辑
- [ ] 添加命令行参数支持 `--server` 模式
- [ ] 删除原 `market_visualizer_server.py` 文件

#### 步骤 1.3：更新导入关系
- [ ] 更新 `market_status_visualizer.py` 的导入语句
- [ ] 确保所有功能正常运行

### 第二阶段：设计文档整理

#### 步骤 2.1：创建设计文档
- [ ] 整理已完成的功能列表
- [ ] 记录 API 接口设计
- [ ] 记录数据库结构设计
- [ ] 记录前端页面设计
- [ ] 记录 Dual Thrust 算法参数说明

#### 步骤 2.2：更新 README
- [ ] 更新使用说明
- [ ] 添加命令行参数说明
- [ ] 添加 Web 服务使用说明

### 第三阶段：Git 提交

#### 步骤 3.1：更新 .gitignore
- [ ] 添加 `*.db` 排除规则
- [ ] 添加 `market_visualizer_out/*.db` 排除规则
- [ ] 添加其他临时文件排除规则

#### 步骤 3.2：提交代码
- [ ] 检查待提交文件列表
- [ ] 编写提交信息
- [ ] 推送到 GitHub

## 整合后的文件结构

```
autofish_bot_v2/
├── market_status_visualizer.py   # 整合后的主程序
│   ├── 数据类定义 (TestCase, TestResult, DailyStatus)
│   ├── MarketVisualizerDB 类
│   ├── MarketVisualizerServer 类
│   ├── DataProvider 类
│   ├── MarketVisualizer 类
│   └── 命令行入口
├── templates/
│   └── index.html
├── market_visualizer_out/
│   ├── *.md
│   ├── *.png
│   └── *.html
└── docs/
    └── market_visualizer_design.md  # 新建设计文档
```

## 命令行使用方式

```bash
# CLI 模式 - 生成报告
python market_status_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310 --algorithm dual_thrust --generate-all

# Server 模式 - 启动 Web 服务
python market_status_visualizer.py --server --port 5001
```

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 整合后代码过长 | 中 | 使用类封装，保持代码结构清晰 |
| 导入冲突 | 低 | 仔细检查命名冲突 |
| 功能遗漏 | 低 | 整合后进行全面测试 |

## 验收标准

1. ✅ 整合后的 `market_status_visualizer.py` 包含所有功能
2. ✅ CLI 模式正常工作
3. ✅ Server 模式正常工作
4. ✅ 设计文档完整
5. ✅ 代码已提交到 GitHub
6. ✅ db 文件已被排除
