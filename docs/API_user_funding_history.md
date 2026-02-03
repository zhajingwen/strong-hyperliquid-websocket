# user_funding_history() API 详细说明

## 📋 接口概述

`user_funding_history()` 用于获取 Hyperliquid 用户的**资金费率历史记录**（Funding Rate History）。

资金费率是永续合约特有的机制，用于使合约价格锚定现货价格：
- **正费率**：多头持仓者支付给空头持仓者
- **负费率**：空头持仓者支付给多头持仓者

---

## 🔧 方法签名

```python
def user_funding_history(
    user: str,
    startTime: int,
    endTime: Optional[int] = None
) -> List[Dict]
```

### 参数说明

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `user` | str | ✅ | 用户地址（42字符的十六进制格式，如 `0x...`） |
| `startTime` | int | ✅ | 起始时间（毫秒时间戳，包含） |
| `endTime` | int | ❌ | 结束时间（毫秒时间戳，包含），默认为当前时间 |

### 返回值

`List[Dict]` - 资金费率记录列表

---

## 📊 返回数据结构

### 完整示例

```json
{
    "time": 1762387200000,
    "hash": "0x0000000000000000000000000000000000000000000000000000000000000000",
    "delta": {
        "type": "funding",
        "coin": "BTC",
        "usdc": "-14.391152",
        "szi": "0.54353",
        "fundingRate": "0.0000106497",
        "nSamples": 24
    }
}
```

### 字段详解

#### 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `time` | int | 资金费率结算时间（毫秒时间戳） |
| `hash` | str | 交易哈希，通常为 `0x0000...` 表示系统自动结算 |
| `delta` | Dict | 资金费率详情（核心数据） |

#### delta 对象字段

| 字段 | 类型 | 说明 | 示例值 |
|------|------|------|--------|
| `type` | str | 记录类型，固定为 `"funding"` | `"funding"` |
| `coin` | str | 币种代码 | `"BTC"`, `"ETH"`, `"HYPE"` |
| `usdc` | str | **资金费用（USDC 计价）** | `"-14.391152"` |
| `szi` | str | **持仓量（Signed Size）** | `"0.54353"` |
| `fundingRate` | str | **资金费率（百分比）** | `"0.0000106497"` |
| `nSamples` | int | 样本数（通常为 24，表示统计周期） | `24` |

---

## 💡 核心字段解读

### 1️⃣ `usdc` - 资金费用

表示该次结算中用户**实际支付/收取**的资金费：

- **正数**（如 `"15.995961"`）：用户**收取**费用
  - 说明：持有空头仓位，多头支付费用给你

- **负数**（如 `"-14.391152"`）：用户**支付**费用
  - 说明：持有多头仓位，你支付费用给空头

**计算公式**：
```
资金费用 = 持仓量 × 标记价格 × 资金费率
usdc = szi × mark_price × fundingRate
```

### 2️⃣ `szi` - 持仓量

表示结算时用户的**持仓方向和数量**：

- **正数**（如 `"0.54353"`）：**多头持仓**（Long）
  - 持有 0.54353 个 BTC 多单

- **负数**（如 `"-4283.8083333333"`）：**空头持仓**（Short）
  - 持有 4283.81 个 LDO 空单

### 3️⃣ `fundingRate` - 资金费率

表示该次结算的**费率百分比**：

- **正费率**（如 `"0.0000106497"`）：多头支付空头
  - 市场处于**升水**（Contango）

- **负费率**（如 `"-0.0000974305"`）：空头支付多头
  - 市场处于**贴水**（Backwardation）

**年化费率计算**：
```python
年化费率 = fundingRate × 8 × 365
# Hyperliquid 每天结算 8 次（每 3 小时一次）
```

**示例**：
- 费率 = `0.0000106497`
- 年化费率 = `0.0000106497 × 8 × 365 = 3.11%`

---

## 📈 使用场景

### 1. 资金费用统计

计算用户在特定时间段内的总资金费收支：

```python
from hyperliquid.info import Info
import time

info = Info(skip_ws=True)
address = "0x162cc7c861ebd0c06b3d72319201150482518185"

# 获取最近 30 天数据
current_time = int(time.time() * 1000)
start_time = current_time - (30 * 24 * 60 * 60 * 1000)

funding_data = info.user_funding_history(address, start_time)

# 统计总费用
total_funding = sum(float(record['delta']['usdc']) for record in funding_data)
print(f"30天资金费用: {total_funding:.2f} USDC")

# 区分收入/支出
income = sum(float(r['delta']['usdc']) for r in funding_data if float(r['delta']['usdc']) > 0)
expense = sum(float(r['delta']['usdc']) for r in funding_data if float(r['delta']['usdc']) < 0)

print(f"收入: {income:.2f} USDC")
print(f"支出: {expense:.2f} USDC")
print(f"净收益: {total_funding:.2f} USDC")
```

### 2. 费率分析

