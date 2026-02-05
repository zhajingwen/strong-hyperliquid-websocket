"""
监控指定用户的交易动态

订阅内容：
- userFills: 用户成交记录
- orderUpdates: 用户订单状态更新
- userEvents: 用户事件通知

使用方法：
    # 单地址监控
    python scripts/watch_user_trades.py [地址]
    python scripts/watch_user_trades.py --address 0x138fb48dc319a514e13217acdb7ef97441f1b515

    # 批量监控（从配置文件读取）
    python scripts/watch_user_trades.py --file scripts/monitor_transations_tragets.txt
    python scripts/watch_user_trades.py -f scripts/monitor_transations_tragets.txt
"""

import sys
import os
import logging
import argparse
import threading
from datetime import datetime
from typing import Any, List, Dict, Set, Optional

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hyperliquid.utils import constants
from enhanced_ws_manager import EnhancedWebSocketManager, ConnectionState


# ==================== 去重管理 ====================
# 使用有限大小的集合进行去重，防止内存泄漏
class DeduplicationCache:
    """
    去重缓存 - 使用有限大小的集合避免内存泄漏
    重连后自动保留已打印的记录，跳过重复消息
    """
    def __init__(self, max_size: int = 10000):
        self.max_size = max_size
        self._cache: set = set()
        self._order: list = []  # 保持插入顺序，用于淘汰最旧的

    def contains(self, key: str) -> bool:
        """检查是否已存在"""
        return key in self._cache

    def add(self, key: str) -> None:
        """添加到缓存"""
        if key in self._cache:
            return
        # 如果缓存已满，移除最旧的元素
        if len(self._cache) >= self.max_size:
            oldest = self._order.pop(0)
            self._cache.discard(oldest)
        self._cache.add(key)
        self._order.append(key)

    def size(self) -> int:
        """返回当前缓存大小"""
        return len(self._cache)


# 去重缓存实例
printed_fills = DeduplicationCache(max_size=10000)      # 成交去重 (基于 tid)
printed_orders = DeduplicationCache(max_size=5000)      # 订单更新去重 (基于 oid+status+timestamp)
printed_events = DeduplicationCache(max_size=5000)      # 用户事件去重


# ==================== 多连接池管理器 ====================

