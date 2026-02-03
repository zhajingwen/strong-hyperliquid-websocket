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
    net_deposits: float = 0.0           # 净充值 (USD) - 仅 deposit/withdraw
    total_deposits: float = 0.0         # 总充值 (USD)
    total_withdrawals: float = 0.0      # 总提现 (USD)
    actual_initial_capital: float = 0.0 # 实际初始资金 (USD) - 传统方法
    corrected_roi: float = 0.0          # 校准后的ROI (%) - 传统方法

    # 转账相关字段（区分盈亏转移）
    total_transfers_in: float = 0.0     # 转入总额 (send/subAccountTransfer)
    total_transfers_out: float = 0.0    # 转出总额 (send/subAccountTransfer)
    net_transfers: float = 0.0          # 净转账 (USD)
    true_capital: float = 0.0           # 真实本金 (仅 deposit/withdraw，不含转账)
    true_capital_roi: float = 0.0       # 基于真实本金的 ROI (%)

    # P0 修复新增字段
    bankruptcy_count: int = 0           # 爆仓次数
    sharpe_method: str = "standard"     # 计算方法标记

    # 回撤详细信息（P0优化新增）
    max_drawdown_legacy: float = 0.0       # 旧算法回撤（对比用）
    drawdown_quality: str = "estimated"    # 回撤质量：enhanced|standard|estimated
    drawdown_count: int = 0                # 回撤次数
    largest_drawdown_pct: float = 0.0      # 单次最大回撤
    drawdown_improvement_pct: float = 0.0  # 算法改进幅度

    # 未实现盈亏回撤（P1优化新增）
    max_drawdown_with_unrealized: float = 0.0  # 含未实现盈亏的回撤

    # ROI 扩展指标（P1优化新增）
    time_weighted_roi: float = 0.0         # 时间加权ROI（考虑资金使用时长）
    annualized_roi: float = 0.0            # 年化ROI
    total_roi: float = 0.0                 # 总ROI（含未实现盈亏）
    roi_quality: str = "estimated"         # ROI质量：actual|estimated

    # Sharpe比率扩展指标（P2优化新增）
    sharpe_quality: str = "estimated"      # Sharpe质量：enhanced|standard|estimated|estimated_fallback
    funding_pnl: float = 0.0               # 资金费率盈亏（USD）
    funding_contribution: float = 0.0      # 资金费率贡献百分比（%）


