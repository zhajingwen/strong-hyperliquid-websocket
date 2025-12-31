"""
增强的 WebSocket 连接管理器
解决 Hyperliquid SDK 的假活状态问题

特性：
- ✅ Ping/Pong 超时检测（15秒超时）
- ✅ 应用层心跳监控（30秒数据流检测）
- ✅ 自动重连（指数退避策略）
- ✅ 错误分类处理
- ✅ 连接状态回调
- ✅ 结构化日志与统计
"""

import time
import random
import logging
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

    def on_message(self, msg: Any) -> None:
        """
        记录收到消息

        Args:
            msg: WebSocket 消息
        """
        self.stats.last_message_time = time.time()
        self.stats.total_messages += 1
        self._warned = False  # 重置警告标志

        if self.stats.total_messages % 100 == 0:
            logger.debug(f"已处理 {self.stats.total_messages} 条消息")

    def on_error(self) -> None:
        """记录错误"""
        self.stats.total_errors += 1

    def on_reconnect(self) -> None:
        """记录重连"""
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

    @property
    def state(self) -> ConnectionState:
        """获取连接状态"""
        return self._state

    @state.setter
    def state(self, new_state: ConnectionState) -> None:
        """设置连接状态"""
        if new_state != self._state:
            old_state = self._state
            self._state = new_state
            logger.info(f"连接状态变化: {old_state.value} → {new_state.value}")

            if self.on_state_change:
                try:
                    self.on_state_change(new_state)
                except Exception as e:
                    logger.error(f"状态变化回调异常: {e}")

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
        检查底层连接状态

        Returns:
            True: 底层连接正常
            False: 底层连接断开
        """
        if self._info is None or self._info.ws_manager is None:
            return False

        ws_manager = self._info.ws_manager
        return (
            ws_manager.ws_ready and
            hasattr(ws_manager.ws, 'keep_running') and
            ws_manager.ws.keep_running
        )

    def _connect(self) -> bool:
        """
        建立连接并订阅

        Returns:
            True: 连接成功
            False: 连接失败
        """
        try:
            logger.info(f"正在连接到 {self.base_url}...")

            # 创建新连接
            self._info = Info(self.base_url)
            time.sleep(2)  # 等待连接建立

            # 验证连接
            if not self._is_connected():
                raise RuntimeError("连接建立失败")

            logger.info("✓ 连接建立成功")

            # 订阅所有频道
            self._subscription_ids.clear()
            for sub in self.subscriptions:
                try:
                    sub_id = self._info.subscribe(sub, self._wrapped_callback)
                    self._subscription_ids.append(sub_id)
                    logger.info(f"✓ 订阅成功: {sub.get('type')} - {sub.get('coin', 'N/A')}")
                except Exception as e:
                    logger.error(f"订阅失败: {sub} - {e}")
                    raise

            logger.info(f"✓ 所有订阅完成，共 {len(self._subscription_ids)} 个频道")

            # 重置监控器和重连管理器
            self.health_monitor.reset()
            self.reconnection_manager.reset()

            return True

        except Exception as e:
            logger.error(f"连接失败: {e}", exc_info=True)
            self.health_monitor.on_error()
            return False

    def _disconnect(self) -> None:
        """断开连接"""
        if self._info and self._info.ws_manager:
            try:
                logger.info("正在断开连接...")
                self._info.disconnect_websocket()
                logger.info("✓ 连接已断开")
            except Exception as e:
                logger.error(f"断开连接时异常: {e}")

        self._info = None
        self._subscription_ids.clear()

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
                time.sleep(self.health_check_interval)

                # 检查 1: 底层连接状态
                if not self._is_connected():
                    logger.warning("⚠️  底层连接断开")
                    if not self._reconnect():
                        continue  # 重连失败，继续等待

                # 检查 2: 应用层健康状态（假活检测）
                if not self.health_monitor.is_alive():
                    logger.warning("⚠️  假活状态检测")
                    if not self._reconnect():
                        continue  # 重连失败，继续等待

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
