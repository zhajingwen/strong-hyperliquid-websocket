# 指标计算使用示例

**版本**: 1.0
**日期**: 2026-02-03

---

## 📋 快速开始

### 基础使用

```python
from address_analyzer.metrics_engine import MetricsEngine

# 准备数据
address = "0x1234..."
fills = [...]  # 交易记录列表
state = {...}  # 用户状态数据

# 计算指标
metrics = MetricsEngine.calculate_metrics(
    address=address,
    fills=fills,
    state=state
)

# 查看结果
print(f"胜率: {metrics.win_rate:.2f}%")
print(f"ROI: {metrics.roi:.2f}%")
print(f"Sharpe比率: {metrics.sharpe_ratio:.4f}")
print(f"最大回撤: {metrics.max_drawdown:.2f}%")
```

---

## 🎯 完整示例（含出入金和资金费率）

### 数据准备

```python
# 1. 交易记录
fills = [
    {
        'time': 1738483200000,  # 毫秒时间戳
        'closedPnl': '1500.50',  # 已实现盈亏
        'sz': '10.5'  # 交易规模
    },
    {
        'time': 1738569600000,
        'closedPnl': '-800.25',
        'sz': '8.2'
    },
    # ... 更多交易
]

# 2. 用户状态（含未实现盈亏和资金费率）
state = {
    'marginSummary': {
        'accountValue': '12500.75'  # 账户总价值
    },
    'assetPositions': [
        {
            'position': {
                'coin': 'BTC',
                'unrealizedPnl': '350.50',  # 未实现盈亏
                'cumFunding': {
                    'allTime': '-125.30',  # 累计资金费（负数=收益）
                    'sinceOpen': '-50.20',
                    'sinceChange': '-25.10'
                }
            }
        }
    ]
}

# 3. 出入金记录
transfer_data = {
    'ledger': [
        {
            'time': 1738310400000,
            'delta': {
                'type': 'deposit',
                'usdc': '10000'  # 充值$10,000
            }
        },
        {
            'time': 1738656000000,
            'delta': {
                'type': 'withdraw',
                'usdc': '2000'  # 提现$2,000
            }
        }
    ],
    'net_deposits': 8000.0,  # 净充值
    'total_deposits': 10000.0,
    'total_withdrawals': 2000.0,
    'actual_initial_capital': 10000.0  # 实际初始资金
}
```

### 完整计算

```python
from address_analyzer.metrics_engine import MetricsEngine

# 计算完整指标
metrics = MetricsEngine.calculate_metrics(
    address="0x1234...",
    fills=fills,
    state=state,
    transfer_data=transfer_data
)

# 基础指标
print("=== 基础指标 ===")
print(f"总交易数: {metrics.total_trades}")
print(f"胜率: {metrics.win_rate:.2f}%")
print(f"总盈亏: ${metrics.total_pnl:.2f}")
print(f"账户价值: ${metrics.account_value:.2f}")

# ROI指标
print("\n=== ROI指标 ===")
print(f"传统ROI: {metrics.roi:.2f}%")
print(f"校准ROI: {metrics.corrected_roi:.2f}%")
print(f"时间加权ROI: {metrics.time_weighted_roi:.2f}%")
print(f"年化ROI: {metrics.annualized_roi:.2f}%")
print(f"总ROI（含未实现）: {metrics.total_roi:.2f}%")
print(f"ROI质量: {metrics.roi_quality}")

# Sharpe比率
print("\n=== Sharpe比率 ===")
print(f"Sharpe比率: {metrics.sharpe_ratio:.4f}")
print(f"资金费率盈亏: ${metrics.funding_pnl:.2f}")
print(f"资金费率贡献: {metrics.funding_contribution:.2f}%")
print(f"Sharpe质量: {metrics.sharpe_quality}")

# 最大回撤
print("\n=== 最大回撤 ===")
print(f"最大回撤: {metrics.max_drawdown:.2f}%")
print(f"含未实现回撤: {metrics.max_drawdown_with_unrealized:.2f}%")
print(f"回撤次数: {metrics.drawdown_count}")
print(f"单次最大回撤: {metrics.largest_drawdown_pct:.2f}%")
print(f"回撤质量: {metrics.drawdown_quality}")

# 出入金统计
print("\n=== 出入金统计 ===")
print(f"净充值: ${metrics.net_deposits:.2f}")
print(f"总充值: ${metrics.total_deposits:.2f}")
print(f"总提现: ${metrics.total_withdrawals:.2f}")
print(f"实际初始资金: ${metrics.actual_initial_capital:.2f}")
```

---

## 🔍 分场景使用

### 场景1：仅有交易数据（基础场景）

```python
# 最小数据集
metrics = MetricsEngine.calculate_metrics(
    address="0x1234...",
    fills=fills,
    state={'marginSummary': {'accountValue': '12500'}}
)

# 质量标记
print(f"ROI质量: {metrics.roi_quality}")  # 'estimated'
print(f"回撤质量: {metrics.drawdown_quality}")  # 'estimated'
print(f"Sharpe质量: {metrics.sharpe_quality}")  # 'estimated_fallback'
```