class MultiConnectionManager:
    """
    多连接池管理器

    解决 Hyperliquid API 单连接最多追踪 10 个用户的限制。
    自动将用户分组，每组创建独立 WebSocket 连接。
    """

    MAX_USERS_PER_CONNECTION = 10

    def __init__(
        self,
        base_url: str,
        addresses: List[str],
        message_callback,
        health_check_interval: float = 5.0,
        data_timeout: float = 120.0,
        max_retries: int = 0,
        on_state_change=None
    ):
        """
        初始化多连接池

        Args:
            base_url: API 基础 URL
            addresses: 要监控的地址列表
            message_callback: 消息回调函数
            health_check_interval: 健康检查间隔
            data_timeout: 数据超时时间
            max_retries: 最大重连次数
            on_state_change: 状态变化回调
        """
        self.base_url = base_url
        self.addresses = addresses
        self.message_callback = message_callback
        self.health_check_interval = health_check_interval
        self.data_timeout = data_timeout
        self.max_retries = max_retries
        self.on_state_change = on_state_change

        self.managers: List[EnhancedWebSocketManager] = []
        self.threads: List[threading.Thread] = []
        self._running = False
        self._lock = threading.Lock()

        # 连接状态追踪
        self._connection_states: Dict[int, ConnectionState] = {}

        # 初始化连接池
        self._init_connection_pool()

    def _init_connection_pool(self) -> None:
        """初始化连接池，将用户分组"""
        # 按 MAX_USERS_PER_CONNECTION 分组
        for group_idx, i in enumerate(range(0, len(self.addresses), self.MAX_USERS_PER_CONNECTION)):
            group_addresses = self.addresses[i:i + self.MAX_USERS_PER_CONNECTION]
            subscriptions = self._build_subscriptions(group_addresses)

            # 为每个连接创建状态回调
            state_callback = self._create_state_callback(group_idx)

            manager = EnhancedWebSocketManager(
                base_url=self.base_url,
                subscriptions=subscriptions,
                message_callback=self.message_callback,
                health_check_interval=self.health_check_interval,
                data_timeout=self.data_timeout,
                max_retries=self.max_retries,
                on_state_change=state_callback
            )

            self.managers.append(manager)
            self._connection_states[group_idx] = ConnectionState.DISCONNECTED

        logging.info(
            f"连接池初始化完成: {len(self.managers)} 个连接, "
            f"共监控 {len(self.addresses)} 个用户"
        )

    def _build_subscriptions(self, addresses: List[str]) -> List[Dict[str, Any]]:
        """为地址列表构建订阅配置"""
        subscriptions = []
        for addr in addresses:
            subscriptions.append({"type": "userFills", "user": addr})
            subscriptions.append({"type": "orderUpdates", "user": addr})
            subscriptions.append({"type": "userEvents", "user": addr})
        return subscriptions

    def _create_state_callback(self, group_idx: int):
        """为每个连接创建状态回调"""
        def callback(state: ConnectionState):
            with self._lock:
                old_state = self._connection_states.get(group_idx)
                self._connection_states[group_idx] = state

            # 打印连接池状态
            emoji_map = {
                ConnectionState.DISCONNECTED: "⭕",
                ConnectionState.CONNECTING: "🔄",
                ConnectionState.CONNECTED: "✅",
                ConnectionState.RECONNECTING: "🔄",
                ConnectionState.FAILED: "❌",
            }
            emoji = emoji_map.get(state, "❓")

            start_idx = group_idx * self.MAX_USERS_PER_CONNECTION
            end_idx = min(start_idx + self.MAX_USERS_PER_CONNECTION, len(self.addresses))
            user_count = end_idx - start_idx

            print(f"{emoji} 连接池 #{group_idx + 1} ({user_count}用户): {state.value}")

            # 调用用户的状态回调
            if self.on_state_change:
                self.on_state_change(state)

        return callback

    def start(self) -> None:
        """启动所有连接"""
        if self._running:
            logging.warning("连接池已在运行中")
            return

        self._running = True
        self.threads.clear()

        print(f"\n🚀 启动连接池 ({len(self.managers)} 个连接)...\n")

        # 启动每个连接（在独立线程中）
        for idx, manager in enumerate(self.managers):
            start_idx = idx * self.MAX_USERS_PER_CONNECTION
            end_idx = min(start_idx + self.MAX_USERS_PER_CONNECTION, len(self.addresses))
            user_count = end_idx - start_idx

            t = threading.Thread(
                target=self._run_manager,
                args=(manager, idx),
                daemon=True,
                name=f"WSPool-{idx + 1}"
            )
            self.threads.append(t)
            t.start()

            logging.info(f"连接池 #{idx + 1} 已启动 (用户 {start_idx + 1}-{end_idx})")

            # 错开启动时间，避免同时连接
            if idx < len(self.managers) - 1:
                threading.Event().wait(0.5)

        # 主线程等待所有连接
        try:
            while self._running:
                # 检查是否所有线程都还活着
                alive_count = sum(1 for t in self.threads if t.is_alive())
                if alive_count == 0:
                    logging.warning("所有连接线程已停止")
                    break
                threading.Event().wait(1.0)
        except KeyboardInterrupt:
            print("\n收到中断信号，正在停止所有连接...")
        finally:
            self.stop()

    def _run_manager(self, manager: EnhancedWebSocketManager, idx: int) -> None:
        """在独立线程中运行单个管理器"""
        try:
            manager.start()
        except Exception as e:
            logging.error(f"连接池 #{idx + 1} 异常: {e}", exc_info=True)

    def stop(self) -> None:
        """停止所有连接"""
        if not self._running:
            return

        logging.info("正在停止所有连接...")
        self._running = False

        # 停止所有管理器
        for idx, manager in enumerate(self.managers):
            try:
                manager.stop()
                logging.info(f"连接池 #{idx + 1} 已停止")
            except Exception as e:
                logging.error(f"停止连接池 #{idx + 1} 异常: {e}")

        # 等待线程结束
        for t in self.threads:
            if t.is_alive():
                t.join(timeout=2.0)

        print(f"\n✅ 所有连接已停止\n")

    def get_stats(self) -> Dict[str, Any]:
        """获取连接池统计信息"""
        stats = {
            "total_connections": len(self.managers),
            "total_users": len(self.addresses),
            "connection_states": {},
            "managers": []
        }

        for idx, manager in enumerate(self.managers):
            with self._lock:
                state = self._connection_states.get(idx, ConnectionState.DISCONNECTED)

            stats["connection_states"][f"pool_{idx + 1}"] = state.value
            stats["managers"].append(manager.get_stats())

        return stats


