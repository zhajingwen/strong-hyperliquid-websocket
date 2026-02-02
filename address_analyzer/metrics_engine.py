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
    roi: float               # 收益率 (%)
    sharpe_ratio: float      # 夏普比率
    total_pnl: float         # 总PNL (USD)
    account_value: float     # 账户价值 (USD)
    max_drawdown: float      # 最大回撤 (%)
    avg_trade_size: float    # 平均交易规模
    total_volume: float      # 总交易量
    net_deposit: float       # 净投入
    first_trade_time: int    # 首次交易时间
    last_trade_time: int     # 最后交易时间
    active_days: int         # 活跃天数


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
        计算胜率

        Args:
            fills: 交易记录列表

        Returns:
            胜率百分比 (0-100)
        """
        if not fills:
            return 0.0

        winning_trades = sum(
            1 for fill in fills
            if MetricsEngine._get_pnl(fill) > 0
        )

        win_rate = (winning_trades / len(fills)) * 100

        # 边界保护：胜率应该在 0-100 之间
        return max(0.0, min(100.0, win_rate))

    @staticmethod
    def calculate_pnl_and_roi(
        fills: List[Dict],
        account_value: float,
        net_deposit: Optional[float] = None
    ) -> tuple[float, float]:
        """
        计算总PNL和ROI

        Args:
            fills: 交易记录列表
            account_value: 当前账户价值
            net_deposit: 净投入（总入金-总出金），如果为None则使用已实现PNL计算

        Returns:
            (total_pnl, roi)
        """
        if not fills:
            return 0.0, 0.0

        # 计算已实现PNL（所有交易的closedPnl总和）
        realized_pnl = sum(MetricsEngine._get_pnl(fill) for fill in fills)

        # 如果有净投入数据，使用会计恒等式
        if net_deposit is not None and net_deposit > 0:
            # 总PNL = 账户价值 - 净投入
            total_pnl = account_value - net_deposit
            # ROI = (总PNL / 净投入) * 100
            roi = (total_pnl / net_deposit) * 100
        else:
            # 没有入金数据，使用已实现PNL作为近似值
            total_pnl = realized_pnl
            # 假设初始资金为账户价值减去已实现PNL
            initial_capital = account_value - realized_pnl
            if initial_capital > 0:
                roi = (realized_pnl / initial_capital) * 100
            else:
                roi = 0.0

        # 日志记录异常大的ROI（>10000%）
        if abs(roi) > 10000:
            logger.warning(f"检测到异常大的ROI: {roi:.2f}% (PNL:{total_pnl:.2f}, Deposit:{net_deposit})")

        # 边界保护：ROI 不应超过 DECIMAL(12,2) 的限制
        roi = max(-9999999999.99, min(9999999999.99, roi))

        return total_pnl, roi

    @staticmethod
    def calculate_sharpe_ratio(fills: List[Dict], net_deposit: float = 10000) -> float:
        """
        计算夏普比率

        Args:
            fills: 交易记录列表（按时间排序）
            net_deposit: 净投入资金（用于计算收益率）

        Returns:
            夏普比率
        """
        if not fills or len(fills) < 2:
            return 0.0

        # 按时间排序
        sorted_fills = sorted(fills, key=lambda x: x.get('time', 0))

        # 计算每笔交易的收益率
        returns = []
        for fill in sorted_fills:
            pnl = MetricsEngine._get_pnl(fill)
            # 收益率 = PNL / 资金
            ret = pnl / net_deposit if net_deposit > 0 else 0
            returns.append(ret)

        if not returns or len(returns) < 2:
            return 0.0

        # 转换为 numpy 数组
        returns_array = np.array(returns)

        # 计算平均收益率和标准差
        mean_return = np.mean(returns_array)
        std_return = np.std(returns_array, ddof=1)

        if std_return == 0:
            return 0.0

        # 年化因子（假设平均每天交易一次）
        # 实际应该根据交易频率调整
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

        trades_per_day = trading_days / time_span_days if time_span_days > 0 else 1

        # 年化收益率和标准差
        annual_return = mean_return * MetricsEngine.ANNUAL_DAYS * trades_per_day
        annual_std = std_return * np.sqrt(MetricsEngine.ANNUAL_DAYS * trades_per_day)

        # 夏普比率 = (年化收益率 - 无风险利率) / 年化标准差
        sharpe = (annual_return - MetricsEngine.RISK_FREE_RATE) / annual_std

        return float(sharpe)

    @staticmethod
    def calculate_max_drawdown(fills: List[Dict]) -> float:
        """
        计算最大回撤

        Args:
            fills: 交易记录列表（按时间排序）

        Returns:
            最大回撤百分比
        """
        if not fills:
            return 0.0

        # 按时间排序
        sorted_fills = sorted(fills, key=lambda x: x.get('time', 0))

        # 构建累计PNL时间序列
        cumulative_pnl = []
        running_total = 0.0

        for fill in sorted_fills:
            running_total += MetricsEngine._get_pnl(fill)
            cumulative_pnl.append(running_total)

        if not cumulative_pnl:
            return 0.0

        # 计算最大回撤
        peak = cumulative_pnl[0]
        max_drawdown = 0.0

        for current_value in cumulative_pnl:
            # 更新峰值
            if current_value > peak:
                peak = current_value

            # 计算当前回撤
            if peak > 0:
                drawdown = (peak - current_value) / peak
                max_drawdown = max(max_drawdown, drawdown)

        max_drawdown_pct = max_drawdown * 100

        # 日志记录异常大的回撤（>500%）
        if max_drawdown_pct > 500:
            logger.warning(f"检测到异常大的最大回撤: {max_drawdown_pct:.2f}%")

        # 边界保护：最大回撤理论上不应超过 999,999%
        return min(max_drawdown_pct, 999999.99)

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
        net_deposit: Optional[float] = None
    ) -> AddressMetrics:
        """
        计算地址的完整指标

        Args:
            address: 地址
            fills: 交易记录列表
            state: 账户状态
            net_deposit: 净投入资金

        Returns:
            AddressMetrics 对象
        """
        if not fills:
            logger.warning(f"地址无交易记录: {address[:10]}...")
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
                net_deposit=0.0,
                first_trade_time=0,
                last_trade_time=0,
                active_days=0
            )

        # 获取账户价值
        account_value = 0.0
        if state and 'marginSummary' in state:
            account_value = float(state['marginSummary'].get('accountValue', 0))

        # 如果没有净投入数据，使用账户价值作为估计
        if net_deposit is None:
            realized_pnl = sum(MetricsEngine._get_pnl(f) for f in fills)
            net_deposit = account_value - realized_pnl
            if net_deposit <= 0:
                net_deposit = 10000  # 默认假设10k初始资金

        # 计算各项指标
        win_rate = cls.calculate_win_rate(fills)
        total_pnl, roi = cls.calculate_pnl_and_roi(fills, account_value, net_deposit)
        sharpe_ratio = cls.calculate_sharpe_ratio(fills, net_deposit)
        max_drawdown = cls.calculate_max_drawdown(fills)
        avg_trade_size, total_volume = cls.calculate_trade_statistics(fills)
        active_days = cls.calculate_active_days(fills)

        # 时间范围
        sorted_fills = sorted(fills, key=lambda x: x.get('time', 0))
        first_trade_time = sorted_fills[0].get('time', 0)
        last_trade_time = sorted_fills[-1].get('time', 0)

        logger.info(f"指标计算完成: {address[:10]}... - 胜率:{win_rate:.1f}% ROI:{roi:.1f}%")

        return AddressMetrics(
            address=address,
            total_trades=len(fills),
            win_rate=win_rate,
            roi=roi,
            sharpe_ratio=sharpe_ratio,
            total_pnl=total_pnl,
            account_value=account_value,
            max_drawdown=max_drawdown,
            avg_trade_size=avg_trade_size,
            total_volume=total_volume,
            net_deposit=net_deposit,
            first_trade_time=first_trade_time,
            last_trade_time=last_trade_time,
            active_days=active_days
        )


def test_metrics():
    """测试指标计算"""
    # 模拟交易数据
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
        state=test_state,
        net_deposit=10000
    )

    print(f"\n{'='*60}")
    print(f"指标计算测试结果")
    print(f"{'='*60}")
    print(f"地址: {metrics.address}")
    print(f"总交易数: {metrics.total_trades}")
    print(f"胜率: {metrics.win_rate:.1f}%")
    print(f"ROI: {metrics.roi:.1f}%")
    print(f"夏普比率: {metrics.sharpe_ratio:.2f}")
    print(f"总PNL: ${metrics.total_pnl:,.2f}")
    print(f"账户价值: ${metrics.account_value:,.2f}")
    print(f"最大回撤: {metrics.max_drawdown:.1f}%")
    print(f"平均交易规模: ${metrics.avg_trade_size:,.2f}")
    print(f"总交易量: ${metrics.total_volume:,.2f}")
    print(f"活跃天数: {metrics.active_days}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    test_metrics()
