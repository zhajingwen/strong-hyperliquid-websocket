"""
指标计算引擎 - 基于交易数据计算各类指标
"""

import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class AddressMetrics:
    """地址交易指标"""
    address: str
    total_trades: int
    win_rate: float          # 胜率 (%)
    roi: float               # 收益率 (%) - 旧版推算初始资金
    sharpe_ratio: float      # 夏普比率
    total_pnl: float         # 总PNL = 已实现PNL (USD)
    account_value: float     # 账户价值 (USD)
    max_drawdown: float      # 最大回撤 (%)
    avg_trade_size: float    # 平均交易规模
    total_volume: float      # 总交易量
    first_trade_time: int    # 首次交易时间
    last_trade_time: int     # 最后交易时间
    active_days: int         # 活跃天数

    # 新增：出入金相关字段
    net_deposits: float = 0.0           # 净充值 (USD)
    total_deposits: float = 0.0         # 总充值 (USD)
    total_withdrawals: float = 0.0      # 总提现 (USD)
    actual_initial_capital: float = 0.0 # 实际初始资金 (USD)
    corrected_roi: float = 0.0          # 校准后的ROI (%)


class MetricsEngine:
    """交易指标计算引擎"""

    ANNUAL_DAYS = 365  # 加密货币全年交易，不使用252交易日
    RISK_FREE_RATE = 0.02  # 无风险利率 2%

    @staticmethod
    def _get_pnl(fill: Dict) -> float:
        """
        获取交易PNL，支持两种命名格式
        - API格式: closedPnl
        - 数据库格式: closed_pnl
        """
        return float(fill.get('closedPnl') or fill.get('closed_pnl', 0))

    @staticmethod
    def calculate_win_rate(fills: List[Dict]) -> float:
        """
        计算胜率（改进版：排除零PNL交易）

        算法改进：
        - 只统计有盈亏的交易（排除零PNL交易）
        - 零PNL通常是：开仓、部分平仓、手续费抵消等
        - 将零PNL算作失败交易不合理
        - 符合交易分析行业标准（参考Apex Liquid Bot算法）

        Args:
            fills: 交易记录列表

        Returns:
            胜率百分比 (0-100)

        Examples:
            >>> # 假设有5笔交易：2盈利、1亏损、2零PNL（开仓）
            >>> fills = [
            ...     {'closedPnl': 100},   # 盈利
            ...     {'closedPnl': -50},   # 亏损
            ...     {'closedPnl': 0},     # 开仓（零PNL）
            ...     {'closedPnl': 0},     # 开仓（零PNL）
            ...     {'closedPnl': 200},   # 盈利
            ... ]
            >>> # 旧算法：2/5 = 40%（不合理）
            >>> # 新算法：2/3 = 66.67%（排除零PNL，更准确）
        """
        if not fills:
            return 0.0

        # 统计有盈亏的交易
        winning_trades = 0
        total_pnl_trades = 0

        for fill in fills:
            pnl = MetricsEngine._get_pnl(fill)
            # 排除零PNL交易（开仓、部分平仓等）
            if pnl != 0:
                total_pnl_trades += 1
                if pnl > 0:
                    winning_trades += 1

        # 没有有效交易时返回0
        if total_pnl_trades == 0:
            return 0.0

        win_rate = (winning_trades / total_pnl_trades) * 100

        # 边界保护：胜率应该在 0-100 之间
        return max(0.0, min(100.0, win_rate))

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

        # 边界保护：如果结果为负或极小值，降级到推算初始资金
        if actual_initial <= 0:
            fallback = account_value - realized_pnl
            logger.warning(
                f"实际初始资金计算为负 ({actual_initial:.2f})，"
                f"降级到推算初始资金 ({fallback:.2f})"
            )
            return max(fallback, 100.0)  # 最低保证 $100

        return actual_initial

    @staticmethod
    def calculate_corrected_roi(realized_pnl: float, actual_initial_capital: float) -> float:
        """
        计算校准后的ROI

        公式：校准ROI = (已实现PNL / 实际初始资金) × 100

        Args:
            realized_pnl: 已实现PNL
            actual_initial_capital: 实际初始资金

        Returns:
            校准后的ROI (%)
        """
        if actual_initial_capital <= 0:
            return 0.0

        corrected_roi = (realized_pnl / actual_initial_capital) * 100

        # 边界保护
        return max(-999999.99, min(999999.99, corrected_roi))

    @staticmethod
    def calculate_pnl_and_roi(
        fills: List[Dict],
        account_value: float,
        net_deposits: float = 0.0,
        has_transfer_data: bool = False
    ) -> tuple[float, float, float, float]:
        """
        计算总PNL和ROI（新版返回4个值）

        总PNL = 所有交易的已实现PNL之和 (sum of closedPnl)
        Legacy ROI = (已实现PNL / 推算初始资金) * 100
        Corrected ROI = (已实现PNL / 实际初始资金) * 100

        Args:
            fills: 交易记录列表
            account_value: 当前账户价值
            net_deposits: 净充值（默认0）
            has_transfer_data: 是否有出入金数据

        Returns:
            (total_pnl, legacy_roi, actual_initial_capital, corrected_roi)
        """
        if not fills:
            return 0.0, 0.0, 0.0, 0.0

        # 计算已实现PNL（所有交易的closedPnl总和）
        realized_pnl = sum(MetricsEngine._get_pnl(fill) for fill in fills)
        total_pnl = realized_pnl

        # 计算旧版ROI：基于推算的初始资金
        estimated_initial = account_value - realized_pnl
        if estimated_initial > 0:
            legacy_roi = (realized_pnl / estimated_initial) * 100
        else:
            legacy_roi = 0.0

        # 边界保护
        legacy_roi = max(-999999.99, min(999999.99, legacy_roi))

        # 如果有出入金数据，计算真实初始资金和校准ROI
        if has_transfer_data:
            actual_initial = MetricsEngine.calculate_actual_initial_capital(
                account_value, realized_pnl, net_deposits
            )
            corrected_roi = MetricsEngine.calculate_corrected_roi(realized_pnl, actual_initial)
        else:
            # 降级策略
            actual_initial = estimated_initial
            corrected_roi = legacy_roi

        return total_pnl, legacy_roi, actual_initial, corrected_roi

    @staticmethod
    def calculate_sharpe_ratio(
        fills: List[Dict],
        account_value: float,
        actual_initial_capital: Optional[float] = None
    ) -> float:
        """
        计算夏普比率（改进版：动态资金基准，考虑复利效应）

        算法改进：
        1. 使用动态资金基准（每笔交易后更新资金）
        2. 考虑复利效应（盈利后资金增长，亏损后资金减少）
        3. 更准确反映策略的真实风险收益特征
        4. 支持真实初始资金（如果提供出入金数据）

        Args:
            fills: 交易记录列表（按时间排序）
            account_value: 当前账户价值
            actual_initial_capital: 实际初始资金（可选，有出入金数据时提供）

        Returns:
            夏普比率

        算法说明：
            旧算法问题：
            - 使用固定资金基准，忽略资金变化
            - 示例：初始1000美元，第1笔赚200，第2笔赚300
              旧算法：ret1=200/1000=20%, ret2=300/1000=30%（错误）
              新算法：ret1=200/1000=20%, ret2=300/1200=25%（正确）

            新算法优势：
            - 每笔交易基于当前实际资金计算收益率
            - 符合复利交易的实际情况
            - 更准确反映风险调整后的收益
        """
        if not fills or len(fills) < 2:
            return 0.0

        # 确定初始资金：优先使用真实初始资金，否则推算
        if actual_initial_capital is not None and actual_initial_capital > 0:
            initial_capital = actual_initial_capital
        else:
            realized_pnl = sum(MetricsEngine._get_pnl(f) for f in fills)
            initial_capital = account_value - realized_pnl

        # 边界保护：初始资金不应为负或过小
        if initial_capital <= 0:
            initial_capital = max(account_value, 1000)  # 最低1K
        else:
            initial_capital = max(initial_capital, 100)  # 最低100美元

        # 按时间排序
        sorted_fills = sorted(fills, key=lambda x: x.get('time', 0))

        # 计算每笔交易的收益率（动态资金基准）
        returns = []
        running_capital = initial_capital

        for fill in sorted_fills:
            pnl = MetricsEngine._get_pnl(fill)

            # 基于当前资金计算收益率
            if running_capital > 0:
                ret = pnl / running_capital
                returns.append(ret)

                # 更新资金基准（复利效应）
                running_capital += pnl

                # 保护：资金不应为负（使用杠杆可能爆仓）
                if running_capital < 0:
                    running_capital = max(account_value * 0.01, 10)  # 重置为1%或10美元
            else:
                # 资金已经为0或负，跳过此交易
                continue

        if not returns or len(returns) < 2:
            return 0.0

        # 转换为 numpy 数组
        returns_array = np.array(returns)

        # 计算平均收益率和标准差（贝塞尔校正）
        mean_return = np.mean(returns_array)
        std_return = np.std(returns_array, ddof=1)

        if std_return == 0:
            return 0.0

        # 年化因子（基于实际交易频率）
        trading_days = len(returns)

        # 处理两种时间格式
        first_time = sorted_fills[0]['time']
        last_time = sorted_fills[-1]['time']

        if isinstance(first_time, datetime) and isinstance(last_time, datetime):
            # 数据库格式：datetime 对象
            time_span_days = (last_time - first_time).total_seconds() / 86400
        else:
            # API 格式：毫秒时间戳
            time_span_days = (last_time - first_time) / (1000 * 86400)

        # 避免除零
        if time_span_days <= 0:
            time_span_days = 1

        trades_per_day = trading_days / time_span_days

        # 年化收益率和标准差
        annual_return = mean_return * MetricsEngine.ANNUAL_DAYS * trades_per_day
        annual_std = std_return * np.sqrt(MetricsEngine.ANNUAL_DAYS * trades_per_day)

        # 夏普比率 = (年化收益率 - 无风险利率) / 年化标准差
        sharpe = (annual_return - MetricsEngine.RISK_FREE_RATE) / annual_std

        return float(sharpe)

    @staticmethod
    def calculate_max_drawdown(
        fills: List[Dict],
        account_value: float = 0.0,
        actual_initial_capital: Optional[float] = None
    ) -> float:
        """
        计算最大回撤（改进版：基于账户权益曲线）

        算法改进：
        1. 从初始资金开始计算（而非第一笔交易的PNL）
        2. 基于账户权益曲线（equity = 初始资金 + 累计PNL）
        3. 修复初始峰值可能为负的BUG
        4. 符合行业标准的权益回撤计算方式
        5. 支持真实初始资金（如果提供出入金数据）

        Args:
            fills: 交易记录列表（按时间排序）
            account_value: 当前账户价值
            actual_initial_capital: 实际初始资金（可选，有出入金数据时提供）

        Returns:
            最大回撤百分比

        算法说明：
            旧算法问题：
            - 如果第一笔交易亏损，peak为负值，导致回撤计算错误
            - 只基于累计PNL，不符合权益曲线标准

            新算法：
            - 推算初始资金 = 当前账户价值 - 累计已实现PNL
            - 构建权益曲线 = [初始资金, 初始资金+PNL1, 初始资金+PNL1+PNL2, ...]
            - 从初始资金作为峰值开始计算回撤
        """
        if not fills:
            return 0.0

        # 按时间排序
        sorted_fills = sorted(fills, key=lambda x: x.get('time', 0))

        # 确定初始资金：优先使用真实初始资金，否则推算
        if actual_initial_capital is not None and actual_initial_capital > 0:
            initial_capital = actual_initial_capital
        else:
            realized_pnl = sum(MetricsEngine._get_pnl(f) for f in fills)
            initial_capital = account_value - realized_pnl

        # 边界保护：初始资金不应为负或过小
        if initial_capital <= 0:
            # 如果账户亏损严重导致初始资金为负，使用账户价值作为基准
            initial_capital = max(account_value, 100)  # 最低100美元

        # 构建权益曲线（从初始资金开始）
        equity_curve = [initial_capital]
        running_equity = initial_capital

        for fill in sorted_fills:
            running_equity += MetricsEngine._get_pnl(fill)
            equity_curve.append(running_equity)

        # 计算最大回撤（从初始资金作为第一个峰值）
        peak = initial_capital
        max_drawdown = 0.0

        for equity in equity_curve:
            # 更新峰值
            if equity > peak:
                peak = equity

            # 计算当前回撤
            if peak > 0:
                drawdown = (peak - equity) / peak
                max_drawdown = max(max_drawdown, drawdown)
            # 边界情况：峰值为0时，如果权益为负，回撤为100%
            elif equity < 0:
                max_drawdown = max(max_drawdown, 1.0)  # 100%回撤

        max_drawdown_pct = max_drawdown * 100

        # 日志记录异常大的回撤（>200%）
        if max_drawdown_pct > 200:
            logger.warning(
                f"检测到异常大的最大回撤: {max_drawdown_pct:.2f}% "
                f"(初始资金: ${initial_capital:.2f}, 当前权益: ${running_equity:.2f})"
            )

        # 边界保护：最大回撤理论上不应超过 100%（除非使用杠杆）
        # 加密货币可能有高杠杆，允许超过100%但限制在999.99%
        return min(max_drawdown_pct, 999.99)

    @staticmethod
    def calculate_trade_statistics(fills: List[Dict]) -> tuple[float, float]:
        """
        计算交易统计信息

        Args:
            fills: 交易记录列表

        Returns:
            (avg_trade_size, total_volume)
        """
        if not fills:
            return 0.0, 0.0

        # 平均交易规模（以USD计）
        trade_sizes = []
        total_volume = 0.0

        for fill in fills:
            price = float(fill.get('px', 0))
            size = float(fill.get('sz', 0))
            volume = price * size
            trade_sizes.append(volume)
            total_volume += volume

        avg_trade_size = sum(trade_sizes) / len(trade_sizes) if trade_sizes else 0.0

        return avg_trade_size, total_volume

    @staticmethod
    def calculate_win_rate_detailed(fills: List[Dict]) -> Dict[str, float]:
        """
        计算详细的胜率统计信息（增强版）

        提供更全面的交易分析数据，包括：
        - 胜率（排除零PNL）
        - 盈利/亏损交易数量
        - 平均盈利/亏损金额
        - 盈亏比（平均盈利/平均亏损）

        Args:
            fills: 交易记录列表

        Returns:
            详细统计字典：
            {
                'win_rate': 胜率百分比,
                'total_trades': 总交易数,
                'winning_trades': 盈利交易数,
                'losing_trades': 亏损交易数,
                'zero_pnl_trades': 零PNL交易数,
                'avg_win': 平均盈利金额,
                'avg_loss': 平均亏损金额,
                'profit_factor': 盈亏比（总盈利/总亏损）
            }
        """
        if not fills:
            return {
                'win_rate': 0.0,
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'zero_pnl_trades': 0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0
            }

        winning_trades = 0
        losing_trades = 0
        zero_pnl_trades = 0
        total_wins = 0.0
        total_losses = 0.0

        for fill in fills:
            pnl = MetricsEngine._get_pnl(fill)

            if pnl > 0:
                winning_trades += 1
                total_wins += pnl
            elif pnl < 0:
                losing_trades += 1
                total_losses += abs(pnl)
            else:
                zero_pnl_trades += 1

        # 计算胜率（排除零PNL）
        total_pnl_trades = winning_trades + losing_trades
        win_rate = (winning_trades / total_pnl_trades * 100) if total_pnl_trades > 0 else 0.0

        # 计算平均盈利/亏损
        avg_win = total_wins / winning_trades if winning_trades > 0 else 0.0
        avg_loss = total_losses / losing_trades if losing_trades > 0 else 0.0

        # 计算盈亏比（Profit Factor）
        profit_factor = total_wins / total_losses if total_losses > 0 else (float('inf') if total_wins > 0 else 0.0)

        return {
            'win_rate': max(0.0, min(100.0, win_rate)),
            'total_trades': len(fills),
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'zero_pnl_trades': zero_pnl_trades,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor if profit_factor != float('inf') else 1000.0
        }

    @staticmethod
    def calculate_active_days(fills: List[Dict]) -> int:
        """
        计算活跃天数

        Args:
            fills: 交易记录列表

        Returns:
            活跃天数
        """
        if not fills:
            return 0

        # 提取所有交易日期（去重）
        trading_dates = set()
        for fill in fills:
            time_value = fill.get('time', 0)

            # 处理两种情况：毫秒时间戳（API）或 datetime 对象（数据库）
            if isinstance(time_value, datetime):
                date = time_value.date()
            elif isinstance(time_value, int):
                date = datetime.fromtimestamp(time_value / 1000).date()
            else:
                continue

            trading_dates.add(date)

        return len(trading_dates)

    @classmethod
    def calculate_metrics(
        cls,
        address: str,
        fills: List[Dict],
        state: Optional[Dict] = None,
        transfer_data: Optional[Dict] = None
    ) -> AddressMetrics:
        """
        计算地址的完整指标

        Args:
            address: 地址
            fills: 交易记录列表
            state: 账户状态
            transfer_data: 出入金统计数据 (可选)

        Returns:
            AddressMetrics 对象
        """
        if not fills:
            logger.warning(f"地址无交易记录: {address}")
            return AddressMetrics(
                address=address,
                total_trades=0,
                win_rate=0.0,
                roi=0.0,
                sharpe_ratio=0.0,
                total_pnl=0.0,
                account_value=0.0,
                max_drawdown=0.0,
                avg_trade_size=0.0,
                total_volume=0.0,
                first_trade_time=0,
                last_trade_time=0,
                active_days=0
            )

        # 获取账户价值
        account_value = float(
            (state or {}).get('marginSummary', {}).get('accountValue', 0)
        )

        # 提取出入金数据
        has_transfer_data = transfer_data is not None
        net_deposits = transfer_data.get('net_deposits', 0.0) if transfer_data else 0.0
        total_deposits = transfer_data.get('total_deposits', 0.0) if transfer_data else 0.0
        total_withdrawals = transfer_data.get('total_withdrawals', 0.0) if transfer_data else 0.0

        # 计算各项指标
        win_rate = cls.calculate_win_rate(fills)

        # 计算PNL和ROI（新版返回4个值）
        total_pnl, legacy_roi, actual_initial, corrected_roi = cls.calculate_pnl_and_roi(
            fills, account_value, net_deposits, has_transfer_data
        )

        # 使用真实初始资金计算夏普比率和最大回撤
        sharpe_ratio = cls.calculate_sharpe_ratio(fills, account_value, actual_initial)
        max_drawdown = cls.calculate_max_drawdown(fills, account_value, actual_initial)

        avg_trade_size, total_volume = cls.calculate_trade_statistics(fills)
        active_days = cls.calculate_active_days(fills)

        # 时间范围
        sorted_fills = sorted(fills, key=lambda x: x.get('time', 0))
        first_trade_time = sorted_fills[0].get('time', 0)
        last_trade_time = sorted_fills[-1].get('time', 0)

        logger.info(
            f"指标计算完成: {address} - 胜率:{win_rate:.1f}% "
            f"ROI(旧):{legacy_roi:.1f}% ROI(校准):{corrected_roi:.1f}%"
        )

        return AddressMetrics(
            address=address,
            total_trades=len(fills),
            win_rate=win_rate,
            roi=legacy_roi,  # 保留旧版ROI
            sharpe_ratio=sharpe_ratio,
            total_pnl=total_pnl,
            account_value=account_value,
            max_drawdown=max_drawdown,
            avg_trade_size=avg_trade_size,
            total_volume=total_volume,
            first_trade_time=first_trade_time,
            last_trade_time=last_trade_time,
            active_days=active_days,
            # 新增字段
            net_deposits=net_deposits,
            total_deposits=total_deposits,
            total_withdrawals=total_withdrawals,
            actual_initial_capital=actual_initial,
            corrected_roi=corrected_roi
        )


