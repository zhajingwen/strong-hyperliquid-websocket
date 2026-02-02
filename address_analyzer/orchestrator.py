"""
主控制器 - 协调所有模块，实现完整工作流
"""

import asyncio
import logging
from typing import List, Optional
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

from .log_parser import LogParser
from .api_client import HyperliquidAPIClient
from .metrics_engine import MetricsEngine, AddressMetrics
from .data_store import DataStore, get_store
from .output_renderer import OutputRenderer

logger = logging.getLogger(__name__)


class Orchestrator:
    """主控制器 - 协调整个分析工作流"""

    def __init__(
        self,
        log_path: str = "trades.log",
        force_refresh: bool = False,
        max_concurrent: int = 10,
        rate_limit: int = 50
    ):
        """
        初始化主控制器

        Args:
            log_path: trades.log 路径
            force_refresh: 强制刷新（忽略缓存）
            max_concurrent: 最大并发数
            rate_limit: API速率限制
        """
        self.log_path = log_path
        self.force_refresh = force_refresh

        # 初始化组件
        self.log_parser = LogParser(log_path)
        self.store: Optional[DataStore] = None
        self.api_client: Optional[HyperliquidAPIClient] = None
        self.metrics_engine = MetricsEngine()
        self.renderer = OutputRenderer()

        self.max_concurrent = max_concurrent
        self.rate_limit = rate_limit

    async def initialize(self):
        """初始化数据库和API客户端"""
        logger.info("初始化数据存储...")
        self.store = get_store()
        await self.store.connect(max_connections=self.max_concurrent * 2)

        logger.info("初始化API客户端...")
        self.api_client = HyperliquidAPIClient(
            store=self.store,
            max_concurrent=self.max_concurrent,
            rate_limit=self.rate_limit
        )

    async def cleanup(self):
        """清理资源"""
        if self.store:
            await self.store.close()

    async def run(
        self,
        output_terminal: bool = True,
        output_html: bool = True,
        html_path: str = "output/analysis_report.html",
        terminal_path: Optional[str] = None,
        top_n: int = 50
    ) -> List[AddressMetrics]:
        """
        运行完整分析流程

        Args:
            output_terminal: 输出终端表格
            output_html: 输出HTML报告
            html_path: HTML报告路径
            terminal_path: 终端输出保存路径（可选）
            top_n: 终端显示前N个地址

        Returns:
            指标列表
        """
        try:
            # 1. 解析日志
            self.renderer.console.print("\n[bold cyan]步骤 1/5:[/bold cyan] 解析交易日志...")
            address_stats = self.log_parser.parse()
            addresses = list(address_stats.keys())
            logger.info(f"解析到 {len(addresses)} 个唯一地址")
            self.renderer.console.print(f"✅ 解析到 [bold]{len(addresses)}[/bold] 个唯一地址\n")

            # 2. 更新地址表
            self.renderer.console.print("[bold cyan]步骤 2/5:[/bold cyan] 更新地址数据库...")
            await self.store.upsert_addresses([
                {
                    'address': addr,
                    'taker_count': stats['taker_count'],
                    'maker_count': stats['maker_count']
                }
                for addr, stats in address_stats.items()
            ])
            self.renderer.console.print("✅ 地址数据库已更新\n")

            # 3. 获取待处理地址
            if self.force_refresh:
                pending_addresses = addresses
                self.renderer.console.print("[yellow]⚠️  强制刷新模式：将重新获取所有地址数据[/yellow]\n")
            else:
                pending_addresses = await self.store.get_pending_addresses()
                if not pending_addresses:
                    pending_addresses = addresses
                    self.renderer.console.print("[yellow]⚠️  未找到待处理地址，将获取所有地址数据[/yellow]\n")
                else:
                    self.renderer.console.print(f"📋 发现 [bold]{len(pending_addresses)}[/bold] 个待处理地址\n")

            # 4. 批量获取API数据
            self.renderer.console.print(f"[bold cyan]步骤 3/5:[/bold cyan] 获取API数据（{len(pending_addresses)} 个地址）...")

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeRemainingColumn(),
                console=self.renderer.console
            ) as progress:
                task = progress.add_task("正在获取数据...", total=len(pending_addresses))

                async def process_address(addr: str) -> Optional[dict]:
                    """处理单个地址"""
                    try:
                        # 更新状态为处理中
                        await self.store.update_processing_status(addr, 'processing')

                        # 获取数据
                        data = await self.api_client.fetch_address_data(addr, save_to_db=True)

                        # 更新状态为完成
                        await self.store.update_processing_status(addr, 'completed')

                        progress.advance(task)
                        return data

                    except Exception as e:
                        logger.error(f"处理地址失败: {addr[:10]}... - {e}")
                        await self.store.update_processing_status(addr, 'failed', str(e))
                        progress.advance(task)
                        return None

                # 并发处理
                tasks = [process_address(addr) for addr in pending_addresses]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # 过滤失败结果
                successful_results = [r for r in results if r and not isinstance(r, Exception)]

            self.renderer.console.print(f"✅ 成功获取 [bold]{len(successful_results)}[/bold] 个地址的数据\n")

            # API 统计
            stats = self.api_client.get_stats()
            self.renderer.console.print(
                f"[dim]API 统计: 请求 {stats['total_requests']} 次, "
                f"缓存命中 {stats['cache_hits']} 次 ({stats['cache_hit_rate']:.1%}), "
                f"错误 {stats['api_errors']} 次[/dim]\n"
            )

            # 5. 计算指标
            self.renderer.console.print(f"[bold cyan]步骤 4/5:[/bold cyan] 计算交易指标...")

            all_metrics = []
            for addr in addresses:
                # 从数据库读取交易记录
                fills = await self.store.get_fills(addr)
                if not fills:
                    logger.warning(f"地址无交易记录: {addr[:10]}...")
                    continue

                # 获取账户状态（从缓存）
                state = await self.store.get_api_cache(f"user_state:{addr}")

                # 计算指标
                metrics = self.metrics_engine.calculate_metrics(
                    address=addr,
                    fills=fills,
                    state=state
                )
                all_metrics.append(metrics)

                # 保存到缓存
                await self.store.save_metrics(addr, {
                    'total_trades': metrics.total_trades,
                    'win_rate': metrics.win_rate,
                    'roi': metrics.roi,
                    'sharpe_ratio': metrics.sharpe_ratio,
                    'total_pnl': metrics.total_pnl,
                    'account_value': metrics.account_value,
                    'max_drawdown': metrics.max_drawdown,
                    'net_deposit': metrics.net_deposit
                })

            self.renderer.console.print(f"✅ 计算完成 [bold]{len(all_metrics)}[/bold] 个地址的指标\n")

            # 6. 输出报告
            self.renderer.console.print("[bold cyan]步骤 5/5:[/bold cyan] 生成报告...\n")

            if output_terminal:
                self.renderer.render_terminal(all_metrics, top_n=top_n, save_path=terminal_path)

            if output_html and all_metrics:
                self.renderer.render_html(all_metrics, output_path=html_path)

            self.renderer.console.print("\n[bold green]✨ 分析完成！[/bold green]\n")

            return all_metrics

        except Exception as e:
            logger.error(f"分析流程失败: {e}", exc_info=True)
            self.renderer.console.print(f"\n[bold red]❌ 错误: {e}[/bold red]\n")
            raise


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='Hyperliquid 交易地址分析工具')
    parser.add_argument('--log-path', default='trades.log', help='trades.log 路径')
    parser.add_argument('--force-refresh', action='store_true', help='强制刷新（忽略缓存）')
    parser.add_argument('--output', choices=['terminal', 'html', 'both'], default='both', help='输出格式')
    parser.add_argument('--html-path', default='output/analysis_report.html', help='HTML报告路径')
    parser.add_argument('--terminal-path', help='终端输出保存路径')
    parser.add_argument('--top-n', type=int, default=50, help='终端显示前N个地址')
    parser.add_argument('--concurrent', type=int, default=10, help='最大并发数')
    parser.add_argument('--rate-limit', type=int, default=50, help='API速率限制（请求/秒）')

    args = parser.parse_args()

    # 初始化控制器
    orchestrator = Orchestrator(
        log_path=args.log_path,
        force_refresh=args.force_refresh,
        max_concurrent=args.concurrent,
        rate_limit=args.rate_limit
    )

    try:
        await orchestrator.initialize()

        # 运行分析
        await orchestrator.run(
            output_terminal=args.output in ('terminal', 'both'),
            output_html=args.output in ('html', 'both'),
            html_path=args.html_path,
            terminal_path=args.terminal_path,
            top_n=args.top_n
        )

    finally:
        await orchestrator.cleanup()


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(main())