### 场景2：有出入金数据（标准场景）

```python
metrics = MetricsEngine.calculate_metrics(
    address="0x1234...",
    fills=fills,
    state=state,
    transfer_data=transfer_data  # 提供出入金数据
)

# 质量提升
print(f"ROI质量: {metrics.roi_quality}")  # 'actual'
print(f"回撤质量: {metrics.drawdown_quality}")  # 'enhanced'
print(f"Sharpe质量: {metrics.sharpe_quality}")  # 'standard'
```

### 场景3：完整数据（最佳场景）

```python
# state包含未实现盈亏和资金费率
metrics = MetricsEngine.calculate_metrics(
    address="0x1234...",
    fills=fills,
    state=state,  # 含未实现盈亏和资金费率
    transfer_data=transfer_data
)

# 最高质量
print(f"回撤质量: {metrics.drawdown_quality}")  # 'enhanced'
print(f"Sharpe质量: {metrics.sharpe_quality}")  # 'enhanced'
print(f"含未实现回撤: {metrics.max_drawdown_with_unrealized:.2f}%")
print(f"资金费率贡献: {metrics.funding_contribution:.2f}%")
```

---

## 📊 质量标记使用指南

### 根据质量筛选

```python
def filter_high_quality_metrics(metrics_list):
    """筛选高质量指标数据"""
    return [
        m for m in metrics_list
        if m.sharpe_quality == 'enhanced'
        and m.drawdown_quality == 'enhanced'
        and m.roi_quality == 'actual'
    ]

# 使用
high_quality = filter_high_quality_metrics(all_metrics)
print(f"高质量数据: {len(high_quality)}/{len(all_metrics)}")
```

### 质量降级处理

```python
def get_recommended_roi(metrics):
    """根据质量选择最佳ROI"""
    if metrics.roi_quality == 'actual':
        # 最高质量：使用真实本金ROI
        return metrics.true_capital_roi
    elif metrics.time_weighted_roi != 0:
        # 中等质量：使用时间加权ROI
        return metrics.time_weighted_roi
    else:
        # 基础质量：使用传统ROI
        return metrics.roi

# 使用
best_roi = get_recommended_roi(metrics)
print(f"推荐ROI: {best_roi:.2f}%")
```

---

## 🎨 可视化示例

### 指标对比图

```python
import matplotlib.pyplot as plt

def plot_roi_comparison(metrics):
    """对比不同ROI计算方法"""
    labels = ['传统ROI', '校准ROI', '时间加权ROI', '年化ROI', '总ROI']
    values = [
        metrics.roi,
        metrics.corrected_roi,
        metrics.time_weighted_roi,
        metrics.annualized_roi,
        metrics.total_roi
    ]

    plt.figure(figsize=(10, 6))
    plt.bar(labels, values)
    plt.title('ROI计算方法对比')
    plt.ylabel('ROI (%)')
    plt.axhline(y=0, color='r', linestyle='--', alpha=0.3)
    plt.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.show()

# 使用
plot_roi_comparison(metrics)
```

### 质量仪表盘

```python
def print_quality_dashboard(metrics):
    """打印质量仪表盘"""
    quality_map = {
        'enhanced': '🟢 优秀',
        'actual': '🟢 真实',
        'standard': '🟡 标准',
        'estimated': '🟠 估算',
        'estimated_fallback': '🔴 降级'
    }

    print("=" * 50)
    print("📊 数据质量仪表盘")
    print("=" * 50)
    print(f"ROI质量:     {quality_map.get(metrics.roi_quality, '❓ 未知')}")
    print(f"回撤质量:    {quality_map.get(metrics.drawdown_quality, '❓ 未知')}")
    print(f"Sharpe质量:  {quality_map.get(metrics.sharpe_quality, '❓ 未知')}")
    print("=" * 50)

    # 综合评分
    scores = {
        'enhanced': 5, 'actual': 5,
        'standard': 3,
        'estimated': 2,
        'estimated_fallback': 1
    }
    avg_score = sum([
        scores.get(metrics.roi_quality, 0),
        scores.get(metrics.drawdown_quality, 0),
        scores.get(metrics.sharpe_quality, 0)
    ]) / 3

    if avg_score >= 4:
        print("✅ 综合评价: 高质量数据，可信度高")
    elif avg_score >= 3:
        print("⚠️  综合评价: 中等质量数据，谨慎使用")
    else:
        print("❌ 综合评价: 低质量数据，仅供参考")

# 使用
print_quality_dashboard(metrics)
```

---

## 🔧 高级用法

### 单独计算指标

