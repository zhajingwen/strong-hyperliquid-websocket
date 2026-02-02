#!/usr/bin/env python3
"""
Hyperliquid 交易地址分析工具 CLI 入口

用法:
    python analyze_addresses.py
    python analyze_addresses.py --force-refresh
    python analyze_addresses.py --output html --html-path report.html
"""

import asyncio
import logging
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from address_analyzer.orchestrator import Orchestrator


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Hyperliquid 交易地址分析工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基础用法（完整分析）
  python analyze_addresses.py

  # 强制刷新缓存
  python analyze_addresses.py --force-refresh

  # 仅输出HTML报告
  python analyze_addresses.py --output html

  # 自定义HTML路径
  python analyze_addresses.py --html-path output/my_report.html

  # 调整并发和速率限制
  python analyze_addresses.py --concurrent 20 --rate-limit 100

  # 保存终端输出到文件
  python analyze_addresses.py --terminal-path output/terminal.txt

  # 调试模式
  python analyze_addresses.py --verbose
        """
    )

    parser.add_argument(
        '--log-path',
        default='trades.log',
        help='trades.log 文件路径（默认: trades.log）'
    )
    parser.add_argument(
        '--force-refresh',
        action='store_true',
        help='强制刷新所有数据（忽略缓存）'
    )
    parser.add_argument(
        '--output',
        choices=['terminal', 'html', 'both'],
        default='both',
        help='输出格式（默认: both）'
    )
    parser.add_argument(
        '--html-path',
        default='output/analysis_report.html',
        help='HTML报告保存路径（默认: output/analysis_report.html）'
    )
    parser.add_argument(
        '--terminal-path',
        help='终端输出保存路径（可选）'
    )
    parser.add_argument(
        '--top-n',
        type=int,
        default=50,
        help='终端显示前N个地址（默认: 50）'
    )
    parser.add_argument(
        '--concurrent',
        type=int,
        default=10,
        help='最大并发请求数（默认: 10）'
    )
    parser.add_argument(
        '--rate-limit',
        type=float,  # 改为float以支持小数
        default=50.0,
        help='API速率限制（请求/秒，默认: 50）'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='详细日志输出'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='调试模式（超详细日志）'
    )

    args = parser.parse_args()

    # 配置日志
    log_level = logging.DEBUG if args.debug else (logging.INFO if args.verbose else logging.WARNING)
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    # 检查日志文件是否存在
    if not Path(args.log_path).exists():
        print(f"❌ 错误: 日志文件不存在: {args.log_path}")
        sys.exit(1)

    # 初始化控制器
    orchestrator = Orchestrator(
        log_path=args.log_path,
        force_refresh=args.force_refresh,
        max_concurrent=args.concurrent,
        rate_limit=args.rate_limit
    )

    try:
        # 初始化
        await orchestrator.initialize()

        # 运行分析
        await orchestrator.run(
            output_terminal=args.output in ('terminal', 'both'),
            output_html=args.output in ('html', 'both'),
            html_path=args.html_path,
            terminal_path=args.terminal_path,
            top_n=args.top_n
        )

        # 返回成功
        return 0

    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断操作")
        return 130

    except Exception as e:
        logging.error(f"程序异常: {e}", exc_info=True)
        return 1

    finally:
        await orchestrator.cleanup()


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
