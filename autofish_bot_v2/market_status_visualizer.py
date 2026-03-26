#!/usr/bin/env python3
"""
行情状态可视化系统

集成了数据获取、算法运行、状态整合、报告生成、Web服务器等完整功能。

使用方法:
    命令行模式:
        python market_status_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310
        python market_status_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310 --algorithm dual_thrust
    
    Web服务器模式:
        python market_status_visualizer.py --server
"""

import os
import sys
import argparse
import asyncio
import re
import json
import time
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from decimal import Decimal
import sqlite3

import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS

plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'STHeiti', 'Hiragino Sans GB', 'Microsoft YaHei', 'WenQuanYi Micro Hei']
plt.rcParams['axes.unicode_minus'] = False

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from binance_kline_fetcher import KlineFetcher
from market_status_detector import (
    MarketStatusDetector,
    DualThrustAlgorithm,
    ImprovedStatusAlgorithm,
    AlwaysRangingAlgorithm,
    CompositeAlgorithm,
    ADXAlgorithm,
    RealTimeStatusAlgorithm,
    MarketStatus,
    StatusResult,
)
from database.test_results_db import (
    TestResultsDB,
    MarketVisualizerCase,
    MarketVisualizerResult,
)


@dataclass
class DailyStatus:
    """每日行情状态"""
    date: str
    timestamp: int
    status: MarketStatus
    confidence: float
    reason: str
    open_price: float
    close_price: float
    high_price: float
    low_price: float


@dataclass
class StatusRange:
    """行情状态区间"""
    start_date: str
    end_date: str
    status: MarketStatus
    duration: int
    start_price: float
    end_price: float
    price_change: float


@dataclass
class StatusChangeEvent:
    """状态变化事件"""
    date: str
    from_status: MarketStatus
    to_status: MarketStatus
    price: float
    reason: str


class DataProvider:
    """数据提供者 - 负责获取K线数据"""
    
    def __init__(self):
        self.fetcher = KlineFetcher()
    
    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """获取K线数据"""
        start_time = int(start_date.timestamp() * 1000)
        end_time = int(end_date.timestamp() * 1000)
        
        return await self.fetcher.fetch_kline(
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time
        )
    
    def klines_to_dataframe(self, klines: List[Dict]) -> pd.DataFrame:
        """将K线数据转换为DataFrame"""
        if not klines:
            return pd.DataFrame()
        
        df = pd.DataFrame(klines)
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('datetime', inplace=True)
        df = df[['open', 'high', 'low', 'close', 'volume']]
        df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = df[col].astype(float)
        
        return df


class AlgorithmRunner:
    """算法运行器 - 负责运行行情判断算法"""
    
    ALGORITHMS = {
        'dual_thrust': DualThrustAlgorithm,
        'improved': ImprovedStatusAlgorithm,
        'always_ranging': AlwaysRangingAlgorithm,
        'composite': CompositeAlgorithm,
        'adx': ADXAlgorithm,
        'realtime': RealTimeStatusAlgorithm,
    }
    
    def __init__(self, algorithm_name: str, algorithm_config: Dict):
        self.algorithm_name = algorithm_name
        self.algorithm_config = algorithm_config
        self.algorithm = self._create_algorithm()
    
    def _create_algorithm(self):
        """创建算法实例（空配置时算法类会自动使用默认配置）"""
        algo_class = self.ALGORITHMS.get(self.algorithm_name, AlwaysRangingAlgorithm)
        return algo_class(self.algorithm_config if self.algorithm_config else None)
    
    def run(self, klines: List[Dict]) -> List[DailyStatus]:
        """运行算法，获取每日状态"""
        results = []
        
        min_periods = self.algorithm.get_required_periods()
        
        for i in range(min_periods, len(klines)):
            window = klines[:i + 1]
            current_kline = klines[i]
            
            status_result = self.algorithm.calculate(window, self.algorithm_config)
            
            daily_status = DailyStatus(
                date=datetime.fromtimestamp(current_kline['timestamp'] / 1000).strftime('%Y-%m-%d'),
                timestamp=current_kline['timestamp'],
                status=status_result.status,
                confidence=status_result.confidence,
                reason=status_result.reason,
                open_price=current_kline['open'],
                close_price=current_kline['close'],
                high_price=current_kline['high'],
                low_price=current_kline['low'],
            )
            results.append(daily_status)
        
        return results


class StatusIntegrator:
    """状态整合器 - 负责将每日状态整合为区间"""
    
    def integrate(self, daily_statuses: List[DailyStatus]) -> Tuple[List[StatusRange], List[StatusChangeEvent]]:
        """整合每日状态为区间"""
        if not daily_statuses:
            return [], []
        
        ranges = []
        events = []
        
        current_status = daily_statuses[0].status
        start_date = daily_statuses[0].date
        start_price = daily_statuses[0].open_price
        
        for i, ds in enumerate(daily_statuses):
            if ds.status != current_status:
                end_price = daily_statuses[i - 1].close_price
                price_change = ((end_price - start_price) / start_price) * 100
                
                ranges.append(StatusRange(
                    start_date=start_date,
                    end_date=daily_statuses[i - 1].date,
                    status=current_status,
                    duration=i - daily_statuses.index(next(d for d in daily_statuses if d.date == start_date)),
                    start_price=start_price,
                    end_price=end_price,
                    price_change=price_change,
                ))
                
                events.append(StatusChangeEvent(
                    date=ds.date,
                    from_status=current_status,
                    to_status=ds.status,
                    price=ds.open_price,
                    reason=ds.reason,
                ))
                
                current_status = ds.status
                start_date = ds.date
                start_price = ds.open_price
        
        if daily_statuses:
            end_price = daily_statuses[-1].close_price
            price_change = ((end_price - start_price) / start_price) * 100
            
            ranges.append(StatusRange(
                start_date=start_date,
                end_date=daily_statuses[-1].date,
                status=current_status,
                duration=len(daily_statuses) - sum(r.duration for r in ranges),
                start_price=start_price,
                end_price=end_price,
                price_change=price_change,
            ))
        
        return ranges, events
    
    def calculate_statistics(self, daily_statuses: List[DailyStatus], ranges: List[StatusRange]) -> Dict:
        """计算统计信息"""
        if not daily_statuses or not ranges:
            return {}
        
        total_intervals = len(daily_statuses)
        
        status_intervals = {
            MarketStatus.RANGING: 0,
            MarketStatus.TRENDING_UP: 0,
            MarketStatus.TRENDING_DOWN: 0,
        }
        
        for ds in daily_statuses:
            if ds.status in status_intervals:
                status_intervals[ds.status] += 1
        
        status_counts = {
            MarketStatus.RANGING: 0,
            MarketStatus.TRENDING_UP: 0,
            MarketStatus.TRENDING_DOWN: 0,
        }
        
        for r in ranges:
            if r.status in status_counts:
                status_counts[r.status] += 1
        
        return {
            'total_intervals': total_intervals,
            'status_intervals': status_intervals,
            'status_percent': {
                k: (v / total_intervals * 100) if total_intervals > 0 else 0
                for k, v in status_intervals.items()
            },
            'status_counts': status_counts,
            'total_ranges': len(ranges),
        }


