"""
Hyperliquid WebSocket 订阅测试（增强版）

使用增强的 WebSocket 管理器，解决假活状态问题。

特性：
- ✅ 自动健康检查（假活检测）
- ✅ 自动重连（指数退避策略）
- ✅ 连接状态监控
- ✅ 统计信息输出
- ✅ 优雅关闭

使用方法：
    python ws_holcv.py [选项]

选项：
    --verbose    详细日志模式
    --timeout N  数据流超时时间（秒，默认30）
    --retries N  最大重连次数（默认10，0表示无限）
"""

import sys
import logging
from typing import Any

from hyperliquid.utils import constants
from enhanced_ws_manager import (
    EnhancedWebSocketManager,
    ConnectionState
)


# ==================== 配置区 ====================

# API 端点
BASE_URL = constants.MAINNET_API_URL

# 订阅列表
SUBSCRIPTIONS = [
    # 高频数据（用于假活检测）
    # {"type": "allMids"},  # 全市场中间价，高频更新

    # 市场数据
    # {"type": "l2Book", "coin": "ETH"},
    # {"type": "trades", "coin": "ETH"},
    {"type": "candle", "coin": "ETH", "interval": "1m"},
    # {"type": "bbo", "coin": "ETH"},

    # 资产上下文
    # {"type": "activeAssetCtx", "coin": "BTC"},  # Perp
    # {"type": "activeAssetCtx", "coin": "@1"},   # Spot

    # 用户数据订阅（需要账户地址）
    # {"type": "userEvents", "user": "YOUR_ADDRESS"},
    # {"type": "userFills", "user": "YOUR_ADDRESS"},
    # {"type": "orderUpdates", "user": "YOUR_ADDRESS"},
    # {"type": "userFundings", "user": "YOUR_ADDRESS"},
    # {"type": "userNonFundingLedgerUpdates", "user": "YOUR_ADDRESS"},
    # {"type": "webData2", "user": "YOUR_ADDRESS"},
    # {"type": "activeAssetData", "user": "YOUR_ADDRESS", "coin": "BTC"},
]

# 健康检查配置
HEALTH_CHECK_INTERVAL = 5.0  # 每5秒检查一次
DATA_TIMEOUT = 60.0  # 60秒无数据视为假活（适配低频K线数据）
MAX_RETRIES = 0  # 最大重连次数（0表示无限重连）


# ==================== 回调函数 ====================

def safe_print(msg: Any) -> None:
    """
    安全的消息打印函数

    Args:
        msg: WebSocket 消息
    """
    try:
        # 提取消息类型
        channel = msg.get("channel", "unknown")

        # 简化输出
        if channel == "allMids":
            # allMids 数据量大，只打印前3个币种
            data = msg.get("data", {})
            preview = dict(list(data.items())[:3])
            print(f"[allMids] 收到 {len(data)} 个币种价格，示例: {preview}")

        elif channel == "trades":
            # 交易数据
            trades = msg.get("data", [])
            if trades:
                trade = trades[0]
                print(
                    f"[trades] {trade.get('coin')} - "
                    f"价格: ${trade.get('px')}, "
                    f"数量: {trade.get('sz')}, "
                    f"方向: {trade.get('side')}"
                )

        elif channel == "l2Book":
            # 订单簿
            data = msg.get("data", {})
            coin = data.get("coin", "N/A")
            levels = data.get("levels", [[], []])
            bid_count = len(levels[0]) if len(levels) > 0 else 0
            ask_count = len(levels[1]) if len(levels) > 1 else 0
            print(f"[l2Book] {coin} - Bids: {bid_count}, Asks: {ask_count}")

        elif channel == "candle":
            # K线数据
            data = msg.get("data", {})
            print(data)
            print(
                f"[candle] {data.get('s')} {data.get('i')} - "
                f"O: {data.get('o')}, H: {data.get('h')}, "
                f"L: {data.get('l')}, C: {data.get('c')}"
            )

        elif channel == "bbo":
            # 最优买卖价
            data = msg.get("data", {})
            coin = data.get("coin", "N/A")
            bid = data.get("bid", "N/A")
            ask = data.get("ask", "N/A")
            print(f"[bbo] {coin} - Bid: {bid}, Ask: {ask}")

        elif channel in ["activeAssetCtx", "activeSpotAssetCtx"]:
            # 资产上下文
            data = msg.get("data", {})
            coin = data.get("coin", "N/A")
            mark_px = data.get("markPx", "N/A")
            funding = data.get("funding", "N/A")
            print(f"[{channel}] {coin} - 标记价: {mark_px}, 资金费率: {funding}")

        elif channel == "user":
            # 用户事件
            data = msg.get("data", {})
            print(f"[userEvents] {data}")

        elif channel == "userFills":
            # 用户成交
            data = msg.get("data", {})
            fills = data.get("fills", [])
            print(f"[userFills] 收到 {len(fills)} 笔成交")

        elif channel == "orderUpdates":
            # 订单更新
            data = msg.get("data", [])
            print(f"[orderUpdates] 收到 {len(data)} 个订单更新")

        else:
            # 其他消息类型
            print(f"[{channel}] {msg}")

    except Exception as e:
        logging.error(f"打印消息时异常: {e}")
        # 异常时输出原始消息
        print(f"[raw] {msg}")


def on_connection_state_change(state: ConnectionState) -> None:
    """
    连接状态变化回调

    Args:
        state: 新的连接状态
    """
    state_emoji = {
        ConnectionState.DISCONNECTED: "⭕",
        ConnectionState.CONNECTING: "🔄",
        ConnectionState.CONNECTED: "✅",
        ConnectionState.RECONNECTING: "🔄",
        ConnectionState.FAILED: "❌",
    }

    emoji = state_emoji.get(state, "❓")
    print(f"\n{emoji} 连接状态变化: {state.value}\n")


# ==================== 主程序 ====================

def parse_args():
    """解析命令行参数"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Hyperliquid WebSocket 订阅测试（增强版）"
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
    parser.add_argument(
        "--retries",
        type=int,
        default=MAX_RETRIES,
        help=f"最大重连次数（默认{MAX_RETRIES}，0表示无限）"
    )
    parser.add_argument(
        "--check-interval",
        type=float,
        default=HEALTH_CHECK_INTERVAL,
        help=f"健康检查间隔（秒，默认{HEALTH_CHECK_INTERVAL}）"
    )

    return parser.parse_args()


def main():
    """主函数"""
    # 解析参数
    args = parse_args()

    # 配置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("enhanced_ws_manager").setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger("enhanced_ws_manager").setLevel(logging.INFO)

    # 打印配置
    print("="*60)
    print("Hyperliquid WebSocket 订阅测试（增强版）")
    print("="*60)
    print(f"API 端点: {BASE_URL}")
    print(f"订阅数量: {len(SUBSCRIPTIONS)}")
    print(f"健康检查间隔: {args.check_interval}秒")
    print(f"数据流超时: {args.timeout}秒")
    print(f"最大重连次数: {args.retries if args.retries > 0 else '无限'}")
    print("="*60)
    print("\n按 Ctrl+C 停止程序\n")

    # 创建增强管理器
    manager = EnhancedWebSocketManager(
        base_url=BASE_URL,
        subscriptions=SUBSCRIPTIONS,
        message_callback=safe_print,
        health_check_interval=args.check_interval,
        data_timeout=args.timeout,
        max_retries=args.retries,
        on_state_change=on_connection_state_change
    )

    # 启动管理器（会阻塞直到 Ctrl+C）
    try:
        manager.start()
    except Exception as e:
        logging.error(f"程序异常: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
