# Strong Hyperliquid WebSocket

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> Hyperliquid 交易所 WebSocket API 的增强连接管理工具

一个基于原生 `websocket-client` 的高可靠性 WebSocket 连接管理器，专为解决 Hyperliquid 官方 SDK 的假活检测、重连机制、超时控制等问题而设计。

---

## 🌟 核心特性

### 🔍 双层假活检测
- **底层连接检查**：实时监控 WebSocket 连接状态、socket 文件描述符、线程存活性
- **应用层心跳监控**：基于数据流的假活检测（默认 30 秒超时）
- **智能警告机制**：超过警告阈值（30 秒）时发出警告，超过超时阈值（60 秒）时触发重连

### 🔄 智能重连机制
- **指数退避策略**：自适应重连延迟（初始 1 秒，最大 60 秒）
- **随机抖动**：防止多客户端同时重连（25% 延迟抖动）
- **可配置重试次数**：支持有限次数或无限重试
- **优雅降级**：达到最大重试次数后进入 FAILED 状态

### 🎯 连接生命周期管理
- **5 状态机模型**：
  - `DISCONNECTED` - 未连接
  - `CONNECTING` - 连接中
  - `CONNECTED` - 已连接
  - `RECONNECTING` - 重连中
  - `FAILED` - 连接失败（达到最大重试次数）
- **状态变化回调**：实时通知应用层连接状态变化
- **线程安全**：使用递归锁保护状态变更

### 📊 健康监控与统计
- **实时指标追踪**：
  - 总消息数、重连次数、错误次数
  - 连接运行时长、空闲时间
  - 健康度百分比（基于数据流活跃度）
- **定期健康报告**：每处理 1000 条消息输出一次详细报告
- **统一 API 接口**：通过 `get_stats()` 获取完整统计信息

### 🛡️ 优雅关闭与资源清理
- **协同停止机制**：使用 Event 信号协调线程停止
- **5 秒超时保护**：确保线程在合理时间内终止
- **资源自动释放**：清理 WebSocket 连接、线程引用、订阅列表
- **最终报告输出**：停止时输出完整运行统计

---

## 🤔 为什么需要这个项目？

### 官方 SDK 的核心问题

| 问题类型 | 严重程度 | 影响 | 本项目的解决方案 |
|---------|---------|------|----------------|
| **假活状态无检测** | 🔴 P0 | 连接看似正常但无数据流，程序无限阻塞 | 应用层数据流监控（30 秒超时） |
| **重连机制缺失** | 🔴 P0 | 断线后需手动重启程序 | 指数退避自动重连 + 抖动策略 |
| **无超时控制** | 🟠 P1 | `run()` 无限阻塞，无法优雅退出 | 5 秒超时保护 + 协同停止机制 |
| **底层连接检查缺陷** | 🟠 P1 | 只检查 `ws.sock`，遗漏线程/信号状态 | 4 层连接检查（对象/信号/线程/socket） |
| **错误处理粗糙** | 🟡 P2 | 异常直接抛出，无分类处理 | 结构化错误分类 + 统计追踪 |

### 技术对比示例

**官方 SDK 的问题场景**：
```python
# 官方 SDK - 假活状态无法检测
ws = WebsocketManager(...)
ws.run()  # 连接断开但仍阻塞，无法自动恢复
```

**本项目的解决方案**：
```python
# 增强管理器 - 自动检测假活并重连
manager = EnhancedWebSocketManager(
    base_url=BASE_URL,
    subscriptions=SUBSCRIPTIONS,
    message_callback=callback,
    data_timeout=30.0,  # 30 秒无数据触发重连
    max_retries=10       # 最大重连 10 次
)
manager.start()  # 自动健康检查 + 智能重连
```

**详细技术分析**：参见 [docs/sdk-vs-raw-websocket.md](docs/sdk-vs-raw-websocket.md)

---

## 🚀 快速开始

### 环境要求

- **Python**: 3.12 或更高版本
- **依赖包**:
  - `hyperliquid-python-sdk>=0.21.0` (用于常量和工具)
  - `websocket-client` (原生 WebSocket 支持)

