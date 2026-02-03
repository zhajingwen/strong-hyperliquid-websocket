# Perp + Spot 账户价值融合计算 - 修改总结

## 问题背景

之前的账户价值计算只考虑了 Perp 账户（通过 `user_state` API），完全忽略了 Spot 账户的价值，导致：

- 账户价值计算不准确
- ROI 计算偏差巨大
- 无法反映真实的资产状况

**根本原因**：
- `user_state` API 只返回 Perp 账户状态（`marginSummary.accountValue`）
- Spot 账户需要单独通过 `spotClearinghouseState` API 查询
- 正确的账户价值 = Perp 账户价值 + Spot 账户价值

## 修改内容

### 1. api_client.py

#### 新增方法：`get_spot_state()`

```python
async def get_spot_state(
    self,
    address: str,
    use_cache: bool = True
) -> Optional[Dict]:
    """
    获取 Spot 账户状态（spotClearinghouseState API）

    Args:
        address: 用户地址
        use_cache: 是否使用缓存

    Returns:
        Spot 账户状态数据，包含 balances 字段
    """
```

**功能**：
- 调用 `spotClearinghouseState` API 获取 Spot 账户余额
- 支持缓存机制
- 返回包含 `balances` 字段的完整 Spot 账户状态

#### 修改方法：`fetch_address_data()`

**变更**：
- 添加 `spot_state_task = self.get_spot_state(address)`
- 在 `asyncio.gather()` 中并发获取 Spot 账户状态
- 在返回字典中添加 `spot_state` 字段

**效果**：
- 数据采集阶段自动获取并缓存 Spot 账户状态
- 与其他 API 调用并发执行，不影响性能

### 2. metrics_engine.py

#### 修改数据类：`AddressMetrics`

**新增字段**：
```python
# 账户价值分解（新增）
perp_value: float = 0.0  # Perp 账户价值 (USD)
spot_value: float = 0.0  # Spot 账户价值 (USD)
```

**位置**：放在所有必需字段之后，保持 dataclass 字段顺序规则

#### 修改方法：`calculate_metrics()`

**函数签名变更**：
```python
@classmethod
def calculate_metrics(
    cls,
    address: str,
    fills: List[Dict],
    state: Optional[Dict] = None,
    transfer_data: Optional[Dict] = None,
    spot_state: Optional[Dict] = None  # 新增参数
) -> AddressMetrics:
```

**计算逻辑变更**：

1. **分别提取 Perp 和 Spot 账户价值**：

```python
# 获取 Perp 账户价值
perp_value = float(
    (state or {}).get('marginSummary', {}).get('accountValue', 0)
)

# 获取 Spot 账户价值
spot_value = 0.0
if spot_state and 'balances' in spot_state:
    for balance in spot_state['balances']:
        coin = balance.get('coin', '')
        total = float(balance.get('total', 0))

        if total > 0:
            if coin == 'USDC':
                # USDC 按 1:1 计价
                spot_value += total
            else:
                # 其他代币使用 entryNtl（入账价值）
                entry_ntl = float(balance.get('entryNtl', 0))
                spot_value += entry_ntl

# 计算总账户价值 = Perp + Spot
account_value = perp_value + spot_value
```

2. **返回值更新**：

在返回的 `AddressMetrics` 对象中添加：
```python
perp_value=perp_value,
spot_value=spot_value,
```

### 3. orchestrator.py

#### 修改数据采集逻辑

**变更**：
```python
# 获取账户状态（从缓存）
state = await self.store.get_api_cache(f"user_state:{addr}")

# 获取 Spot 账户状态（从缓存）
spot_state = await self.store.get_api_cache(f"spot_state:{addr}")

# 计算指标（传入新参数，包括 spot_state）
metrics = self.metrics_engine.calculate_metrics(
    address=addr,
    fills=fills,
    state=state,
    transfer_data=transfer_stats,
    spot_state=spot_state
)
```

#### 修改缓存保存逻辑

**变更**：
```python
await self.store.save_metrics(addr, {
    'total_trades': metrics.total_trades,
    'win_rate': metrics.win_rate,
    'roi': metrics.roi,
    'sharpe_ratio': metrics.sharpe_ratio,
    'total_pnl': metrics.total_pnl,
    'account_value': metrics.account_value,
    'perp_value': metrics.perp_value,  # 新增
    'spot_value': metrics.spot_value,  # 新增
    'max_drawdown': metrics.max_drawdown,
    'net_deposit': metrics.net_deposits
})
```

## 测试验证

### 测试脚本：`test_perp_spot_integration.py`

