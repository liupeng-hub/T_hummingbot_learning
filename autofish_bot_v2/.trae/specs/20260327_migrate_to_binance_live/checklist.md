# 检查清单

## 阶段一：需求分析与设计

### 1.1 需求确认
- [ ] 确认需要移植的功能模块
- [ ] 确认数据存储方案（新建专用数据表）
- [ ] 确认 Web 展示需求
- [ ] 确认参数化封装需求

### 1.2 设计评审
- [ ] 数据表设计评审
- [ ] API 接口设计评审
- [ ] 代码修改方案评审
- [ ] 参数配置结构评审

## 阶段二：数据库实现

### 2.1 表结构创建
- [ ] live_sessions 表创建成功
- [ ] live_orders 表创建成功
- [ ] live_capital_history 表创建成功
- [ ] live_capital_statistics 表创建成功
- [ ] 索引创建成功

### 2.2 数据类实现
- [ ] LiveSession 数据类定义
- [ ] LiveOrder 数据类定义
- [ ] LiveCapitalHistory 数据类定义
- [ ] LiveCapitalStatistics 数据类定义

### 2.3 CRUD 方法实现
- [ ] create_session 方法
- [ ] get_session 方法
- [ ] list_sessions 方法
- [ ] update_session 方法
- [ ] stop_session 方法
- [ ] create_order 方法
- [ ] get_order 方法
- [ ] get_orders_by_session 方法
- [ ] update_order 方法
- [ ] update_order_state 方法
- [ ] save_capital_history 方法
- [ ] get_capital_history 方法
- [ ] save_capital_statistics 方法
- [ ] get_capital_statistics 方法

### 2.4 数据库测试
- [ ] 会话管理 CRUD 测试通过
- [ ] 订单管理 CRUD 测试通过
- [ ] 资金历史 CRUD 测试通过
- [ ] 资金统计 CRUD 测试通过
- [ ] 外键约束测试通过
- [ ] 级联删除测试通过

## 阶段三：核心功能移植

### 3.1 资金池管理
- [ ] CapitalPoolFactory 导入成功
- [ ] BinanceLiveTrader 初始化资金池
- [ ] 订单创建使用入场资金策略
- [ ] 订单平仓更新资金池
- [ ] 资金变化历史记录保存

### 3.2 入场资金策略
- [ ] EntryCapitalStrategyFactory 导入成功
- [ ] fixed 模式支持
- [ ] compound 模式支持
- [ ] default 模式支持
- [ ] 入场资金计算正确
- [ ] 入场总资金计算正确

### 3.3 入场价格策略
- [ ] EntryPriceStrategyFactory 导入成功
- [ ] fixed 策略支持
- [ ] atr 策略支持
- [ ] 入场价格计算正确

### 3.4 市场状态检测
- [ ] 现有市场状态检测逻辑分析完成
- [ ] 行情状态变化处理逻辑移植
- [ ] 停止交易逻辑实现
- [ ] 恢复交易逻辑实现
- [ ] 行情状态变化通知实现

### 3.5 A1 超时重挂
- [ ] a1_timeout_minutes 参数支持
- [ ] _check_first_entry_timeout 方法实现
- [ ] 主循环调用超时检查
- [ ] 超时重挂通知实现
- [ ] 超时重挂后订单状态正确

## 阶段四：Web API 实现

### 4.1 会话管理接口
- [ ] GET /api/live/sessions 接口
- [ ] POST /api/live/sessions 接口
- [ ] GET /api/live/sessions/<id> 接口
- [ ] DELETE /api/live/sessions/<id> 接口
- [ ] POST /api/live/sessions/<id>/stop 接口

### 4.2 订单查询接口
- [ ] GET /api/live/sessions/<id>/orders 接口
- [ ] GET /api/live/sessions/<id>/orders/<order_id> 接口
- [ ] 订单状态过滤功能
- [ ] 订单层级过滤功能
- [ ] 订单轮次过滤功能

### 4.3 资金查询接口
- [ ] GET /api/live/sessions/<id>/capital 接口
- [ ] GET /api/live/sessions/<id>/statistics 接口
- [ ] 分页功能正常
- [ ] 数据格式正确

### 4.4 实时状态接口
- [ ] GET /api/live/current 接口
- [ ] GET /api/live/current/orders 接口
- [ ] GET /api/live/current/pnl 接口
- [ ] 实时数据更新正确

## 阶段五：Web 前端实现

### 5.1 实盘会话列表页面
- [ ] 页面布局完成
- [ ] 会话列表展示
- [ ] 状态筛选功能
- [ ] 交易对筛选功能
- [ ] 分页功能
- [ ] 点击进入详情

### 5.2 实盘会话详情页面
- [ ] 页面布局完成
- [ ] 配置信息展示
- [ ] 订单列表展示
- [ ] 资金历史图表
- [ ] 盈亏统计展示
- [ ] 按轮次分组展示

## 阶段六：参数化封装

### 6.1 配置管理
- [ ] LiveConfig 类实现
- [ ] 配置加载功能
- [ ] 配置验证功能
- [ ] 默认值合并功能
- [ ] 必填字段检查

### 6.2 配置参数
- [ ] 基础参数支持
- [ ] 资金池参数支持
- [ ] 入场价格策略参数支持
- [ ] 行情感知参数支持
- [ ] 权重参数支持

### 6.3 启动入口
- [ ] 命令行参数解析
- [ ] 配置文件加载
- [ ] 测试网/主网切换

## 阶段七：测试与文档

### 7.1 单元测试
- [ ] 数据库操作测试
- [ ] 资金池计算测试
- [ ] 入场资金策略测试
- [ ] 入场价格策略测试
- [ ] 配置验证测试

### 7.2 集成测试
- [ ] 订单创建流程测试
- [ ] 订单成交流程测试
- [ ] 订单平仓流程测试
- [ ] 资金池更新流程测试
- [ ] A1 超时重挂流程测试

### 7.3 文档
- [ ] binance_live_guide.md 编写
- [ ] API 文档更新
- [ ] 配置示例文档
- [ ] 使用说明文档

## 阶段八：部署与验收

### 8.1 部署准备
- [ ] 代码审查通过
- [ ] 所有测试通过
- [ ] 文档完整
- [ ] 配置示例准备

### 8.2 功能验收
- [ ] 实盘会话创建正常
- [ ] 订单创建正常
- [ ] 订单成交处理正常
- [ ] 订单平仓处理正常
- [ ] 资金池更新正常
- [ ] 数据库存储正常
- [ ] Web 展示正常
- [ ] 参数配置正常

### 8.3 性能验收
- [ ] 数据库查询性能正常
- [ ] API 响应时间正常
- [ ] 前端加载速度正常

---

## 验收标准

### 功能完整性
- [ ] 所有规划功能已实现
- [ ] 所有接口正常工作
- [ ] 所有页面正常显示

### 代码质量
- [ ] 代码风格一致
- [ ] 无明显性能问题
- [ ] 无安全漏洞

### 文档完整性
- [ ] 使用文档完整
- [ ] API 文档完整
- [ ] 配置说明完整

### 测试覆盖
- [ ] 单元测试覆盖核心逻辑
- [ ] 集成测试覆盖主要流程
- [ ] 所有测试通过