### 安装

**方式 1：使用 uv（推荐）**
```bash
uv sync
```

**方式 2：使用 pip**
```bash
pip install hyperliquid-python-sdk
```

### 基础使用

```python
from hyperliquid.utils import constants
from enhanced_ws_manager import EnhancedWebSocketManager

# 定义订阅列表
subscriptions = [
    {"type": "allMids"},  # 全市场中间价
    {"type": "l2Book", "coin": "ETH"},  # ETH 订单簿
    {"type": "trades", "coin": "BTC"},  # BTC 成交记录
]

# 定义消息回调
def on_message(msg):
    print(f"收到消息: {msg}")

# 创建管理器
manager = EnhancedWebSocketManager(
    base_url=constants.MAINNET_API_URL,
    subscriptions=subscriptions,
    message_callback=on_message,
    health_check_interval=5.0,  # 每 5 秒健康检查
    data_timeout=30.0,          # 30 秒无数据触发重连
    max_retries=10              # 最大重连 10 次
)

# 启动（阻塞运行，Ctrl+C 停止）
manager.start()
```

### 命令行快速测试

```bash
# 基础运行
python ws_holcv.py

# 详细日志模式
python ws_holcv.py --verbose

# 自定义超时和重试次数
python ws_holcv.py --timeout 60 --retries 20

# 自定义健康检查间隔
python ws_holcv.py --check-interval 10
```

---

## 📖 使用示例

### 示例 1：订阅多个市场数据

```python
from hyperliquid.utils import constants
from enhanced_ws_manager import EnhancedWebSocketManager, ConnectionState

# 订阅配置
subscriptions = [
    {"type": "allMids"},                              # 全市场中间价（高频）
    {"type": "l2Book", "coin": "ETH"},                # ETH 订单簿
    {"type": "trades", "coin": "BTC"},                # BTC 交易流
    {"type": "candle", "coin": "SOL", "interval": "1m"}, # SOL 1 分钟 K 线
    {"type": "bbo", "coin": "ARB"},                   # ARB 最优买卖价
]

# 消息处理回调
def process_message(msg):
    channel = msg.get("channel", "unknown")
    data = msg.get("data", {})

    if channel == "trades":
        print(f"成交: {data.get('coin')} @ {data.get('px')}")
    elif channel == "l2Book":
        print(f"订单簿更新: {data.get('coin')}")
    # ... 其他业务逻辑

# 连接状态监控
def on_state_change(state: ConnectionState):
    if state == ConnectionState.CONNECTED:
        print("✅ 连接已建立，开始接收数据")
    elif state == ConnectionState.RECONNECTING:
        print("🔄 连接断开，正在重连...")
    elif state == ConnectionState.FAILED:
        print("❌ 重连失败，请检查网络或增加重试次数")

# 创建管理器
manager = EnhancedWebSocketManager(
    base_url=constants.MAINNET_API_URL,
    subscriptions=subscriptions,
    message_callback=process_message,
    on_state_change=on_state_change,
    data_timeout=60.0,  # 适配低频 K 线数据
    max_retries=0       # 无限重连
)

manager.start()
```

### 示例 2：用户数据订阅

```python
# 需要提供用户地址
USER_ADDRESS = "0x1234..."  # 替换为实际地址

subscriptions = [
    {"type": "userEvents", "user": USER_ADDRESS},          # 用户事件
    {"type": "userFills", "user": USER_ADDRESS},           # 成交记录
    {"type": "orderUpdates", "user": USER_ADDRESS},        # 订单更新
    {"type": "userFundings", "user": USER_ADDRESS},        # 资金费率记录
    {"type": "activeAssetData", "user": USER_ADDRESS, "coin": "BTC"},  # 资产数据
]

def handle_user_data(msg):
    channel = msg.get("channel")

    if channel == "userFills":
        fills = msg.get("data", {}).get("fills", [])
        for fill in fills:
            print(f"成交通知: {fill.get('coin')} {fill.get('side')} {fill.get('sz')} @ {fill.get('px')}")

    elif channel == "orderUpdates":
        orders = msg.get("data", [])
        print(f"订单更新: {len(orders)} 个订单状态变化")

manager = EnhancedWebSocketManager(
    base_url=constants.MAINNET_API_URL,
    subscriptions=subscriptions,
    message_callback=handle_user_data,
)
manager.start()
```