# ==================== 配置区 ====================

# 默认监控地址
DEFAULT_ADDRESS = "0x138fb48dc319a514e13217acdb7ef97441f1b515"

# 默认配置文件路径
DEFAULT_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "monitor_transations_tragets.txt"
)

# API 端点
BASE_URL = constants.MAINNET_API_URL

# 健康检查配置
HEALTH_CHECK_INTERVAL = 5.0
DATA_TIMEOUT = 120.0  # 用户可能不频繁交易，适当放宽超时
MAX_RETRIES = 0  # 无限重连

# 地址别名映射（可选，用于更友好的显示）
ADDRESS_ALIASES: Dict[str, str] = {
    # "0x138fb48dc319a514e13217acdb7ef97441f1b515": "主账户",
}

# 已监控的地址集合（用于消息显示）
MONITORED_ADDRESSES: Set[str] = set()

# 调试模式
DEBUG_MODE: bool = False


# ==================== 地址管理 ====================

def load_addresses_from_file(filepath: str) -> List[str]:
    """
    从配置文件加载地址列表

    支持格式：
    - 每行一个地址
    - 空行会被忽略
    - '---' 分隔符会被忽略
    - '#' 开头的行为注释

    Args:
        filepath: 配置文件路径

    Returns:
        地址列表
    """
    addresses = []

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"配置文件不存在: {filepath}")

    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()

            # 跳过空行
            if not line:
                continue

            # 跳过分隔符
            if line.startswith('---'):
                continue

            # 跳过注释
            if line.startswith('#'):
                continue

            # 验证地址格式
            if not line.startswith('0x') or len(line) != 42:
                logging.warning(f"第 {line_num} 行地址格式无效，已跳过: {line}")
                continue

            # 转为小写统一格式
            address = line.lower()
            if address not in addresses:
                addresses.append(address)

    return addresses


def format_address(address: str, short: bool = True) -> str:
    """
    格式化地址显示

    Args:
        address: 钱包地址
        short: 是否使用短格式

    Returns:
        格式化后的地址字符串
    """
    addr_lower = address.lower()

    # 检查是否有别名
    alias = ADDRESS_ALIASES.get(addr_lower)
    if alias:
        if short:
            return f"{alias}"
        return f"{alias} ({addr_lower[:8]}...{addr_lower[-6:]})"

    # 无别名，使用短地址
    if short:
        return f"{address[:8]}...{address[-6:]}"
    return address


def get_address_index(address: str) -> int:
    """获取地址在监控列表中的索引（用于显示编号）"""
    addr_lower = address.lower()
    try:
        addresses_list = sorted(MONITORED_ADDRESSES)
        return addresses_list.index(addr_lower) + 1
    except ValueError:
        return 0


# ==================== 回调函数 ====================

def format_timestamp(ts: int) -> str:
    """格式化时间戳"""
    return datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]


