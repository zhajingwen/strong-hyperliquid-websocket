# 技术选型分析：官方 SDK vs 原生 WebSocket 库

## 结论

**直接用原生 websocket 库更合适。** SDK 的 WebSocket 封装对简单的一次性脚本足够用，但对需要高可靠性的长连接管理场景，它的设计（HTTP+WS 耦合、无超时控制、不可控的线程模型）是根本性的障碍。

---

## 1. SDK 实际提供了什么

SDK 的 `WebsocketManager` 所做的事：

| 功能 | 复杂度 | SDK 实现质量 |
|------|--------|-------------|
| 连接 `wss://api.hyperliquid.xyz/ws` | 极低 | 绑定在 Info() 构造函数中，无法独立控制 |
| 发送 `{"method":"subscribe",...}` | 极低 | `ws.send()` 无超时保护 |
| 消息路由（identifier 匹配） | 低 | 约 70 行映射代码 |
| Ping 保活 | 极低 | `stop_event.wait(50)` 导致 50 秒阻塞 |
| 订阅队列（ws 未就绪时排队） | 低 | 正常 |

Hyperliquid 的 WebSocket 协议本身非常简单：

```python
# 连接
ws = websocket.WebSocketApp("wss://api.hyperliquid.xyz/ws", ...)

# 订阅
ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "allMids"}}))

# 取消订阅
ws.send(json.dumps({"method": "unsubscribe", "subscription": {"type": "allMids"}}))

# 保活
ws.send(json.dumps({"method": "ping"}))
```

SDK 在 WebSocket 层面的抽象价值很低，协议交互总共就三种 JSON 消息。

---

## 2. SDK 的核心问题：耦合

SDK 最大的设计问题是 **`Info.__init__` 把 HTTP 元数据请求和 WebSocket 连接耦合在一起**：

```python
class Info(API):
    def __init__(self, base_url, skip_ws=False):
        super().__init__(base_url)               # timeout=None
        self.spot_meta_data = self.spot_meta()   # HTTP 阻塞
        ...
        if not skip_ws:
            self.ws_manager = WebsocketManager(...)
            self.ws_manager.start()              # 后台线程
        ...
        self.perp_dexs_data = self.perp_dexs()   # HTTP 阻塞
        self.meta_data = self.meta(...)           # HTTP 阻塞（循环）
```

这意味着：

- **每次重连都要重新执行所有 HTTP 请求**（spot_meta、perp_dexs、meta），即使这些元数据几乎不变
- **HTTP 请求阻塞 → WebSocket 连接被连带阻塞**
- **无法单独重启 WebSocket 而保留 HTTP 数据**

当前 `enhanced_ws_manager` 本质上是在**对抗 SDK 的设计**——给一个不可控的黑盒加超时包装，用 daemon 线程包裹阻塞调用。这种"补丁式"做法虽然能解决问题，但增加了复杂度和不确定性（泄漏的 daemon 线程、残留的 Info 对象等）。

---

## 3. 建议方案：原生 websocket + SDK 仅做 HTTP

```
┌──────────────────────────────────────────────────────┐
│                  EnhancedWebSocketManager             │
├─────────────────────┬────────────────────────────────┤
│   HTTP 层（可选）    │         WebSocket 层            │
│                     │                                │
│  Info(skip_ws=True) │  websocket.WebSocketApp(...)   │
│  或直接 requests     │  ├─ 自控连接/断开/超时          │
│  获取 spot_meta 等   │  ├─ 自控订阅/取消订阅           │
│  (仅首次或按需)      │  ├─ 自控 ping 间隔             │
│                     │  └─ 自控重连策略                │
└─────────────────────┴────────────────────────────────┘
```

---

## 4. 收益分析

### 4.1 消除已知问题

| 已知问题 | 严重程度 | 用 SDK | 用原生 websocket |
|----------|----------|--------|-----------------|
| P0: Info() 无超时控制 | 致命 | 需 daemon 线程包装 | **彻底消除**（WS 不绑定 HTTP） |
| P1: subscribe() 超时失效 | 高 | ThreadPoolExecutor 陷阱 | **彻底消除**（自控 `ws.send()` + `sock.settimeout()`） |
| P2: disconnect 阻塞 50s | 高 | 需 daemon 线程包装 | **彻底消除**（自控 ping 线程，`Event.wait(10)`） |
| P3: 假活阈值不合理 | 中 | 需修改默认值 | 需修改默认值（与库选择无关） |
| P4: 订阅后缺少验证 | 中 | 需手动添加 | 需手动添加（与库选择无关） |
| P5: unsubscribe 数据结构 | 低 | 受 SDK 签名限制 | **彻底消除**（自己管理订阅映射） |
| P6: warning 不缩放 | 低 | 需修改 HealthMonitor | 需修改 HealthMonitor（与库选择无关） |

