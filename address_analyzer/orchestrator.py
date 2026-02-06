"""
主控制器 - 协调所有模块，实现完整工作流
"""

import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Set
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

        # 黑名单
        self.blacklist: Set[str] = set()
        self._load_blacklist()

    def _load_blacklist(self):
        """从 blacklist.txt 加载黑名单地址"""
        blacklist_path = Path(__file__).parent / "blacklist.txt"
        if not blacklist_path.exists():
            logger.info("未找到黑名单文件，跳过黑名单过滤")
            return
        with open(blacklist_path, "r") as f:
            for line in f:
                addr = line.strip().lower()
                if addr:
                    self.blacklist.add(addr)
        if self.blacklist:
            logger.info(f"已加载黑名单: {len(self.blacklist)} 个地址")

    async def initialize(self):
        """初始化数据库和API客户端"""
        logger.info("========== 开始初始化 ==========")
        logger.info("初始化数据存储...")
        self.store = get_store()
        await self.store.connect(max_connections=self.max_concurrent * 2)
        logger.info(f"数据库连接池已建立: 最大连接数 {self.max_concurrent * 2}")

        logger.info("初始化API客户端...")
        self.api_client = HyperliquidAPIClient(
            store=self.store,
            max_concurrent=self.max_concurrent,
            rate_limit=self.rate_limit
        )
        logger.info(f"API客户端已初始化: 最大并发 {self.max_concurrent}, 速率限制 {self.rate_limit} req/s")
        logger.info("========== 初始化完成 ==========\n")

    async def cleanup(self):
        """清理资源"""
        logger.info("开始清理资源...")
        if self.store:
            await self.store.close()
            logger.info("数据库连接已关闭")

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
            logger.info(f"步骤 1/5: 开始解析交易日志文件: {self.log_path}")
            address_stats = self.log_parser.parse()
            total_parsed = len(address_stats)
            logger.info(f"步骤 1/5: 解析到 {total_parsed} 个唯一地址")

            # 过滤黑名单地址
            if self.blacklist:
                before_count = len(address_stats)
                address_stats = {
                    addr: stats for addr, stats in address_stats.items()
                    if addr.lower() not in self.blacklist
                }
                blacklisted_count = before_count - len(address_stats)
                if blacklisted_count > 0:
                    logger.info(f"已过滤黑名单地址: {blacklisted_count} 个")
                    self.renderer.console.print(f"🚫 已过滤黑名单地址 [bold]{blacklisted_count}[/bold] 个\n")

            addresses = list(address_stats.keys())
            logger.info(f"步骤 1/5 完成: 最终 {len(addresses)} 个有效地址")
            self.renderer.console.print(f"✅ 解析到 [bold]{total_parsed}[/bold] 个唯一地址，有效 [bold]{len(addresses)}[/bold] 个\n")

            # 2. 更新地址表
            self.renderer.console.print("[bold cyan]步骤 2/5:[/bold cyan] 更新地址数据库...")
            logger.info(f"步骤 2/5: 开始更新地址数据库，共 {len(addresses)} 个地址")
            await self.store.upsert_addresses([
                {
                    'address': addr,
                    'taker_count': stats['taker_count'],
                    'maker_count': stats['maker_count']
                }
                for addr, stats in address_stats.items()
            ])
            logger.info("步骤 2/5 完成: 地址数据库已更新")
            self.renderer.console.print("✅ 地址数据库已更新\n")

            # 3. 获取待处理地址
            if self.force_refresh:
                pending_addresses = addresses
                logger.info(f"强制刷新模式: 将重新获取所有 {len(addresses)} 个地址的数据")
                self.renderer.console.print("[yellow]⚠️  强制刷新模式：将重新获取所有地址数据[/yellow]\n")
            else:
                pending_addresses = await self.store.get_pending_addresses()
                if not pending_addresses:
                    pending_addresses = addresses
                    logger.info(f"未找到待处理地址，将获取所有 {len(addresses)} 个地址的数据")
                    self.renderer.console.print("[yellow]⚠️  未找到待处理地址，将获取所有地址数据[/yellow]\n")
                else:
                    logger.info(f"发现 {len(pending_addresses)} 个待处理地址（共 {len(addresses)} 个地址）")
                    self.renderer.console.print(f"📋 发现 [bold]{len(pending_addresses)}[/bold] 个待处理地址\n")

            # 4. 批量获取API数据
            self.renderer.console.print(f"[bold cyan]步骤 3/5:[/bold cyan] 获取API数据（{len(pending_addresses)} 个地址）...")
            logger.info(f"步骤 3/5: 开始获取API数据，共 {len(pending_addresses)} 个待处理地址")

            # 进度计数器
            processed_count = 0
            success_count = 0
            failed_count = 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeRemainingColumn(),
                console=self.renderer.console
            ) as progress:
                task = progress.add_task("正在获取数据...", total=len(pending_addresses))

                async def process_address(addr: str, index: int) -> Optional[dict]:
                    """处理单个地址"""
                    nonlocal processed_count, success_count, failed_count

                    try:
                        logger.info(f"[{index}/{len(pending_addresses)}] 开始处理地址: {addr}")

                        # 更新状态为处理中
                        await self.store.update_processing_status(addr, 'processing')

                        # 获取数据
                        data = await self.api_client.fetch_address_data(addr, save_to_db=True)

                        # 更新状态为完成
                        await self.store.update_processing_status(addr, 'completed')

                        # 标记地址数据已完整获取
                        await self.store.mark_address_complete(addr)

                        processed_count += 1
                        success_count += 1
                        progress.advance(task)

                        logger.info(
                            f"[{index}/{len(pending_addresses)}] ✅ 成功处理: {addr} "
                            f"(已处理: {processed_count}, 成功: {success_count}, 失败: {failed_count})"
                        )
                        return data

                    except Exception as e:
                        processed_count += 1
                        failed_count += 1
                        logger.error(
                            f"[{index}/{len(pending_addresses)}] ❌ 处理失败: {addr[:10]}... - {e} "
                            f"(已处理: {processed_count}, 成功: {success_count}, 失败: {failed_count})"
                        )
                        await self.store.update_processing_status(addr, 'failed', str(e))
                        progress.advance(task)
                        return None

                # 并发处理（为每个地址分配索引）
                tasks = [process_address(addr, idx + 1) for idx, addr in enumerate(pending_addresses)]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # 过滤失败结果
                successful_results = [r for r in results if r and not isinstance(r, Exception)]

            logger.info(f"步骤 3/5 完成: 共处理 {processed_count} 个地址，成功 {success_count} 个，失败 {failed_count} 个")

            self.renderer.console.print(f"✅ 成功获取 [bold]{len(successful_results)}[/bold] 个地址的数据\n")

            # API 统计
            stats = self.api_client.get_stats()
            logger.info(
                f"API 统计: 总请求 {stats['total_requests']} 次, "
                f"缓存命中 {stats['cache_hits']} 次 (命中率: {stats['cache_hit_rate']:.1%}), "
                f"API错误 {stats['api_errors']} 次"
            )
            self.renderer.console.print(
                f"[dim]API 统计: 请求 {stats['total_requests']} 次, "
                f"缓存命中 {stats['cache_hits']} 次 ({stats['cache_hit_rate']:.1%}), "
                f"错误 {stats['api_errors']} 次[/dim]\n"
            )

            # 5. 计算指标
            self.renderer.console.print(f"[bold cyan]步骤 4/5:[/bold cyan] 计算交易指标...")
            logger.info(f"步骤 4/5: 开始计算交易指标，共 {len(addresses)} 个地址")

            all_metrics = []
            calculated_count = 0
            qualified_count = 0
            skipped_no_fills = 0
            skipped_few_fills = 0
            skipped_filters = 0
            skipped_liquidation = 0

            for idx, addr in enumerate(addresses, 1):
                logger.info(f"[{idx}/{len(addresses)}] 计算指标: {addr}")

                # 检查最近1周是否有爆仓记录（优先检查，避免无效计算）
                has_recent_liq = await self.store.has_recent_liquidation(addr, days=7)
                if has_recent_liq:
                    skipped_liquidation += 1
                    logger.warning(f"[{idx}/{len(addresses)}] 地址 {addr[:10]}... 最近1周有爆仓记录，跳过分析")
                    continue

                # 从数据库读取交易记录
                fills = await self.store.get_fills(addr)
                if not fills:
                    skipped_no_fills += 1
                    logger.warning(f"[{idx}/{len(addresses)}] 地址无交易记录: {addr[:10]}... (跳过)")
                    continue

                if len(fills) < 10:
                    skipped_few_fills += 1
                    logger.warning(f"[{idx}/{len(addresses)}] 地址 {addr[:10]}... 历史订单仅 {len(fills)} 笔（<10），跳过分析")
                    continue

                # 获取账户状态（从数据库）
                state = await self.store.get_latest_user_state(addr)

                # 获取 Spot 账户状态（从数据库）
                spot_state = await self.store.get_latest_spot_state(addr)

                # 获取出入金统计
                transfer_stats = await self.store.get_net_deposits(addr)

                # 计算指标（传入新参数，包括 spot_state）
                metrics = self.metrics_engine.calculate_metrics(
                    address=addr,
                    fills=fills,
                    state=state,
                    transfer_data=transfer_stats,
                    spot_state=spot_state
                )

                # 保存到缓存
                await self.store.save_metrics(addr, {
                    'total_trades': metrics.total_trades,
                    'win_rate': metrics.win_rate,
                    'total_pnl': metrics.total_pnl,
                })

                calculated_count += 1

                # 筛选条件
                if metrics.total_pnl < 0:
                    skipped_filters += 1
                    logger.warning(f"[{idx}/{len(addresses)}] 地址 {addr[:10]}... 总PNL<0，跳过报告输出")
                    continue
                if metrics.win_rate < 60:
                    skipped_filters += 1
                    logger.warning(f"[{idx}/{len(addresses)}] 地址 {addr[:10]}... 胜率<60%，跳过报告输出")
                    continue

                qualified_count += 1
                all_metrics.append(metrics)
                logger.info(
                    f"[{idx}/{len(addresses)}] ✅ 地址符合条件: {addr[:10]}... "
                    f"(PNL: {metrics.total_pnl:.2f}, 胜率: {metrics.win_rate:.1f}%)"
                )

            logger.info(
                f"步骤 4/5 完成: 共计算 {calculated_count} 个地址，"
                f"符合条件 {qualified_count} 个，"
                f"最近爆仓跳过 {skipped_liquidation} 个，"
                f"无交易记录 {skipped_no_fills} 个，"
                f"订单不足10笔跳过 {skipped_few_fills} 个，"
                f"不符合筛选条件 {skipped_filters} 个"
            )
            self.renderer.console.print(f"✅ 计算完成 [bold]{len(all_metrics)}[/bold] 个地址的指标\n")

            # 6. 输出报告
            self.renderer.console.print("[bold cyan]步骤 5/5:[/bold cyan] 生成报告...\n")
            logger.info(f"步骤 5/5: 开始生成报告，共 {len(all_metrics)} 个符合条件的地址")

            if output_terminal:
                logger.info(f"生成终端报告: 显示前 {top_n} 个地址")
                if terminal_path:
                    logger.info(f"终端报告将保存到: {terminal_path}")
                self.renderer.render_terminal(all_metrics, top_n=top_n, save_path=terminal_path)

            if output_html and all_metrics:
                logger.info(f"生成HTML报告: {html_path}")
                self.renderer.render_html(all_metrics, output_path=html_path)
                logger.info(f"HTML报告已保存: {html_path}")

            logger.info(
                f"========== 分析完成 ==========\n"
                f"总地址数: {len(addresses)}\n"
                f"待处理地址: {len(pending_addresses)}\n"
                f"成功获取数据: {success_count}\n"
                f"获取失败: {failed_count}\n"
                f"最近爆仓跳过: {skipped_liquidation}\n"
                f"计算指标: {calculated_count}\n"
                f"符合筛选条件: {qualified_count}\n"
                f"最终报告地址数: {len(all_metrics)}\n"
                f"=============================="
            )
            self.renderer.console.print("\n[bold green]✨ 分析完成！[/bold green]\n")

            return all_metrics

        except Exception as e:
            logger.error(f"分析流程失败: {e}", exc_info=True)
            self.renderer.console.print(f"\n[bold red]❌ 错误: {e}[/bold red]\n")
            raise