class MetricsEngine:
    """交易指标计算引擎"""

    ANNUAL_DAYS = 365  # 加密货币全年交易，不使用252交易日
    DEFAULT_RISK_FREE_RATE = 0.04  # 默认无风险利率 4%（2024年市场水平）
    _risk_free_rate = DEFAULT_RISK_FREE_RATE  # 类变量，可动态修改

    @classmethod
    def set_risk_free_rate(cls, rate: float):
        """
        设置无风险利率

        Args:
            rate: 年化无风险利率（0-20%范围）

        Raises:
            ValueError: 如果利率超出合理范围
        """
        if not 0 <= rate <= 0.20:
            raise ValueError(f"利率超出合理范围 (0-20%): {rate}")
        cls._risk_free_rate = rate
        logger.info(f"无风险利率更新为: {rate:.2%}")

    @classmethod
    def get_risk_free_rate(cls) -> float:
        """
        获取当前无风险利率

        Returns:
            当前无风险利率
        """
        return cls._risk_free_rate

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
        has_transfer_data: bool = False,
        true_capital: Optional[float] = None
    ) -> tuple[float, float, float, float, float]:
        """
        计算总PNL和ROI（扩展版返回5个值，支持两种本金口径）

        总PNL = 所有交易的已实现PNL之和 (sum of closedPnl)
        Legacy ROI = (已实现PNL / 推算初始资金) * 100
        Corrected ROI = (已实现PNL / 实际初始资金) * 100 - 传统方法（含转账）
        True Capital ROI = (已实现PNL / 真实本金) * 100 - 保守方法（仅充值/提现）

        Args:
            fills: 交易记录列表
            account_value: 当前账户价值
            net_deposits: 净充值（默认0）- 传统方法，包含转账
            has_transfer_data: 是否有出入金数据
            true_capital: 真实本金（仅充值/提现，不含转账）

        Returns:
            (total_pnl, legacy_roi, actual_initial_capital, corrected_roi, true_capital_roi)
        """
        if not fills:
            return 0.0, 0.0, 0.0, 0.0, 0.0

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
            # 传统方法：包含转账的初始资金
            actual_initial = MetricsEngine.calculate_actual_initial_capital(
                account_value, realized_pnl, net_deposits
            )
            corrected_roi = MetricsEngine.calculate_corrected_roi(realized_pnl, actual_initial)

            # 保守方法：基于真实本金（仅充值/提现）
            if true_capital is not None and true_capital > 0:
                true_capital_roi = MetricsEngine.calculate_corrected_roi(realized_pnl, true_capital)
            else:
                # 如果没有真实本金数据，使用传统方法
                true_capital_roi = corrected_roi
        else:
            # 降级策略
            actual_initial = estimated_initial
            corrected_roi = legacy_roi
            true_capital_roi = legacy_roi

        return total_pnl, legacy_roi, actual_initial, corrected_roi, true_capital_roi

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
                annualized_roi = (total_return_rate ** (1/years) - 1) * 100
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

    @classmethod
    def calculate_sharpe_ratio(
        cls,
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

        # 按时间排序（带优化检测）
        sorted_fills = cls._ensure_sorted_fills(fills)

        # 计算每笔交易的收益率（动态资金基准）
        returns = []
        running_capital = initial_capital
        bankruptcy_detected = False

        for fill in sorted_fills:
            pnl = MetricsEngine._get_pnl(fill)

            if running_capital > 0 and not bankruptcy_detected:
                ret = pnl / running_capital
                returns.append(ret)
                running_capital += pnl

                # 爆仓检测 - 终止计算而非重置
                if running_capital <= 0:
                    logger.warning(
                        f"检测到爆仓: 资金 {running_capital - pnl:.2f} → {running_capital:.2f}, "
                        f"在第 {len(returns)} 笔交易后终止 Sharpe 计算"
                    )
                    bankruptcy_detected = True
                    break  # 终止，不再处理后续交易
            else:
                # 已爆仓或资金为负，跳过所有后续交易
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

        # 计算时间跨度
        trading_days = len(returns)
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

        # 使用改进的年化算法（基于实际时间跨度）
        if trading_days > 0 and time_span_days > 0:
            # 方法：基于实际持有期计算年化
            # 1. 计算总收益率
            total_return = np.sum(returns_array)  # 简单相加（保守）

            # 2. 转换为年化收益率（基于实际天数）
            years = time_span_days / MetricsEngine.ANNUAL_DAYS
            if years > 0:
                # 年化公式: (1 + 总收益)^(1/年数) - 1
                annual_return = (1 + total_return) ** (1 / years) - 1
            else:
                annual_return = 0.0

            # 3. 年化标准差（基于每日波动）
            # 假设每天交易一次,计算日波动
            daily_volatility = std_return * np.sqrt(trading_days / time_span_days)
            annual_std = daily_volatility * np.sqrt(MetricsEngine.ANNUAL_DAYS)

            # 异常值保护
            if np.isnan(annual_return) or np.isinf(annual_return):
                annual_return = 0.0
            if np.isnan(annual_std) or np.isinf(annual_std) or annual_std == 0:
                annual_std = 1.0
        else:
            annual_return = 0.0
            annual_std = 1.0

        # 异常值检测
        if annual_std == 0 or np.isnan(annual_std) or np.isinf(annual_std):
            logger.warning(f"年化标准差异常: {annual_std}")
            return 0.0

        if np.isnan(annual_return) or np.isinf(annual_return):
            logger.warning(f"年化收益率异常: {annual_return}")
            return 0.0

        # 夏普比率 = (年化收益率 - 无风险利率) / 年化标准差
        sharpe = (annual_return - cls.get_risk_free_rate()) / annual_std

        # 异常值处理
        if np.isnan(sharpe) or np.isinf(sharpe):
            return 0.0

        # Sharpe > 10 通常表明计算错误
        if abs(sharpe) > 10:
            logger.warning(
                f"Sharpe 比率异常大: {sharpe:.2f}, "
                f"年化收益={annual_return:.2%}, 波动={annual_std:.2%}"
            )

        # 数据库边界保护：DECIMAL(10, 4) 最大值为 999,999.9999
        sharpe = max(-999999.9999, min(999999.9999, sharpe))

        return float(sharpe)

    @classmethod
    def calculate_sharpe_ratio_enhanced(
        cls,
        fills: List[Dict],
        account_value: float,
        actual_initial_capital: Optional[float] = None,
        ledger: Optional[List[Dict]] = None,
        address: Optional[str] = None,
        state: Optional[Dict] = None
    ) -> tuple[float, Dict]:
        """
        改进版Sharpe比率计算（P2优化：集成出入金和资金费率）

        优化点：
        1. 集成ledger数据，正确处理出入金对资金基准的影响
        2. 整合资金费率数据，计入总收益
        3. 基于动态资金基准计算收益率序列

        Args:
            fills: 交易记录列表
            account_value: 当前账户价值
            actual_initial_capital: 实际初始资金
            ledger: 出入金记录（可选）
            address: 钱包地址（可选）
            state: 用户状态数据（包含资金费率，可选）

        Returns:
            (sharpe_ratio, details)

        Details包含：
            - quality: 质量标记
            - funding_pnl: 资金费率盈亏
            - funding_contribution: 资金费率贡献百分比
        """
        # 如果没有ledger和state，降级到旧算法
        if not ledger and not state:
            sharpe_old = cls.calculate_sharpe_ratio(fills, account_value, actual_initial_capital)
            return sharpe_old, {'quality': 'estimated_fallback', 'funding_pnl': 0.0, 'funding_contribution': 0.0}

        if not fills or len(fills) < 2:
            return 0.0, {'quality': 'insufficient_data', 'funding_pnl': 0.0, 'funding_contribution': 0.0}

        # 1. 获取资金费率盈亏
        funding_pnl = 0.0
        if state:
            for asset in state.get('assetPositions', []):
                pos = asset.get('position', {})
                cum_funding = pos.get('cumFunding', {})
                # 使用allTime累计总资金费（负数=收益，正数=成本）
                all_time_funding = cum_funding.get('allTime', '0')
                # 资金费率：负数表示收到，正数表示支付
                # 为了统一，我们将"收到"作为正收益
                funding_pnl -= float(all_time_funding)

        # 2. 合并交易和出入金事件
        events = []

        # 添加交易事件
        for fill in fills:
            events.append({
                'time': fill.get('time', 0),
                'type': 'trade',
                'pnl': MetricsEngine._get_pnl(fill)
            })

        # 添加出入金事件
        if ledger and address:
            for record in ledger:
                amount = cls._extract_ledger_amount(record, address)
                if amount != 0:
                    events.append({
                        'time': record.get('time', 0),
                        'type': 'cash_flow',
                        'amount': amount
                    })

        # 3. 按时间排序
        events.sort(key=lambda x: x['time'])

        # 4. 确定初始资金
        if actual_initial_capital is not None and actual_initial_capital > 0:
            initial_capital = actual_initial_capital
            quality = 'enhanced'
        else:
            # 推算初始资金：当前价值 - 已实现盈亏 - 资金费
            realized_pnl = sum(e['pnl'] for e in events if e['type'] == 'trade')
            initial_capital = account_value - realized_pnl - funding_pnl

            if initial_capital <= 0:
                initial_capital = max(account_value, 1000)
                quality = 'estimated'
            else:
                quality = 'standard'

        # 边界保护
        if initial_capital <= 0:
            initial_capital = max(account_value, 1000)

        # 5. 构建收益率序列（考虑出入金）
        returns = []
        running_capital = initial_capital
        bankruptcy_detected = False

        for event in events:
            if event['type'] == 'cash_flow':
                # 出入金事件：调整资金基准，不计入收益率
                running_capital += event['amount']

            elif event['type'] == 'trade':
                # 交易事件：基于当前资金计算收益率
                if running_capital > 0 and not bankruptcy_detected:
                    pnl = event['pnl']
                    ret = pnl / running_capital
                    returns.append(ret)
                    running_capital += pnl

                    # 爆仓检测
                    if running_capital <= 0:
                        logger.warning(
                            f"检测到爆仓: 资金 {running_capital - pnl:.2f} → {running_capital:.2f}"
                        )
                        bankruptcy_detected = True
                        break

        if not returns or len(returns) < 2:
            return 0.0, {'quality': quality, 'funding_pnl': funding_pnl, 'funding_contribution': 0.0}

        # 6. 将资金费率加入总收益（在计算年化收益时考虑）
        # 资金费率视为额外收益，分摊到整个交易周期
        total_trading_pnl = sum(e['pnl'] for e in events if e['type'] == 'trade')
        total_pnl_with_funding = total_trading_pnl + funding_pnl

        # 计算资金费率贡献百分比
        if total_trading_pnl != 0:
            funding_contribution = (funding_pnl / abs(total_trading_pnl)) * 100
        else:
            funding_contribution = 0.0

        # 7. 计算年化收益率和波动率
        returns_array = np.array(returns)
        mean_return = np.mean(returns_array)
        std_return = np.std(returns_array, ddof=1)

        if std_return == 0:
            return 0.0, {'quality': quality, 'funding_pnl': funding_pnl, 'funding_contribution': funding_contribution}

        # 计算时间跨度
        sorted_fills = cls._ensure_sorted_fills(fills)
        first_time = sorted_fills[0]['time']
        last_time = sorted_fills[-1]['time']

        if isinstance(first_time, datetime) and isinstance(last_time, datetime):
            time_span_days = (last_time - first_time).total_seconds() / 86400
        else:
            time_span_days = (last_time - first_time) / (1000 * 86400)

        if time_span_days <= 0:
            time_span_days = 1

        # 年化计算（包含资金费率影响）
        trading_days = len(returns)
        if trading_days > 0 and time_span_days > 0:
            years = time_span_days / MetricsEngine.ANNUAL_DAYS

            if years > 0:
                # 使用包含资金费的总收益计算年化
                total_return_with_funding = total_pnl_with_funding / initial_capital
                annual_return = (1 + total_return_with_funding) ** (1 / years) - 1
            else:
                annual_return = 0.0

            # 年化波动率
            daily_volatility = std_return * np.sqrt(trading_days / time_span_days)
            annual_std = daily_volatility * np.sqrt(MetricsEngine.ANNUAL_DAYS)

            # 异常值保护
            if np.isnan(annual_return) or np.isinf(annual_return):
                annual_return = 0.0
            if np.isnan(annual_std) or np.isinf(annual_std) or annual_std == 0:
                annual_std = 1.0
        else:
            annual_return = 0.0
            annual_std = 1.0

        # 计算Sharpe比率
        if annual_std == 0 or np.isnan(annual_std) or np.isinf(annual_std):
            sharpe = 0.0
        else:
            sharpe = (annual_return - cls.get_risk_free_rate()) / annual_std

        # 异常值处理
        if np.isnan(sharpe) or np.isinf(sharpe):
            sharpe = 0.0

        # 边界保护
        sharpe = max(-999999.9999, min(999999.9999, sharpe))

        details = {
            'quality': quality,
            'funding_pnl': funding_pnl,
            'funding_contribution': funding_contribution,
            'annual_return': annual_return,
            'annual_std': annual_std
        }

        return float(sharpe), details

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
    def calculate_max_drawdown(
        cls,
        fills: List[Dict],
        account_value: float = 0.0,
        actual_initial_capital: Optional[float] = None,
        ledger: Optional[List[Dict]] = None,
        address: Optional[str] = None,
        state: Optional[Dict] = None  # 新增：用于获取未实现盈亏
    ) -> tuple[float, Dict]:
        """
        计算最大回撤（改进版：考虑出入金影响）

        算法改进：
        1. 从初始资金开始计算（而非第一笔交易的PNL）
        2. 基于账户权益曲线（equity = 初始资金 + 累计PNL）
        3. 修复初始峰值可能为负的BUG
        4. 支持真实初始资金（如果提供出入金数据）
        5. ✨ 考虑出入金事件（提现不算回撤，充值调整峰值）

        Args:
            fills: 交易记录列表（按时间排序）
            account_value: 当前账户价值
            actual_initial_capital: 实际初始资金（可选）
            ledger: 出入金记录（可选，提供则使用改进算法）
            address: 用户地址（使用ledger时必需）

        Returns:
            (max_drawdown_pct, details)

            details = {
                'max_drawdown': float,           # 主要指标（考虑出入金）
                'max_drawdown_legacy': float,    # 旧算法（对比用）
                'quality': str,                  # 'enhanced' | 'standard' | 'estimated'
                'drawdown_count': int,           # 回撤次数
                'largest_drawdown_pct': float,   # 单次最大回撤
            }

        算法说明：
            旧算法问题：
            - 将提现误算为交易亏损，导致回撤虚高
            - 未调整充值后的峰值

            新算法（使用ledger时）：
            - 合并交易和出入金事件，按时间排序
            - 出入金事件调整峰值（而非视为盈亏）
            - 只有交易盈亏才会产生回撤
        """
        if not fills:
            empty_details = {
                'max_drawdown': 0.0,
                'max_drawdown_legacy': 0.0,
                'quality': 'no_data',
                'drawdown_count': 0,
                'largest_drawdown_pct': 0.0
            }
            return 0.0, empty_details

        # 如果提供了ledger数据，使用改进算法
        if ledger is not None and address is not None:
            return cls._calculate_dd_with_ledger(
                fills, ledger, account_value, actual_initial_capital, address, state
            )
        else:
            # 降级到旧算法
            dd_pct, quality = cls._calculate_dd_legacy(
                fills, account_value, actual_initial_capital
            )
            details = {
                'max_drawdown': dd_pct,
                'max_drawdown_legacy': dd_pct,
                'quality': quality,
                'drawdown_count': 0,
                'largest_drawdown_pct': dd_pct
            }
            return dd_pct, details

    @classmethod
    def _calculate_dd_legacy(
        cls,
        fills: List[Dict],
        account_value: float,
        actual_initial_capital: Optional[float] = None
    ) -> tuple[float, str]:
        """
        旧版最大回撤计算（保留作为降级方案）

        Returns:
            (max_drawdown_pct, quality)
        """
        # 按时间排序（带优化检测）
        sorted_fills = cls._ensure_sorted_fills(fills)

        # 确定初始资金：优先使用真实初始资金，否则推算
        if actual_initial_capital is not None and actual_initial_capital > 0:
            initial_capital = actual_initial_capital
            quality = 'standard'
        else:
            realized_pnl = sum(MetricsEngine._get_pnl(f) for f in fills)
            initial_capital = account_value - realized_pnl
            quality = 'estimated'

        # 边界保护：初始资金不应为负或过小
        if initial_capital <= 0:
            initial_capital = max(account_value, 100)
            quality = 'estimated_fallback'

        # 构建权益曲线（从初始资金开始）
        running_equity = initial_capital
        peak = initial_capital
        max_drawdown = 0.0

        for fill in sorted_fills:
            running_equity += MetricsEngine._get_pnl(fill)

            # 更新峰值
            if running_equity > peak:
                peak = running_equity

            # 计算当前回撤
            if peak > 0:
                drawdown = (peak - running_equity) / peak
                max_drawdown = max(max_drawdown, drawdown)
            elif running_equity < 0:
                max_drawdown = max(max_drawdown, 1.0)  # 100%回撤

        max_drawdown_pct = max_drawdown * 100

        # 日志记录异常大的回撤（>200%）
        if max_drawdown_pct > 200:
            logger.warning(
                f"检测到异常大的最大回撤: {max_drawdown_pct:.2f}% "
                f"(初始资金: ${initial_capital:.2f}, 当前权益: ${running_equity:.2f})"
            )

        # 边界保护
        max_drawdown_pct = min(max_drawdown_pct, 999.99)

        return max_drawdown_pct, quality

    @classmethod
    def _calculate_dd_with_ledger(
        cls,
        fills: List[Dict],
        ledger: List[Dict],
        account_value: float,
        actual_initial_capital: Optional[float],
        address: str,
        state: Optional[Dict] = None  # 新增：用于获取未实现盈亏
    ) -> tuple[float, Dict]:
        """
        改进版最大回撤计算（考虑出入金和未实现盈亏）

        核心思想：
        1. 合并交易和出入金事件，按时间排序
        2. 出入金事件调整峰值（而非视为盈亏）
        3. 只有交易盈亏才会产生回撤
        4. 可选：计算含未实现盈亏的回撤

        Returns:
            (max_drawdown_pct, details)
        """
        # 1. 合并所有事件
        events = []

        # 添加交易事件
        for fill in fills:
            events.append({
                'time': fill.get('time', 0),
                'type': 'trade',
                'pnl': MetricsEngine._get_pnl(fill)
            })

        # 添加出入金事件
        for record in ledger:
            amount = cls._extract_ledger_amount(record, address)
            if amount != 0:
                events.append({
                    'time': record.get('time', 0),
                    'type': 'cash_flow',
                    'amount': amount  # 正数=流入，负数=流出
                })

        # 2. 按时间排序
        events.sort(key=lambda x: x['time'])

        # 3. 确定初始资金
        if actual_initial_capital is not None and actual_initial_capital > 0:
            initial_capital = actual_initial_capital
            quality = 'enhanced'
        else:
            realized_pnl = sum(e['pnl'] for e in events if e['type'] == 'trade')
            initial_capital = account_value - realized_pnl
            quality = 'standard'

        if initial_capital <= 0:
            initial_capital = max(account_value, 100)
            quality = 'estimated'

        # 4. 构建权益曲线（考虑出入金）
        # 核心思想：
        # - running_equity 追踪当前权益
        # - peak 追踪历史最高权益
        # - 出入金调整权益和峰值，但不产生回撤
        # - 只有交易盈亏才会产生回撤

        running_equity = 0.0  # 从0开始，通过出入金和交易累积
        peak = 0.0
        max_drawdown = 0.0
        drawdown_count = 0
        in_drawdown = False
        largest_dd = 0.0

        equity_curve = []

        for event in events:
            if event['type'] == 'cash_flow':
                # 出入金事件：同时调整权益和峰值
                cash_flow = event['amount']
                running_equity += cash_flow

                # 关键：出入金同步调整峰值
                # 这样提现后，峰值降低，不会产生虚假回撤
                if cash_flow > 0:
                    # 充值：峰值增加
                    peak += cash_flow
                else:
                    # 提现：峰值减少
                    # 如果提现后权益仍高于调整后的峰值，更新峰值
                    peak += cash_flow
                    if running_equity > peak:
                        peak = running_equity

            elif event['type'] == 'trade':
                # 交易事件：产生盈亏，可能产生回撤
                pnl = event['pnl']
                running_equity += pnl

                # 计算回撤（在更新峰值之前）
                if peak > 0 and running_equity < peak:
                    drawdown = (peak - running_equity) / peak

                    if not in_drawdown and drawdown > 0.01:  # 超过1%才算回撤
                        drawdown_count += 1
                        in_drawdown = True

                    max_drawdown = max(max_drawdown, drawdown)
                    largest_dd = max(largest_dd, drawdown)
                elif running_equity < 0 and peak > 0:
                    # 爆仓情况
                    max_drawdown = max(max_drawdown, 1.0)
                    largest_dd = max(largest_dd, 1.0)

                # 更新峰值（在计算回撤之后）
                if running_equity > peak:
                    peak = running_equity
                    # 从回撤中恢复
                    if in_drawdown:
                        in_drawdown = False

            equity_curve.append({
                'time': event['time'],
                'equity': running_equity,
                'peak': peak,
                'drawdown': (peak - running_equity) / peak if peak > 0 else 0,
                'event_type': event['type']
            })

        # 5. 计算含未实现盈亏的回撤（P1优化）
        max_drawdown_with_unrealized = max_drawdown  # 默认与已实现相同

        if state:
            # 获取未实现盈亏
            unrealized_pnl = sum(
                float(pos['position'].get('unrealizedPnl', 0))
                for pos in state.get('assetPositions', [])
            )

            # 在当前权益上加上未实现盈亏，看是否产生更大的回撤
            if unrealized_pnl != 0:
                current_equity_with_unrealized = running_equity + unrealized_pnl

                # 计算含未实现的回撤
                if peak > 0 and current_equity_with_unrealized < peak:
                    drawdown_with_unrealized = (peak - current_equity_with_unrealized) / peak
                    max_drawdown_with_unrealized = max(max_drawdown, drawdown_with_unrealized)
                elif current_equity_with_unrealized < 0 and peak > 0:
                    # 爆仓情况
                    max_drawdown_with_unrealized = 1.0

                logger.debug(
                    f"未实现盈亏影响：当前权益=${running_equity:.2f}, "
                    f"未实现=${unrealized_pnl:.2f}, "
                    f"含未实现回撤={max_drawdown_with_unrealized*100:.2f}%"
                )

        # 6. 计算旧算法对比
        legacy_dd, _ = cls._calculate_dd_legacy(fills, account_value, actual_initial_capital)

        # 7. 返回详细信息
        max_drawdown_pct = min(max_drawdown * 100, 999.99)
        largest_dd_pct = min(largest_dd * 100, 999.99)
        max_drawdown_with_unrealized_pct = min(max_drawdown_with_unrealized * 100, 999.99)

        details = {
            'max_drawdown': max_drawdown_pct,
            'max_drawdown_legacy': legacy_dd,
            'quality': quality,
            'drawdown_count': drawdown_count,
            'largest_drawdown_pct': largest_dd_pct,
            'improvement_pct': legacy_dd - max_drawdown_pct if legacy_dd > max_drawdown_pct else 0.0,
            'max_drawdown_with_unrealized': max_drawdown_with_unrealized_pct  # P1新增
        }

        # 日志记录改进效果
        if details['improvement_pct'] > 5:
            logger.info(
                f"回撤算法改进：旧算法={legacy_dd:.2f}%, "
                f"新算法={max_drawdown_pct:.2f}%, "
                f"改进={details['improvement_pct']:.2f}%"
            )

        return max_drawdown_pct, details

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
    def detect_bankruptcy(
        cls,
        fills: List[Dict],
        account_value: float,
        actual_initial_capital: Optional[float] = None
    ) -> int:
        """
        检测爆仓次数（资金降至 0 或负值）

        Args:
            fills: 交易记录列表（按时间排序）
            account_value: 当前账户价值
            actual_initial_capital: 实际初始资金（可选）

        Returns:
            爆仓次数
        """
        if not fills:
            return 0

        # 确定初始资金
        if actual_initial_capital is not None and actual_initial_capital > 0:
            initial_capital = actual_initial_capital
        else:
            realized_pnl = sum(MetricsEngine._get_pnl(f) for f in fills)
            initial_capital = account_value - realized_pnl

        if initial_capital <= 0:
            initial_capital = max(account_value, 1000)

        # 按时间排序（带优化检测）
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

        # 提取转账数据（新增）
        total_transfers_in = transfer_data.get('total_transfers_in', 0.0) if transfer_data else 0.0
        total_transfers_out = transfer_data.get('total_transfers_out', 0.0) if transfer_data else 0.0
        net_transfers = transfer_data.get('net_transfers', 0.0) if transfer_data else 0.0

        # 计算真实本金（仅充值/提现，不含转账）
        true_capital = (total_deposits - total_withdrawals) if has_transfer_data else 0.0

        # 计算各项指标
        win_rate = cls.calculate_win_rate(fills)

        # 计算PNL和ROI（扩展版返回5个值，支持两种本金口径）
        total_pnl, legacy_roi, actual_initial, corrected_roi, true_capital_roi = cls.calculate_pnl_and_roi(
            fills, account_value, net_deposits, has_transfer_data, true_capital
        )

        # 计算时间加权ROI（P1优化，如果有ledger数据）
        ledger_data = transfer_data.get('ledger', None) if transfer_data else None
        if ledger_data and address:
            time_weighted_roi, annualized_roi, total_roi, roi_quality = cls.calculate_time_weighted_roi(
                fills, ledger_data, account_value, address, state
            )
        else:
            # 降级：无ledger数据时使用简单年化
            time_weighted_roi = corrected_roi

            # 确保fills已排序
            sorted_fills_for_roi = cls._ensure_sorted_fills(fills)

            total_days = (
                (sorted_fills_for_roi[-1].get('time', 0) - sorted_fills_for_roi[0].get('time', 0)) / (1000 * 86400)
                if len(sorted_fills_for_roi) > 0 else 1
            )
            years = max(total_days / 365, 1/365)
            if years > 0 and actual_initial > 0:
                total_return_rate = account_value / actual_initial
                annualized_roi = (total_return_rate ** (1/years) - 1) * 100
            else:
                annualized_roi = corrected_roi

            # 总ROI（含未实现）
            unrealized_pnl = sum(
                float(pos['position'].get('unrealizedPnl', 0))
                for pos in (state or {}).get('assetPositions', [])
            ) if state else 0.0
            total_pnl_with_unrealized = total_pnl + unrealized_pnl
            total_roi = (total_pnl_with_unrealized / actual_initial * 100) if actual_initial > 0 else 0.0

            roi_quality = 'estimated'

        # 使用真实初始资金计算夏普比率（P2优化：集成出入金和资金费率）
        ledger_data = transfer_data.get('ledger', None) if transfer_data else None
        sharpe_ratio, sharpe_details = cls.calculate_sharpe_ratio_enhanced(
            fills, account_value, actual_initial, ledger_data, address, state
        )

        # 计算最大回撤（使用改进算法，如果有ledger数据）
        max_drawdown, dd_details = cls.calculate_max_drawdown(
            fills, account_value, actual_initial, ledger_data, address, state  # P1: 传入state
        )

        # 检测爆仓次数
        bankruptcy_count = cls.detect_bankruptcy(fills, account_value, actual_initial)

        avg_trade_size, total_volume = cls.calculate_trade_statistics(fills)
        active_days = cls.calculate_active_days(fills)

        # 时间范围（带优化检测）
        sorted_fills = cls._ensure_sorted_fills(fills)
        first_trade_time = sorted_fills[0].get('time', 0)
        last_trade_time = sorted_fills[-1].get('time', 0)

        logger.info(
            f"指标计算完成: {address} - 胜率:{win_rate:.1f}% "
            f"ROI(旧):{legacy_roi:.1f}% ROI(校准):{corrected_roi:.1f}% ROI(真实本金):{true_capital_roi:.1f}%"
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
            # 出入金字段（传统方法，包含转账）
            net_deposits=net_deposits,
            total_deposits=total_deposits,
            total_withdrawals=total_withdrawals,
            actual_initial_capital=actual_initial,
            corrected_roi=corrected_roi,
            # 转账字段（新增，区分盈亏转移）
            total_transfers_in=total_transfers_in,
            total_transfers_out=total_transfers_out,
            net_transfers=net_transfers,
            true_capital=true_capital,
            true_capital_roi=true_capital_roi,
            # P0 修复字段
            bankruptcy_count=bankruptcy_count,
            sharpe_method="compound_interest",
            # 回撤详细信息（P0优化）
            max_drawdown_legacy=dd_details.get('max_drawdown_legacy', max_drawdown),
            drawdown_quality=dd_details.get('quality', 'estimated'),
            drawdown_count=dd_details.get('drawdown_count', 0),
            largest_drawdown_pct=dd_details.get('largest_drawdown_pct', max_drawdown),
            drawdown_improvement_pct=dd_details.get('improvement_pct', 0.0),
            # 未实现盈亏回撤（P1优化）
            max_drawdown_with_unrealized=dd_details.get('max_drawdown_with_unrealized', max_drawdown),
            # ROI扩展指标（P1优化）
            time_weighted_roi=time_weighted_roi,
            annualized_roi=annualized_roi,
            total_roi=total_roi,
            roi_quality=roi_quality,
            # Sharpe比率扩展指标（P2优化）
            sharpe_quality=sharpe_details.get('quality', 'estimated'),
            funding_pnl=sharpe_details.get('funding_pnl', 0.0),
            funding_contribution=sharpe_details.get('funding_contribution', 0.0)
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