def on_message(msg: Any) -> None:
    """
    消息回调处理函数
    """
    try:
        channel = msg.get("channel", "unknown")
        data = msg.get("data", {})

        # 调试模式：打印原始消息
        if DEBUG_MODE and channel not in ["pong", "subscriptionResponse"]:
            import json
            print(f"\n🔍 [DEBUG] channel={channel}")
            print(f"🔍 [DEBUG] data={json.dumps(data, indent=2, default=str)[:500]}")

        if channel == "user":
            # userEvents 通道 - 从 data 中获取 user
            user = data.get("user", "") if isinstance(data, dict) else ""
            handle_user_events(data, user)

        elif channel == "userFills":
            # 用户成交记录 - user 在 data 中
            handle_user_fills(data)

        elif channel == "orderUpdates":
            # 订单状态更新 - user 在 data 中
            user = data.get("user", "") if isinstance(data, dict) else ""
            orders = data.get("orders", data) if isinstance(data, dict) else data
            handle_order_updates(orders, user)

        elif channel == "error":
            error_msg = msg.get("data", "")
            if "Already unsubscribed" not in error_msg:
                # 订阅超限错误只打印一次摘要
                if "10 total users" in error_msg:
                    # 使用计数器避免重复打印
                    if not hasattr(on_message, '_limit_error_count'):
                        on_message._limit_error_count = 0
                    on_message._limit_error_count += 1
                    if on_message._limit_error_count <= 3:
                        print(f"❌ [订阅超限] {error_msg} (第 {on_message._limit_error_count} 次)")
                    elif on_message._limit_error_count == 4:
                        print(f"❌ [订阅超限] 后续相同错误将不再显示...")
                else:
                    print(f"❌ [错误] {error_msg}")

        elif channel == "subscriptionResponse":
            # 订阅响应，忽略
            pass

        else:
            # 其他未知消息，打印完整内容便于调试
            print(f"📨 [{channel}] {msg}")

    except Exception as e:
        logging.error(f"处理消息异常: {e}")
        print(f"[原始消息] {msg}")


def handle_user_events(data: Any, user: str = "") -> None:
    """处理用户事件"""
    # 尝试从 data 中获取 user
    if not user and isinstance(data, dict):
        user = data.get("user", "")

    # 如果没有用户信息，跳过打印（过滤无效消息）
    if not user:
        logging.debug(f"跳过无用户信息的用户事件: {data}")
        return

    # 去重处理：构建事件唯一标识
    if isinstance(data, dict):
        # 提取关键信息构建去重键
        fills = data.get("fills", [])
        funding = data.get("funding", {})
        liquidation = data.get("liquidation", {})
        non_user_cancel = data.get("nonUserCancel", [])

        # 构建去重键：用户 + fills的tid列表 + funding/liquidation内容
        fill_tids = sorted([f.get("tid", "") for f in fills if f.get("tid")])
        event_key = f"{user}:fills={','.join(fill_tids)}:funding={bool(funding)}:liq={bool(liquidation)}:cancel={len(non_user_cancel)}"

        if printed_events.contains(event_key):
            return
        printed_events.add(event_key)
    else:
        # 非字典数据，用字符串表示去重
        event_key = f"{user}:{str(data)[:100]}"
        if printed_events.contains(event_key):
            return
        printed_events.add(event_key)

    addr_display = format_address(user)
    addr_idx = get_address_index(user)
    idx_tag = f"[#{addr_idx}]" if addr_idx > 0 else ""

    print("\n" + "═" * 100)
    print(f"📢 用户事件 {idx_tag} {addr_display}")
    print(f"   地址: {user}")
    print("═" * 100)

    if isinstance(data, dict):
        # 变量已在上方提取，直接使用
        if fills:
            print(f"\n🔸 成交事件 ({len(fills)} 笔):")
            for fill in fills:
                print_fill(fill, indent=4)

        if funding:
            print(f"\n🔸 资金费率事件:")
            print(f"    {funding}")

        if liquidation:
            print(f"\n🔸 清算事件:")
            print(f"    {liquidation}")

        if non_user_cancel:
            print(f"\n🔸 非用户取消 ({len(non_user_cancel)} 笔):")
            for cancel in non_user_cancel:
                print(f"    {cancel}")

    else:
        print(f"  数据: {data}")

    print("═" * 100 + "\n")