### 示例 3：高频交易场景

```python
import time

# 高频场景配置
manager = EnhancedWebSocketManager(
    base_url=constants.MAINNET_API_URL,
    subscriptions=[
        {"type": "allMids"},  # 全市场价格（每秒数百条）
        {"type": "bbo", "coin": "ETH"},  # 最优买卖价
    ],
    message_callback=lambda msg: None,  # 高频场景可能不需要打印
    health_check_interval=2.0,  # 更频繁的健康检查
    data_timeout=10.0,          # 更短的超时时间
    max_retries=5               # 快速失败策略
)

# 启动后立即获取统计
manager.start()  # 在单独的线程中运行

# 主线程可以定期查询统计
while True:
    stats = manager.get_stats()
    print(f"当前消息数: {stats['health_report']['stats']['total_messages']}")
    time.sleep(5)
```

### 示例 4：获取连接统计信息

```python
# 在管理器运行时获取统计
stats = manager.get_stats()

print(f"""
连接状态: {stats['state']}
订阅数量: {stats['subscription_count']}

健康报告:
  存活状态: {stats['health_report']['is_alive']}
  健康度: {stats['health_report']['health_percentage']:.1f}%
  空闲时间: {stats['health_report']['idle_time']:.1f}秒

消息统计:
  总消息数: {stats['health_report']['stats']['total_messages']}
  重连次数: {stats['health_report']['stats']['total_reconnects']}
  错误次数: {stats['health_report']['stats']['total_errors']}
  运行时长: {stats['health_report']['stats']['uptime_seconds']:.1f}秒

重连状态:
  当前重试: {stats['reconnection_stats']['retry_count']}/{stats['reconnection_stats']['max_retries']}
  下次延迟: {stats['reconnection_stats']['next_delay']:.2f}秒
""")
```

---

## ⚙️ 配置说明

### EnhancedWebSocketManager 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base_url` | `str` | - | API 基础 URL（自动转换 http(s) → ws(s)） |
| `subscriptions` | `List[Dict]` | - | 订阅列表（详见下方订阅类型） |
| `message_callback` | `Callable` | - | 消息回调函数 `(msg: Any) -> None` |
| `health_check_interval` | `float` | `5.0` | 健康检查间隔（秒） |
| `data_timeout` | `float` | `30.0` | 数据流超时时间（秒），超时触发重连 |
| `max_retries` | `int` | `10` | 最大重连次数（0 表示无限重连） |
| `on_state_change` | `Callable` | `None` | 状态变化回调 `(state: ConnectionState) -> None` |

### 订阅类型详解

#### 市场数据订阅

```python
# 全市场中间价（高频，适合假活检测）
{"type": "allMids"}

# 订单簿深度（L2）
{"type": "l2Book", "coin": "ETH"}

# 成交记录
{"type": "trades", "coin": "BTC"}

# K 线数据
{"type": "candle", "coin": "SOL", "interval": "1m"}  # interval: 1m, 5m, 15m, 1h, 4h, 1d

# 最优买卖价
{"type": "bbo", "coin": "ARB"}
```

#### 资产上下文订阅

```python
# Perp 资产上下文（标记价格、资金费率等）
{"type": "activeAssetCtx", "coin": "BTC"}

# Spot 资产上下文（使用 @N 格式）
{"type": "activeAssetCtx", "coin": "@1"}  # @1 表示第一个现货资产
```

#### 用户数据订阅（需要地址）