class ReportGenerator:
    """报告生成器 - 负责生成MD报告"""
    
    STATUS_NAMES = {
        MarketStatus.RANGING: '震荡',
        MarketStatus.TRENDING_UP: '上涨',
        MarketStatus.TRENDING_DOWN: '下跌',
        MarketStatus.UNKNOWN: '未知',
        MarketStatus.TRANSITIONING: '过渡',
    }
    
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
    
    def generate(
        self,
        symbol: str,
        interval: str,
        date_range: str,
        algorithm: str,
        algorithm_config: Dict,
        daily_statuses: List[DailyStatus],
        ranges: List[StatusRange],
        events: List[StatusChangeEvent],
        statistics: Dict,
        seq: int,
    ) -> str:
        """生成MD报告"""
        
        lines = []
        lines.append("# 行情可视化分析报告")
        lines.append("")
        
        lines.append("## 基本信息")
        lines.append("")
        lines.append(f"- 交易对: {symbol}")
        lines.append(f"- 时间范围: {date_range}")
        lines.append(f"- K线周期: {interval}")
        lines.append(f"- 算法: {algorithm}")
        
        config_str = ", ".join([f"{k}={v}" for k, v in algorithm_config.items() if v is not None])
        if config_str:
            lines.append(f"- 算法参数: {config_str}")
        lines.append("")
        
        lines.append("## 统计摘要")
        lines.append("")
        lines.append("| 状态 | 周期数 | 占比 | 区间数 |")
        lines.append("|------|--------|------|--------|")
        
        for status in [MarketStatus.RANGING, MarketStatus.TRENDING_UP, MarketStatus.TRENDING_DOWN]:
            name = self.STATUS_NAMES.get(status, '未知')
            intervals = statistics['status_intervals'].get(status, 0)
            percent = statistics['status_percent'].get(status, 0)
            counts = statistics['status_counts'].get(status, 0)
            lines.append(f"| {name} | {intervals} | {percent:.1f}% | {counts} |")
        lines.append("")
        
        lines.append("## 区间行情状态")
        lines.append("")
        lines.append("| 序号 | 开始日期 | 结束日期 | 状态 | 持续周期 | 起始价 | 结束价 | 涨跌幅 |")
        lines.append("|------|----------|----------|------|----------|--------|--------|--------|")
        
        for i, r in enumerate(ranges, 1):
            name = self.STATUS_NAMES.get(r.status, '未知')
            change_sign = '+' if r.price_change >= 0 else ''
            lines.append(f"| {i} | {r.start_date} | {r.end_date} | {name} | {r.duration} | {r.start_price:.2f} | {r.end_price:.2f} | {change_sign}{r.price_change:.1f}% |")
        lines.append("")
        
        lines.append("## 每日行情状态（前30天）")
        lines.append("")
        lines.append("| 日期 | 状态 | 置信度 | 原因 |")
        lines.append("|------|------|--------|------|")
        
        for ds in daily_statuses[:30]:
            name = self.STATUS_NAMES.get(ds.status, '未知')
            lines.append(f"| {ds.date} | {name} | {ds.confidence:.2f} | {ds.reason} |")
        lines.append("")
        
        if events:
            lines.append("## 状态变化事件")
            lines.append("")
            lines.append("| 日期 | 从状态 | 到状态 | 价格 | 原因 |")
            lines.append("|------|--------|--------|------|------|")
            
            for e in events:
                from_name = self.STATUS_NAMES.get(e.from_status, '未知')
                to_name = self.STATUS_NAMES.get(e.to_status, '未知')
                lines.append(f"| {e.date} | {from_name} | {to_name} | {e.price:.2f} | {e.reason} |")
            lines.append("")
        
        content = "\n".join(lines)
        
        filename = f"market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq:03d}.md"
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return filepath


