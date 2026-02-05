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
from datetime import datetime
from typing import Any, List, Dict, Set

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hyperliquid.utils import constants
from enhanced_ws_manager import EnhancedWebSocketManager, ConnectionState


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

        if channel == "user":
            # userEvents 通道
            handle_user_events(data)

        elif channel == "userFills":
            # 用户成交记录
            handle_user_fills(data)

        elif channel == "orderUpdates":
            # 订单状态更新
            handle_order_updates(data)

        elif channel == "error":
            error_msg = msg.get("data", "")
            if "Already unsubscribed" not in error_msg:
                print(f"❌ [错误] {error_msg}")

        elif channel == "subscriptionResponse":
            # 订阅响应，忽略
            pass

        else:
            # 其他未知消息
            print(f"📨 [{channel}] {msg}")

    except Exception as e:
        logging.error(f"处理消息异常: {e}")
        print(f"[原始消息] {msg}")


def handle_user_events(data: Any) -> None:
    """处理用户事件"""
    print("\n" + "═" * 100)
    print(f"📢 用户事件 (userEvents)")
    print("═" * 100)

    if isinstance(data, dict):
        # 检查各类事件
        fills = data.get("fills", [])
        funding = data.get("funding", {})
        liquidation = data.get("liquidation", {})
        non_user_cancel = data.get("nonUserCancel", [])

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

    # 获取地址编号和格式化显示
    addr_idx = get_address_index(user)
    addr_display = format_address(user)
    idx_tag = f"[#{addr_idx}]" if addr_idx > 0 else ""

    snapshot_tag = " [快照]" if is_snapshot else ""
    print("\n" + "═" * 100)
    print(f"💰 用户成交{snapshot_tag} {idx_tag} {addr_display}")
    print(f"   地址: {user}")
    print(f"   共 {len(fills)} 笔成交")
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

    px = fill.get("px", "0")
    sz = fill.get("sz", "0")
    time_ts = fill.get("time", 0)
    time_str = format_timestamp(time_ts) if time_ts else "N/A"

    start_position = fill.get("startPosition", "N/A")
    closed_pnl = fill.get("closedPnl", "0")
    fee = fill.get("fee", "0")
    fee_token = fill.get("feeToken", "USDC")
    oid = fill.get("oid", "N/A")
    tid = fill.get("tid", "N/A")
    crossed = fill.get("crossed", False)
    liquidation = fill.get("liquidation", False)

    print(f"{prefix}{side_emoji} {coin} {side_text}")
    print(f"{prefix}  时间:       {time_str}")
    print(f"{prefix}  价格:       ${px}")
    print(f"{prefix}  数量:       {sz}")
    print(f"{prefix}  成交额:     ${float(px) * float(sz):.4f}")
    print(f"{prefix}  起始仓位:   {start_position}")
    print(f"{prefix}  已实现盈亏: ${closed_pnl}")
    print(f"{prefix}  手续费:     {fee} {fee_token}")
    print(f"{prefix}  订单ID:     {oid}")
    print(f"{prefix}  成交ID:     {tid}")

    if crossed:
        print(f"{prefix}  ⚡ 穿仓成交")
    if liquidation:
        print(f"{prefix}  ⚠️  清算成交")


def handle_order_updates(data: Any, user: str = "") -> None:
    """处理订单状态更新"""
    if not data:
        return

    # orderUpdates 返回的是订单列表
    orders = data if isinstance(data, list) else [data]

    # 尝试从订单中获取用户地址
    if not user and orders:
        user = orders[0].get("user", "")

    # 获取地址编号和格式化显示
    addr_idx = get_address_index(user) if user else 0
    addr_display = format_address(user) if user else "未知"
    idx_tag = f"[#{addr_idx}]" if addr_idx > 0 else ""

    print("\n" + "═" * 100)
    print(f"📋 订单更新 {idx_tag} {addr_display} ({len(orders)} 个)")
    if user:
        print(f"   地址: {user}")
    print("═" * 100)

    for idx, order in enumerate(orders, 1):
        print(f"\n  ── 订单 #{idx} ──")
        print_order(order, indent=4)

    print("═" * 100 + "\n")


def print_order(order: dict, indent: int = 0) -> None:
    """打印订单详情"""
    prefix = " " * indent

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
    status = order.get("status", "N/A")
    status_timestamp = order.get("statusTimestamp", 0)

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


def main():
    """主函数"""
    global MONITORED_ADDRESSES

    args = parse_args()

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

    # 打印配置
    print("\n" + "=" * 70)
    print("🔍 Hyperliquid 用户交易批量监控")
    print("=" * 70)
    print(f"监控地址数: {len(addresses)} 个")
    print(f"订阅总数:   {len(subscriptions)} 个 (每地址 3 个频道)")
    print(f"API 端点:   {BASE_URL}")
    print(f"数据超时:   {args.timeout}秒")
    print("-" * 70)
    print("监控地址列表:")
    for idx, addr in enumerate(sorted(addresses), 1):
        alias = ADDRESS_ALIASES.get(addr, "")
        alias_tag = f" ({alias})" if alias else ""
        print(f"  #{idx:02d} {addr}{alias_tag}")
    print("-" * 70)
    print("订阅频道: userFills, orderUpdates, userEvents")
    print("=" * 70)
    print("\n按 Ctrl+C 停止监控\n")

    # 创建管理器
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