```python
USER = "0xYourAddress"

# 用户事件（订单、仓位变化等）
{"type": "userEvents", "user": USER}

# 用户成交记录
{"type": "userFills", "user": USER}

# 订单状态更新
{"type": "orderUpdates", "user": USER}

# 资金费率记录
{"type": "userFundings", "user": USER}

# 非资金费率账本更新
{"type": "userNonFundingLedgerUpdates", "user": USER}

# Web 数据（前端用）
{"type": "webData2", "user": USER}

# 特定资产的用户数据
{"type": "activeAssetData", "user": USER, "coin": "BTC"}
```

### 命令行参数（ws_holcv.py）

```bash
python ws_holcv.py [选项]

选项:
  --verbose              启用详细日志（DEBUG 级别）
  --timeout N            数据流超时时间（秒，默认 60）
  --retries N            最大重连次数（默认 0 = 无限）
  --check-interval N     健康检查间隔（秒，默认 5.0）
```

---

## 🏗️ 技术架构

### 核心组件架构

```
┌─────────────────────────────────────────────────────┐
│       EnhancedWebSocketManager（主管理器）          │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌─────────────────┐  ┌──────────────────────┐    │
│  │  HealthMonitor  │  │ ReconnectionManager  │    │
│  │  (健康监控器)    │  │   (重连管理器)       │    │
│  ├─────────────────┤  ├──────────────────────┤    │
│  │ • 假活检测      │  │ • 指数退避           │    │
│  │ • 消息统计      │  │ • 随机抖动           │    │
│  │ • 空闲时间监控  │  │ • 重试计数           │    │
│  └─────────────────┘  └──────────────────────┘    │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │       WebSocketApp (websocket-client)        │  │
│  ├──────────────────────────────────────────────┤  │
│  │ • 底层 WebSocket 连接                        │  │
│  │ • on_open / on_message / on_error / on_close │  │
│  │ • ping/pong 保活机制                         │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### HealthMonitor 详解

**功能**：
- ✅ 应用层数据流监控（基于 `last_message_time`）
- ✅ 双阈值检测：警告阈值（30 秒）+ 超时阈值（60 秒）
- ✅ 线程安全统计（使用 `threading.Lock`）
- ✅ 健康度计算：`(1 - idle_time / timeout) * 100`

**关键方法**：
```python
health_monitor.is_alive()          # 返回 True/False
health_monitor.on_message(msg)     # 更新 last_message_time
health_monitor.get_health_report() # 获取详细报告
```

### ReconnectionManager 详解

**重连策略**：
```python
delay = min(initial_delay * (backoff_factor ** retry_count), max_delay)

# 示例：
# 第 1 次重连：1 秒
# 第 2 次重连：2 秒
# 第 3 次重连：4 秒
# 第 4 次重连：8 秒
# 第 5 次重连：16 秒
# 第 6 次重连：32 秒
# 第 7 次及以后：60 秒（达到 max_delay）
```

**抖动算法**：
```python
jitter_amount = delay * 0.25  # 25% 抖动范围
final_delay = delay + random.uniform(-jitter_amount, jitter_amount)

# 示例：delay=10 秒
# 实际延迟范围：7.5 ~ 12.5 秒
```

### WebSocketApp 详解

**连接流程**：
```
1. 创建 WebSocketApp 对象
   ↓
2. 在守护线程中运行 run_forever()
   ↓
3. 等待 _ws_ready 信号（最多 10 秒）
   ↓
4. 发送订阅消息
   ↓
5. 启动 ping 保活线程（每 10 秒发送一次）
   ↓
6. 进入消息接收循环
```

**底层连接检查（4 层验证）**：
```python
# 1. WebSocketApp 对象存在
if self._ws is None: return False

# 2. 就绪信号已设置
if not self._ws_ready.is_set(): return False

# 3. WebSocket 线程存活
if not self._ws_thread.is_alive(): return False

# 4. 底层 socket 可用
try:
    self._ws.sock.fileno()  # 抛出异常则 socket 已关闭
