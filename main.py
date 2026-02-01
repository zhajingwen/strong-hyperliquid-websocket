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
    {"type": "l2Book", "coin": "PURR"},
    {"type": "trades", "coin": "PURR"},
    {"type": "candle", "coin": "PURR", "interval": "5m"},
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
            # 交易数据 - 丰富的表格式输出
            from datetime import datetime

            trades = msg.get("data", [])
            if not trades:
                return

            # 按时间戳降序排序，获取最新的5条交易
            sorted_trades = sorted(trades, key=lambda x: x.get('time', 0), reverse=True)
            recent_trades = sorted_trades[:5]

            # 计算统计数据
            total_volume = sum(float(t.get('sz', 0)) for t in recent_trades)
            buy_trades = [t for t in recent_trades if t.get('side') == 'B']
            sell_trades = [t for t in recent_trades if t.get('side') == 'A']
            avg_price = sum(float(t.get('px', 0)) for t in recent_trades) / len(recent_trades)

            # 打印分隔线和标题
            print("\n" + "═" * 120)
            print(f"📊 [{recent_trades[0].get('coin', 'N/A')}] 最新交易详情 (共 {len(trades)} 笔，显示最新 {len(recent_trades)} 笔)")
            print("═" * 120)

            # 打印每笔交易的详细信息
            for idx, trade in enumerate(recent_trades, 1):
                # 提取所有字段
                coin = trade.get('coin', 'N/A')
                side = trade.get('side', 'N/A')
                side_text = "买入 (Buy)" if side == 'B' else "卖出 (Sell)"
                side_emoji = "🟢" if side == 'B' else "🔴"

                price = float(trade.get('px', 0))
                size = float(trade.get('sz', 0))
                volume = price * size

                timestamp = trade.get('time', 0)
                time_str = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

                tx_hash = trade.get('hash', 'N/A')
                tid = trade.get('tid', 'N/A')
                users = trade.get('users', [])

                # 打印分隔线
                print("\n" + "─" * 120)
                print(f"交易 #{idx} {side_emoji} {side_text}")
                print("─" * 120)

                # 基本信息
                print(f"  币种:         {coin}")
                print(f"  时间:         {time_str} (时间戳: {timestamp})")
                print(f"  方向:         {side_text} ({side})")
                print(f"  价格:         ${price:.8f}")
                print(f"  数量:         {size:.4f}")
                print(f"  成交额:       ${volume:.4f}")
                print(f"  交易ID:       {tid}")

                # 交易哈希
                print(f"  交易哈希:     {tx_hash}")

                # 参与方信息（users[0]=taker主动方, users[1]=maker挂单方）
                print(f"  参与方数量:   {len(users)}")
                if users:
                    print(f"  参与方详情:")

                    # 根据交易方向标注买卖方
                    if side == 'B':  # 主动买入
                        taker_role = "买方 (Taker 主动买入)"
                        maker_role = "卖方 (Maker 挂单卖出)"
                    else:  # 主动卖出
                        taker_role = "卖方 (Taker 主动卖出)"
                        maker_role = "买方 (Maker 挂单买入)"

                    if len(users) >= 1:
                        print(f"    🔸 {taker_role}")
                        print(f"       {users[0]}")
                    if len(users) >= 2:
                        print(f"    🔹 {maker_role}")
                        print(f"       {users[1]}")

            # 打印统计摘要
            print("\n" + "═" * 120)
            print(
                f"📈 统计汇总: "
                f"买入 {len(buy_trades)} 笔 | "
                f"卖出 {len(sell_trades)} 笔 | "
                f"总成交量 {total_volume:.4f} | "
                f"平均价格 ${avg_price:.8f}"
            )
            print("═" * 120 + "\n")

        elif channel == "l2Book":
            # 订单簿 - 详细深度展示
            from datetime import datetime

            data = msg.get("data", {})
            coin = data.get("coin", "N/A")
            timestamp = data.get("time", 0)
            time_str = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

            levels = data.get("levels", [[], []])
            bids = levels[0] if len(levels) > 0 else []  # 买单（价格从高到低）
            asks = levels[1] if len(levels) > 1 else []  # 卖单（价格从低到高）

            if not bids and not asks:
                return

            # 显示前10档深度
            display_depth = 10

            print("\n" + "═" * 130)
            print(f"📖 [{coin}] 订单簿深度 (L2 Order Book)")
            print(f"   更新时间: {time_str}")
            print("═" * 130)

            # 计算最优买卖价和价差
            best_bid = float(bids[0]['px']) if bids else 0
            best_ask = float(asks[0]['px']) if asks else 0
            spread = best_ask - best_bid if best_bid and best_ask else 0
            spread_pct = (spread / best_bid * 100) if best_bid else 0

            # 计算总深度
            total_bid_size = sum(float(b['sz']) for b in bids)
            total_ask_size = sum(float(a['sz']) for a in asks)

            # 打印市场概况
            print(f"\n💰 市场概况:")
            print(f"   最优买价 (Best Bid): ${best_bid:.6f}")
            print(f"   最优卖价 (Best Ask): ${best_ask:.6f}")
            print(f"   买卖价差 (Spread):   ${spread:.6f} ({spread_pct:.3f}%)")
            print(f"   买单总量: {total_bid_size:,.1f} | 卖单总量: {total_ask_size:,.1f}")

            # 打印深度表格（最优价在顶部，买单在左，卖单在右）
            print("\n" + "─" * 140)
            print(f"{'档位':<6} {'':10} {'买单价格 ($)':<16} {'买单数量':<16} {'订单数*':<10} | {'':10} {'卖单价格 ($)':<16} {'卖单数量':<16} {'订单数*':<10}")
            print("─" * 140)

            max_depth = max(len(asks), len(bids))
            display_rows = min(display_depth, max_depth)

            for i in range(display_rows):
                level = i + 1

                # 买单（正序显示，最优价=最高买价在顶部）- 放在左边
                if i < len(bids):
                    bid = bids[i]  # bids本身已经是从高到低排序
                    bid_px = float(bid['px'])
                    bid_sz = float(bid['sz'])
                    bid_n = bid['n']
                    # 如果有多个订单聚合，添加高亮标记
                    bid_n_str = f"{bid_n} ⭐" if bid_n > 1 else str(bid_n)
                    # 第1档标注为最优价
                    bid_label = "🟢" if i == 0 else "🟢"
                    bid_str = f"{bid_label:<10} ${bid_px:<14.6f} {bid_sz:<16,.1f} {bid_n_str:<10}"
                else:
                    bid_str = f"{'':10} {'-':<14} {'-':<16} {'-':<10}"

                # 卖单（正序显示，最优价=最低卖价在顶部）- 放在右边
                if i < len(asks):
                    ask = asks[i]  # asks本身已经是从低到高排序
                    ask_px = float(ask['px'])
                    ask_sz = float(ask['sz'])
                    ask_n = ask['n']
                    # 如果有多个订单聚合，添加高亮标记
                    ask_n_str = f"{ask_n} ⭐" if ask_n > 1 else str(ask_n)
                    # 第1档标注为最优价
                    ask_label = "🔴" if i == 0 else "🔴"
                    ask_str = f"{ask_label:<10} ${ask_px:<14.6f} {ask_sz:<16,.1f} {ask_n_str:<10}"
                else:
                    ask_str = f"{'':10} {'-':<14} {'-':<16} {'-':<10}"

                print(f"{level:<6} {bid_str} | {ask_str}")

            # 打印深度统计
            print("─" * 140)

            # 计算前N档累计深度
            top_n = min(5, len(bids), len(asks))
            top_bid_size = sum(float(bids[i]['sz']) for i in range(top_n)) if bids else 0
            top_ask_size = sum(float(asks[i]['sz']) for i in range(top_n)) if asks else 0

            print(
                f"📊 深度统计: "
                f"总档位 {len(bids)}买/{len(asks)}卖 | "
                f"前{top_n}档买量 {top_bid_size:,.1f} | "
                f"前{top_n}档卖量 {top_ask_size:,.1f}"
            )
            print("═" * 140 + "\n")

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
