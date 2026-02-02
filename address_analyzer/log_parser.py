"""
日志解析器 - 从 trades.log 提取交易地址
"""

import re
from typing import Dict, Set
from pathlib import Path
from collections import Counter
import logging

logger = logging.getLogger(__name__)


class LogParser:
    """解析 trades.log 提取所有唯一交易地址"""

    # 正则表达式模式 - 严格匹配42字符的以太坊地址
    TAKER_PATTERN = r'🔸.*\n\s+(0x[a-fA-F0-9]{40})'
    MAKER_PATTERN = r'🔹.*\n\s+(0x[a-fA-F0-9]{40})'

    # 地址验证模式
    ETH_ADDRESS_PATTERN = re.compile(r'^0x[a-fA-F0-9]{40}$', re.IGNORECASE)

    def __init__(self, log_path: str | Path):
        """
        初始化日志解析器

        Args:
            log_path: trades.log 文件路径
        """
        self.log_path = Path(log_path)
        if not self.log_path.exists():
            raise FileNotFoundError(f"日志文件不存在: {self.log_path}")

    def _validate_address(self, address: str) -> bool:
        """
        验证以太坊地址格式

        Args:
            address: 地址字符串

        Returns:
            是否有效
        """
        if not address or not isinstance(address, str):
            return False
        # 必须是 42 字符且匹配十六进制模式
        return len(address) == 42 and bool(self.ETH_ADDRESS_PATTERN.match(address))

    def parse(self) -> Dict[str, Dict]:
        """
        解析日志文件，提取所有地址及统计信息

        Returns:
            {
                '0x...': {
                    'address': '0x...',
                    'taker_count': 10,
                    'maker_count': 5,
                    'total_count': 15
                }
            }
        """
        logger.info(f"开始解析日志: {self.log_path}")

        # 读取日志内容
        with open(self.log_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 提取 Taker 地址
        taker_addresses = re.findall(self.TAKER_PATTERN, content, re.MULTILINE)
        # 严格验证：只保留符合以太坊地址格式的地址
        taker_addresses = [addr for addr in taker_addresses if self._validate_address(addr)]
        taker_counter = Counter(taker_addresses)
        logger.info(f"提取到 {len(taker_addresses)} 个 Taker 交易，{len(taker_counter)} 个唯一地址")

        # 提取 Maker 地址
        maker_addresses = re.findall(self.MAKER_PATTERN, content, re.MULTILINE)
        # 严格验证：只保留符合以太坊地址格式的地址
        maker_addresses = [addr for addr in maker_addresses if self._validate_address(addr)]
        maker_counter = Counter(maker_addresses)
        logger.info(f"提取到 {len(maker_addresses)} 个 Maker 交易，{len(maker_counter)} 个唯一地址")

        # 合并统计
        all_addresses: Set[str] = set(taker_counter.keys()) | set(maker_counter.keys())
        address_stats = {}

        for addr in all_addresses:
            # 标准化地址格式（小写）
            normalized_addr = addr.lower()
            taker_count = taker_counter.get(addr, 0)
            maker_count = maker_counter.get(addr, 0)

            address_stats[normalized_addr] = {
                'address': normalized_addr,
                'taker_count': taker_count,
                'maker_count': maker_count,
                'total_count': taker_count + maker_count
            }

        logger.info(f"总计提取到 {len(address_stats)} 个唯一地址")
        return address_stats

    def get_address_list(self) -> list[str]:
        """
        获取地址列表（仅地址字符串）

        Returns:
            地址列表
        """
        stats = self.parse()
        return list(stats.keys())

    def get_summary(self) -> Dict:
        """
        获取解析摘要统计

        Returns:
            {
                'total_addresses': 395,
                'total_taker_trades': 1000,
                'total_maker_trades': 500,
                'top_taker_addresses': [...],
                'top_maker_addresses': [...]
            }
        """
        stats = self.parse()

        total_taker = sum(s['taker_count'] for s in stats.values())
        total_maker = sum(s['maker_count'] for s in stats.values())

        # 排序找出最活跃地址
        sorted_by_taker = sorted(
            stats.values(),
            key=lambda x: x['taker_count'],
            reverse=True
        )
        sorted_by_maker = sorted(
            stats.values(),
            key=lambda x: x['maker_count'],
            reverse=True
        )

        return {
            'total_addresses': len(stats),
            'total_taker_trades': total_taker,
            'total_maker_trades': total_maker,
            'top_taker_addresses': [
                {'address': s['address'], 'count': s['taker_count']}
                for s in sorted_by_taker[:10]
            ],
            'top_maker_addresses': [
                {'address': s['address'], 'count': s['maker_count']}
                for s in sorted_by_maker[:10]
            ]
        }


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(level=logging.INFO)

    parser = LogParser('trades.log')
    summary = parser.get_summary()

    print(f"\n{'='*60}")
    print(f"日志解析摘要")
    print(f"{'='*60}")
    print(f"总地址数: {summary['total_addresses']}")
    print(f"总 Taker 交易: {summary['total_taker_trades']}")
    print(f"总 Maker 交易: {summary['total_maker_trades']}")
    print(f"\n前10个最活跃 Taker 地址:")
    for i, addr_info in enumerate(summary['top_taker_addresses'], 1):
        print(f"  {i}. {addr_info['address'][:10]}...{addr_info['address'][-8:]}: {addr_info['count']} 笔")
    print(f"\n前10个最活跃 Maker 地址:")
    for i, addr_info in enumerate(summary['top_maker_addresses'], 1):
        print(f"  {i}. {addr_info['address'][:10]}...{addr_info['address'][-8:]}: {addr_info['count']} 笔")