except: return False
```

### 连接状态机流程图

```
                        ┌─────────────────┐
                        │  DISCONNECTED   │
                        └────────┬────────┘
                                 │ start()
                                 ↓
                        ┌─────────────────┐
                   ┌───→│   CONNECTING    │
                   │    └────────┬────────┘
                   │             │
                   │             ↓
                   │    ┌─────────────────┐
                   │    │    CONNECTED    │←─────┐
                   │    └────────┬────────┘      │
                   │             │                │
                   │             ↓（假活/断线）   │ 重连成功
                   │    ┌─────────────────┐      │
                   └────│  RECONNECTING   │──────┘
                        └────────┬────────┘
                                 │ 重连失败（超过最大次数）
                                 ↓
                        ┌─────────────────┐
                        │     FAILED      │
                        └─────────────────┘
```

### 假活检测流程图

```
┌──────────────────────────────────────────────────┐
│          每 5 秒执行健康检查                      │
└────────────────┬─────────────────────────────────┘
                 │
                 ↓
        ┌────────────────┐
        │ 检查 1: 底层连接 │
        │ _is_connected()│
        └────────┬────────┘
                 │
        ┌────────┴─────────┐
        │                  │
        ↓ False            ↓ True
  ┌──────────┐      ┌────────────────┐
  │ 触发重连  │      │ 检查 2: 应用层  │
  └──────────┘      │ health_monitor │
                    │  .is_alive()   │
                    └────────┬────────┘
                             │
                    ┌────────┴─────────┐
                    │                  │
                    ↓ False            ↓ True
              ┌──────────┐        ┌──────────┐
              │ 触发重连  │        │ 继续运行  │
              └──────────┘        └──────────┘

假活判定条件:
  idle_time = 当前时间 - last_message_time

  if idle_time > warning_threshold (30秒):
      输出警告日志

  if idle_time > timeout (60秒):
      返回 False（假活状态）
```

---

## 📊 API 文档

### EnhancedWebSocketManager 类

#### 初始化方法

```python
def __init__(
    base_url: str,
    subscriptions: List[Dict[str, Any]],
    message_callback: Callable[[Any], None],
    health_check_interval: float = 5.0,
    data_timeout: float = 30.0,
    max_retries: int = 10,
    on_state_change: Optional[Callable[[ConnectionState], None]] = None
)
```

**参数说明**：参见「配置说明」章节

#### 核心方法

```python
# 启动管理器（阻塞运行）
manager.start() -> None

# 停止管理器（优雅关闭）
manager.stop() -> None

# 获取完整统计信息
manager.get_stats() -> Dict[str, Any]
# 返回格式：
# {
#     "state": "connected",
#     "health_report": {...},
#     "reconnection_stats": {...},
#     "subscription_count": 5
# }
```

#### 属性

```python
# 连接状态（只读）
manager.state -> ConnectionState

# 健康监控器
manager.health_monitor -> HealthMonitor

# 重连管理器
manager.reconnection_manager -> ReconnectionManager
```

### ConnectionState 枚举

```python
class ConnectionState(Enum):
    DISCONNECTED = "disconnected"    # 未连接
    CONNECTING = "connecting"        # 连接中
    CONNECTED = "connected"          # 已连接
    RECONNECTING = "reconnecting"    # 重连中
    FAILED = "failed"                # 连接失败
```

### HealthMonitor 类

#### 初始化

```python
def __init__(
    timeout: float = 60.0,           # 数据流超时时间
    warning_threshold: float = 30.0  # 警告阈值
)
```

#### 核心方法

```python
# 检查连接是否存活
is_alive() -> bool

# 获取健康报告
get_health_report() -> Dict[str, Any]
# 返回格式：
# {
#     "is_alive": True,
#     "idle_time": 2.5,
#     "timeout": 60.0,
#     "health_percentage": 95.8,
#     "stats": {
#         "total_messages": 1234,
#         "total_reconnects": 0,
#         "total_errors": 0,
#         "uptime_seconds": 300.5,
#         "idle_seconds": 2.5
#     }
# }

