# Hyperliquid WebSocket 重连失败问题分析报告

## 1. 问题描述

网络短暂断开后恢复正常，但 WebSocket 管理器未能成功重新连接，程序疑似挂起，无任何新日志输出。

---

## 2. 日志时间线

| 时间 | 事件 | 来源 |
|------|------|------|
| `03:12:36` | 最后一条有效数据（ETH candle） | 应用层 |
| `03:12:54` | 警告：17.6秒无数据 | `enhanced_ws_manager` |
| `03:13:09` | 假活检测触发（32.7秒无数据）→ 启动重连 | `enhanced_ws_manager` |
| `03:13:09` | 状态变化：`connected → reconnecting` | `enhanced_ws_manager` |
| `03:13:12` | 断开旧连接，状态变化：`reconnecting → disconnected` | `enhanced_ws_manager` |
| `03:13:13` | **重连尝试 1**：DNS 解析失败 `NameResolutionError` | `urllib3` |
| `03:13:13` | 状态变化：`connecting → disconnected`，重连失败 | `enhanced_ws_manager` |
| `03:13:14` | 健康检查检测到底层连接断开 → 再次重连 | `enhanced_ws_manager` |
| `03:13:14` | 等待 1.52 秒后重连（尝试 2/∞） | `enhanced_ws_manager` |
| `03:13:15` | **重连尝试 2**：开始 `_connect()` → `Info(base_url)` | `enhanced_ws_manager` |
| `03:13:32` | `Websocket connected`（SDK 后台线程） | `websocket` |
| `03:14:20` | `Connection to remote host was lost`（SDK 后台线程） | `websocket` |
| 此后 | **无任何日志输出，程序疑似挂起** | — |

### 关键观察

从 `03:13:15`（"正在连接到 https://api.hyperliquid.xyz..."）之后，**没有出现任何 `enhanced_ws_manager` 的日志**：

- 没有 `"开始订阅 X 个频道..."`
- 没有 `"✅ 连接成功并完成订阅"`
- 没有 `"✓ 重连成功"` 或 `"✗ 重连失败"`

仅有 SDK 后台 websocket 线程的两条日志（connected 和 lost），说明**主线程在 `Info(base_url)` 构造函数内部被阻塞**。

---

## 3. 根本原因分析

### 原因 1（主因）：`Info(base_url)` 构造函数无超时控制，导致主线程无限阻塞

#### 调用链

```
enhanced_ws_manager.py:554  _reconnect()
  → enhanced_ws_manager.py:437  self._info = Info(self.base_url)   ← 阻塞点
    → hyperliquid/info.py:36     self.spot_meta()                  ← HTTP POST，无超时
    → hyperliquid/info.py:59     self.perp_dexs()                  ← HTTP POST，无超时
    → hyperliquid/info.py:68     self.meta(dex=perp_dex)           ← HTTP POST，无超时（循环）
      → hyperliquid/api.py:23    self.session.post(url, json=payload, timeout=self.timeout)
                                                                      ↑ self.timeout = None
```

#### SDK 源码关键点

**`hyperliquid/api.py:12-23`**：

```python
class API:
    def __init__(self, base_url=None, timeout=None):
        self.timeout = timeout          # 默认为 None

    def post(self, url_path, payload=None):
        response = self.session.post(
            url, json=payload,
            timeout=self.timeout         # None → 无超时限制！
        )
```

**`requests.Session.post(timeout=None)`** 的行为是**无限等待**，直到收到响应或 TCP 连接彻底断开。

#### 阻塞场景

```
时间线：
03:13:15  Info(base_url) 开始执行
          ├─ ws_manager.start()        → 后台线程启动 WebSocket
          └─ self.spot_meta()          → HTTP POST /info，阻塞等待响应...
                                          ↓
03:13:32  [后台线程] WebSocket 连接成功
                                          ↓  （主线程仍阻塞在 HTTP 请求中）
03:14:20  [后台线程] WebSocket 连接断开
                                          ↓  （主线程仍阻塞在 HTTP 请求中）
  ...     主线程可能永久阻塞
          健康检查循环无法运行
          无法检测 WebSocket 断开
          无法发起新的重连
```

在网络恢复期间，TCP 连接可能已建立但响应缓慢，或处于半开连接状态，导致 HTTP 请求永远不会超时也不会返回。

---

### 原因 2：`disconnect_websocket()` 可能阻塞最多 50 秒

#### SDK 源码

**`hyperliquid/websocket_manager.py:101-105`**：