**7 个问题中的 5 个被彻底消除**（P0/P1/P2/P5/P6），剩余 P3/P4 是应用层逻辑，与用什么库无关。

### 4.2 重连速度提升

| 步骤 | 用 SDK（当前） | 用原生 websocket |
|------|---------------|-----------------|
| 断开旧连接 | `disconnect_websocket()` 可阻塞 50s | `ws.close()` 毫秒级 |
| 创建连接对象 | `Info(base_url)` 多次 HTTP 请求，无超时 | 无此步骤 |
| 建立 WebSocket | 耦合在 Info() 内部 | `WebSocketApp.run_forever()` 独立控制 |
| 重新订阅 | `Info.subscribe()` 经过 SDK 转发 | 直接 `ws.send()` |
| **总耗时** | **秒级到无限** | **毫秒到秒级** |

### 4.3 架构简化

```
当前（用 SDK）：
  enhanced_ws_manager
    → Info(base_url)           ← 黑盒，不可控
      → API.post()             ← timeout=None
      → WebsocketManager       ← 隐藏线程模型
        → WebSocketApp          ← 实际连接
        → ping_sender           ← 50s wait
    → daemon 线程包装 Info()    ← 补丁
    → daemon 线程包装 subscribe ← 补丁
    → daemon 线程包装 disconnect← 补丁

改为（原生 websocket）：
  enhanced_ws_manager
    → WebSocketApp              ← 直接控制
    → 自管理订阅                ← 透明
    → 自管理 ping               ← 可控间隔
    → 自管理超时                ← socket 级别
```

减少了三层 daemon 线程包装，架构更扁平、更可预测。

---

## 5. 需要自行实现的部分

| 需自行实现 | 工作量 | 说明 |
|-----------|--------|------|
| WebSocket 连接管理 | ~30 行 | `WebSocketApp` + `run_forever` in thread |
| 订阅消息收发 | ~10 行 | 三种 JSON 格式（subscribe/unsubscribe/ping） |
| 消息路由 | ~50 行 | 从 SDK 的 `subscription_to_identifier` / `ws_msg_to_identifier` 复用 |
| Ping 保活 | ~15 行 | `Event.wait(10)` + `ws.send(ping)` |
| 连接状态检测 | 已有 | 现有 `_is_connected()` 逻辑可简化复用 |
| **合计新增** | **~100 行** | |

消息路由的映射逻辑可以直接从 SDK 的 `websocket_manager.py:13-74` 中提取，这部分是纯数据映射，不涉及连接管理。

---

## 6. HTTP 元数据的处理

如果业务逻辑需要 `spot_meta`、`perp_dexs` 等元数据（如币种名称映射），有两种方式：

**方式 A：SDK `Info(skip_ws=True)`**

```python
# 仅使用 SDK 的 HTTP 功能，跳过 WebSocket
info = Info(base_url, skip_ws=True)
spot_meta = info.spot_meta_data
# WebSocket 连接独立管理
```

**方式 B：直接用 requests**

```python
import requests
session = requests.Session()
spot_meta = session.post(f"{base_url}/info", json={"type": "spotMeta"}, timeout=10).json()
```

方式 A 更简洁但仍有 `timeout=None` 的问题。方式 B 完全自主可控。

两种方式都只需在启动时执行一次（或按需刷新），不影响 WebSocket 重连速度。

---

## 7. 总结

| 维度 | 官方 SDK | 原生 websocket |
|------|---------|---------------|
| 初始开发量 | 少 | 多 ~100 行 |
| 连接可控性 | 低（黑盒） | 高（完全透明） |
| 超时控制 | 无（需补丁） | 原生支持 |
| 重连速度 | 慢（秒级到无限） | 快（毫秒到秒级） |
| 问题消除 | 0/7（需逐个修补） | 5/7（架构层面消除） |
| 长期维护 | 受 SDK 更新影响 | 自主可控 |
| 适用场景 | 简单脚本、一次性查询 | 高可靠长连接 |

对于需要高可靠性的长连接场景，原生 websocket 是更合理的选择。增加约 100 行代码的代价，换来的是架构层面消除 5 个已知问题、完全可控的连接生命周期、以及更快的重连速度。

---

*报告生成时间：2026-01-27*