# 重置监控器
reset() -> None
```

#### 内部方法（通常由管理器调用）

```python
on_message(msg: Any) -> None     # 记录收到消息
on_error() -> None               # 记录错误
on_reconnect() -> None           # 记录重连
```

### ReconnectionManager 类

#### 初始化

```python
def __init__(
    initial_delay: float = 1.0,     # 初始延迟
    max_delay: float = 60.0,        # 最大延迟
    max_retries: int = 10,          # 最大重试次数（0 = 无限）
    backoff_factor: float = 2.0,    # 退避因子
    jitter: bool = True             # 是否添加抖动
)
```

#### 核心方法

```python
# 判断是否应该重试
should_retry() -> bool

# 计算下次重连延迟
get_delay() -> float

# 等待并执行重连
wait_before_retry() -> None

# 重置重连计数器
reset() -> None

# 获取重连统计
get_stats() -> Dict[str, Any]
# 返回格式：
# {
#     "retry_count": 3,
#     "max_retries": 10,
#     "last_attempt_time": 1234567890.0,
#     "next_delay": 8.25
# }
```

---

## 🔧 开发指南

### 项目结构

```
strong-hyperliquid-websocket/
├── enhanced_ws_manager.py   # 核心管理器（787 行）
│   ├── ConnectionState      # 连接状态枚举
│   ├── ConnectionStats      # 统计数据类
│   ├── HealthMonitor        # 健康监控器
│   ├── ReconnectionManager  # 重连管理器
│   └── EnhancedWebSocketManager  # 主管理器
│
├── ws_holcv.py              # 应用示例（264 行）
│   ├── SUBSCRIPTIONS        # 订阅配置
│   ├── safe_print()         # 消息格式化
│   └── main()               # 主函数
│
├── main.py                  # 入口脚本（软链接到 ws_holcv.py）
├── pyproject.toml           # 项目配置
├── README.md                # 本文档
│
└── docs/
    └── sdk-vs-raw-websocket.md  # 技术决策文档
```

### 运行测试

```bash
# 基础测试
python ws_holcv.py

# 压力测试（高频数据）
python ws_holcv.py --timeout 10 --check-interval 2

# 断线重连测试（断开网络后观察重连行为）
python ws_holcv.py --verbose --retries 5

# 假活检测测试（等待 30 秒触发警告，60 秒触发重连）
python ws_holcv.py --verbose --timeout 60
```

### 代码规范

- **类型注解**：所有公共方法必须使用类型注解
- **文档字符串**：关键类和方法需要完整的 docstring
- **日志级别**：
  - `DEBUG`: 详细调试信息（连接检查、订阅细节）
  - `INFO`: 正常运行信息（状态变化、健康报告）
  - `WARNING`: 警告信息（数据流异常、重连准备）
  - `ERROR`: 错误信息（连接失败、异常捕获）
- **线程安全**：所有共享状态使用锁保护

### 扩展开发示例

**自定义健康检查逻辑**：

```python
from enhanced_ws_manager import EnhancedWebSocketManager, HealthMonitor

class CustomHealthMonitor(HealthMonitor):
    def is_alive(self) -> bool:
        # 自定义假活检测逻辑
        idle_time = self.stats.get_idle_time()

        # 示例：动态超时（根据消息数量调整）
        dynamic_timeout = self.timeout
        if self.stats.total_messages > 10000:
            dynamic_timeout = self.timeout * 1.5  # 高频场景放宽超时

        return idle_time < dynamic_timeout

# 使用自定义监控器
manager = EnhancedWebSocketManager(...)
manager.health_monitor = CustomHealthMonitor(timeout=30.0)
manager.start()
```

**自定义重连策略**：

```python
from enhanced_ws_manager import ReconnectionManager

class AggressiveReconnection(ReconnectionManager):
    def get_delay(self) -> float:
        # 更激进的重连策略（固定 1 秒延迟）
        return 1.0

manager = EnhancedWebSocketManager(...)
manager.reconnection_manager = AggressiveReconnection(max_retries=20)
manager.start()
```

---

## 🐛 故障排查

### 常见问题 1：连接无限阻塞

**症状**：程序启动后无响应，无日志输出

**原因**：
- 网络不通，连接超时
- 防火墙拦截 WebSocket 连接
- API URL 错误

**解决方案**：
```bash
# 1. 启用详细日志
python ws_holcv.py --verbose