def handle_user_fills(data: Any) -> None:
    """处理用户成交记录"""
    if not data:
        return

    # userFills 返回格式: {"isSnapshot": bool, "user": str, "fills": [...]}
    is_snapshot = data.get("isSnapshot", False)
    user = data.get("user", "")
    fills = data.get("fills", [])

    if not fills:
        return

    # 去重过滤：跳过已打印的成交记录
    new_fills = []
    for fill in fills:
        tid = fill.get("tid", "")
        if tid and not printed_fills.contains(tid):
            printed_fills.add(tid)
            new_fills.append(fill)

    if not new_fills:
        return

    fills = new_fills[-1:]  # 只显示最新一条
    # 获取地址编号和格式化显示
    addr_idx = get_address_index(user)
    addr_display = format_address(user)
    idx_tag = f"[#{addr_idx}]" if addr_idx > 0 else ""

    snapshot_tag = " [快照]" if is_snapshot else ""
    print("\n" + "═" * 100)
    # print(f"💰 用户成交{snapshot_tag} {idx_tag} {addr_display}")
    print(f"   地址: {user}")
    # print(f"   共 {len(fills)} 笔成交")
    print("═" * 100)

    for idx, fill in enumerate(fills, 1):
        print(f"\n  ── 成交 #{idx} ──")
        print_fill(fill, indent=4)

    print("═" * 100 + "\n")


def print_fill(fill: dict, indent: int = 0) -> None:
    """打印成交详情"""
    prefix = " " * indent

    coin = fill.get("coin", "N/A")
    side = fill.get("side", "N/A")
    side_text = "买入" if side == "B" else "卖出"
    side_emoji = "🟢" if side == "B" else "🔴"

    # 方向信息 (dir): "Open Long", "Open Short", "Close Long", "Close Short"
    direction = fill.get("dir", "")
    start_position = fill.get("startPosition", "0")

    # 判断是否为合约交易（有 dir 字段表示合约）
    is_perp = bool(direction)

    # 区分建仓/加仓/平仓
    dir_text = ""
    if direction:
        try:
            pos = float(start_position)
        except (ValueError, TypeError):
            pos = 0

        if direction == "Open Long":
            if pos == 0:
                dir_text = "📈 建多"  # 建仓做多
            elif pos > 0:
                dir_text = "📈 加多"  # 加仓做多
            else:
                dir_text = "📈 开多"  # 反向开仓
        elif direction == "Open Short":
            if pos == 0:
                dir_text = "📉 建空"  # 建仓做空
            elif pos < 0:
                dir_text = "📉 加空"  # 加仓做空
            else:
                dir_text = "📉 开空"  # 反向开仓
        elif direction == "Close Long":
            dir_text = "📤 平多"
        elif direction == "Close Short":
            dir_text = "📥 平空"
        else:
            dir_text = direction

    px = fill.get("px", "0")
    sz = fill.get("sz", "0")
    time_ts = fill.get("time", 0)
    time_str = format_timestamp(time_ts) if time_ts else "N/A"

    fee = fill.get("fee", "0")
    fee_token = fill.get("feeToken", "USDC")
    oid = fill.get("oid", "N/A")
    tid = fill.get("tid", "N/A")
    crossed = fill.get("crossed", False)
    liquidation = fill.get("liquidation", False)

    # 标题行
    if is_perp:
        # 合约：币种 + 买卖 + 方向
        title = f"{side_emoji} {coin} {side_text} ({dir_text})"
        trade_type = "🔮 合约"
    else:
        # 现货：简化显示
        title = f"{side_emoji} {coin} {side_text}"
        trade_type = "💰 现货"

    print(f"{prefix}{title}")
    print(f"{prefix}  类型:       {trade_type}")
    print(f"{prefix}  时间:       {time_str}")
    print(f"{prefix}  价格:       ${px}")
    print(f"{prefix}  数量:       {sz}")
    print(f"{prefix}  成交额:     ${float(px) * float(sz):.4f}")
    print(f"{prefix}  手续费:     {fee} {fee_token}")

    # 合约特有字段
    if is_perp:
        closed_pnl = fill.get("closedPnl", "0")
        print(f"{prefix}  起始仓位:   {start_position}")
        if float(closed_pnl) != 0:
            pnl_emoji = "📈" if float(closed_pnl) > 0 else "📉"
            print(f"{prefix}  已实现盈亏: {pnl_emoji} ${closed_pnl}")

    print(f"{prefix}  订单ID:     {oid}")
    print(f"{prefix}  成交ID:     {tid}")

    # crossed: 合约表示穿仓，现货表示吃单(taker)
    if crossed:
        if is_perp:
            print(f"{prefix}  ⚡ 穿仓成交")
        else:
            print(f"{prefix}  🎯 Taker成交")
    if liquidation:
        print(f"{prefix}  ⚠️  清算成交")