创建了完整的测试脚本，验证以下内容：

1. ✅ API 客户端正确获取 Perp 和 Spot 账户状态
2. ✅ 手动计算与 MetricsEngine 计算结果一致
3. ✅ 账户价值分解正确（Perp + Spot = Total）
4. ✅ 所有指标正确计算

### 测试结果（地址 0xde786a32f80731923d6297c14ef43ca1c8fd4b44）

```
手动计算结果:
  Perp 账户价值: $358.80
  Spot 账户价值: $319.71
  ═══════════════════════════
  总账户价值: $678.52

MetricsEngine 计算结果:
  Perp 账户价值: $358.80
  Spot 账户价值: $319.71
  ═══════════════════════════
  总账户价值: $678.52

差异分析:
  Perp 差异: $0.00 ✅
  Spot 差异: $0.00 ✅
  总价值差异: $0.00 ✅

✅ 测试通过！Perp + Spot 账户价值融合计算正确
```

## 影响范围

### 修改的文件

1. `address_analyzer/api_client.py` - 添加 Spot 账户状态获取逻辑
2. `address_analyzer/metrics_engine.py` - 修改账户价值计算逻辑
3. `address_analyzer/orchestrator.py` - 更新数据采集和指标计算流程

### 新增的文件

1. `test_perp_spot_integration.py` - 集成测试脚本
2. `docs/PERP_SPOT_INTEGRATION_SUMMARY.md` - 本文档

### 向后兼容性

✅ **完全向后兼容**

- 所有新增参数都有默认值
- 现有调用代码无需修改即可正常工作
- 新增字段不影响现有数据结构

### 性能影响

✅ **性能影响最小**

- 新增的 `get_spot_state()` 调用与其他 API 并发执行
- 支持缓存机制，避免重复请求
- 计算逻辑增加的复杂度可忽略不计

## 正确使用方法

### 代码示例

```python
from address_analyzer.api_client import HyperliquidAPIClient
from address_analyzer.metrics_engine import MetricsEngine
from address_analyzer.data_store import get_store

# 初始化
store = get_store()
await store.connect()

client = HyperliquidAPIClient(store=store)

# 获取完整数据（包括 Spot 账户）
data = await client.fetch_address_data(address)

# 计算指标（传入 spot_state）
metrics = MetricsEngine.calculate_metrics(
    address=address,
    fills=data['fills'],
    state=data['state'],
    spot_state=data['spot_state'],  # 必须传入
    transfer_data=transfer_stats
)

# 查看结果
print(f"Perp 账户: ${metrics.perp_value:,.2f}")
print(f"Spot 账户: ${metrics.spot_value:,.2f}")
print(f"总账户价值: ${metrics.account_value:,.2f}")
```

### 重要说明

⚠️ **Spot 代币估值方法**

- **USDC**: 按 1:1 美元计价
- **其他代币**: 使用 `entryNtl`（入账价值，即历史成本）
- **注意**: `entryNtl` 不是实时市值，如需精确估值应获取实时价格

⚠️ **内部转账处理**

- Perp ↔ Spot 之间的转账不影响总资产
- 只改变资金在两个账户间的分布
- 计算 ROI 时应使用总账户价值

⚠️ **CORE_DEPOSIT_WALLET 转账**

- 来自 `0x6b9e773128f453f5c2c60935ee2de2cbc5390a24` 的转入是桥接操作
- 可能是循环资金，计算本金时不应重复计入
- 只计算真实的 deposit（充值）

## 关键改进

### 修复前

- ❌ 只统计 Perp 账户价值
- ❌ 完全忽略 Spot 账户资产
- ❌ ROI 计算严重偏差
- ❌ 无法反映真实资产状况

### 修复后

- ✅ 同时统计 Perp 和 Spot 账户价值
- ✅ 正确汇总总账户价值（Perp + Spot）
- ✅ ROI 计算准确
- ✅ 提供账户价值分解（透明度更高）

## 总结

本次修改成功实现了 Perp 和 Spot 账户价值的融合计算，解决了账户价值统计不准确的核心问题。修改：

1. ✅ **架构清晰** - 分别获取、分别计算、最后汇总
2. ✅ **向后兼容** - 所有新增参数都有默认值
3. ✅ **性能优化** - 并发获取、支持缓存
4. ✅ **测试完整** - 包含完整的测试脚本和验证
5. ✅ **文档完善** - 详细的修改说明和使用指南

---

**Created**: 2026-02-03
**Author**: Claude Sonnet 4.5
**Status**: ✅ Completed & Tested
