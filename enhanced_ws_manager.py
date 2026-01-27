"""
增强的 WebSocket 连接管理器
基于原生 websocket-client 的 WebSocket 连接管理

特性：
- ✅ 双层假活检测（底层连接状态 + 应用层心跳监控）
- ✅ 应用层数据流监控（默认 30 秒超时）
- ✅ 自动重连（指数退避策略）
- ✅ 错误分类处理
- ✅ 连接状态回调
- ✅ 结构化日志与统计
"""

import json
import time
import random
import logging
import threading
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

import websocket  # websocket-client


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """连接状态枚举"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass
class ConnectionStats:
    """连接统计信息"""
    total_messages: int = 0
    total_reconnects: int = 0
    total_errors: int = 0
    last_message_time: float = field(default_factory=time.time)
    last_reconnect_time: Optional[float] = None
    connection_start_time: float = field(default_factory=time.time)

    def get_uptime(self) -> float:
        """获取连接持续时间（秒）"""
        return time.time() - self.connection_start_time

    def get_idle_time(self) -> float:
        """获取空闲时间（秒）"""
        return time.time() - self.last_message_time

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "total_messages": self.total_messages,
            "total_reconnects": self.total_reconnects,
            "total_errors": self.total_errors,
            "uptime_seconds": self.get_uptime(),
            "idle_seconds": self.get_idle_time(),
            "last_reconnect_time": self.last_reconnect_time,
        }


class HealthMonitor:
    """
    健康监控器

    功能：
    - 检测数据流中断（假活状态）
    - 追踪消息统计
    - 提供健康状态报告
    """

    def __init__(
        self,
        timeout: float = 60.0,
        warning_threshold: float = 30.0
    ):
        """
        初始化健康监控器

        Args:
            timeout: 数据流超时时间（秒），超过此时间无数据则判定为假活
            warning_threshold: 警告阈值（秒），超过此时间无数据发出警告
        """
        self.timeout = timeout
        self.warning_threshold = warning_threshold
        self.stats = ConnectionStats()
        self._warned = False

        # 线程安全保护
        self._stats_lock = threading.Lock()
        self._warned_lock = threading.Lock()

    def on_message(self, msg: Any) -> None:
        """
        记录收到消息

        Args:
            msg: WebSocket 消息
        """
        with self._stats_lock:
            self.stats.last_message_time = time.time()
            self.stats.total_messages += 1

        with self._warned_lock:
            self._warned = False  # 重置警告标志

        # 使用局部变量避免重复加锁
        with self._stats_lock:
            total_messages = self.stats.total_messages

        if total_messages % 100 == 0:
            logger.debug(f"已处理 {total_messages} 条消息")

    def on_error(self) -> None:
        """记录错误"""
        with self._stats_lock:
            self.stats.total_errors += 1

    def on_reconnect(self) -> None:
        """记录重连"""
        with self._stats_lock:
            self.stats.total_reconnects += 1
            self.stats.last_reconnect_time = time.time()

    def is_alive(self) -> bool:
        """
        检查连接是否存活

        Returns:
            True: 连接正常
            False: 疑似假活状态
        """
        idle_time = self.stats.get_idle_time()

        # 警告阈值检查
        with self._warned_lock:
            if idle_time > self.warning_threshold and not self._warned:
                logger.warning(
                    f"⚠️  数据流异常：{idle_time:.1f}秒无数据 "
                    f"(警告阈值: {self.warning_threshold}秒)"
                )
                self._warned = True

        # 超时检查
        if idle_time > self.timeout:
            logger.error(
                f"❌ 假活检测：{idle_time:.1f}秒无数据流 "
                f"(超时阈值: {self.timeout}秒)"
            )
            return False

        return True

    def get_health_report(self) -> Dict[str, Any]:
        """
        获取健康报告

        Returns:
            包含统计信息的字典
        """
        idle_time = self.stats.get_idle_time()
        return {
            "is_alive": self.is_alive(),
            "idle_time": idle_time,
            "timeout": self.timeout,
            "health_percentage": max(0, min(100, (1 - idle_time / self.timeout) * 100)),
            "stats": self.stats.to_dict(),
        }

    def reset(self) -> None:
        """重置监控器"""
        self.stats = ConnectionStats()
        self._warned = False


class ReconnectionManager:
    """
    重连管理器

    功能：
    - 指数退避重连策略
    - 重连次数限制
    - 重连状态追踪
    """

    def __init__(
        self,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        max_retries: int = 10,
        backoff_factor: float = 2.0,
        jitter: bool = True
    ):
        """
        初始化重连管理器

        Args:
            initial_delay: 初始重连延迟（秒）
            max_delay: 最大重连延迟（秒）
            max_retries: 最大重连次数（0表示无限制）
            backoff_factor: 退避因子（每次失败延迟倍数）
            jitter: 是否添加随机抖动
        """
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.jitter = jitter

        self.retry_count = 0
        self.last_attempt_time = 0.0

    def should_retry(self) -> bool:
        """
        判断是否应该重试

        Returns:
            True: 应该重试
            False: 已达到最大重试次数
        """
        if self.max_retries == 0:
            return True  # 无限重试
        return self.retry_count < self.max_retries

    def get_delay(self) -> float:
        """
        计算下次重连的延迟时间

        Returns:
            延迟时间（秒）
        """
        # 指数退避
        delay = min(
            self.initial_delay * (self.backoff_factor ** self.retry_count),
            self.max_delay
        )

        # 添加随机抖动（防止多个客户端同时重连）
        if self.jitter:
            jitter_amount = delay * 0.25  # 25% 抖动
            delay += random.uniform(-jitter_amount, jitter_amount)

        return max(0, delay)

    def wait_before_retry(self) -> None:
        """等待下次重连"""
        delay = self.get_delay()
        logger.info(
            f"等待 {delay:.2f} 秒后重连 "
            f"(尝试 {self.retry_count + 1}/{self.max_retries if self.max_retries > 0 else '∞'})"
        )
        time.sleep(delay)
        self.retry_count += 1
        self.last_attempt_time = time.time()

    def reset(self) -> None:
        """重置重连计数器"""
        self.retry_count = 0
        self.last_attempt_time = 0.0

    def get_stats(self) -> Dict[str, Any]:
        """获取重连统计"""
        return {
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "last_attempt_time": self.last_attempt_time,
            "next_delay": self.get_delay(),
        }


class EnhancedWebSocketManager:
    """
    增强的 WebSocket 连接管理器

    基于原生 websocket-client 的 WebSocket 连接管理，提供：
    - 自动健康检查
    - 自动重连
    - 连接状态管理
    - 统计与监控
    """

    def __init__(
        self,
        base_url: str,
        subscriptions: List[Dict[str, Any]],
        message_callback: Callable[[Any], None],
        health_check_interval: float = 5.0,
        data_timeout: float = 30.0,
        max_retries: int = 10,
        on_state_change: Optional[Callable[[ConnectionState], None]] = None
    ):
        """
        初始化增强管理器

        Args:
            base_url: API 基础 URL
            subscriptions: 订阅列表
            message_callback: 消息回调函数
            health_check_interval: 健康检查间隔（秒）
            data_timeout: 数据流超时时间（秒）
            max_retries: 最大重连次数
            on_state_change: 连接状态变化回调
        """
        self.base_url = base_url
        self.subscriptions = subscriptions
        self.user_callback = message_callback
        self.health_check_interval = health_check_interval
        self.on_state_change = on_state_change

        # 组件初始化
        self.health_monitor = HealthMonitor(timeout=data_timeout)
        self.reconnection_manager = ReconnectionManager(max_retries=max_retries)

        # 连接状态
        self._state = ConnectionState.DISCONNECTED
        self._running = False

        # 线程安全保护
        self._state_lock = threading.RLock()  # 使用递归锁避免死锁

        # WebSocket 连接
        self._ws: Optional[websocket.WebSocketApp] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ping_thread: Optional[threading.Thread] = None

        # 连接控制
        # 将 http(s)://... 转换为 ws(s)://...
        if base_url.startswith("https"):
            self._ws_url = "wss" + base_url[len("https"):] + "/ws"
        else:
            self._ws_url = "ws" + base_url[len("http"):] + "/ws"
        self._ws_ready = threading.Event()       # WebSocket 连接就绪信号
        self._ws_stop_event = threading.Event()  # 停止信号
        self._connection_timeout = 10.0          # 最大等待时间（秒）

        # 订阅管理
        self._active_subscriptions: List[Dict[str, Any]] = []

    @property
    def state(self) -> ConnectionState:
        """获取连接状态"""
        with self._state_lock:
            return self._state

    @state.setter
    def state(self, new_state: ConnectionState) -> None:
        """设置连接状态"""
        # 在锁内检查并更新状态
        with self._state_lock:
            if new_state == self._state:
                return  # 避免重复触发

            old_state = self._state
            self._state = new_state
            logger.info(f"连接状态变化: {old_state.value} → {new_state.value}")

        # 回调在锁外执行，避免死锁
        if self.on_state_change:
            try:
                self.on_state_change(new_state)
            except Exception as e:
                logger.error(f"状态变化回调异常: {e}", exc_info=True)

    # ==================== WebSocket 回调方法 ====================

    def _on_ws_open(self, ws) -> None:
        """WebSocket 连接建立回调"""
        logger.info("WebSocket 连接已建立")
        self._ws_ready.set()

    def _on_ws_message(self, ws, message: str) -> None:
        """
        WebSocket 消息回调

        解析 JSON 消息，过滤内部协议消息（pong、subscriptionResponse），
        将业务数据传递给用户回调。
        """
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning(f"无法解析 WebSocket 消息: {message[:200]}")
            return

        # 过滤内部协议消息
        if isinstance(data, dict):
            method = data.get("method")
            if method == "pong":
                return
            channel = data.get("channel")
            if channel == "subscriptionResponse":
                logger.debug(f"订阅响应: {data}")
                return

        # 业务数据传递给用户回调
        self._wrapped_callback(data)

    def _on_ws_error(self, ws, error) -> None:
        """WebSocket 错误回调"""
        logger.error(f"WebSocket 错误: {error}")
        self.health_monitor.on_error()

    def _on_ws_close(self, ws, close_status_code, close_msg) -> None:
        """WebSocket 连接关闭回调"""
        logger.info(f"WebSocket 连接已关闭 (code={close_status_code}, msg={close_msg})")
        self._ws_ready.clear()

    # ==================== 辅助方法 ====================

    def _send_ping(self) -> None:
        """定时发送 ping 保活（每 10 秒）"""
        while not self._ws_stop_event.is_set():
            self._ws_stop_event.wait(timeout=10.0)
            if self._ws_stop_event.is_set():
                break
            try:
                if self._ws and self._ws_ready.is_set():
                    self._ws.send(json.dumps({"method": "ping"}))
            except Exception as e:
                logger.debug(f"Ping 发送失败: {e}")

    def _cleanup_ws(self) -> None:
        """清理 WebSocket 连接资源"""
        # 设置停止信号
        self._ws_stop_event.set()

        # 关闭 WebSocket
        if self._ws:
            try:
                self._ws.close()
            except Exception as e:
                logger.debug(f"关闭 WebSocket 异常: {e}")

        # 等待线程结束（5 秒超时）
        if self._ping_thread and self._ping_thread.is_alive():
            self._ping_thread.join(timeout=5.0)
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=5.0)

        # 清理引用
        self._ws = None
        self._ws_thread = None
        self._ping_thread = None
        self._ws_ready.clear()

    def _send_subscription(self, subscription: Dict[str, Any], method: str = "subscribe") -> None:
        """
        发送订阅/取消订阅消息

        Args:
            subscription: 订阅配置字典
            method: "subscribe" 或 "unsubscribe"
        """
        msg = {"method": method, "subscription": subscription}
        self._ws.send(json.dumps(msg))

    # ==================== 核心方法 ====================

    def _wrapped_callback(self, msg: Any) -> None:
        """
        包装的消息回调

        Args:
            msg: WebSocket 消息
        """
        # 更新健康监控
        self.health_monitor.on_message(msg)

        # 调用用户回调
        try:
            self.user_callback(msg)
        except Exception as e:
            logger.error(f"用户回调异常: {e}", exc_info=True)
            self.health_monitor.on_error()

    def _is_connected(self) -> bool:
        """
        检查底层 WebSocket 是否已连接

        Returns:
            True: 底层连接正常
            False: 底层连接断开
        """
        try:
            # 检查 1: WebSocketApp 对象
            if self._ws is None:
                logger.debug("连接检查失败: WebSocket对象为None")
                return False

            # 检查 2: 就绪信号
            if not self._ws_ready.is_set():
                logger.debug("连接检查失败: ws_ready未设置")
                return False

            # 检查 3: WebSocket 线程存活
            if self._ws_thread is None or not self._ws_thread.is_alive():
                logger.debug("连接检查失败: WebSocket线程已停止")
                return False

            # 检查 4: 底层 socket 状态
            ws = self._ws
            if hasattr(ws, 'sock'):
                if ws.sock is None:
                    logger.debug("连接检查失败: 底层socket为None")
                    return False
                try:
                    if hasattr(ws.sock, 'fileno'):
                        ws.sock.fileno()
                except Exception as sock_error:
                    logger.debug(f"连接检查失败: socket已关闭 - {sock_error}")
                    return False

            # 所有检查通过
            logger.debug("连接检查通过: 底层连接正常")
            return True

        except Exception as e:
            logger.warning(f"连接检查异常: {type(e).__name__} - {e}")
            return False

    def _connect(self) -> bool:
        """
        建立连接并订阅

        Returns:
            True: 连接成功
            False: 连接失败
        """
        try:
            self.state = ConnectionState.CONNECTING

            # 清除事件
            self._ws_stop_event.clear()
            self._ws_ready.clear()

            # 创建 WebSocketApp
            logger.info(f"正在连接到 {self._ws_url}...")
            self._ws = websocket.WebSocketApp(
                self._ws_url,
                on_open=self._on_ws_open,
                on_message=self._on_ws_message,
                on_error=self._on_ws_error,
                on_close=self._on_ws_close,
            )

            # daemon 线程启动 run_forever
            self._ws_thread = threading.Thread(
                target=self._ws.run_forever,
                daemon=True,
            )
            self._ws_thread.start()

            # 等待连接就绪
            ready = self._ws_ready.wait(timeout=self._connection_timeout)
            if not ready:
                logger.warning(f"连接超时（{self._connection_timeout}秒）")
                self._cleanup_ws()
                self.state = ConnectionState.DISCONNECTED
                self.health_monitor.on_error()
                return False

            # 启动 ping 保活线程
            self._ping_thread = threading.Thread(
                target=self._send_ping,
                daemon=True,
            )
            self._ping_thread.start()

            # 逐个发送订阅消息
            logger.info(f"开始订阅 {len(self.subscriptions)} 个频道...")
            self._active_subscriptions.clear()
            for sub in self.subscriptions:
                try:
                    self._send_subscription(sub)
                    self._active_subscriptions.append(sub)
                    logger.debug(f"已订阅: {sub}")
                except Exception as sub_error:
                    logger.error(f"订阅失败: {sub} - {sub_error}")
                    raise

            # 验证连接仍然存活
            if not self._is_connected():
                logger.error("订阅完成后连接已断开")
                self._cleanup_ws()
                self._active_subscriptions.clear()
                self.state = ConnectionState.DISCONNECTED
                self.health_monitor.on_error()
                return False

            self.state = ConnectionState.CONNECTED
            logger.info("✅ 连接成功并完成订阅")

            # 重置监控器和重连管理器
            self.health_monitor.reset()
            self.reconnection_manager.reset()

            return True

        except Exception as e:
            logger.error(f"连接失败: {e}", exc_info=True)
            self._cleanup_ws()
            self._active_subscriptions.clear()
            self.state = ConnectionState.DISCONNECTED
            self.health_monitor.on_error()
            return False

    def _disconnect(self) -> None:
        """断开连接并清理资源"""
        logger.info("正在断开连接...")

        try:
            sub_count = len(self._active_subscriptions)
            if sub_count > 0:
                logger.debug(f"断开连接将清理 {sub_count} 个订阅")

            self._cleanup_ws()
            logger.info("WebSocket 已断开")

        except Exception as e:
            logger.error(f"断开连接时异常: {e}", exc_info=True)

        finally:
            self._active_subscriptions.clear()
            self.state = ConnectionState.DISCONNECTED

    def _reconnect(self) -> bool:
        """
        执行重连

        Returns:
            True: 重连成功
            False: 重连失败
        """
        logger.warning("检测到连接问题，准备重连...")

        # 更新状态
        self.state = ConnectionState.RECONNECTING

        # 断开旧连接
        self._disconnect()

        # 检查是否应该重试
        if not self.reconnection_manager.should_retry():
            logger.error(
                f"❌ 已达到最大重连次数 ({self.reconnection_manager.max_retries})，停止重连"
            )
            self.state = ConnectionState.FAILED
            return False

        # 等待后重试
        self.reconnection_manager.wait_before_retry()

        # 尝试重连
        if self._connect():
            self.health_monitor.on_reconnect()
            self.state = ConnectionState.CONNECTED
            logger.info("✓ 重连成功")
            return True
        else:
            logger.error("✗ 重连失败")
            return False

    def start(self) -> None:
        """启动连接管理器"""
        if self._running:
            logger.warning("管理器已在运行中")
            return

        self._running = True
        logger.info("启动增强 WebSocket 管理器")

        # 初始连接
        self.state = ConnectionState.CONNECTING
        if self._connect():
            self.state = ConnectionState.CONNECTED
        else:
            self.state = ConnectionState.DISCONNECTED
            logger.error("初始连接失败")
            return

        # 主循环：健康检查
        try:
            while self._running:
                time.sleep(0.1)  # 降低 CPU 占用

                # 定时健康检查
                current_time = time.time()
                if not hasattr(self, '_last_check_time'):
                    self._last_check_time = current_time

                if current_time - self._last_check_time >= self.health_check_interval:
                    self._last_check_time = current_time

                    # 统一的连接健康检查
                    needs_reconnect = False
                    reconnect_reason = ""

                    # 检查 1: 底层连接状态
                    if not self._is_connected():
                        needs_reconnect = True
                        reconnect_reason = "底层连接已断开"
                    # 检查 2: 应用层假活检测（仅在底层连接正常时检查）
                    elif not self.health_monitor.is_alive():
                        needs_reconnect = True
                        reconnect_reason = f"假活检测触发（{self.health_monitor.stats.get_idle_time():.1f}秒无数据）"

                    # 执行重连
                    if needs_reconnect:
                        logger.warning(f"⚠️  检测到问题: {reconnect_reason}")
                        if not self._reconnect():
                            # 重连失败，但继续循环等待下次检查
                            continue

                    # 定期输出健康报告
                    if self.health_monitor.stats.total_messages > 0 and \
                       self.health_monitor.stats.total_messages % 1000 == 0:
                        self._print_health_report()

        except KeyboardInterrupt:
            logger.info("\n收到中断信号，正在停止...")
        except Exception as e:
            logger.error(f"管理器异常: {e}", exc_info=True)
        finally:
            self.stop()

    def stop(self) -> None:
        """停止连接管理器"""
        if not self._running:
            return

        logger.info("正在停止增强 WebSocket 管理器...")
        self._running = False

        # 输出最终报告
        self._print_health_report()

        # 断开连接
        self._disconnect()
        self.state = ConnectionState.DISCONNECTED

        logger.info("✓ 管理器已停止")

    def _print_health_report(self) -> None:
        """打印健康报告"""
        report = self.health_monitor.get_health_report()
        logger.info(
            f"\n"
            f"{'='*60}\n"
            f"健康报告 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n"
            f"{'='*60}\n"
            f"连接状态: {self.state.value}\n"
            f"存活状态: {'✅ 健康' if report['is_alive'] else '❌ 假活'}\n"
            f"健康度: {report['health_percentage']:.1f}%\n"
            f"空闲时间: {report['idle_time']:.1f}秒 / {report['timeout']}秒\n"
            f"---\n"
            f"总消息数: {report['stats']['total_messages']}\n"
            f"重连次数: {report['stats']['total_reconnects']}\n"
            f"错误次数: {report['stats']['total_errors']}\n"
            f"运行时长: {report['stats']['uptime_seconds']:.1f}秒\n"
            f"{'='*60}\n"
        )

    def get_stats(self) -> Dict[str, Any]:
        """
        获取完整统计信息

        Returns:
            统计信息字典
        """
        return {
            "state": self.state.value,
            "health_report": self.health_monitor.get_health_report(),
            "reconnection_stats": self.reconnection_manager.get_stats(),
            "subscription_count": len(self._active_subscriptions),
        }
