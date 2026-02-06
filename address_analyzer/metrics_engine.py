"""
指标计算引擎 - 基于交易数据计算各类指标
"""

import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class AddressMetrics:
    """地址交易指标"""
    address: str
    total_trades: int
    win_rate: float          # 胜率 (%)
    total_pnl: float         # 总PNL = 已实现PNL (USD)
    avg_trade_size: float    # 平均交易规模
    total_volume: float      # 总交易量
    first_trade_time: int    # 首次交易时间
    last_trade_time: int     # 最后交易时间
    active_days: int         # 活跃天数


    # 出入金相关字段
    total_deposits: float = 0.0         # 总充值 (USD)
    total_withdrawals: float = 0.0      # 总提现 (USD)
    actual_initial_capital: float = 0.0 # 实际初始资金 (USD) - 传统方法

    # 转账相关字段（区分盈亏转移）
    total_transfers_in: float = 0.0     # 转入总额 (send/subAccountTransfer)
    total_transfers_out: float = 0.0    # 转出总额 (send/subAccountTransfer)
    net_transfers: float = 0.0          # 净转账 (USD)
    true_capital: float = 0.0           # 真实本金 (仅 deposit/withdraw，不含转账)
    true_capital_roi: float = 0.0       # 基于真实本金的 ROI (%)

    # P0 修复新增字段
    bankruptcy_count: int = 0           # 爆仓次数
    # ROI 扩展指标（P1优化新增）
    time_weighted_roi: float = 0.0         # 时间加权ROI（考虑资金使用时长）
    annualized_roi: float = 0.0            # 年化ROI
    total_roi: float = 0.0                 # 总ROI（含未实现盈亏）
    roi_quality: str = "estimated"         # ROI质量：actual|estimated

    # 累计收益率指标（新增）
    initial_capital_corrected: float = 0.0 # 校正后的账户初始值（含外部转入）