def test_metrics():
    """测试指标计算"""
    print(f"\n{'='*70}")
    print(f"🧪 指标计算测试 - P0改进效果验证")
    print(f"{'='*70}\n")

    # 测试1：胜率算法改进
    print("📊 测试1：胜率算法改进对比")
    print("-" * 70)
    test_fills_with_zeros = [
        {'time': 1704067200000, 'closedPnl': '100', 'px': '50000', 'sz': '0.1'},   # 盈利
        {'time': 1704153600000, 'closedPnl': '-50', 'px': '50100', 'sz': '0.1'},   # 亏损
        {'time': 1704240000000, 'closedPnl': '0', 'px': '50200', 'sz': '0.2'},     # 零PNL（开仓）
        {'time': 1704326400000, 'closedPnl': '0', 'px': '50300', 'sz': '0.15'},    # 零PNL（开仓）
        {'time': 1704412800000, 'closedPnl': '200', 'px': '50400', 'sz': '0.1'},   # 盈利
    ]

    detailed_stats = MetricsEngine.calculate_win_rate_detailed(test_fills_with_zeros)

    print(f"总交易数: {detailed_stats['total_trades']} 笔")
    print(f"  - 盈利交易: {detailed_stats['winning_trades']} 笔")
    print(f"  - 亏损交易: {detailed_stats['losing_trades']} 笔")
    print(f"  - 零PNL交易: {detailed_stats['zero_pnl_trades']} 笔（开仓/部分平仓）")
    print(f"\n胜率计算:")
    print(f"  - 旧算法（错误）: {detailed_stats['winning_trades']}/{detailed_stats['total_trades']} = {detailed_stats['winning_trades']/detailed_stats['total_trades']*100:.1f}%")
    print(f"  - 新算法（正确）: {detailed_stats['winning_trades']}/{detailed_stats['winning_trades']+detailed_stats['losing_trades']} = {detailed_stats['win_rate']:.1f}%")
    print(f"  - 差异: {detailed_stats['win_rate'] - detailed_stats['winning_trades']/detailed_stats['total_trades']*100:.1f}%")

    # 测试2：Sharpe Ratio 改进（动态资金基准）
    print(f"\n{'='*70}")
    print(f"📊 测试2：Sharpe Ratio 改进对比（动态 vs 固定资金基准）")
    print("-" * 70)

    # 构造有明显复利效应的数据
    test_fills_compound = [
        {'time': 1704067200000, 'closedPnl': '200', 'px': '50000', 'sz': '0.2'},   # +200 (资金1000->1200)
        {'time': 1704153600000, 'closedPnl': '300', 'px': '50100', 'sz': '0.3'},   # +300 (资金1200->1500)
        {'time': 1704240000000, 'closedPnl': '-150', 'px': '50200', 'sz': '0.15'}, # -150 (资金1500->1350)
        {'time': 1704326400000, 'closedPnl': '400', 'px': '50300', 'sz': '0.4'},   # +400 (资金1350->1750)
        {'time': 1704412800000, 'closedPnl': '250', 'px': '50400', 'sz': '0.25'},  # +250 (资金1750->2000)
    ]

    account_val = 2000.0  # 最终账户价值

    # 计算新算法的夏普比率
    sharpe_new = MetricsEngine.calculate_sharpe_ratio(test_fills_compound, account_val)

    print(f"交易序列（展示复利效应）:")
    running = 1000
    for i, fill in enumerate(test_fills_compound, 1):
        pnl = float(fill['closedPnl'])
        ret_new = pnl / running
        running += pnl
        print(f"  第{i}笔: PNL=${pnl:+.0f}, 资金基准=${running-pnl:.0f}, 收益率={ret_new*100:.1f}%, 新资金=${running:.0f}")

    print(f"\n夏普比率:")
    print(f"  - 新算法（动态资金基准）: {sharpe_new:.4f}")
    print(f"  - 优势: 考虑复利效应，更准确反映风险收益")

    # 测试3：Max Drawdown 改进（基于权益曲线）
    print(f"\n{'='*70}")
    print(f"📊 测试3：Max Drawdown 改进对比（权益曲线 vs 累计PNL）")
    print("-" * 70)

    test_fills_dd = [
        {'time': 1704067200000, 'closedPnl': '500', 'px': '50000', 'sz': '0.5'},   # 峰值
        {'time': 1704153600000, 'closedPnl': '-300', 'px': '50100', 'sz': '0.3'},  # 回撤
        {'time': 1704240000000, 'closedPnl': '-200', 'px': '50200', 'sz': '0.2'},  # 继续回撤
        {'time': 1704326400000, 'closedPnl': '400', 'px': '50300', 'sz': '0.4'},   # 恢复
    ]

    account_val_dd = 1400.0
    max_dd = MetricsEngine.calculate_max_drawdown(test_fills_dd, account_val_dd)

    # 构建权益曲线展示
    realized_pnl = sum(float(f['closedPnl']) for f in test_fills_dd)
    initial = account_val_dd - realized_pnl
    print(f"初始资金: ${initial:.0f}")
    print(f"权益曲线:")
    equity = initial
    peak = initial
    for i, fill in enumerate(test_fills_dd, 1):
        pnl = float(fill['closedPnl'])
        equity += pnl
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        print(f"  第{i}笔后: 权益=${equity:.0f}, 峰值=${peak:.0f}, 回撤={dd:.1f}%")

    print(f"\n最大回撤:")
    print(f"  - 新算法（基于权益曲线）: {max_dd:.1f}%")
    print(f"  - 优势: 从初始资金开始，避免负峰值BUG")

    # 测试4：完整指标计算
    print(f"\n{'='*70}")
    print(f"📊 测试4：完整指标计算")
    print("-" * 70)
    test_fills = [
        {'time': 1704067200000, 'closedPnl': '100', 'px': '50000', 'sz': '0.1'},
        {'time': 1704153600000, 'closedPnl': '-50', 'px': '50100', 'sz': '0.1'},
        {'time': 1704240000000, 'closedPnl': '200', 'px': '50200', 'sz': '0.2'},
        {'time': 1704326400000, 'closedPnl': '150', 'px': '50300', 'sz': '0.15'},
        {'time': 1704412800000, 'closedPnl': '-30', 'px': '50400', 'sz': '0.1'},
    ]

    test_state = {
        'marginSummary': {
            'accountValue': '10500'
        }
    }

    metrics = MetricsEngine.calculate_metrics(
        address='0xtest123',
        fills=test_fills,
        state=test_state
    )

    print(f"地址: {metrics.address}")
    print(f"总交易数: {metrics.total_trades}")
    print(f"胜率: {metrics.win_rate:.1f}% (✅ 排除零PNL)")
    print(f"ROI: {metrics.roi:.1f}%")
    print(f"夏普比率: {metrics.sharpe_ratio:.2f} (✅ 动态资金基准)")
    print(f"总PNL: ${metrics.total_pnl:,.2f}")
    print(f"账户价值: ${metrics.account_value:,.2f}")
    print(f"最大回撤: {metrics.max_drawdown:.1f}% (✅ 权益曲线)")
    print(f"平均交易规模: ${metrics.avg_trade_size:,.2f}")
    print(f"总交易量: ${metrics.total_volume:,.2f}")
    print(f"活跃天数: {metrics.active_days}")

    print(f"\n{'='*70}")
    print(f"✅ P0改进验证完成！")
    print(f"{'='*70}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    test_metrics()
