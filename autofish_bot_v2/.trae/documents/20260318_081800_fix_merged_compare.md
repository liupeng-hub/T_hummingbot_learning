# 修复合并对比显示问题

## 问题分析

在 `renderMergedCompare` 函数的 overlay 模式（K线上方色带）中，我修改后的代码结构有问题：

**原代码逻辑**：
- 每个 dataset 创建一个 candlestick series
- 每个 series 有自己的 markArea（行情色带）
- 通过 `layerGap * dsIdx` 让不同算法的色带在不同层级

**我修改后的错误逻辑**：
- 把所有 markAreaData 合并成一个数组
- 只创建一个 candlestick series
- 导致所有色带叠加在一起，布局混乱

## 修复方案

恢复原来的逻辑结构，但只使用第一个 dataset 的 K 线数据：

```javascript
} else {
    const barHeight = priceRange * 0.008;
    const gapRatio = 0.03;
    const layerGap = priceRange * 0.08;
    
    const series = [];
    const legendData = [];
    
    datasets.forEach((ds, dsIdx) => {
        const baseGap = layerGap * dsIdx;
        
        const markAreaData = ds.statusGroups.map(group => {
            const gap = priceRange * gapRatio;
            const barY = group.highPrice + baseGap + gap;
            const color = getStatusColor(group.status);
            
            return [
                {
                    xAxis: group.startIndex,
                    yAxis: barY,
                    name: getStatusText(group.status),
                    itemStyle: {
                        color: color.replace(')', ', 0.6)'),
                    },
                },
                {
                    xAxis: group.endIndex + 1,
                    yAxis: barY + barHeight,
                }
            ];
        });
        
        legendData.push(ds.name);
        
        // 只使用第一个 dataset 的 K 线数据
        const ohlcData = dsIdx === 0 ? ds.ohlc : [];
        
        series.push({
            name: ds.name,
            type: 'candlestick',
            data: ohlcData,  // 只有第一个 dataset 有 K 线数据
            itemStyle: {
                color: '#ef4444',
                color0: '#22c55e',
                borderColor: '#ef4444',
                borderColor0: '#22c55e',
            },
            markArea: {
                silent: true,
                data: markAreaData,  // 每个 dataset 有自己的 markArea
            },
            z: dsIdx + 1,
        });
    });
    
    // ... rest of the option
}
```

## 修改文件

`web/visualizer/index.html` - `renderMergedCompare` 函数中的 overlay 模式部分
