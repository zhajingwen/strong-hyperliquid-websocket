"""
增强的 WebSocket 连接管理器
解决 Hyperliquid SDK 的假活状态问题

特性：
- ✅ 双层假活检测（底层连接状态 + 应用层心跳监控）
- ✅ 应用层数据流监控（默认 30 秒超时）
- ✅ 自动重连（指数退避策略）
- ✅ 错误分类处理
- ✅ 连接状态回调
- ✅ 结构化日志与统计
"""

import time
import random
import logging
import threading
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from hyperliquid.info import Info
from hyperliquid.utils.types import Subscription


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
        timeout: float = 30.0,
        warning_threshold: float = 15.0
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

    封装 Hyperliquid SDK 的 WebSocket 连接，提供：
    - 自动健康检查
    - 自动重连
    - 连接状态管理
    - 统计与监控
    """

    def __init__(
        self,
        base_url: str,
        subscriptions: List[Subscription],
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
        self._info: Optional[Info] = None
        self._running = False
        self._subscription_ids: List[int] = []

        # 线程安全保护
        self._state_lock = threading.RLock()  # 使用递归锁避免死锁

        # 连接就绪事件
        self._connection_ready_event = threading.Event()
        self._connection_timeout = 10.0  # 最大等待时间（秒）

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
            # 检查 Info 对象
            if self._info is None:
                return False

            # 检查 ws_manager
            if not hasattr(self._info, 'ws_manager') or self._info.ws_manager is None:
                return False

            ws_manager = self._info.ws_manager

            # 检查 ws_ready 标志
            if not getattr(ws_manager, 'ws_ready', False):
                return False

            # 检查 WebSocket 对象
            if not hasattr(ws_manager, 'ws') or ws_manager.ws is None:
                return False

            # 检查运行状态
            ws = ws_manager.ws
            keep_running = getattr(ws, 'keep_running', False)

            # 额外检查：WebSocket 连接是否已打开
            # websocket-client 库的连接状态
            if hasattr(ws, 'sock') and ws.sock is None:
                return False

            return keep_running

        except Exception as e:
            logger.debug(f"检查连接状态异常: {e}")
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
            self._connection_ready_event.clear()

            # 创建连接
            logger.info(f"正在连接到 {self.base_url}...")
            self._info = Info(self.base_url)

            # 启动连接状态检查线程
            def wait_for_ready():
                start_time = time.time()
                while time.time() - start_time < self._connection_timeout:
                    if self._is_connected():
                        self._connection_ready_event.set()
                        return
                    time.sleep(0.1)  # 100ms 轮询间隔
                logger.warning(f"连接超时（{self._connection_timeout}秒），但继续尝试订阅")
                self._connection_ready_event.set()  # 超时也放行

            check_thread = threading.Thread(target=wait_for_ready, daemon=True)
            check_thread.start()

            # 等待连接就绪或超时
            ready = self._connection_ready_event.wait(timeout=self._connection_timeout)
            if not ready:
                logger.warning("等待连接就绪超时")

            # 订阅频道（事务性）
            logger.info(f"开始订阅 {len(self.subscriptions)} 个频道...")
            temp_subscription_ids = []  # 临时存储
            try:
                for sub in self.subscriptions:
                    try:
                        sub_id = self._info.subscribe(sub, self._wrapped_callback)
                        temp_subscription_ids.append(sub_id)
                        logger.debug(f"已订阅: {sub} (ID: {sub_id})")
                    except Exception as sub_error:
                        logger.error(f"订阅失败: {sub} - {sub_error}")
                        # 回滚：取消已订阅的频道
                        for sid in temp_subscription_ids:
                            try:
                                self._info.unsubscribe(sid)
                            except:
                                pass  # 尽力而为
                        raise  # 重新抛出异常

                # 所有订阅成功，提交
                self._subscription_ids = temp_subscription_ids
                self.state = ConnectionState.CONNECTED
                logger.info("✅ 连接成功并完成订阅")
            except Exception as sub_error:
                logger.error(f"订阅过程失败: {sub_error}")
                raise

            # 重置监控器和重连管理器
            self.health_monitor.reset()
            self.reconnection_manager.reset()

            return True

        except Exception as e:
            logger.error(f"连接失败: {e}", exc_info=True)
            self.state = ConnectionState.DISCONNECTED
            self.health_monitor.on_error()
            return False

    def _disconnect(self) -> None:
        """断开连接并清理资源"""
        logger.info("正在断开连接...")

        try:
            # 先取消订阅
            if self._info and self._subscription_ids:
                for sub_id in self._subscription_ids:
                    try:
                        self._info.unsubscribe(sub_id)
                        logger.debug(f"已取消订阅: {sub_id}")
                    except Exception as unsub_error:
                        logger.warning(f"取消订阅失败 ({sub_id}): {unsub_error}")

            # 再断开连接
            if self._info and hasattr(self._info, 'ws_manager') and self._info.ws_manager:
                self._info.disconnect_websocket()
                logger.info("WebSocket 已断开")

        except Exception as e:
            logger.error(f"断开连接时异常: {e}", exc_info=True)
            # 不吞噬异常，但确保清理继续

        finally:
            # 无论如何都清理状态
            self._subscription_ids.clear()
            self._info = None
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
            "subscription_count": len(self._subscription_ids),
        }