# 2. 检查网络连接
curl -I https://api.hyperliquid.xyz/info

# 3. 检查 WebSocket 端点
wscat -c wss://api.hyperliquid.xyz/ws

# 4. 调整连接超时（在代码中修改 _connection_timeout）
manager._connection_timeout = 30.0  # 增加到 30 秒
```

### 常见问题 2：频繁重连

**症状**：日志显示连续重连，无法稳定连接

**原因**：
- `data_timeout` 设置过短（小于数据更新频率）
- 网络不稳定
- 订阅了低频数据源（如 1 小时 K 线）

**解决方案**：
```python
# 方案 1：增加超时时间
manager = EnhancedWebSocketManager(
    ...,
    data_timeout=120.0,  # 增加到 120 秒
)

# 方案 2：添加高频数据源（用于保活）
subscriptions = [
    {"type": "allMids"},  # 添加高频数据源
    # ... 其他低频订阅
]

# 方案 3：调整健康检查间隔
manager = EnhancedWebSocketManager(
    ...,
    health_check_interval=10.0,  # 降低检查频率
)
```

### 常见问题 3：消息处理异常

**症状**：日志显示 "用户回调异常"，但程序继续运行

**原因**：
- 回调函数中存在未捕获的异常
- 消息格式与预期不符

**解决方案**：
```python
def safe_callback(msg):
    try:
        # 业务逻辑
        channel = msg.get("channel", "unknown")

        # 添加类型检查
        if not isinstance(msg, dict):
            print(f"警告: 消息格式异常 {type(msg)}")
            return

        # 处理数据
        if channel == "trades":
            # ... 业务代码
            pass

    except KeyError as e:
        print(f"消息字段缺失: {e}")
    except Exception as e:
        print(f"处理消息异常: {e}")
        import traceback
        traceback.print_exc()

# 使用安全回调
manager = EnhancedWebSocketManager(
    ...,
    message_callback=safe_callback
)
```

### 常见问题 4：资源泄漏

**症状**：长时间运行后内存占用持续增长

**原因**：
- 回调函数中累积数据未清理
- 线程未正确终止

**解决方案**：
```python
# 方案 1：定期清理数据
class DataProcessor:
    def __init__(self):
        self.buffer = []
        self.max_buffer_size = 1000

    def process(self, msg):
        self.buffer.append(msg)

        # 定期清理
        if len(self.buffer) > self.max_buffer_size:
            self.buffer = self.buffer[-self.max_buffer_size:]

# 方案 2：确保正确停止
try:
    manager.start()
except KeyboardInterrupt:
    print("正在停止...")
    manager.stop()  # 确保调用 stop()

# 方案 3：使用上下文管理器（可扩展）
class WebSocketContext:
    def __enter__(self):
        self.manager = EnhancedWebSocketManager(...)
        return self.manager

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.manager.stop()

with WebSocketContext() as manager:
    manager.start()  # 自动清理
```

---

## 📝 贡献指南

欢迎提交 Issue 和 Pull Request！

**贡献流程**：
1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 开启 Pull Request

**开发建议**：
- 添加功能前请先开 Issue 讨论
- 保持代码风格一致（类型注解 + docstring）
- 添加必要的测试用例
- 更新 README.md 文档

---

## 📄 许可证

本项目采用 [MIT License](https://opensource.org/licenses/MIT) 开源许可。

---

## 🔗 相关链接

- **Hyperliquid 官方文档**: https://hyperliquid.gitbook.io/hyperliquid-docs
- **Hyperliquid Python SDK**: https://github.com/hyperliquid-dex/hyperliquid-python-sdk
- **WebSocket Client**: https://github.com/websocket-client/websocket-client
- **技术决策文档**: [docs/sdk-vs-raw-websocket.md](docs/sdk-vs-raw-websocket.md)

---

## 📧 联系方式

如有问题或建议，请通过以下方式联系：

- **GitHub Issues**: [提交 Issue](../../issues)
- **Pull Requests**: [提交 PR](../../pulls)

---

**最后更新**: 2024-01-29