def handle_order_updates(data: Any, user: str = "") -> None:
    """处理订单状态更新"""
    if not data:
        return

    # orderUpdates 返回格式可能是:
    # 1. {"user": "0x...", "orders": [...]}
    # 2. 直接是订单列表 [...]
    # 3. 包含 order 字段的对象 {"order": {...}, "status": "...", ...}
    if isinstance(data, dict):
        if not user:
            user = data.get("user", "")
        # 检查是否有 orders 字段
        if "orders" in data:
            orders = data.get("orders", [])
        else:
            orders = [data]
        if not isinstance(orders, list):
            orders = [orders]
    elif isinstance(data, list):
        orders = data
        # 尝试从第一个订单中获取用户地址
        if not user and orders:
            user = orders[0].get("user", "")
    else:
        orders = [data]

    if not orders:
        return

    # 去重过滤：基于 oid + status + statusTimestamp 去重
    new_orders = []
    for order_data in orders:
        # 提取订单信息
        if "order" in order_data:
            order = order_data.get("order", {})
            status = order_data.get("status", order.get("status", ""))
            status_ts = order_data.get("statusTimestamp", order.get("statusTimestamp", 0))
        else:
            order = order_data
            status = order.get("status", "")
            status_ts = order.get("statusTimestamp", 0)

        oid = order.get("oid", "")
        # 构建去重键
        dedup_key = f"{oid}:{status}:{status_ts}"
        if dedup_key and not printed_orders.contains(dedup_key):
            printed_orders.add(dedup_key)
            new_orders.append(order_data)

    if not new_orders:
        return

    orders = new_orders

    # 如果没有用户信息，跳过打印（过滤无效消息）
    if not user:
        logging.debug(f"跳过无用户信息的订单更新: {data}")
        return

    # 获取地址编号和格式化显示
    addr_idx = get_address_index(user)
    addr_display = format_address(user)
    idx_tag = f"[#{addr_idx}]" if addr_idx > 0 else ""

    print("\n" + "═" * 100)
    print(f"📋 订单更新 {idx_tag} {addr_display} ({len(orders)} 个)")
    print(f"   地址: {user}")
    print("═" * 100)

    for idx, order in enumerate(orders, 1):
        print(f"\n  ── 订单 #{idx} ──")
        print_order(order, indent=4)

    print("═" * 100 + "\n")


def print_order(order_data: dict, indent: int = 0) -> None:
    """打印订单详情"""
    prefix = " " * indent

    # orderUpdates 消息格式可能是:
    # 1. 直接的订单对象 {"coin": ..., "side": ..., ...}
    # 2. 包装的对象 {"order": {...}, "status": ..., "statusTimestamp": ...}
    if "order" in order_data:
        order = order_data.get("order", {})
        status = order_data.get("status", order.get("status", "N/A"))
        status_timestamp = order_data.get("statusTimestamp", order.get("statusTimestamp", 0))
    else:
        order = order_data
        status = order.get("status", "N/A")
        status_timestamp = order.get("statusTimestamp", 0)

    # 订单基本信息
    coin = order.get("coin", "N/A")
    side = order.get("side", "N/A")
    side_text = "买入" if side == "B" else "卖出"
    side_emoji = "🟢" if side == "B" else "🔴"

    limit_px = order.get("limitPx", "N/A")
    sz = order.get("sz", "0")
    orig_sz = order.get("origSz", sz)

    oid = order.get("oid", "N/A")
    cloid = order.get("cloid", None)

    # 状态映射
    status_map = {
        "open": "📖 挂单中",
        "filled": "✅ 已成交",
        "canceled": "❌ 已取消",
        "triggered": "⚡ 已触发",
        "rejected": "🚫 已拒绝",
        "marginCanceled": "⚠️ 保证金取消",
    }
    status_display = status_map.get(status, f"❓ {status}")

    time_str = format_timestamp(status_timestamp) if status_timestamp else "N/A"

    print(f"{prefix}{side_emoji} {coin} {side_text} - {status_display}")
    print(f"{prefix}  时间:       {time_str}")
    print(f"{prefix}  限价:       ${limit_px}")
    print(f"{prefix}  数量:       {sz} / {orig_sz}")
    print(f"{prefix}  订单ID:     {oid}")
    if cloid:
        print(f"{prefix}  客户端ID:   {cloid}")

    # 触发订单信息
    trigger_px = order.get("triggerPx", None)
    trigger_condition = order.get("triggerCondition", None)
    if trigger_px:
        print(f"{prefix}  触发价:     ${trigger_px} ({trigger_condition})")

    # 减仓信息
    reduce_only = order.get("reduceOnly", False)
    if reduce_only:
        print(f"{prefix}  📉 仅减仓订单")

    # 订单类型
    order_type = order.get("orderType", None)
    if order_type:
        print(f"{prefix}  类型:       {order_type}")


