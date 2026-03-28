// Autofish V2 实盘监控前端

const API_BASE = '/api';
let refreshInterval = null;

// 格式化数字
function formatNumber(num, decimals = 2) {
    if (num === null || num === undefined) return '-';
    return parseFloat(num).toFixed(decimals);
}

// 格式化货币
function formatCurrency(num) {
    if (num === null || num === undefined) return '-';
    const value = parseFloat(num);
    const sign = value >= 0 ? '+' : '';
    return sign + value.toFixed(2) + ' USDT';
}

// 获取状态颜色类
function getProfitClass(value) {
    if (value > 0) return 'profit';
    if (value < 0) return 'loss';
    return '';
}

// 获取订单级别样式
function getLevelClass(level) {
    return `level-${level}`;
}

// 获取订单状态样式
function getStateClass(state) {
    return `state-${state}`;
}

// 加载数据
async function loadData() {
    try {
        await Promise.all([
            loadStatus(),
            loadOrders(),
            loadCapital(),
            loadStats()
        ]);
        document.getElementById('last-update').textContent = '最后更新: ' + new Date().toLocaleTimeString();
    } catch (error) {
        console.error('加载数据失败:', error);
        showError('加载数据失败: ' + error.message);
    }
}

// 显示错误
function showError(message) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error';
    errorDiv.textContent = message;
    document.getElementById('status').prepend(errorDiv);
    setTimeout(() => errorDiv.remove(), 5000);
}

// 加载状态
async function loadStatus() {
    const response = await fetch(`${API_BASE}/status`);
    const data = await response.json();

    const statusHtml = `
        <div class="stat-grid">
            <div class="stat-item">
                <div class="stat-value">${data.symbol || '-'}</div>
                <div class="stat-label">交易对</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${data.testnet ? '测试网' : '主网'}</div>
                <div class="stat-label">网络</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${data.ws_connected ? '🟢 已连接' : '🔴 未连接'}</div>
                <div class="stat-label">WebSocket</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${data.market_status || '-'}</div>
                <div class="stat-label">行情状态</div>
            </div>
        </div>
    `;
    document.getElementById('status').innerHTML = statusHtml;
}

// 加载订单
async function loadOrders() {
    const response = await fetch(`${API_BASE}/orders`);
    const data = await response.json();

    if (!data.orders || data.orders.length === 0) {
        document.getElementById('orders').innerHTML = '<div class="card"><h2>订单列表</h2><p class="loading">暂无订单</p></div>';
        return;
    }

    const ordersHtml = data.orders.map(order => `
        <tr>
            <td><span class="order-level ${getLevelClass(order.level)}">A${order.level}</span></td>
            <td><span class="${getStateClass(order.state)}">${order.state}</span></td>
            <td>${formatNumber(order.entry_price)}</td>
            <td>${formatNumber(order.quantity, 6)}</td>
            <td>${formatNumber(order.take_profit_price)}</td>
            <td>${formatNumber(order.stop_loss_price)}</td>
            <td class="${getProfitClass(order.profit)}">${formatCurrency(order.profit)}</td>
        </tr>
    `).join('');

    document.getElementById('orders').innerHTML = `
        <div class="card full-width">
            <h2>订单列表 (${data.orders.length})</h2>
            <table class="orders-table">
                <thead>
                    <tr>
                        <th>层级</th>
                        <th>状态</th>
                        <th>入场价</th>
                        <th>数量</th>
                        <th>止盈价</th>
                        <th>止损价</th>
                        <th>盈亏</th>
                    </tr>
                </thead>
                <tbody>${ordersHtml}</tbody>
            </table>
        </div>
    `;
}

// 加载资金池
async function loadCapital() {
    const response = await fetch(`${API_BASE}/capital`);
    const data = await response.json();

    const capitalHtml = `
        <div class="stat-grid">
            <div class="stat-item">
                <div class="stat-value">${formatNumber(data.initial_capital)}</div>
                <div class="stat-label">初始资金</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${formatNumber(data.trading_capital)}</div>
                <div class="stat-label">交易资金</div>
            </div>
            <div class="stat-item">
                <div class="stat-value profit">${formatNumber(data.profit_pool)}</div>
                <div class="stat-label">利润池</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${data.withdrawal_count}</div>
                <div class="stat-label">提现次数</div>
            </div>
            <div class="stat-item">
                <div class="stat-value profit">${formatNumber(data.total_profit)}</div>
                <div class="stat-label">总盈利</div>
            </div>
            <div class="stat-item">
                <div class="stat-value loss">${formatNumber(Math.abs(data.total_loss))}</div>
                <div class="stat-label">总亏损</div>
            </div>
        </div>
    `;
    document.getElementById('capital').innerHTML = `<div class="card"><h2>资金池</h2>${capitalHtml}</div>`;
}

// 加载统计
async function loadStats() {
    const response = await fetch(`${API_BASE}/stats`);
    const data = await response.json();

    const statsHtml = `
        <div class="stat-grid">
            <div class="stat-item">
                <div class="stat-value">${data.total_trades}</div>
                <div class="stat-label">总交易数</div>
            </div>
            <div class="stat-item">
                <div class="stat-value profit">${data.win_trades}</div>
                <div class="stat-label">盈利次数</div>
            </div>
            <div class="stat-item">
                <div class="stat-value loss">${data.loss_trades}</div>
                <div class="stat-label">亏损次数</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${formatNumber(data.win_rate, 1)}%</div>
                <div class="stat-label">胜率</div>
            </div>
            <div class="stat-item">
                <div class="stat-value ${getProfitClass(data.net_profit)}">${formatCurrency(data.net_profit)}</div>
                <div class="stat-label">净盈亏</div>
            </div>
        </div>
    `;

    const statsDiv = document.getElementById('stats');
    if (statsDiv) {
        statsDiv.innerHTML = `<div class="card"><h2>交易统计</h2>${statsHtml}</div>`;
    }
}

// 开始自动刷新
function startAutoRefresh(interval = 5000) {
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
    refreshInterval = setInterval(loadData, interval);
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    // 创建布局
    const app = document.getElementById('app');
    app.innerHTML = `
        <button class="refresh-btn" onclick="loadData()">🔄 刷新</button>
        <div class="container">
            <div class="grid">
                <div id="status" class="card"><div class="loading">加载中...</div></div>
                <div id="capital" class="card"><div class="loading">加载中...</div></div>
                <div id="stats" class="card"><div class="loading">加载中...</div></div>
            </div>
            <div class="grid">
                <div id="orders"></div>
            </div>
        </div>
        <div id="last-update" class="last-update"></div>
    `;

    // 加载数据
    loadData();

    // 开始自动刷新（每 5 秒）
    startAutoRefresh(5000);
});