"""
输出渲染器 - 生成终端表格和HTML报告
"""

import logging
from typing import List, Optional
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from jinja2 import Template

from .metrics_engine import AddressMetrics

logger = logging.getLogger(__name__)


class OutputRenderer:
    """输出渲染器 - 终端表格和HTML报告"""

    def __init__(self):
        """初始化渲染器"""
        self.console = Console()

    def render_terminal(
        self,
        metrics_list: List[AddressMetrics],
        top_n: int = 50,
        save_path: Optional[str] = None
    ):
        """
        渲染终端表格输出

        Args:
            metrics_list: 指标列表
            top_n: 显示前N个地址
            save_path: 保存路径（可选）
        """
        # 按总PNL排序
        sorted_metrics = sorted(
            metrics_list,
            key=lambda x: x.total_pnl,
            reverse=True
        )[:top_n]

        # 创建标题
        title = Panel(
            Text("🔍 Hyperliquid 交易地址分析报告", justify="center", style="bold cyan"),
            border_style="cyan"
        )
        self.console.print(title)

        # 汇总统计
        self._render_summary(metrics_list)

        # 详细表格
        self._render_table(sorted_metrics)

        # 保存到文件
        if save_path:
            with open(save_path, 'w', encoding='utf-8') as f:
                # 使用 Console 的 export_text 方法
                console_file = Console(file=f, width=120)
                console_file.print(title)
                self._render_summary(metrics_list, console=console_file)
                self._render_table(sorted_metrics, console=console_file)
            logger.info(f"终端报告已保存: {save_path}")

    def _render_summary(
        self,
        metrics_list: List[AddressMetrics],
        console: Optional[Console] = None
    ):
        """渲染汇总统计"""
        if console is None:
            console = self.console

        total_addresses = len(metrics_list)

        # 处理空列表情况
        if total_addresses == 0:
            summary_text = """
[bold yellow]⚠️  暂无可用的交易数据[/bold yellow]

请检查：
1. 地址是否有历史交易记录
2. API是否正常返回数据
3. 数据库连接是否正常
            """
            panel = Panel(
                summary_text.strip(),
                title="📊 汇总统计",
                border_style="yellow"
            )
            console.print(panel)
            console.print()
            return

        profitable = sum(1 for m in metrics_list if m.total_pnl > 0)
        unprofitable = total_addresses - profitable

        total_pnl = sum(m.total_pnl for m in metrics_list)
        avg_win_rate = sum(m.win_rate for m in metrics_list) / total_addresses
        avg_sharpe = sum(m.sharpe_ratio for m in metrics_list) / total_addresses

        # 创建汇总面板
        summary_text = f"""
[bold]总地址数:[/bold] {total_addresses}
[bold green]盈利地址:[/bold green] {profitable} ({profitable/total_addresses*100:.1f}%)
[bold red]亏损地址:[/bold red] {unprofitable} ({unprofitable/total_addresses*100:.1f}%)
[bold]总PNL:[/bold] ${total_pnl:,.2f}
[bold]平均胜率:[/bold] {avg_win_rate:.1f}%
[bold]平均夏普比率:[/bold] {avg_sharpe:.2f}
        """

        panel = Panel(
            summary_text.strip(),
            title="📊 汇总统计",
            border_style="green"
        )
        console.print(panel)
        console.print()

    def _render_table(
        self,
        metrics_list: List[AddressMetrics],
        console: Optional[Console] = None
    ):
        """渲染详细表格"""
        if console is None:
            console = self.console

        # 创建表格
        table = Table(
            title="📈 交易地址详细数据",
            show_header=True,
            header_style="bold magenta",
            border_style="blue"
        )

        # 添加列
        table.add_column("#", style="dim", width=4)
        table.add_column("地址", style="cyan", width=16)
        table.add_column("交易数", justify="right", width=8)
        table.add_column("胜率", justify="right", width=8)
        table.add_column("ROI", justify="right", width=10)
        table.add_column("夏普", justify="right", width=8)
        table.add_column("总PNL", justify="right", width=12)
        table.add_column("账户价值", justify="right", width=12)
        table.add_column("最大回撤", justify="right", width=10)

        # 添加行
        for i, metrics in enumerate(metrics_list, 1):
            # 颜色编码
            pnl_color = "green" if metrics.total_pnl > 0 else "red"
            roi_color = "green" if metrics.roi > 0 else "red"

            # 地址缩写
            addr_short = f"{metrics.address[:6]}...{metrics.address[-4:]}"

            table.add_row(
                str(i),
                addr_short,
                str(metrics.total_trades),
                f"{metrics.win_rate:.1f}%",
                f"[{roi_color}]{metrics.roi:+.1f}%[/{roi_color}]",
                f"{metrics.sharpe_ratio:.2f}",
                f"[{pnl_color}]${metrics.total_pnl:,.0f}[/{pnl_color}]",
                f"${metrics.account_value:,.0f}",
                f"{metrics.max_drawdown:.1f}%"
            )

        console.print(table)

    def render_html(
        self,
        metrics_list: List[AddressMetrics],
        output_path: str = "output/analysis_report.html"
    ):
        """
        渲染HTML报告

        Args:
            metrics_list: 指标列表
            output_path: 输出路径
        """
        # 按总PNL排序
        sorted_metrics = sorted(
            metrics_list,
            key=lambda x: x.total_pnl,
            reverse=True
        )

        # 准备数据
        profitable = sum(1 for m in metrics_list if m.total_pnl > 0)
        unprofitable = len(metrics_list) - profitable
        total_pnl = sum(m.total_pnl for m in metrics_list)
        avg_win_rate = sum(m.win_rate for m in metrics_list) / len(metrics_list) if metrics_list else 0
        avg_sharpe = sum(m.sharpe_ratio for m in metrics_list) / len(metrics_list) if metrics_list else 0

        # HTML模板
        template_str = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hyperliquid 交易地址分析报告</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0f1419;
            color: #e0e0e0;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 {
            text-align: center;
            color: #00d4ff;
            margin-bottom: 30px;
            font-size: 2.5em;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: #1a1f2e;
            padding: 20px;
            border-radius: 10px;
            border: 1px solid #2a3f5f;
        }
        .stat-label { color: #8899a6; font-size: 0.9em; margin-bottom: 5px; }
        .stat-value { font-size: 2em; font-weight: bold; color: #00d4ff; }
        .stat-value.green { color: #00ff88; }
        .stat-value.red { color: #ff4444; }
        .charts-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .chart-container {
            background: #1a1f2e;
            padding: 20px;
            border-radius: 10px;
            border: 1px solid #2a3f5f;
        }
        table {
            width: 100%;
            background: #1a1f2e;
            border-collapse: collapse;
            border-radius: 10px;
            overflow: hidden;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #2a3f5f;
        }
        th {
            background: #252d3f;
            color: #00d4ff;
            font-weight: bold;
        }
        tr:hover { background: #252d3f; }
        .positive { color: #00ff88; }
        .negative { color: #ff4444; }
        .address { font-family: monospace; }
        .footer {
            text-align: center;
            margin-top: 30px;
            color: #8899a6;
            font-size: 0.9em;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 Hyperliquid 交易地址分析报告</h1>

        <!-- 汇总统计 -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">总地址数</div>
                <div class="stat-value">{{ total_addresses }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">盈利地址</div>
                <div class="stat-value green">{{ profitable }} ({{ (profitable/total_addresses*100)|round(1) }}%)</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">亏损地址</div>
                <div class="stat-value red">{{ unprofitable }} ({{ (unprofitable/total_addresses*100)|round(1) }}%)</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">总PNL</div>
                <div class="stat-value {% if total_pnl > 0 %}green{% else %}red{% endif %}">
                    ${{ "{:,.0f}".format(total_pnl) }}
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-label">平均胜率</div>
                <div class="stat-value">{{ avg_win_rate|round(1) }}%</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">平均夏普比率</div>
                <div class="stat-value">{{ avg_sharpe|round(2) }}</div>
            </div>
        </div>

        <!-- 图表 -->
        <div class="charts-grid">
            <div class="chart-container">
                <canvas id="winRateChart"></canvas>
            </div>
            <div class="chart-container">
                <canvas id="pnlChart"></canvas>
            </div>
        </div>

        <!-- 详细表格 -->
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>地址</th>
                    <th>交易数</th>
                    <th>胜率</th>
                    <th>ROI</th>
                    <th>夏普比率</th>
                    <th>总PNL</th>
                    <th>账户价值</th>
                    <th>最大回撤</th>
                </tr>
            </thead>
            <tbody>
                {% for m in metrics %}
                <tr>
                    <td>{{ loop.index }}</td>
                    <td class="address">{{ m.address[:10] }}...{{ m.address[-8:] }}</td>
                    <td>{{ m.total_trades }}</td>
                    <td>{{ m.win_rate|round(1) }}%</td>
                    <td class="{% if m.roi > 0 %}positive{% else %}negative{% endif %}">
                        {{ m.roi|round(1) }}%
                    </td>
                    <td>{{ m.sharpe_ratio|round(2) }}</td>
                    <td class="{% if m.total_pnl > 0 %}positive{% else %}negative{% endif %}">
                        ${{ "{:,.0f}".format(m.total_pnl) }}
                    </td>
                    <td>${{ "{:,.0f}".format(m.account_value) }}</td>
                    <td>{{ m.max_drawdown|round(1) }}%</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>

        <div class="footer">
            生成时间: {{ timestamp }}<br>
            数据来源: Hyperliquid API
        </div>
    </div>

    <script>
        // 胜率分布直方图
        const winRateData = {{ win_rates|tojson }};
        new Chart(document.getElementById('winRateChart'), {
            type: 'bar',
            data: {
                labels: ['0-20%', '20-40%', '40-60%', '60-80%', '80-100%'],
                datasets: [{
                    label: '地址数量',
                    data: [
                        winRateData.filter(x => x < 20).length,
                        winRateData.filter(x => x >= 20 && x < 40).length,
                        winRateData.filter(x => x >= 40 && x < 60).length,
                        winRateData.filter(x => x >= 60 && x < 80).length,
                        winRateData.filter(x => x >= 80).length,
                    ],
                    backgroundColor: '#00d4ff',
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    title: { display: true, text: '胜率分布', color: '#e0e0e0' },
                    legend: { labels: { color: '#e0e0e0' } }
                },
                scales: {
                    x: { ticks: { color: '#e0e0e0' } },
                    y: { ticks: { color: '#e0e0e0' } }
                }
            }
        });

        // PNL分布图
        const pnlData = {{ pnls|tojson }};
        new Chart(document.getElementById('pnlChart'), {
            type: 'scatter',
            data: {
                datasets: [{
                    label: 'PNL 分布',
                    data: pnlData.map((pnl, i) => ({x: i, y: pnl})),
                    backgroundColor: pnlData.map(pnl => pnl > 0 ? '#00ff88' : '#ff4444'),
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    title: { display: true, text: 'PNL 分布', color: '#e0e0e0' },
                    legend: { labels: { color: '#e0e0e0' } }
                },
                scales: {
                    x: { ticks: { color: '#e0e0e0' }, title: { display: true, text: '地址索引', color: '#e0e0e0' } },
                    y: { ticks: { color: '#e0e0e0' }, title: { display: true, text: 'PNL (USD)', color: '#e0e0e0' } }
                }
            }
        });
    </script>
</body>
</html>
        """

        # 准备图表数据
        win_rates = [m.win_rate for m in sorted_metrics]
        pnls = [m.total_pnl for m in sorted_metrics]

        # 渲染模板
        template = Template(template_str)
        html_content = template.render(
            total_addresses=len(metrics_list),
            profitable=profitable,
            unprofitable=unprofitable,
            total_pnl=total_pnl,
            avg_win_rate=avg_win_rate,
            avg_sharpe=avg_sharpe,
            metrics=sorted_metrics,
            win_rates=win_rates,
            pnls=pnls,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )

        # 保存文件
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(html_content, encoding='utf-8')

        logger.info(f"HTML报告已生成: {output_path}")
        self.console.print(f"\n✅ HTML报告已生成: [cyan]{output_path}[/cyan]")


def test_renderer():
    """测试渲染器"""
    # 模拟数据
    test_metrics = [
        AddressMetrics(
            address=f"0xtest{i:040x}",
            total_trades=100 + i * 10,
            win_rate=50 + i * 2,
            roi=10 + i * 5,
            sharpe_ratio=1.5 + i * 0.1,
            total_pnl=1000 + i * 500,
            account_value=10000 + i * 1000,
            max_drawdown=20 - i,
            avg_trade_size=5000,
            total_volume=500000 + i * 10000,
            net_deposit=10000,
            first_trade_time=1704067200000,
            last_trade_time=1704326400000,
            active_days=30 + i
        )
        for i in range(10)
    ]

    renderer = OutputRenderer()

    # 渲染终端输出
    renderer.render_terminal(test_metrics, top_n=10)

    # 渲染HTML报告
    renderer.render_html(test_metrics, "output/test_report.html")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    test_renderer()