class MetricsEngine:
    """交易指标计算引擎"""

    @staticmethod
    def _get_pnl(fill: Dict) -> float:
        """
        获取交易PNL，支持两种命名格式
        - API格式: closedPnl
        - 数据库格式: closed_pnl
        """
        return float(fill.get('closedPnl') or fill.get('closed_pnl', 0))

    @staticmethod
    def _ensure_sorted_fills(fills: List[Dict]) -> List[Dict]:
        """
        确保 fills 按时间排序（带排序检测以避免重复排序）

        Args:
            fills: 交易列表

        Returns:
            排序后的交易列表
        """
        if not fills:
            return fills

        # 快速检查是否已排序（只检查前100个）
        sample_size = min(len(fills) - 1, 100)
        is_sorted = all(
            fills[i].get('time', 0) <= fills[i+1].get('time', 0)
            for i in range(sample_size)
        )

        if is_sorted:
            return fills  # 已排序，直接返回
        else:
            logger.debug("检测到未排序数据，执行排序")
            return sorted(fills, key=lambda x: x.get('time', 0))

    @classmethod
    def _collect_metrics_data(
        cls,
        fills: List[Dict],
    ) -> Dict:
        """
        单次遍历收集所有指标计算所需的数据

        性能优化：将原来的 16+ 次遍历合并为 1 次
        复杂度：O(N) + O(N log N) 排序（如需要）

        Args:
            fills: 交易记录列表

        Returns:
            包含所有预计算数据的字典
        """
        if not fills:
            return {
                'total_trades': 0,
                'realized_pnl': 0.0,
                'winning_trades': 0,
                'losing_trades': 0,
                'total_volume': 0.0,
                'avg_trade_size': 0.0,
                'first_trade_time': 0,
                'last_trade_time': 0,
                'active_days': 0,
                'sorted_fills': [],
            }

        # 初始化计数器和累加器
        realized_pnl = 0.0
        winning_trades = 0
        losing_trades = 0
        total_volume = 0.0
        trading_dates = set()
        time_sequence = []

        # 排序检测
        is_sorted = True
        prev_time = -float('inf')

        # === 单次遍历 ===
        for fill in fills:
            pnl = cls._get_pnl(fill)
            time_val = fill.get('time', 0)

            # 1. PNL 统计
            realized_pnl += pnl
            if pnl > 0:
                winning_trades += 1
            elif pnl < 0:
                losing_trades += 1

            # 2. 交易量
            price = float(fill.get('px', 0))
            size = float(fill.get('sz', 0))
            total_volume += price * size

            # 3. 排序检测
            # 处理 datetime 和毫秒时间戳两种格式
            if isinstance(time_val, datetime):
                time_comparable = time_val.timestamp() * 1000
            else:
                time_comparable = time_val

            if time_comparable < prev_time:
                is_sorted = False
            prev_time = time_comparable

            # 4. 活跃天数
            if isinstance(time_val, datetime):
                trading_dates.add(time_val.date())
            elif isinstance(time_val, int) and time_val > 0:
                trading_dates.add(datetime.fromtimestamp(time_val / 1000).date())

            # 5. 时间序列
            time_sequence.append(time_val)

        # 排序处理
        if not is_sorted:
            sorted_fills = sorted(fills, key=lambda x: x.get('time', 0))
            time_sequence = [f.get('time', 0) for f in sorted_fills]
            logger.debug("检测到未排序数据，已执行排序")
        else:
            sorted_fills = fills

        # 计算派生指标
        total_trades = len(fills)
        avg_trade_size = total_volume / total_trades if total_trades > 0 else 0.0
        first_trade_time = time_sequence[0] if time_sequence else 0
        last_trade_time = time_sequence[-1] if time_sequence else 0

        return {
            'total_trades': total_trades,
            'realized_pnl': realized_pnl,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'total_volume': total_volume,
            'avg_trade_size': avg_trade_size,
            'first_trade_time': first_trade_time,
            'last_trade_time': last_trade_time,
            'active_days': len(trading_dates),
            'sorted_fills': sorted_fills,
        }

    @staticmethod
    def calculate_actual_initial_capital(
        account_value: float,
        realized_pnl: float,
        net_deposits: float
    ) -> float:
        """
        计算实际初始资金

        公式：实际初始资金 = 当前账户价值 - 已实现PNL - 净充值

        推导逻辑：
            当前账户 = 初始资金 + 交易盈亏 + 充值 - 提现
            初始资金 = 当前账户 - 交易盈亏 - (充值 - 提现)

        Args:
            account_value: 当前账户价值
            realized_pnl: 已实现PNL
            net_deposits: 净充值（总充值 - 总提现）

        Returns:
            实际初始资金，如果计算结果 ≤ 0 则降级到推算初始资金
        """
        actual_initial = account_value - realized_pnl - net_deposits

        # 边界保护：如果结果为负或极小值，使用动态降级策略
        if actual_initial <= 0:
            fallback = account_value - realized_pnl

            if fallback > 0:
                # 使用推算初始资金
                logger.warning(f"降级到推算初始资金: {fallback:.2f}")
                return fallback
            else:
                # 动态保守估计
                conservative = max(
                    account_value * 1.1,      # 假设亏损不超过10%
                    abs(realized_pnl) * 0.5,  # 初始资金至少是亏损的50%
                    100.0
                )
                logger.warning(f"使用保守估计: {conservative:.2f}")
                return conservative

        return actual_initial

    @classmethod
    def calculate_time_weighted_roi(
        cls,
        fills: List[Dict],
        ledger: List[Dict],
        account_value: float,
        address: str,
        state: Optional[Dict] = None
    ) -> tuple[float, float, float, str]:
        """
        计算时间加权ROI、年化ROI和总ROI

        时间加权ROI考虑每笔资金的投入时长，更公平地评估收益率。

        Args:
            fills: 交易记录列表
            ledger: 出入金记录
            account_value: 当前账户价值
            address: 用户地址
            state: 账户状态（用于获取未实现盈亏）

        Returns:
            (time_weighted_roi, annualized_roi, total_roi, quality)

        算法说明：
            时间加权ROI = 总收益 / (资金 × 时间的加权平均)

            示例：
            - 第1天投入$10K，持有100天，赚$1K
            - 第50天追加$5K，持有50天
            - 平均资金使用 = (10K×100 + 5K×50) / 100 = 12.5K
            - 时间加权ROI = $1K / $12.5K = 8%
        """
        if not fills or not ledger:
            return 0.0, 0.0, 0.0, 'insufficient_data'

        import time as time_module

        # 1. 合并所有事件并按时间排序
        events = []

        # 添加交易事件
        for fill in fills:
            events.append({
                'time': fill.get('time', 0),
                'type': 'trade',
                'pnl': cls._get_pnl(fill)
            })

        # 添加出入金事件
        for record in ledger:
            amount = cls._extract_ledger_amount(record, address)
            if amount != 0:
                events.append({
                    'time': record.get('time', 0),
                    'type': 'cash_flow',
                    'amount': amount
                })

        events.sort(key=lambda x: x['time'])

        if not events:
            return 0.0, 0.0, 0.0, 'no_events'

        # 2. 计算时间加权资金和总收益
        capital_time_weighted = 0.0  # 资金×时间的累积
        total_return = 0.0            # 总交易收益
        running_capital = 0.0         # 当前资金
        last_time = events[0]['time']

        for event in events:
            time_delta_ms = event['time'] - last_time
            time_delta_days = time_delta_ms / (1000 * 86400)

            # 累积资金×时间
            if running_capital > 0 and time_delta_days > 0:
                capital_time_weighted += running_capital * time_delta_days

            # 更新资金和收益
            if event['type'] == 'cash_flow':
                running_capital += event['amount']
            elif event['type'] == 'trade':
                total_return += event['pnl']
                running_capital += event['pnl']

            last_time = event['time']

        # 计算到当前时间的资金×时间
        current_time_ms = int(time_module.time() * 1000)
        final_time_delta_days = (current_time_ms - last_time) / (1000 * 86400)

        if running_capital > 0 and final_time_delta_days > 0:
            capital_time_weighted += running_capital * final_time_delta_days

        # 3. 计算时间加权ROI
        if capital_time_weighted > 0:
            # 时间加权ROI = 总收益 / (资金×时间的平均/365) × 100
            # 即：总收益 / (年化资金平均值) × 100
            time_weighted_roi = (total_return / (capital_time_weighted / 365)) * 100
            quality = 'actual'
        else:
            time_weighted_roi = 0.0
            quality = 'insufficient_capital'

        # 4. 计算年化ROI
        total_days = (current_time_ms - events[0]['time']) / (1000 * 86400)
        years = max(total_days / 365, 1/365)  # 至少1天

        if running_capital > 0 and years > 0:
            # 年化ROI = ((最终价值 / 初始投入) ^ (1/年数) - 1) × 100
            initial_capital_total = sum(
                e['amount'] for e in events
                if e['type'] == 'cash_flow' and e['amount'] > 0
            )

            if initial_capital_total > 0:
                total_return_rate = account_value / initial_capital_total

                # 边界保护：防止极端收益率导致数学溢出
                if total_return_rate <= 0:
                    annualized_roi = -99.99  # 完全亏损
                    logger.warning(f"时间加权ROI: 收益率<=0 ({total_return_rate:.4f})")
                elif total_return_rate > 1000:
                    # 超过1000倍收益，限制为合理上限
                    logger.warning(
                        f"时间加权ROI: 极端收益率 {total_return_rate:.2f}倍 "
                        f"(账户=${account_value:,.2f}, 初始=${initial_capital_total:,.2f}), "
                        f"限制年化ROI为10,000%"
                    )
                    annualized_roi = 10000.0
                else:
                    # 使用对数检查是否会溢出
                    import math
                    try:
                        log_return = math.log(total_return_rate)
                        exponent = log_return / years

                        # 检查指数是否会导致溢出（e^700 约为 10^304）
                        if exponent > 700:
                            logger.warning(
                                f"时间加权ROI: 年化计算会溢出: ln({total_return_rate:.2f})/{years:.6f} = {exponent:.2f}, "
                                f"限制年化ROI为10,000%"
                            )
                            annualized_roi = 10000.0
                        elif exponent < -700:
                            logger.warning(
                                f"时间加权ROI: 年化计算接近0: ln({total_return_rate:.2f})/{years:.6f} = {exponent:.2f}, "
                                f"设置为-99.99%"
                            )
                            annualized_roi = -99.99
                        else:
                            # 安全计算
                            annualized_roi = (total_return_rate ** (1/years) - 1) * 100

                            # 二次边界检查
                            if annualized_roi > 10000:
                                logger.warning(f"时间加权ROI: 年化ROI过高 ({annualized_roi:.2f}%)，限制为10,000%")
                                annualized_roi = 10000.0
                            elif annualized_roi < -99.99:
                                logger.warning(f"时间加权ROI: 年化ROI过低 ({annualized_roi:.2f}%)，限制为-99.99%")
                                annualized_roi = -99.99
                    except (OverflowError, ValueError, ZeroDivisionError) as e:
                        logger.error(
                            f"时间加权ROI: 年化ROI计算错误: {e} "
                            f"(收益率={total_return_rate:.2f}, years={years:.6f}), "
                            f"设置为0"
                        )
                        annualized_roi = 0.0
            else:
                annualized_roi = 0.0
        else:
            annualized_roi = 0.0

        # 5. 计算总ROI（含未实现盈亏）
        if state:
            unrealized_pnl = sum(
                float(pos['position'].get('unrealizedPnl', 0))
                for pos in state.get('assetPositions', [])
            )
        else:
            unrealized_pnl = 0.0

        total_pnl_with_unrealized = total_return + unrealized_pnl

        if capital_time_weighted > 0:
            total_roi = (total_pnl_with_unrealized / (capital_time_weighted / 365)) * 100
        else:
            total_roi = 0.0

        # 边界保护
        time_weighted_roi = max(-999999.99, min(999999.99, time_weighted_roi))
        annualized_roi = max(-999999.99, min(999999.99, annualized_roi))
        total_roi = max(-999999.99, min(999999.99, total_roi))

        return time_weighted_roi, annualized_roi, total_roi, quality

    @staticmethod
    def _extract_ledger_amount(record: Dict, target_address: str) -> float:
        """
        从ledger记录中提取金额（带方向）

        Args:
            record: ledger记录
            target_address: 目标地址

        Returns:
            金额（正数=流入，负数=流出）
        """
        delta = record.get('delta', {})
        record_type = delta.get('type', '')
        target = target_address.lower()

        if record_type == 'deposit':
            # 充值：流入
            return float(delta.get('usdc', 0))

        elif record_type == 'withdraw':
            # 提现：流出
            return -float(delta.get('usdc', 0))

        elif record_type == 'send':
            # 转账
            user = delta.get('user', '').lower()
            destination = delta.get('destination', '').lower()
            amount = float(delta.get('amount', 0))

            if destination == target and user != target:
                # 收到转账：流入
                return amount
            elif user == target and destination != target:
                # 发出转账：流出
                return -amount

        elif record_type == 'subAccountTransfer':
            # 子账户转账
            user = delta.get('user', '').lower()
            destination = delta.get('destination', '').lower()
            amount = float(delta.get('usdc', 0))

            if destination == target:
                # 转入子账户：流入
                return amount
            elif user == target:
                # 转出子账户：流出
                return -amount

        return 0.0

    @classmethod
    def detect_bankruptcy(
        cls,
        fills: List[Dict],
        account_value: float,
        actual_initial_capital: Optional[float] = None,
        # P1性能优化参数
        precalculated_realized_pnl: Optional[float] = None,
        precalculated_sorted_fills: Optional[List[Dict]] = None
    ) -> int:
        """
        检测爆仓次数（资金降至 0 或负值）

        Args:
            fills: 交易记录列表（按时间排序）
            account_value: 当前账户价值
            actual_initial_capital: 实际初始资金（可选）
            precalculated_realized_pnl: 预计算的已实现PNL（性能优化）
            precalculated_sorted_fills: 预排序的fills列表（性能优化）

        Returns:
            爆仓次数
        """
        if not fills:
            return 0

        # 确定初始资金
        if actual_initial_capital is not None and actual_initial_capital > 0:
            initial_capital = actual_initial_capital
        else:
            # P1优化：使用预计算的realized_pnl
            if precalculated_realized_pnl is not None:
                realized_pnl = precalculated_realized_pnl
            else:
                realized_pnl = sum(MetricsEngine._get_pnl(f) for f in fills)
            initial_capital = account_value - realized_pnl

        if initial_capital <= 0:
            initial_capital = max(account_value, 1000)

        # P1优化：使用预排序的fills
        if precalculated_sorted_fills is not None:
            sorted_fills = precalculated_sorted_fills
        else:
            sorted_fills = cls._ensure_sorted_fills(fills)

        # 检测爆仓
        bankruptcy_count = 0
        running_capital = initial_capital

        for fill in sorted_fills:
            pnl = MetricsEngine._get_pnl(fill)
            running_capital += pnl

            if running_capital <= 0:
                bankruptcy_count += 1
                logger.info(f"检测到爆仓事件 #{bankruptcy_count}")
                # 爆仓后不再继续
                break

        return bankruptcy_count

    @classmethod
    def calculate_initial_capital_corrected(
        cls,
        address: str,
        ledger_data: List[Dict],
        total_deposits: float,
        total_withdrawals: float
    ) -> tuple[float, float, float]:
        """
        计算校正后的账户初始值（包含外部转入到 Spot）

        Args:
            address: 用户地址
            ledger_data: 账本数据
            total_deposits: 总充值
            total_withdrawals: 总提现

        Returns:
            (校正后的初始值, 外部转入Spot, 外部转出)
        """
        if not ledger_data:
            return total_deposits - total_withdrawals, 0.0, 0.0

        addr_lower = address.lower()
        external_to_spot = 0.0
        external_out = 0.0

        for record in ledger_data:
            delta = record.get('delta', {})
            if delta.get('type') != 'send':
                continue

            amount = float(delta.get('amount', 0))
            user = delta.get('user', '').lower()
            dest = delta.get('destination', '').lower()
            dest_dex = delta.get('destinationDex', '')
            source_dex = delta.get('sourceDex', '')

            # 外部转入到 Spot
            if user != addr_lower and dest == addr_lower and dest_dex == 'spot':
                external_to_spot += amount
                logger.debug(f"外部转入 Spot: ${amount:,.2f}")

            # 外部转出
            elif user == addr_lower and dest != addr_lower:
                external_out += amount
                logger.debug(f"外部转出: ${amount:,.2f}")

        # 校正后的初始值 = 充值 - 提现 + 外部转入Spot - 外部转出
        initial_capital_corrected = (
            total_deposits - total_withdrawals +
            external_to_spot - external_out
        )

        logger.info(
            f"账户初始值校正: 充值${total_deposits:,.2f} - 提现${total_withdrawals:,.2f} + "
            f"外部转入Spot${external_to_spot:,.2f} - 外部转出${external_out:,.2f} = "
            f"${initial_capital_corrected:,.2f}"
        )

        return initial_capital_corrected, external_to_spot, external_out

    @classmethod
    def calculate_metrics(
        cls,
        address: str,
        fills: List[Dict],
        state: Optional[Dict] = None,
        transfer_data: Optional[Dict] = None,
        spot_state: Optional[Dict] = None
    ) -> AddressMetrics:
        """
        计算地址的完整指标

        Args:
            address: 地址
            fills: 交易记录列表
            state: 账户状态（Perp 账户）
            transfer_data: 出入金统计数据 (可选)
            spot_state: Spot 账户状态 (可选)

        Returns:
            AddressMetrics 对象
        """
        if not fills:
            logger.warning(f"地址无交易记录: {address}")
            return AddressMetrics(
                address=address,
                total_trades=0,
                win_rate=0.0,
                total_pnl=0.0,
                avg_trade_size=0.0,
                total_volume=0.0,
                first_trade_time=0,
                last_trade_time=0,
                active_days=0,
            )

        # 直接计算总账户价值
        perp_value_temp = float(
            (state or {}).get('marginSummary', {}).get('accountValue', 0)
        )

        spot_value_temp = 0.0
        if spot_state and 'balances' in spot_state:
            for balance in spot_state['balances']:
                coin = balance.get('coin', '')
                total = float(balance.get('total', 0))

                if total > 0:
                    if coin == 'USDC':
                        # USDC 按 1:1 计价
                        spot_value_temp += total
                    else:
                        # 其他代币使用 entryNtl（入账价值）
                        entry_ntl = float(balance.get('entryNtl', 0))
                        spot_value_temp += entry_ntl

        # 计算总账户价值
        account_value = perp_value_temp + spot_value_temp

        logger.debug(f"内部计算用账户价值: ${account_value:,.2f}")

        # 提取出入金数据
        has_transfer_data = transfer_data is not None
        total_deposits = transfer_data.get('total_deposits', 0.0) if transfer_data else 0.0
        total_withdrawals = transfer_data.get('total_withdrawals', 0.0) if transfer_data else 0.0

        # 提取转账数据（新增）
        total_transfers_in = transfer_data.get('total_transfers_in', 0.0) if transfer_data else 0.0
        total_transfers_out = transfer_data.get('total_transfers_out', 0.0) if transfer_data else 0.0
        net_transfers = transfer_data.get('net_transfers', 0.0) if transfer_data else 0.0

        # 计算真实本金（仅充值/提现，不含转账）
        true_capital = (total_deposits - total_withdrawals) if has_transfer_data else 0.0

        # ========== P1性能优化：单次遍历收集所有数据 ==========
        ledger_data = transfer_data.get('ledger', None) if transfer_data else None
        collected = cls._collect_metrics_data(fills)

        # 从预收集数据中提取指标
        realized_pnl = collected['realized_pnl']
        winning_trades = collected['winning_trades']
        losing_trades = collected['losing_trades']
        total_volume = collected['total_volume']
        avg_trade_size = collected['avg_trade_size']
        active_days = collected['active_days']
        sorted_fills = collected['sorted_fills']
        first_trade_time = collected['first_trade_time']
        last_trade_time = collected['last_trade_time']

        # 使用预收集数据计算胜率（避免重复遍历）
        total_pnl_trades = winning_trades + losing_trades
        win_rate = (winning_trades / total_pnl_trades * 100) if total_pnl_trades > 0 else 0.0
        win_rate = max(0.0, min(100.0, win_rate))

        # 使用预收集的 realized_pnl 计算 PNL 和 ROI
        total_pnl = realized_pnl

        # 计算推算的初始资金
        estimated_initial = account_value - realized_pnl

        # 如果有出入金数据，计算真实初始资金
        if has_transfer_data:
            actual_initial = cls.calculate_actual_initial_capital(
                account_value, realized_pnl, 0.0  # net_deposits=0 因为我们用 true_capital
            )
            # 基于真实本金计算 ROI
            if true_capital > 0:
                true_capital_roi = (realized_pnl / true_capital) * 100
                true_capital_roi = max(-999999.99, min(999999.99, true_capital_roi))
            elif actual_initial > 0:
                true_capital_roi = (realized_pnl / actual_initial) * 100
                true_capital_roi = max(-999999.99, min(999999.99, true_capital_roi))
            else:
                true_capital_roi = 0.0
        else:
            actual_initial = estimated_initial if estimated_initial > 0 else max(account_value, 100)
            if estimated_initial > 0:
                true_capital_roi = (realized_pnl / estimated_initial) * 100
                true_capital_roi = max(-999999.99, min(999999.99, true_capital_roi))
            else:
                true_capital_roi = 0.0

        # 计算时间加权ROI（如果有ledger数据）
        # P1优化：ledger_data 已在前面提取
        if ledger_data and address:
            time_weighted_roi, annualized_roi, total_roi, roi_quality = cls.calculate_time_weighted_roi(
                fills, ledger_data, account_value, address, state
            )
        else:
            # 降级：无ledger数据时使用简单年化
            time_weighted_roi = true_capital_roi

            # P1优化：使用预排序的fills（避免重复排序）
            # 计算总天数（兼容 datetime 和毫秒时间戳）
            if len(sorted_fills) > 0:
                time_diff = last_trade_time - first_trade_time
                # 如果是 timedelta 对象，转换为天数
                from datetime import timedelta
                if isinstance(time_diff, timedelta):
                    total_days = time_diff.total_seconds() / 86400
                elif isinstance(first_trade_time, datetime):
                    # datetime 对象相减得到 timedelta
                    total_days = (last_trade_time - first_trade_time).total_seconds() / 86400
                else:
                    # 假设是毫秒时间戳
                    total_days = time_diff / (1000 * 86400)
            else:
                total_days = 1

            years = max(total_days / 365, 1/365)
            if years > 0 and actual_initial > 0:
                total_return_rate = account_value / actual_initial

                # 边界保护：防止极端收益率导致数学溢出
                if total_return_rate <= 0:
                    # 负收益率或0，使用简单ROI
                    annualized_roi = true_capital_roi
                    logger.warning(f"收益率<=0 ({total_return_rate:.4f})，使用校准ROI")
                elif total_return_rate > 1000:
                    # 超过1000倍收益（100,000%），限制为合理上限
                    logger.warning(
                        f"极端收益率检测: {total_return_rate:.2f}倍 "
                        f"(账户价值=${account_value:,.2f}, 初始资金=${actual_initial:,.2f}), "
                        f"限制年化ROI为10,000%"
                    )
                    annualized_roi = 10000.0  # 设置合理上限
                else:
                    # 使用对数检查是否会溢出：ln(total_return_rate) / years
                    # 如果这个值太大（>700），exp会溢出
                    import math
                    try:
                        log_return = math.log(total_return_rate)
                        exponent = log_return / years

                        # 检查指数是否会导致溢出（e^700 约为 10^304）
                        if exponent > 700:
                            logger.warning(
                                f"年化计算会溢出: ln({total_return_rate:.2f})/{years:.6f} = {exponent:.2f}, "
                                f"限制年化ROI为10,000%"
                            )
                            annualized_roi = 10000.0
                        elif exponent < -700:
                            logger.warning(
                                f"年化计算接近0: ln({total_return_rate:.2f})/{years:.6f} = {exponent:.2f}, "
                                f"设置为-99.99%"
                            )
                            annualized_roi = -99.99
                        else:
                            # 安全计算
                            annualized_roi = (total_return_rate ** (1/years) - 1) * 100

                            # 二次边界检查：年化ROI不应超过10,000%
                            if annualized_roi > 10000:
                                logger.warning(f"年化ROI过高 ({annualized_roi:.2f}%)，限制为10,000%")
                                annualized_roi = 10000.0
                            elif annualized_roi < -99.99:
                                logger.warning(f"年化ROI过低 ({annualized_roi:.2f}%)，限制为-99.99%")
                                annualized_roi = -99.99
                    except (OverflowError, ValueError, ZeroDivisionError) as e:
                        logger.error(
                            f"年化ROI计算错误: {e} "
                            f"(收益率={total_return_rate:.2f}, years={years:.6f}), "
                            f"降级使用校准ROI"
                        )
                        annualized_roi = true_capital_roi
            else:
                annualized_roi = true_capital_roi

            # 总ROI（含未实现）
            unrealized_pnl = sum(
                float(pos['position'].get('unrealizedPnl', 0))
                for pos in (state or {}).get('assetPositions', [])
            ) if state else 0.0
            total_pnl_with_unrealized = total_pnl + unrealized_pnl
            total_roi = (total_pnl_with_unrealized / actual_initial * 100) if actual_initial > 0 else 0.0

            roi_quality = 'estimated'

        # 计算校正后的账户初始值（包含外部转入到 Spot）
        # P1优化：ledger_data 已在前面提取
        if ledger_data and has_transfer_data:
            initial_capital_corrected, _, _ = cls.calculate_initial_capital_corrected(
                address, ledger_data, total_deposits, total_withdrawals
            )
        else:
            initial_capital_corrected = true_capital


        # ========== P1性能优化：传递预计算数据给各指标计算方法 ==========

        # 检测爆仓次数
        # P1优化：传递预计算的 realized_pnl, sorted_fills
        bankruptcy_count = cls.detect_bankruptcy(
            fills, account_value, actual_initial,
            precalculated_realized_pnl=realized_pnl,
            precalculated_sorted_fills=sorted_fills
        )

        # P1优化：使用预收集的 avg_trade_size, total_volume, active_days
        # 不再调用 calculate_trade_statistics 和 calculate_active_days

        # P1优化：使用预收集的 first_trade_time, last_trade_time
        # 不再调用 _ensure_sorted_fills

        logger.info(
            f"指标计算完成: {address} - 胜率:{win_rate:.1f}% "
            f"ROI(真实本金):{true_capital_roi:.1f}%"
        )

        return AddressMetrics(
            address=address,
            total_trades=len(fills),
            win_rate=win_rate,
            total_pnl=total_pnl,
            avg_trade_size=avg_trade_size,
            total_volume=total_volume,
            first_trade_time=first_trade_time,
            last_trade_time=last_trade_time,
            active_days=active_days,
            # 出入金字段（传统方法，包含转账）
            total_deposits=total_deposits,
            total_withdrawals=total_withdrawals,
            actual_initial_capital=actual_initial,
            # 转账字段（新增，区分盈亏转移）
            total_transfers_in=total_transfers_in,
            total_transfers_out=total_transfers_out,
            net_transfers=net_transfers,
            true_capital=true_capital,
            true_capital_roi=true_capital_roi,
            # P0 修复字段
            bankruptcy_count=bankruptcy_count,
            # ROI扩展指标（P1优化）
            time_weighted_roi=time_weighted_roi,
            annualized_roi=annualized_roi,
            total_roi=total_roi,
            roi_quality=roi_quality,
            # 累计收益率指标（新增）
            initial_capital_corrected=initial_capital_corrected,
        )