分析不同币种的平均费率：

```python
from collections import defaultdict

coin_stats = defaultdict(lambda: {'count': 0, 'total_rate': 0.0})

for record in funding_data:
    coin = record['delta']['coin']
    rate = float(record['delta']['fundingRate'])

    coin_stats[coin]['count'] += 1
    coin_stats[coin]['total_rate'] += rate

# 计算平均费率和年化费率
for coin, stats in coin_stats.items():
    avg_rate = stats['total_rate'] / stats['count']
    annual_rate = avg_rate * 8 * 365 * 100  # 转换为百分比

    print(f"{coin:10s} | 平均费率: {avg_rate:.6f} | 年化: {annual_rate:6.2f}%")
```

### 3. 持仓时长分析

计算用户在每个币种上的资金费支付次数（反映持仓时长）：

```python
from collections import Counter

coin_counts = Counter(record['delta']['coin'] for record in funding_data)

for coin, count in coin_counts.most_common(10):
    days = count / 8  # 每天 8 次结算
    print(f"{coin:10s} | 结算次数: {count:4d} | 约持仓 {days:.1f} 天")
```

---

## ⚠️ 注意事项

### 1. 时间戳单位

**重要**：`startTime` 和 `endTime` 必须是**毫秒时间戳**，不是秒！

```python
# ✅ 正确
import time
current_ms = int(time.time() * 1000)
start_ms = current_ms - (30 * 24 * 60 * 60 * 1000)

# ❌ 错误
import time
current_sec = int(time.time())  # 这是秒，不是毫秒！
```

### 2. 数据量限制

- 单次请求可能返回大量数据（测试地址返回 500 条记录）
- 如果时间范围过大，建议分批查询
- 没有持仓时，对应币种不会有资金费记录

### 3. 结算频率

- Hyperliquid 资金费率每 **3 小时**结算一次
- 每天结算 **8 次**（00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 UTC）
- `nSamples` 通常为 24，表示使用 24 个样本点计算费率

### 4. 字符串类型数值

所有数值字段（`usdc`, `szi`, `fundingRate`）都是**字符串类型**，使用前需转换：

```python
# ✅ 正确
usdc = float(record['delta']['usdc'])

# ❌ 错误 - 不能直接计算
total = record['delta']['usdc'] + another_usdc  # TypeError!
```

---

## 🔄 与其他接口的关系

| 接口 | 功能 | 区别 |
|------|------|------|
| `user_funding_history()` | 资金费率历史 | 反映**持仓成本**（时间价值） |
| `user_fills()` | 交易成交记录 | 反映**开平仓操作**（主动交易） |
| `user_state()` | 当前账户状态 | 反映**实时持仓**（快照） |
| `user_non_funding_ledger_updates()` | 非资金费账本变动 | 存取款、转账等操作 |

---

## 📌 实际案例分析

根据测试地址 `0x162cc7c861ebd0c06b3d72319201150482518185` 的数据：

```
【统计周期】90 天
【记录总数】500 条

【涉及币种】16 个
BTC, DOGE, ETH, HYPE, IP, LDO, LTC, MET, MON, MOODENG,
MORPHO, PURR, SAGA, SOL, VIRTUAL, XRP

【资金费用】
• 累计净收益: +23,428.73 USDC
• 收入次数: 342 次，共 +25,277.18 USDC
• 支出次数: 158 次，共 -1,848.45 USDC
• 收益率: 68.4% 的时间在收取费用（持有空头）

【平均费率】
• 单次平均: 0.0020%
• 年化费率: 5.84%

【结论】
该用户主要持有空头仓位，在市场升水期间获得了可观的资金费收益。
```

---

## 🚀 API 客户端集成

在 `address_analyzer/api_client.py` 中的实现：

```python
async def get_user_funding(self, address: str) -> List[Dict]:
    """
    获取用户资金费率历史

    Args:
        address: 用户地址

    Returns:
        资金费率记录列表
    """
    # 验证地址格式
    if not self._validate_address(address):
        logger.error(f"无效的地址格式: {address}")
        return []

    try:
        # 使用正确的方法名：user_funding_history
        # 注意：需要提供 startTime 参数
        start_time = 0  # 从最早时间开始

        async with self.rate_limiter:
            async with self.semaphore:
                funding = self.info.user_funding_history(address, start_time)

        logger.info(f"获取资金费率: {address} ({len(funding)} 条)")
        return funding if funding else []

    except Exception as e:
        logger.warning(f"获取 user_funding_history 失败: {address} - {e}")
        return []
```

---

## 📚 参考资料

- [Hyperliquid API 文档](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api)
- [资金费率机制说明](https://www.binance.com/zh-CN/support/faq/360033525031)
- [永续合约介绍](https://academy.binance.com/zh/articles/what-are-perpetual-futures-contracts)

---

**文档版本**: v1.0
**更新日期**: 2026-02-03
**测试环境**: Hyperliquid Python SDK