```python
# 单独计算最大回撤
max_dd, dd_details = MetricsEngine.calculate_max_drawdown(
    fills=fills,
    account_value=12500.0,
    actual_initial_capital=10000.0,
    ledger=transfer_data['ledger'],
    address="0x1234...",
    state=state
)

print(f"最大回撤: {max_dd:.2f}%")
print(f"回撤次数: {dd_details['drawdown_count']}")
print(f"质量: {dd_details['quality']}")

# 单独计算时间加权ROI
tw_roi, ann_roi, total_roi, quality = MetricsEngine.calculate_time_weighted_roi(
    fills=fills,
    ledger=transfer_data['ledger'],
    account_value=12500.0,
    address="0x1234...",
    state=state
)

print(f"时间加权ROI: {tw_roi:.2f}%")
print(f"年化ROI: {ann_roi:.2f}%")
print(f"质量: {quality}")

# 单独计算Sharpe比率
sharpe, sharpe_details = MetricsEngine.calculate_sharpe_ratio_enhanced(
    fills=fills,
    account_value=12500.0,
    actual_initial_capital=10000.0,
    ledger=transfer_data['ledger'],
    address="0x1234...",
    state=state
)

print(f"Sharpe比率: {sharpe:.4f}")
print(f"资金费率: ${sharpe_details['funding_pnl']:.2f}")
print(f"质量: {sharpe_details['quality']}")
```

### 批量计算

```python
def batch_calculate_metrics(addresses_data):
    """批量计算多个地址的指标"""
    results = []

    for data in addresses_data:
        try:
            metrics = MetricsEngine.calculate_metrics(
                address=data['address'],
                fills=data['fills'],
                state=data['state'],
                transfer_data=data.get('transfer_data')
            )
            results.append({
                'address': data['address'],
                'metrics': metrics,
                'success': True
            })
        except Exception as e:
            results.append({
                'address': data['address'],
                'error': str(e),
                'success': False
            })

    return results

# 使用
addresses_data = [
    {'address': '0x1234...', 'fills': [...], 'state': {...}},
    {'address': '0x5678...', 'fills': [...], 'state': {...}},
    # ... 更多地址
]

results = batch_calculate_metrics(addresses_data)

# 统计
success_count = sum(1 for r in results if r['success'])
print(f"成功计算: {success_count}/{len(results)}")
```

---

## 📚 常见问题

### Q1: 为什么有多个ROI指标？

**A**: 不同场景使用不同ROI：
- **传统ROI**: 快速估算，数据不完整时使用
- **校准ROI**: 有出入金数据时更准确
- **时间加权ROI**: 公平评估不同时期的资金效率
- **年化ROI**: 跨期比较标准化指标
- **总ROI**: 包含未实现盈亏的实时收益

### Q2: 质量标记有什么用？

**A**: 帮助评估数据可靠性：
- **数据筛选**: 只使用高质量数据做决策
- **风险提示**: 低质量数据仅供参考
- **优先级排序**: 优先信任高质量指标

### Q3: 资金费率如何影响Sharpe比率？

**A**: 资金费率计入总收益：
- 做空时通常收到资金费（负数=收益）
- 做多时通常支付资金费（正数=成本）
- 影响总收益率，进而影响Sharpe比率

### Q4: 未实现盈亏如何影响回撤？

**A**: 两种回撤指标：
- **已实现回撤**: 只看已平仓交易
- **含未实现回撤**: 加上当前持仓浮动盈亏
- 含未实现回撤反映真实风险

---

## 🎯 最佳实践

### 1. 数据完整性检查

```python
def validate_data_completeness(fills, state, transfer_data):
    """检查数据完整性"""
    issues = []

    if not fills:
        issues.append("缺少交易记录")

    if not state or 'marginSummary' not in state:
        issues.append("缺少账户状态")

    if not transfer_data:
        issues.append("缺少出入金数据（ROI准确性降低）")

    if state and 'assetPositions' not in state:
        issues.append("缺少仓位数据（无法计算未实现盈亏）")

    return issues

# 使用
issues = validate_data_completeness(fills, state, transfer_data)
if issues:
    print("⚠️  数据完整性问题:")
    for issue in issues:
        print(f"  - {issue}")
```

### 2. 异常值检测

```python
def detect_anomalies(metrics):
    """检测异常指标值"""
    anomalies = []

    if abs(metrics.sharpe_ratio) > 10:
        anomalies.append(f"Sharpe比率异常: {metrics.sharpe_ratio:.2f}")

    if metrics.max_drawdown > 80:
        anomalies.append(f"回撤过大: {metrics.max_drawdown:.2f}%")

    if metrics.win_rate > 95:
        anomalies.append(f"胜率异常高: {metrics.win_rate:.2f}%")

    return anomalies

# 使用
anomalies = detect_anomalies(metrics)
if anomalies:
    print("⚠️  检测到异常值:")
    for anomaly in anomalies:
        print(f"  - {anomaly}")
```

### 3. 性能优化

```python
# 批量计算时缓存中间结果
from functools import lru_cache

@lru_cache(maxsize=1000)
def calculate_metrics_cached(address, fills_hash):
    """缓存指标计算结果"""
    # ... 计算逻辑
    pass

# 使用
import hashlib
fills_hash = hashlib.md5(str(fills).encode()).hexdigest()
metrics = calculate_metrics_cached(address, fills_hash)
```

---

**文档结束** 📘