```python
def stop(self):
    self.stop_event.set()
    self.ws.close()
    if self.ping_sender.is_alive():
        self.ping_sender.join()          # 无超时参数！
```

**`ping_sender` 线程内部**：

```python
def send_ping(self):
    while not self.stop_event.wait(50):  # 每次等待 50 秒
        self.ws.send(json.dumps({"method": "ping"}))
```

`threading.Event.wait(50)` 等待 **50 秒**。当 `stop()` 被调用时：

1. `stop_event.set()` 设置停止标志
2. `ws.close()` 关闭连接
3. `ping_sender.join()` 等待 ping 线程退出
4. ping 线程最多需要 **50 秒** 才能检测到 `stop_event` 并退出

这导致 `_disconnect()` → `disconnect_websocket()` 最多阻塞 50 秒。

---

### 原因 3：订阅完成后缺少连接存活验证

**`enhanced_ws_manager.py:477-480`**：

```python
# 所有订阅成功，提交
self._subscription_ids = temp_subscription_ids
self.state = ConnectionState.CONNECTED
logger.info("✅ 连接成功并完成订阅")
```

订阅完成后直接标记为 `CONNECTED`，没有再次检查 `_is_connected()` 验证底层连接是否仍然存活。如果 WebSocket 在订阅期间断开，`_connect()` 会返回 `True`（假成功）。

---

## 4. 影响评估

| 问题 | 严重程度 | 影响 |
|------|----------|------|
| Info() 无超时 | **致命** | 主线程永久挂起，程序完全失去响应能力 |
| disconnect 阻塞 50s | **高** | 重连延迟增加 50 秒，期间无法处理任何事件 |
| 缺少订阅后验证 | **中** | 可能出现假成功状态，下一轮健康检查才能发现 |

---

## 5. 修复方案

### 5.1 为 `Info()` 构造添加超时保护（最关键）

**文件**：`enhanced_ws_manager.py`

新增方法：

```python
def _create_info_with_timeout(self, timeout: float = 30.0) -> Optional[Info]:
    """在超时限制内创建 Info 对象"""
    result = [None]
    exception = [None]

    def create():
        try:
            result[0] = Info(self.base_url)
        except Exception as e:
            exception[0] = e

    thread = threading.Thread(target=create, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        logger.error(f"Info() 创建超时（{timeout}秒），放弃本次连接")
        return None
    if exception[0]:
        raise exception[0]
    return result[0]
```

在 `_connect()` 中替换第 437 行：

```python
# 旧代码
self._info = Info(self.base_url)

# 新代码
self._info = self._create_info_with_timeout(self._connection_create_timeout)
if self._info is None:
    raise ConnectionError("Info() 创建超时")
```

### 5.2 为 `_disconnect()` 添加超时保护

新增方法：

```python
def _safe_disconnect_websocket(self, timeout: float = 10.0) -> None:
    """带超时的 WebSocket 断开"""
    def do_disconnect():
        try:
            self._info.disconnect_websocket()
        except Exception:
            pass

    thread = threading.Thread(target=do_disconnect, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        logger.warning(f"disconnect_websocket() 超时（{timeout}秒），强制跳过")
```

在 `_disconnect()` 中替换第 513 行的直接调用。

### 5.3 订阅后验证连接状态

在 `_connect()` 订阅成功后（第 480 行之后）添加：

```python
# 验证连接仍然存活
if not self._is_connected():
    logger.error("订阅完成但连接已断开，需要重连")
    raise ConnectionError("连接在订阅过程中断开")
```

### 5.4 新增构造函数参数

在 `__init__` 中添加可配置的超时参数：

```python
def __init__(self, ..., connection_create_timeout: float = 30.0,
             disconnect_timeout: float = 10.0):
    self._connection_create_timeout = connection_create_timeout
    self._disconnect_timeout = disconnect_timeout
```

---

## 6. 验证步骤

1. 运行 `python ws_holcv.py`，确认正常接收数据
2. 断开网络（关闭 Wi-Fi），等待假活检测触发
3. 在重连过程中恢复网络
4. 验证程序在 **30 秒超时 + 退避延迟** 内成功重连
5. 确认日志输出 `"✅ 连接成功并完成订阅"` 和 `"✓ 重连成功"`
6. 确认不再出现程序挂起（无日志输出超过 60 秒）的情况
7. 重复断网/恢复测试 3 次以上，验证稳定性

---

*报告生成时间：2026-01-27*
