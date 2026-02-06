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
        # 按胜率降序排序
        sorted_metrics = sorted(
            metrics_list,
            key=lambda x: x.win_rate,
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

        # 简化的汇总信息
        summary_text = f"""
[bold]总地址数:[/bold] {total_addresses}
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
        table.add_column("地址", style="cyan", width=44, no_wrap=False)
        table.add_column("交易数", justify="right", width=8)
        table.add_column("胜率", justify="right", width=8)
        table.add_column("总PNL", justify="right", width=12)

        # 添加行
        for i, metrics in enumerate(metrics_list, 1):
            # 颜色编码
            pnl_color = "green" if metrics.total_pnl > 0 else "red"

            table.add_row(
                str(i),
                metrics.address,
                str(metrics.total_trades),
                f"{metrics.win_rate:.1f}%",
                f"[{pnl_color}]${metrics.total_pnl:,.0f}[/{pnl_color}]"
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
        # 按胜率降序排序
        sorted_metrics = sorted(
            metrics_list,
            key=lambda x: x.win_rate,
            reverse=True
        )

        # HTML模板
        template_str = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hyperliquid 交易地址分析报告</title>
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
        .address {
            font-family: monospace;
            word-break: break-all;
            max-width: 400px;
        }
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

        <!-- 详细表格 -->
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>地址</th>
                    <th>交易数</th>
                    <th>胜率</th>
                    <th>总PNL</th>
                </tr>
            </thead>
            <tbody>
                {% for m in metrics %}
                <tr>
                    <td>{{ loop.index }}</td>
                    <td class="address">{{ m.address }}</td>
                    <td>{{ m.total_trades }}</td>
                    <td>{{ m.win_rate|round(1) }}%</td>
                    <td class="{% if m.total_pnl > 0 %}positive{% else %}negative{% endif %}">
                        ${{ "{:,.0f}".format(m.total_pnl) }}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>

        <div class="footer">
            生成时间: {{ timestamp }}<br>
            数据来源: Hyperliquid API
        </div>
    </div>
</body>
</html>
        """

        # 渲染模板
        template = Template(template_str)
        html_content = template.render(
            metrics=sorted_metrics,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )

        # 保存文件
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(html_content, encoding='utf-8')

        logger.info(f"HTML报告已生成: {output_path}")
        self.console.print(f"\n✅ HTML报告已生成: [cyan]{output_path}[/cyan]")
