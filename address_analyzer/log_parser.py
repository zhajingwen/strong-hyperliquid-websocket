"""
日志解析器 - 从 trades.log 提取交易地址
"""

import re
from typing import Dict, Set
from pathlib import Path
from collections import Counter
import logging

from .utils import validate_eth_address

logger = logging.getLogger(__name__)


class LogParser:
    """解析 trades.log 提取所有唯一交易地址"""

    # 正则表达式模式 - 严格匹配42字符的以太坊地址
    TAKER_PATTERN = r'🔸.*\n\s+(0x[a-fA-F0-9]{40})'
    MAKER_PATTERN = r'🔹.*\n\s+(0x[a-fA-F0-9]{40})'

    def __init__(self, log_path: str | Path):
        """
        初始化日志解析器

        Args:
            log_path: trades.log 文件路径
        """
        self.log_path = Path(log_path)
        if not self.log_path.exists():
            raise FileNotFoundError(f"日志文件不存在: {self.log_path}")

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
        taker_addresses = [addr for addr in taker_addresses if validate_eth_address(addr)]
        taker_counter = Counter(taker_addresses)
        logger.info(f"提取到 {len(taker_addresses)} 个 Taker 交易，{len(taker_counter)} 个唯一地址")

        # 提取 Maker 地址
        maker_addresses = re.findall(self.MAKER_PATTERN, content, re.MULTILINE)
        # 严格验证：只保留符合以太坊地址格式的地址
        maker_addresses = [addr for addr in maker_addresses if validate_eth_address(addr)]
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