class ChartVisualizer:
    """图表可视化器 - 负责绘制K线图"""
    
    STATUS_COLORS = {
        MarketStatus.RANGING: ('green', 0.2),
        MarketStatus.TRENDING_UP: ('red', 0.2),
        MarketStatus.TRENDING_DOWN: ('blue', 0.2),
    }
    
    STATUS_NAMES = {
        MarketStatus.RANGING: '震荡',
        MarketStatus.TRENDING_UP: '上涨',
        MarketStatus.TRENDING_DOWN: '下跌',
    }
    
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
    
    def plot(
        self,
        df: pd.DataFrame,
        daily_statuses: List[DailyStatus],
        ranges: List[StatusRange],
        symbol: str,
        interval: str,
        date_range: str,
        algorithm: str,
        seq: int,
    ) -> str:
        """绘制K线图并标注行情状态"""
        
        if df.empty:
            return ""
        
        fill_between = []
        
        for r in ranges:
            try:
                start_idx = df.index.get_indexer([pd.to_datetime(r.start_date)], method='nearest')[0]
                end_idx = df.index.get_indexer([pd.to_datetime(r.end_date)], method='nearest')[0]
                
                if start_idx >= 0 and end_idx >= 0:
                    color, alpha = self.STATUS_COLORS.get(r.status, ('gray', 0.2))
                    
                    y_min = df['Low'].iloc[start_idx:end_idx + 1].min() * 0.98
                    y_max = df['High'].iloc[start_idx:end_idx + 1].max() * 1.02
                    
                    fill_between.append(
                        dict(
                            y1=y_max,
                            y2=y_min,
                            where=(df.index >= df.index[start_idx]) & (df.index <= df.index[end_idx]),
                            color=color,
                            alpha=alpha,
                        )
                    )
            except Exception:
                continue
        
        mc = mpf.make_marketcolors(
            up='red',
            down='green',
            edge='inherit',
            wick='inherit',
            volume='in',
        )
        
        style = mpf.make_mpf_style(
            marketcolors=mc,
            gridstyle='-',
            gridcolor='lightgray',
            y_on_right=False,
        )
        
        legend_patches = [
            mpatches.Patch(color='green', alpha=0.3, label='Ranging'),
            mpatches.Patch(color='red', alpha=0.3, label='Trending Up'),
            mpatches.Patch(color='blue', alpha=0.3, label='Trending Down'),
        ]
        
        title = f"{symbol} {interval} {date_range}\nAlgorithm: {algorithm}"
        
        num_days = len(df)
        if num_days > 1500:
            fig_width = 40
            fig_height = 20
            dpi = 200
        elif num_days > 1000:
            fig_width = 32
            fig_height = 16
            dpi = 180
        elif num_days > 500:
            fig_width = 28
            fig_height = 14
            dpi = 150
        else:
            fig_width = 20
            fig_height = 12
            dpi = 150
        
        fig, axes = mpf.plot(
            df,
            type='candle',
            style=style,
            title=title,
            ylabel='Price',
            ylabel_lower='Volume',
            volume=True,
            figsize=(fig_width, fig_height),
            fill_between=fill_between,
            returnfig=True,
        )
        
        ax = axes[0]
        ax.legend(handles=legend_patches, loc='upper left', fontsize=10)
        
        filename = f"market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq:03d}.png"
        filepath = os.path.join(self.output_dir, filename)
        
        fig.savefig(filepath, dpi=dpi, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        
        return filepath


class WebChartVisualizer:
    """Web图表可视化器 - 负责生成交互式K线图HTML"""
    
    STATUS_COLORS = {
        MarketStatus.RANGING: ('rgba(34, 197, 94, 0.3)', 'rgba(34, 197, 94, 0.1)'),
        MarketStatus.TRENDING_UP: ('rgba(239, 68, 68, 0.3)', 'rgba(239, 68, 68, 0.1)'),
        MarketStatus.TRENDING_DOWN: ('rgba(59, 130, 246, 0.3)', 'rgba(59, 130, 246, 0.1)'),
    }
    
    STATUS_NAMES = {
        MarketStatus.RANGING: '震荡',
        MarketStatus.TRENDING_UP: '上涨',
        MarketStatus.TRENDING_DOWN: '下跌',
    }
    
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
    
    def generate_html(
        self,
        df: pd.DataFrame,
        daily_statuses: List['DailyStatus'],
        ranges: List['StatusRange'],
        symbol: str,
        interval: str,
        date_range: str,
        algorithm: str,
        algorithm_config: Dict,
        statistics: Dict,
        seq: int,
    ) -> str:
        """生成交互式HTML K线图"""
        
        dates = df.index.strftime('%Y-%m-%d').tolist()
        ohlc = df[['Open', 'Close', 'Low', 'High']].values.tolist()
        volumes = df['Volume'].tolist()
        
        mark_areas = []
        for r in ranges:
            color, _ = self.STATUS_COLORS.get(r.status, ('rgba(128, 128, 128, 0.3)', 'rgba(128, 128, 128, 0.1)'))
            status_name = self.STATUS_NAMES.get(r.status, '未知')
            
            start_idx = dates.index(r.start_date) if r.start_date in dates else -1
            end_idx = dates.index(r.end_date) if r.end_date in dates else -1
            
            if start_idx >= 0 and end_idx >= 0:
                mark_areas.append([
                    {
                        'xAxis': r.start_date,
                        'name': f'{status_name}',
                        'itemStyle': {'color': color},
                    },
                    {
                        'xAxis': r.end_date,
                        'label': {
                            'show': True,
                            'formatter': f'{status_name} ({r.duration}天)',
                            'position': 'insideTop',
                            'color': '#333',
                            'fontSize': 11,
                        }
                    }
                ])
        
        status_intervals = statistics.get('status_intervals', {})
        status_percent = statistics.get('status_percent', {})
        
        config_str = ", ".join([f"{k}={v}" for k, v in algorithm_config.items() if v is not None])
        
        html_template = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>行情可视化分析 - {symbol}</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: #f5f5f5; }}
        .container {{ max-width: 1600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 12px; margin-bottom: 20px; }}
        .header h1 {{ font-size: 28px; margin-bottom: 10px; }}
        .header .info {{ display: flex; gap: 30px; flex-wrap: wrap; margin-top: 15px; }}
        .header .info-item {{ background: rgba(255,255,255,0.15); padding: 8px 16px; border-radius: 20px; font-size: 14px; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .stat-card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .stat-card h3 {{ font-size: 14px; color: #666; margin-bottom: 8px; }}
        .stat-card .value {{ font-size: 28px; font-weight: bold; }}
        .stat-card.ranging .value {{ color: #22c55e; }}
        .stat-card.up .value {{ color: #ef4444; }}
        .stat-card.down .value {{ color: #3b82f6; }}
        .chart-container {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 20px; }}
        #chart {{ width: 100%; height: 700px; }}
        .legend {{ display: flex; gap: 20px; justify-content: center; padding: 15px; background: white; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .legend-item {{ display: flex; align-items: center; gap: 8px; font-size: 14px; }}
        .legend-color {{ width: 24px; height: 24px; border-radius: 4px; }}
        .legend-color.ranging {{ background: rgba(34, 197, 94, 0.3); }}
        .legend-color.up {{ background: rgba(239, 68, 68, 0.3); }}
        .legend-color.down {{ background: rgba(59, 130, 246, 0.3); }}
        .table-container {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); overflow-x: auto; }}
        .table-container h2 {{ margin-bottom: 15px; color: #333; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; font-weight: 600; position: sticky; top: 0; }}
        tr:hover {{ background: #f8f9fa; }}
        .status-badge {{ padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 500; }}
        .status-badge.ranging {{ background: #dcfce7; color: #166534; }}
        .status-badge.up {{ background: #fee2e2; color: #991b1b; }}
        .status-badge.down {{ background: #dbeafe; color: #1e40af; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 行情可视化分析报告</h1>
            <div class="info">
                <span class="info-item">交易对: {symbol}</span>
                <span class="info-item">时间范围: {date_range}</span>
                <span class="info-item">K线周期: {interval}</span>
                <span class="info-item">算法: {algorithm}</span>
                {f'<span class="info-item">参数: {config_str}</span>' if config_str else ''}
            </div>
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <h3>总周期数</h3>
                <div class="value">{statistics.get('total_intervals', 0)}</div>
            </div>
            <div class="stat-card ranging">
                <h3>震荡周期</h3>
                <div class="value">{status_intervals.get('ranging', 0)} ({status_percent.get('ranging', 0):.1f}%)</div>
            </div>
            <div class="stat-card up">
                <h3>上涨周期</h3>
                <div class="value">{status_intervals.get('trending_up', 0)} ({status_percent.get('trending_up', 0):.1f}%)</div>
            </div>
            <div class="stat-card down">
                <h3>下跌周期</h3>
                <div class="value">{status_intervals.get('trending_down', 0)} ({status_percent.get('trending_down', 0):.1f}%)</div>
            </div>
        </div>
        
        <div class="legend">
            <div class="legend-item"><div class="legend-color ranging"></div><span>震荡区间</span></div>
            <div class="legend-item"><div class="legend-color up"></div><span>上涨趋势</span></div>
            <div class="legend-item"><div class="legend-color down"></div><span>下跌趋势</span></div>
        </div>
        
        <div class="chart-container">
            <div id="chart"></div>
        </div>
        
        <div class="table-container">
            <h2>📋 区间行情状态</h2>
            <table>
                <thead>
                    <tr>
                        <th>序号</th>
                        <th>开始日期</th>
                        <th>结束日期</th>
                        <th>状态</th>
                        <th>持续天数</th>
                        <th>起始价</th>
                        <th>结束价</th>
                        <th>涨跌幅</th>
                    </tr>
                </thead>
                <tbody>
                    {self._generate_table_rows(ranges)}
                </tbody>
            </table>
        </div>
    </div>
    
    <script>
        var chart = echarts.init(document.getElementById('chart'));
        
        var option = {{
            title: {{
                text: '{symbol} K线图',
                left: 'center',
                top: 10
            }},
            tooltip: {{
                trigger: 'axis',
                axisPointer: {{
                    type: 'cross'
                }},
                backgroundColor: 'rgba(255, 255, 255, 0.9)',
                borderColor: '#ccc',
                borderWidth: 1,
                textStyle: {{
                    color: '#333'
                }},
                formatter: function(params) {{
                    var kline = params[0];
                    var vol = params[1];
                    var date = kline.name;
                    var data = kline.data;
                    return '<div style="padding: 5px;">' +
                        '<strong>' + date + '</strong><br/>' +
                        '开盘: ' + data[1] + '<br/>' +
                        '收盘: ' + data[2] + '<br/>' +
                        '最低: ' + data[3] + '<br/>' +
                        '最高: ' + data[4] + '<br/>' +
                        '成交量: ' + (vol ? vol.data : 0) + '</div>';
                }}
            }},
            legend: {{
                data: ['K线', '成交量'],
                top: 40
            }},
            grid: [
                {{ left: '10%', right: '8%', top: 80, height: '55%' }},
                {{ left: '10%', right: '8%', top: '75%', height: '15%' }}
            ],
            xAxis: [
                {{
                    type: 'category',
                    data: {json.dumps(dates)},
                    boundaryGap: true,
                    axisLine: {{ onZero: false }},
                    splitLine: {{ show: false }},
                    min: 'dataMin',
                    max: 'dataMax'
                }},
                {{
                    type: 'category',
                    gridIndex: 1,
                    data: {json.dumps(dates)},
                    boundaryGap: true,
                    axisLine: {{ onZero: false }},
                    axisTick: {{ show: false }},
                    splitLine: {{ show: false }},
                    axisLabel: {{ show: false }},
                    min: 'dataMin',
                    max: 'dataMax'
                }}
            ],
            yAxis: [
                {{
                    scale: true,
                    splitArea: {{ show: true }}
                }},
                {{
                    scale: true,
                    gridIndex: 1,
                    splitNumber: 2,
                    axisLabel: {{ show: false }},
                    axisLine: {{ show: false }},
                    axisTick: {{ show: false }},
                    splitLine: {{ show: false }}
                }}
            ],
            dataZoom: [
                {{
                    type: 'inside',
                    xAxisIndex: [0, 1],
                    start: 0,
                    end: 100
                }},
                {{
                    show: true,
                    xAxisIndex: [0, 1],
                    type: 'slider',
                    bottom: 10,
                    start: 0,
                    end: 100
                }}
            ],
            series: [
                {{
                    name: 'K线',
                    type: 'candlestick',
                    data: {json.dumps(ohlc)},
                    itemStyle: {{
                        color: '#ef4444',
                        color0: '#22c55e',
                        borderColor: '#ef4444',
                        borderColor0: '#22c55e'
                    }},
                    markArea: {{
                        silent: true,
                        data: {json.dumps(mark_areas)}
                    }}
                }},
                {{
                    name: '成交量',
                    type: 'bar',
                    xAxisIndex: 1,
                    yAxisIndex: 1,
                    data: {json.dumps(volumes)},
                    itemStyle: {{
                        color: function(params) {{
                            return params.dataIndex % 2 === 0 ? '#ef4444' : '#22c55e';
                        }}
                    }}
                }}
            ]
        }};
        
        chart.setOption(option);
        
        window.addEventListener('resize', function() {{
            chart.resize();
        }});
    </script>
</body>
</html>'''
        
        filename = f"market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq:03d}.html"
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_template)
        
        return filepath
    
    def _generate_table_rows(self, ranges: List['StatusRange']) -> str:
        """生成表格行HTML"""
        rows = []
        for i, r in enumerate(ranges, 1):
            status_name = self.STATUS_NAMES.get(r.status, '未知')
            status_class = {
                MarketStatus.RANGING: 'ranging',
                MarketStatus.TRENDING_UP: 'up',
                MarketStatus.TRENDING_DOWN: 'down',
            }.get(r.status, '')
            
            change_sign = '+' if r.price_change >= 0 else ''
            change_class = 'up' if r.price_change >= 0 else 'down'
            
            row = f'''<tr>
                <td>{i}</td>
                <td>{r.start_date}</td>
                <td>{r.end_date}</td>
                <td><span class="status-badge {status_class}">{status_name}</span></td>
                <td>{r.duration}</td>
                <td>{r.start_price:.2f}</td>
                <td>{r.end_price:.2f}</td>
                <td style="color: {'#ef4444' if r.price_change >= 0 else '#22c55e'}">{change_sign}{r.price_change:.1f}%</td>
            </tr>'''
            rows.append(row)
        
        return '\n'.join(rows)


class MarketStatusVisualizer:
    """主控制器 - 协调各组件工作"""
    
    def __init__(self, args):
        self.args = args
        self.output_dir = args.output_dir or 'out/test_report/visualizer'
        
        os.makedirs(self.output_dir, exist_ok=True)
        
        self.data_provider = DataProvider()
        self.report_generator = ReportGenerator(self.output_dir)
        self.chart_visualizer = ChartVisualizer(self.output_dir)
        self.web_chart_visualizer = WebChartVisualizer(self.output_dir)
        self.db = TestResultsDB()
    
    def _parse_date_range(self, date_range: str) -> Tuple[datetime, datetime]:
        """解析日期范围"""
        parts = date_range.split('-')
        if len(parts) != 2:
            raise ValueError(f"日期范围格式错误: {date_range}")
        
        start_date = datetime.strptime(parts[0], '%Y%m%d')
        end_date = datetime.strptime(parts[1], '%Y%m%d')
        
        return start_date, end_date
    
    def _build_algorithm_config(self) -> Dict:
        """构建算法配置"""
        # 优先使用 --algorithm-params JSON 参数
        if self.args.algorithm_params:
            try:
                params = json.loads(self.args.algorithm_params)
                if 'params' in params:
                    return params['params']
                return params
            except json.JSONDecodeError as e:
                print(f"[警告] 算法参数 JSON 解析失败: {e}")
        
        # 使用默认配置
        return {}
    
    def _get_next_seq(self, symbol: str, interval: str, date_range: str, algorithm: str) -> int:
        """获取下一个序列号"""
        pattern = f"market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_(\\d+)\\.md"
        
        max_seq = 0
        for filename in os.listdir(self.output_dir):
            match = re.match(pattern, filename)
            if match:
                seq = int(match.group(1))
                max_seq = max(max_seq, seq)
        
        return max_seq + 1
    
    async def run(self):
        """运行可视化流程"""
        print(f"\n{'='*60}")
        print("行情状态可视化分析")
        print(f"{'='*60}")
        print(f"  交易对: {self.args.symbol}")
        print(f"  时间范围: {self.args.date_range}")
        print(f"  K线周期: {self.args.interval}")
        print(f"  算法: {self.args.algorithm}")
        print(f"  输出目录: {self.output_dir}")
        print(f"{'='*60}\n")
        
        start_time = time.time()
        start_date, end_date = self._parse_date_range(self.args.date_range)
        
        print("📥 获取K线数据...")
        klines = await self.data_provider.get_klines(
            symbol=self.args.symbol,
            interval=self.args.interval,
            start_date=start_date,
            end_date=end_date,
        )
        print(f"  获取到 {len(klines)} 根K线")
        
        if not klines:
            print("❌ 没有获取到K线数据")
            return
        
        print("\n🔄 运行行情判断算法...")
        algorithm_config = self._build_algorithm_config()
        runner = AlgorithmRunner(self.args.algorithm, algorithm_config)
        daily_statuses = runner.run(klines)
        print(f"  计算了 {len(daily_statuses)} 天的行情状态")
        
        print("\n📊 整合行情状态区间...")
        integrator = StatusIntegrator()
        ranges, events = integrator.integrate(daily_statuses)
        statistics = integrator.calculate_statistics(daily_statuses, ranges)
        print(f"  整合为 {len(ranges)} 个区间")
        print(f"  状态变化 {len(events)} 次")
        
        seq = self._get_next_seq(self.args.symbol, self.args.interval, self.args.date_range, self.args.algorithm)
        
        generate_all = getattr(self.args, 'generate_all', True)  # 默认生成所有文件
        
        if generate_all:
            print("\n📝 生成MD报告...")
            report_path = self.report_generator.generate(
                symbol=self.args.symbol,
                interval=self.args.interval,
                date_range=self.args.date_range,
                algorithm=self.args.algorithm,
                algorithm_config=algorithm_config,
                daily_statuses=daily_statuses,
                ranges=ranges,
                events=events,
                statistics=statistics,
                seq=seq,
            )
            print(f"  报告已保存: {report_path}")
            
            print("\n📈 生成K线图...")
            df = self.data_provider.klines_to_dataframe(klines)
            chart_path = self.chart_visualizer.plot(
                df=df,
                daily_statuses=daily_statuses,
                ranges=ranges,
                symbol=self.args.symbol,
                interval=self.args.interval,
                date_range=self.args.date_range,
                algorithm=self.args.algorithm,
                seq=seq,
            )
            print(f"  图表已保存: {chart_path}")
            
            print("\n🌐 生成Web可视化...")
            df = self.data_provider.klines_to_dataframe(klines)
            html_path = self.web_chart_visualizer.generate_html(
                df=df,
                daily_statuses=daily_statuses,
                ranges=ranges,
                symbol=self.args.symbol,
                interval=self.args.interval,
                date_range=self.args.date_range,
                algorithm=self.args.algorithm,
                algorithm_config=algorithm_config,
                statistics=statistics,
                seq=seq,
            )
            print(f"  HTML已保存: {html_path}")
        
        print(f"\n{'='*60}")
        print("统计摘要")
        print(f"{'='*60}")
        print(f"  总周期数: {statistics['total_intervals']}")
        print(f"  震荡: {statistics['status_intervals'][MarketStatus.RANGING]} 周期 ({statistics['status_percent'][MarketStatus.RANGING]:.1f}%)")
        print(f"  上涨: {statistics['status_intervals'][MarketStatus.TRENDING_UP]} 周期 ({statistics['status_percent'][MarketStatus.TRENDING_UP]:.1f}%)")
        print(f"  下跌: {statistics['status_intervals'][MarketStatus.TRENDING_DOWN]} 周期 ({statistics['status_percent'][MarketStatus.TRENDING_DOWN]:.1f}%)")
        print(f"{'='*60}\n")
        
        print("\n💾 保存到数据库...")
        case = MarketVisualizerCase(
            name=f"{self.args.symbol}_{self.args.algorithm}_{self.args.date_range}",
            symbol=self.args.symbol,
            interval=self.args.interval,
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d'),
            algorithm=self.args.algorithm,
            algorithm_config=json.dumps(algorithm_config),
            description=f"命令行执行: {self.args.date_range}",
        )
        case_id = self.db.create_visualizer_case(case)
        
        status_ranges = []
        for r in ranges:
            status_ranges.append({
                'status': r.status.value,
                'start_date': r.start_date,
                'end_date': r.end_date,
                'duration': r.duration,
                'start_price': r.start_price,
                'end_price': r.end_price,
                'price_change': r.price_change,
            })
        
        result = MarketVisualizerResult(
            case_id=case_id,
            total_intervals=statistics['total_intervals'],
            ranging_intervals=statistics['status_intervals'][MarketStatus.RANGING],
            trending_up_intervals=statistics['status_intervals'][MarketStatus.TRENDING_UP],
            trending_down_intervals=statistics['status_intervals'][MarketStatus.TRENDING_DOWN],
            ranging_count=statistics['status_counts'][MarketStatus.RANGING],
            trending_up_count=statistics['status_counts'][MarketStatus.TRENDING_UP],
            trending_down_count=statistics['status_counts'][MarketStatus.TRENDING_DOWN],
            status_ranges=json.dumps(status_ranges),
            duration_ms=int((time.time() - start_time) * 1000),
        )
        result_id = self.db.create_visualizer_result(result)
        
        daily_statuses_db = []
        for ds in daily_statuses:
            daily_statuses_db.append({
                'date': ds.date,
                'status': ds.status.value,
                'confidence': ds.confidence,
                'reason': ds.reason,
                'open_price': ds.open_price,
                'close_price': ds.close_price,
                'high_price': ds.high_price,
                'low_price': ds.low_price,
                'volume': 0,
            })
        
        self.db.create_visualizer_details(result_id, daily_statuses_db)
        
        print(f"  测试用例ID: {case_id}")
        print(f"  测试结果ID: {result_id}")
        print(f"  已保存到数据库")


ALGORITHMS = {
    'dual_thrust': {
        'name': 'Dual Thrust',
        'description': 'Dual Thrust 状态过滤器（增强版）- 基于历史波动幅度构建突破区间，针对下跌行情有特殊处理',
        'params': {
            'n_days': {'type': 'int', 'default': 4, 'description': '回看天数'},
            'k1': {'type': 'float', 'default': 0.4, 'description': '上轨系数 K1'},
            'k2': {'type': 'float', 'default': 0.4, 'description': '下轨系数 K2'},
            'k2_down_factor': {'type': 'float', 'default': 0.8, 'description': '下跌敏感系数'},
            'down_confirm_days': {'type': 'int', 'default': 2, 'description': '下跌确认天数'},
            'cooldown_days': {'type': 'int', 'default': 1, 'description': '冷却期(天)'},
        }
    },
    'improved': {
        'name': 'Improved Status',
        'description': '改进的行情判断算法 - 支撑阻力位识别 + 箱体震荡识别，更严格的趋势确认',
        'params': {
            'lookback_period': {'type': 'int', 'default': 60, 'description': '回看周期'},
            'min_range_duration': {'type': 'int', 'default': 10, 'description': '最小震荡持续天数'},
            'max_range_pct': {'type': 'float', 'default': 0.15, 'description': '最大震荡区间比例'},
            'breakout_threshold': {'type': 'float', 'default': 0.03, 'description': '突破阈值'},
            'breakout_confirm_days': {'type': 'int', 'default': 3, 'description': '突破确认天数'},
            'swing_window': {'type': 'int', 'default': 5, 'description': '摆动窗口'},
            'merge_threshold': {'type': 'float', 'default': 0.03, 'description': '合并阈值'},
            'min_touches': {'type': 'int', 'default': 3, 'description': '最小触及次数'},
        }
    },
    'always_ranging': {
        'name': 'Always Ranging',
        'description': '始终返回震荡行情 - 用于与原 binance_backtest 的测试结果对比',
        'params': {}
    },
    'composite': {
        'name': 'Composite',
        'description': '组合算法 - ADX + ATR + 布林带宽度综合判断，多指标融合',
        'params': {
            'adx_period': {'type': 'int', 'default': 14, 'description': 'ADX 周期'},
            'adx_threshold': {'type': 'int', 'default': 25, 'description': 'ADX 阈值'},
            'atr_period': {'type': 'int', 'default': 14, 'description': 'ATR 周期'},
            'atr_multiplier': {'type': 'float', 'default': 1.5, 'description': 'ATR 乘数'},
            'bb_period': {'type': 'int', 'default': 20, 'description': '布林带周期'},
            'bb_std': {'type': 'float', 'default': 2.0, 'description': '布林带标准差'},
            'bb_width_threshold': {'type': 'float', 'default': 0.04, 'description': '布林带宽度阈值'},
            'ma_period': {'type': 'int', 'default': 50, 'description': 'MA 周期'},
        }
    },
    'adx': {
        'name': 'ADX',
        'description': '基于 ADX 的趋势强度判断 - ADX>=阈值时为趋势行情，否则为震荡',
        'params': {
            'period': {'type': 'int', 'default': 14, 'description': 'ADX 周期'},
            'threshold': {'type': 'int', 'default': 25, 'description': '趋势阈值'},
        }
    },
    'realtime': {
        'name': 'RealTime',
        'description': '实时市场状态判断算法 - 价格行为+波动率，增加状态惯性，震荡状态更稳定',
        'params': {
            'lookback_period': {'type': 'int', 'default': 20, 'description': '回看周期'},
            'breakout_threshold': {'type': 'float', 'default': 0.02, 'description': '突破阈值'},
            'consecutive_bars': {'type': 'int', 'default': 3, 'description': '连续K线数'},
            'atr_period': {'type': 'int', 'default': 14, 'description': 'ATR 周期'},
            'expansion_threshold': {'type': 'float', 'default': 1.5, 'description': '扩张阈值'},
            'contraction_threshold': {'type': 'float', 'default': 0.7, 'description': '收缩阈值'},
            'confirm_periods': {'type': 'int', 'default': 2, 'description': '确认周期数'},
            'min_trend_signals': {'type': 'int', 'default': 4, 'description': '最小趋势信号数'},
            'min_trend_confidence': {'type': 'float', 'default': 0.8, 'description': '最小趋势置信度'},
            'min_range_duration': {'type': 'int', 'default': 5, 'description': '最小震荡持续天数'},
        }
    }
}

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT']


def visualizer_case_to_dict(case: Dict) -> Dict:
    """将行情可视化用例转换为字典"""
    return {
        'id': case.get('id'),
        'name': case.get('name'),
        'symbol': case.get('symbol'),
        'interval': case.get('interval'),
        'start_date': case.get('start_date'),
        'end_date': case.get('end_date'),
        'algorithm': case.get('algorithm'),
        'algorithm_config': case.get('algorithm_config', {}),
        'description': case.get('description', ''),
        'created_at': case.get('created_at'),
        'updated_at': case.get('updated_at'),
        'status': case.get('status'),
    }


def visualizer_result_to_dict(result: Dict) -> Dict:
    """将行情可视化结果转换为字典"""
    return {
        'id': result.get('id'),
        'test_case_id': result.get('case_id'),
        'total_intervals': result.get('total_intervals'),
        'ranging_intervals': result.get('ranging_intervals'),
        'trending_up_intervals': result.get('trending_up_intervals'),
        'trending_down_intervals': result.get('trending_down_intervals'),
        'ranging_count': result.get('ranging_count'),
        'trending_up_count': result.get('trending_up_count'),
        'trending_down_count': result.get('trending_down_count'),
        'status_ranges': result.get('status_ranges', []),
        'executed_at': result.get('executed_at'),
        'duration_ms': result.get('duration_ms'),
    }


def visualizer_detail_to_dict(status: Dict) -> Dict:
    """将行情可视化详情转换为字典"""
    amplitude = 0
    if status.get('open_price') and status['open_price'] > 0:
        amplitude = (status['high_price'] - status['low_price']) / status['open_price'] * 100

    return {
        'id': status.get('id'),
        'result_id': status.get('result_id'),
        'date': status.get('date'),
        'status': status.get('status'),
        'confidence': status.get('confidence'),
        'reason': status.get('reason'),
        'open_price': status.get('open_price'),
        'close_price': status.get('close_price'),
        'high_price': status.get('high_price'),
        'low_price': status.get('low_price'),
        'volume': status.get('volume'),
        'amplitude': round(amplitude, 2),
    }


def integrate_status_ranges(daily_results: List[Dict]) -> List[Dict]:
    """将每日状态整合为区间"""
    if not daily_results:
        return []
    
    ranges = []
    current_range = None
    
    for dr in daily_results:
        if current_range is None:
            current_range = {
                'status': dr['status'],
                'start_date': dr['date'],
                'end_date': dr['date'],
                'start_price': dr['open'],
                'end_price': dr['close'],
                'duration': 1,
            }
        elif dr['status'] == current_range['status']:
            current_range['end_date'] = dr['date']
            current_range['end_price'] = dr['close']
            current_range['duration'] += 1
        else:
            start_price = current_range['start_price']
            end_price = current_range['end_price']
            current_range['price_change'] = round((end_price - start_price) / start_price * 100, 2)
            ranges.append(current_range)
            
            current_range = {
                'status': dr['status'],
                'start_date': dr['date'],
                'end_date': dr['date'],
                'start_price': dr['open'],
                'end_price': dr['close'],
                'duration': 1,
            }
    
    if current_range:
        start_price = current_range['start_price']
        end_price = current_range['end_price']
        current_range['price_change'] = round((end_price - start_price) / start_price * 100, 2)
        ranges.append(current_range)
    
    return ranges


class MarketVisualizerServer:
    """Web服务器类"""
    
    def __init__(self, port: int = 5001, output_dir: str = None):
        self.port = port
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.output_dir = output_dir or os.path.join(base_dir, 'out/test_report/visualizer')
        os.makedirs(self.output_dir, exist_ok=True)
        
        self.db = TestResultsDB()
        
        self._setup_logging()
        self.app = self._create_app()
    
    def _setup_logging(self):
        """设置日志"""
        logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        
        log_file = os.path.join(logs_dir, 'market_visualizer_server.log')
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger('MarketVisualizerServer')
    
    def _create_app(self) -> Flask:
        """创建Flask应用"""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        app = Flask(__name__, 
                    template_folder=os.path.join(base_dir, 'web/visualizer'))
        CORS(app)
        
        self.logger.info("服务器初始化完成")
        
        @app.route('/')
        def index():
            self.logger.info("访问主页")
            return send_from_directory(os.path.join(base_dir, 'web/visualizer'), 'index.html')
        
        @app.route('/api/test-cases', methods=['GET'])
        def get_test_cases():
            symbol = request.args.get('symbol')
            algorithm = request.args.get('algorithm')
            status = request.args.get('status')
            limit = request.args.get('limit', 100, type=int)
            offset = request.args.get('offset', 0, type=int)
            
            self.logger.info(f"获取测试用例列表: symbol={symbol}, algorithm={algorithm}, status={status}")
            
            cases = self.db.list_visualizer_cases(
                filters={'symbol': symbol, 'algorithm': algorithm, 'status': status} if any([symbol, algorithm, status]) else None,
                limit=limit,
                offset=offset
            )
            
            total = self.db.count_visualizer_cases({'symbol': symbol, 'algorithm': algorithm, 'status': status} if any([symbol, algorithm, status]) else None)
            
            return jsonify({
                'success': True,
                'data': {
                    'items': [visualizer_case_to_dict(c) for c in cases],
                    'total': total,
                    'limit': limit,
                    'offset': offset
                }
            })
        
        @app.route('/api/test-cases/<test_case_id>', methods=['GET'])
        def get_test_case(test_case_id: str):
            self.logger.info(f"获取测试用例详情: {test_case_id}")
            
            case = self.db.get_visualizer_case(test_case_id)
            if case is None:
                return jsonify({'success': False, 'error': '测试用例不存在'}), 404
            
            result = self.db.get_visualizer_result_by_case(test_case_id)
            
            data = visualizer_case_to_dict(case)
            data['result'] = visualizer_result_to_dict(result) if result else None
            
            return jsonify({'success': True, 'data': data})
        
        @app.route('/api/test-cases', methods=['POST'])
        def create_test_case():
            data = request.get_json()
            
            self.logger.info(f"创建新测试: {data}")
            
            required_fields = ['name', 'symbol', 'start_date', 'end_date', 'algorithm']
            for field in required_fields:
                if field not in data:
                    return jsonify({'success': False, 'error': f'缺少必填字段: {field}'}), 400
            
            algorithm = data['algorithm']
            if algorithm not in ALGORITHMS:
                return jsonify({'success': False, 'error': f'不支持的算法: {algorithm}'}), 400
            
            case = MarketVisualizerCase(
                name=data['name'],
                symbol=data['symbol'],
                interval=data.get('interval', '1d'),
                start_date=data['start_date'],
                end_date=data['end_date'],
                algorithm=algorithm,
                algorithm_config=json.dumps(data.get('algorithm_config', {})),
                description=data.get('description', ''),
            )
            case_id = self.db.create_visualizer_case(case)
            
            self.logger.info(f"测试用例已创建: {case_id} - {case.name}")
            
            generate_files = {
                'md': data.get('generate_md', False),
                'png': data.get('generate_png', False),
                'html': data.get('generate_html', False),
            }
            
            thread = threading.Thread(
                target=self._execute_test_async,
                args=(case_id, generate_files)
            )
            thread.start()
            
            case_dict = {
                'case_id': case_id,
                'name': case.name,
                'symbol': case.symbol,
                'interval': case.interval,
                'start_date': case.start_date,
                'end_date': case.end_date,
                'algorithm': case.algorithm,
                'algorithm_config': json.loads(case.algorithm_config) if case.algorithm_config else {},
                'description': case.description,
                'status': case.status,
            }
            
            return jsonify({
                'success': True,
                'data': case_dict,
                'message': '测试已开始执行'
            })
        
        @app.route('/api/test-cases/<test_case_id>/re-run', methods=['POST'])
        def re_run_test(test_case_id: str):
            self.logger.info(f"重新执行测试: {test_case_id}")
            
            case = self.db.get_visualizer_case(test_case_id)
            if case is None:
                return jsonify({'success': False, 'error': '测试用例不存在'}), 404
            
            self.db.update_visualizer_case_status(test_case_id, 'pending')
            
            thread = threading.Thread(
                target=self._execute_test_async,
                args=(test_case_id,)
            )
            thread.start()
            
            return jsonify({
                'success': True,
                'message': '测试已开始重新执行'
            })
        
        @app.route('/api/test-cases/<test_case_id>', methods=['DELETE'])
        def delete_test_case(test_case_id: str):
            self.logger.info(f"删除测试用例: {test_case_id}")
            
            case = self.db.get_visualizer_case(test_case_id)
            if case is None:
                return jsonify({'success': False, 'error': '测试用例不存在'}), 404
            
            self.db.delete_visualizer_case(test_case_id)
            
            return jsonify({'success': True, 'message': '删除成功'})
        
        @app.route('/api/test-results/<test_result_id>', methods=['GET'])
        def get_test_result(test_result_id: str):
            self.logger.info(f"获取测试结果: {test_result_id}")
            
            result = self.db.get_visualizer_result(test_result_id)
            if result is None:
                return jsonify({'success': False, 'error': '测试结果不存在'}), 404
            
            return jsonify({'success': True, 'data': visualizer_result_to_dict(result)})
        
        @app.route('/api/daily-statuses/<test_result_id>', methods=['GET'])
        def get_daily_statuses(test_result_id: str):
            self.logger.info(f"获取每日状态数据: {test_result_id}")
            
            statuses = self.db.get_visualizer_details(test_result_id)
            
            return jsonify({
                'success': True,
                'data': [visualizer_detail_to_dict(s) for s in statuses]
            })
        
        @app.route('/api/statistics/<test_result_id>', methods=['GET'])
        def get_statistics(test_result_id: str):
            self.logger.info(f"获取统计信息: {test_result_id}")
            
            stats = self.db.get_visualizer_statistics(test_result_id)
            
            return jsonify({'success': True, 'data': stats})
        
        @app.route('/api/klines', methods=['GET'])
        def get_klines():
            symbol = request.args.get('symbol')
            interval = request.args.get('interval', '1d')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            
            self.logger.info(f"获取K线数据: symbol={symbol}, interval={interval}")
            
            if not symbol or not start_date or not end_date:
                return jsonify({'success': False, 'error': '缺少必要参数'}), 400
            
            try:
                fetcher = KlineFetcher()
                klines = asyncio.run(fetcher.get_klines(
                    symbol=symbol,
                    interval=interval,
                    start_time=start_date,
                    end_time=end_date
                ))
                
                return jsonify({
                    'success': True,
                    'data': klines
                })
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @app.route('/api/symbols', methods=['GET'])
        def get_symbols():
            return jsonify({'success': True, 'data': SYMBOLS})
        
        @app.route('/api/algorithms', methods=['GET'])
        def get_algorithms():
            return jsonify({'success': True, 'data': ALGORITHMS})
        
        @app.route('/api/algorithm-params/<algorithm_name>', methods=['GET'])
        def get_algorithm_params(algorithm_name: str):
            if algorithm_name not in ALGORITHMS:
                return jsonify({'success': False, 'error': '算法不存在'}), 404
            
            return jsonify({
                'success': True,
                'data': ALGORITHMS[algorithm_name]['params']
            })
        
        @app.route('/api/compare', methods=['POST'])
        def compare_tests():
            try:
                data = request.get_json()
                test_case_ids = data.get('test_case_ids', [])
                
                if len(test_case_ids) < 2:
                    return jsonify({'success': False, 'error': '至少需要选择2个测试'}), 400
                
                if len(test_case_ids) > 4:
                    return jsonify({'success': False, 'error': '最多只能对比4个测试'}), 400
                
                results = []
                for tc_id in test_case_ids:
                    case = self.db.get_visualizer_case(tc_id)
                    if case is None:
                        continue
                    
                    result = self.db.get_visualizer_result_by_case(tc_id)
                    result_id = result.get('result_id') if result else None
                    stats = self.db.get_visualizer_statistics(result_id) if result_id else None
                    daily_statuses = self.db.get_visualizer_details(result_id) if result_id else []
                    
                    results.append({
                        'test_case': visualizer_case_to_dict(case),
                        'result': visualizer_result_to_dict(result) if result else None,
                        'statistics': stats,
                        'daily_statuses': [visualizer_detail_to_dict(s) for s in daily_statuses],
                    })
                
                return jsonify({'success': True, 'data': results})
            except Exception as e:
                self.logger.error(f"对比测试异常: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        return app
    
    def _execute_test_async(self, test_case_id: str, generate_files: Dict = None):
        """异步执行测试"""
        if generate_files is None:
            generate_files = {'md': False, 'png': False, 'html': False}
        
        try:
            self.logger.info(f"[{test_case_id}] 开始执行测试")
            self.db.update_visualizer_case_status(test_case_id, 'running')
            
            case = self.db.get_visualizer_case(test_case_id)
            if case is None:
                self.logger.error(f"[{test_case_id}] 测试用例不存在")
                return
            
            start_time = time.time()
            
            self.logger.info(f"[{test_case_id}] 开始获取K线数据...")
            fetcher = KlineFetcher()
            
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                start_ts = int(datetime.strptime(case['start_date'], '%Y-%m-%d').timestamp() * 1000)
                end_ts = int(datetime.strptime(case['end_date'], '%Y-%m-%d').timestamp() * 1000) + 86400000 - 1
                
                klines = loop.run_until_complete(fetcher.fetch_kline(
                    symbol=case['symbol'],
                    interval=case['interval'],
                    start_time=start_ts,
                    end_time=end_ts
                ))
                loop.close()
            except Exception as e:
                self.logger.error(f"[{test_case_id}] 获取K线数据异常: {e}")
                self.db.update_visualizer_case_status(test_case_id, 'failed')
                return
            
            if not klines:
                self.logger.error(f"[{test_case_id}] 获取K线数据失败或数据为空")
                self.db.update_visualizer_case_status(test_case_id, 'failed')
                return
            
            self.logger.info(f"[{test_case_id}] 获取到 {len(klines)} 条K线数据")
            
            self.logger.info(f"[{test_case_id}] 开始运行算法: {case['algorithm']}")
            config = case.get('algorithm_config', {}) or {}
            runner = AlgorithmRunner(case['algorithm'], config)
            
            daily_results = runner.run(klines)
            self.logger.info(f"[{test_case_id}] 算法运行完成, 得到 {len(daily_results)} 条每日状态")
            
            status_ranges = integrate_status_ranges([{
                'date': dr.date,
                'status': dr.status.value,
                'open': dr.open_price,
                'close': dr.close_price,
            } for dr in daily_results])
            self.logger.info(f"[{test_case_id}] 整合得到 {len(status_ranges)} 个状态区间")
            
            daily_statuses = []
            ranging_intervals = trending_up_intervals = trending_down_intervals = 0
            ranging_count = trending_up_count = trending_down_count = 0
            
            for dr in daily_results:
                daily_statuses.append({
                    'date': dr.date,
                    'status': dr.status.value,
                    'confidence': dr.confidence,
                    'reason': dr.reason,
                    'open_price': dr.open_price,
                    'close_price': dr.close_price,
                    'high_price': dr.high_price,
                    'low_price': dr.low_price,
                    'volume': 0,
                })
                
                if dr.status.value == 'ranging':
                    ranging_intervals += 1
                elif dr.status.value == 'trending_up':
                    trending_up_intervals += 1
                else:
                    trending_down_intervals += 1
            
            for sr in status_ranges:
                if sr['status'] == 'ranging':
                    ranging_count += 1
                elif sr['status'] == 'trending_up':
                    trending_up_count += 1
                else:
                    trending_down_count += 1
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            result = MarketVisualizerResult(
                case_id=test_case_id,
                total_intervals=len(daily_results),
                ranging_intervals=ranging_intervals,
                trending_up_intervals=trending_up_intervals,
                trending_down_intervals=trending_down_intervals,
                ranging_count=ranging_count,
                trending_up_count=trending_up_count,
                trending_down_count=trending_down_count,
                status_ranges=json.dumps(status_ranges),
                duration_ms=duration_ms,
            )
            result_id = self.db.create_visualizer_result(result)
            
            self.db.create_visualizer_details(result_id, daily_statuses)
            
            self.logger.info(f"[{test_case_id}] 生成输出文件...")
            try:
                viz_daily_statuses = daily_results
                
                viz_ranges = []
                for sr in status_ranges:
                    viz_r = StatusRange(
                        start_date=sr['start_date'],
                        end_date=sr['end_date'],
                        status=MarketStatus(sr['status']),
                        duration=sr['duration'],
                        start_price=sr['start_price'],
                        end_price=sr['end_price'],
                        price_change=sr['price_change'],
                    )
                    viz_ranges.append(viz_r)
                
                statistics = {
                    'total_intervals': len(daily_results),
                    'status_intervals': {
                        MarketStatus.RANGING: ranging_intervals,
                        MarketStatus.TRENDING_UP: trending_up_intervals,
                        MarketStatus.TRENDING_DOWN: trending_down_intervals,
                    },
                    'status_percent': {
                        MarketStatus.RANGING: round(ranging_intervals / len(daily_results) * 100, 1) if daily_results else 0,
                        MarketStatus.TRENDING_UP: round(trending_up_intervals / len(daily_results) * 100, 1) if daily_results else 0,
                        MarketStatus.TRENDING_DOWN: round(trending_down_intervals / len(daily_results) * 100, 1) if daily_results else 0,
                    },
                    'status_counts': {
                        MarketStatus.RANGING: ranging_count,
                        MarketStatus.TRENDING_UP: trending_up_count,
                        MarketStatus.TRENDING_DOWN: trending_down_count,
                    },
                }
                
                date_range_str = f"{case['start_date'].replace('-', '')}-{case['end_date'].replace('-', '')}"
                
                existing_files = [f for f in os.listdir(self.output_dir) if f.startswith(f"market_visualizer_{case['symbol']}_{case['interval']}_{date_range_str}_{case['algorithm']}")]
                seq = len([f for f in existing_files if f.endswith('.md')]) + 1
                
                if generate_files.get('md', False):
                    report_gen = ReportGenerator(self.output_dir)
                    report_path = report_gen.generate(
                        symbol=case['symbol'],
                        interval=case['interval'],
                        date_range=date_range_str,
                        algorithm=case['algorithm'],
                        algorithm_config=config,
                        daily_statuses=viz_daily_statuses,
                        ranges=viz_ranges,
                        events=[],
                        statistics=statistics,
                        seq=seq,
                    )
                    self.logger.info(f"[{test_case_id}] MD报告已生成: {report_path}")
                
                if generate_files.get('png', False) or generate_files.get('html', False):
                    df_data = []
                    for ds in daily_statuses:
                        df_data.append({
                            'datetime': ds['date'],
                            'Open': ds['open_price'],
                            'High': ds['high_price'],
                            'Low': ds['low_price'],
                            'Close': ds['close_price'],
                            'Volume': ds['volume'],
                        })
                    df = pd.DataFrame(df_data)
                    df['datetime'] = pd.to_datetime(df['datetime'])
                    df.set_index('datetime', inplace=True)
                    
                    if generate_files.get('png', False):
                        chart_viz = ChartVisualizer(self.output_dir)
                        chart_path = chart_viz.plot(
                            df=df,
                            daily_statuses=viz_daily_statuses,
                            ranges=viz_ranges,
                            symbol=case['symbol'],
                            interval=case['interval'],
                            date_range=date_range_str,
                            algorithm=case['algorithm'],
                            seq=seq,
                        )
                        self.logger.info(f"[{test_case_id}] PNG图表已生成: {chart_path}")
                    
                    if generate_files.get('html', False):
                        web_viz = WebChartVisualizer(self.output_dir)
                        html_path = web_viz.generate_html(
                            df=df,
                            daily_statuses=viz_daily_statuses,
                            ranges=viz_ranges,
                            symbol=case.symbol,
                            interval=case.interval,
                            date_range=date_range_str,
                            algorithm=case.algorithm,
                            algorithm_config=config,
                            statistics=statistics,
                            seq=seq,
                        )
                        self.logger.info(f"[{test_case_id}] HTML已生成: {html_path}")
                
            except Exception as e:
                self.logger.error(f"[{test_case_id}] 生成文件失败: {e}")
                import traceback
                traceback.print_exc()
            
            self.db.update_visualizer_case_status(test_case_id, 'completed')
            self.logger.info(f"[{test_case_id}] 测试完成")
            
        except Exception as e:
            print(f"执行测试失败: {e}")
            import traceback
            traceback.print_exc()
            self.db.update_visualizer_case_status(test_case_id, 'failed')
    
    def run(self):
        """启动服务器"""
        print(f"启动行情可视化服务器...")
        print(f"访问地址: http://localhost:{self.port}")
        self.app.run(host='0.0.0.0', port=self.port, debug=True)


def main():
    parser = argparse.ArgumentParser(description="行情状态可视化系统")
    
    parser.add_argument('--server', action='store_true', help='启动Web服务器模式')
    parser.add_argument('--port', type=int, default=5001, help='Web服务器端口 (默认: 5001)')
    
    parser.add_argument('--symbol', default='BTCUSDT', help='交易对')
    parser.add_argument('--date-range', help='时间范围 (格式: yyyymmdd-yyyymmdd)')
    parser.add_argument('--interval', default='1d', help='K线周期 (默认: 1d)')
    parser.add_argument('--algorithm', default='dual_thrust', 
                        choices=['dual_thrust', 'improved', 'always_ranging', 'composite', 'adx', 'realtime'],
                        help='行情判断算法')
    parser.add_argument('--algorithm-params', type=str, default=None, help='算法参数 (JSON格式)')
    parser.add_argument('--output-dir', default='out/market_visualizer', help='输出目录')
    parser.add_argument('--generate-all', action='store_true', help='生成所有文件(MD+PNG+HTML)')
    
    args = parser.parse_args()
    
    if args.server:
        server = MarketVisualizerServer(port=args.port, output_dir=args.output_dir)
        server.run()
    else:
        if not args.date_range:
            parser.error("命令行模式需要指定 --date-range 参数")
        visualizer = MarketStatusVisualizer(args)
        asyncio.run(visualizer.run())


if __name__ == '__main__':
    main()