def on_connection_state_change(state: ConnectionState) -> None:
    """连接状态变化回调"""
    state_emoji = {
        ConnectionState.DISCONNECTED: "⭕",
        ConnectionState.CONNECTING: "🔄",
        ConnectionState.CONNECTED: "✅",
        ConnectionState.RECONNECTING: "🔄",
        ConnectionState.FAILED: "❌",
    }

    emoji = state_emoji.get(state, "❓")
    print(f"\n{emoji} 连接状态: {state.value}\n")


# ==================== 主程序 ====================

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="监控指定用户的 Hyperliquid 交易动态",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 监控单个地址
  python scripts/watch_user_trades.py 0x138fb48dc319a514e13217acdb7ef97441f1b515

  # 从配置文件批量监控
  python scripts/watch_user_trades.py -f scripts/monitor_transations_tragets.txt

  # 使用默认配置文件
  python scripts/watch_user_trades.py --file-default
        """
    )
    parser.add_argument(
        "address",
        nargs="?",
        default=None,
        help="要监控的钱包地址"
    )
    parser.add_argument(
        "-a", "--address",
        dest="address_flag",
        help="要监控的钱包地址"
    )
    parser.add_argument(
        "-f", "--file",
        dest="config_file",
        help="从配置文件批量加载地址"
    )
    parser.add_argument(
        "--file-default",
        action="store_true",
        help=f"使用默认配置文件: {os.path.basename(DEFAULT_CONFIG_FILE)}"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="启用详细日志"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用调试模式，打印原始消息"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DATA_TIMEOUT,
        help=f"数据流超时时间（秒，默认{DATA_TIMEOUT}）"
    )

    args = parser.parse_args()

    # 优先使用 --address 参数
    if args.address_flag:
        args.address = args.address_flag

    return args


def build_subscriptions(addresses: List[str]) -> List[Dict[str, Any]]:
    """
    为地址列表构建订阅配置

    Args:
        addresses: 地址列表

    Returns:
        订阅配置列表
    """
    subscriptions = []

    for addr in addresses:
        # 用户成交记录
        subscriptions.append({"type": "userFills", "user": addr})
        # 订单状态更新
        subscriptions.append({"type": "orderUpdates", "user": addr})
        # 用户事件
        subscriptions.append({"type": "userEvents", "user": addr})

    return subscriptions


def get_connection_pool_info(addresses: List[str]) -> str:
    """获取连接池分组信息"""
    max_per_conn = MultiConnectionManager.MAX_USERS_PER_CONNECTION
    num_connections = (len(addresses) + max_per_conn - 1) // max_per_conn

    info_lines = []
    for i in range(num_connections):
        start = i * max_per_conn
        end = min(start + max_per_conn, len(addresses))
        info_lines.append(f"  连接池 #{i + 1}: 用户 {start + 1}-{end} ({end - start}个)")

    return "\n".join(info_lines)


def main():
    """主函数"""
    global MONITORED_ADDRESSES, DEBUG_MODE

    args = parse_args()

    # 设置调试模式
    DEBUG_MODE = args.debug

    # 配置日志
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.getLogger().setLevel(log_level)
    logging.getLogger("enhanced_ws_manager").setLevel(log_level)

    # 确定要监控的地址列表
    addresses = []

    if args.file_default:
        # 使用默认配置文件
        try:
            addresses = load_addresses_from_file(DEFAULT_CONFIG_FILE)
            print(f"📂 从默认配置文件加载: {DEFAULT_CONFIG_FILE}")
        except FileNotFoundError as e:
            print(f"❌ {e}")
            return 1

    elif args.config_file:
        # 使用指定配置文件
        try:
            addresses = load_addresses_from_file(args.config_file)
            print(f"📂 从配置文件加载: {args.config_file}")
        except FileNotFoundError as e:
            print(f"❌ {e}")
            return 1

    elif args.address:
        # 单个地址
        addresses = [args.address.lower()]

    else:
        # 默认使用配置文件（如果存在），否则使用默认地址
        if os.path.exists(DEFAULT_CONFIG_FILE):
            try:
                addresses = load_addresses_from_file(DEFAULT_CONFIG_FILE)
                print(f"📂 自动加载配置文件: {DEFAULT_CONFIG_FILE}")
            except Exception:
                addresses = [DEFAULT_ADDRESS.lower()]
        else:
            addresses = [DEFAULT_ADDRESS.lower()]

    if not addresses:
        print("❌ 没有找到有效的监控地址")
        return 1

    # 保存到全局变量（用于消息显示）
    MONITORED_ADDRESSES = set(addresses)

    # 构建订阅列表
    subscriptions = build_subscriptions(addresses)

    # 检查订阅数量限制
    if len(subscriptions) > 1000:
        print(f"⚠️  警告: 订阅数量 ({len(subscriptions)}) 超过 Hyperliquid 限制 (1000)")
        print(f"   建议减少监控地址数量，当前: {len(addresses)} 个地址")
        return 1

    # 判断是否需要多连接池
    max_per_conn = MultiConnectionManager.MAX_USERS_PER_CONNECTION
    use_multi_connection = len(addresses) > max_per_conn
    num_connections = (len(addresses) + max_per_conn - 1) // max_per_conn if use_multi_connection else 1

    # 打印配置
    print("\n" + "=" * 70)
    print("🔍 Hyperliquid 用户交易批量监控")
    print("=" * 70)
    print(f"监控地址数: {len(addresses)} 个")
    print(f"订阅总数:   {len(subscriptions)} 个 (每地址 3 个频道)")
    print(f"API 端点:   {BASE_URL}")
    print(f"数据超时:   {args.timeout}秒")

    if use_multi_connection:
        print(f"连接模式:   多连接池 ({num_connections} 个连接)")
        print("-" * 70)
        print("连接池分组:")
        print(get_connection_pool_info(addresses))
    else:
        print(f"连接模式:   单连接")

    print("-" * 70)
    print("监控地址列表:")
    for idx, addr in enumerate(sorted(addresses), 1):
        alias = ADDRESS_ALIASES.get(addr, "")
        alias_tag = f" ({alias})" if alias else ""
        # 显示所属连接池
        pool_idx = (idx - 1) // max_per_conn + 1 if use_multi_connection else 1
        pool_tag = f" [池#{pool_idx}]" if use_multi_connection else ""
        print(f"  #{idx:02d} {addr}{alias_tag}{pool_tag}")
    print("-" * 70)
    print("订阅频道: userFills, orderUpdates, userEvents")
    print("=" * 70)
    print("\n按 Ctrl+C 停止监控\n")

    # 创建管理器
    if use_multi_connection:
        # 使用多连接池
        manager = MultiConnectionManager(
            base_url=BASE_URL,
            addresses=addresses,
            message_callback=on_message,
            health_check_interval=HEALTH_CHECK_INTERVAL,
            data_timeout=args.timeout,
            max_retries=MAX_RETRIES,
            on_state_change=on_connection_state_change
        )
    else:
        # 单连接
        manager = EnhancedWebSocketManager(
            base_url=BASE_URL,
            subscriptions=subscriptions,
            message_callback=on_message,
            health_check_interval=HEALTH_CHECK_INTERVAL,
            data_timeout=args.timeout,
            max_retries=MAX_RETRIES,
            on_state_change=on_connection_state_change
        )

    # 启动
    try:
        manager.start()
    except Exception as e:
        logging.error(f"程序异常: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
