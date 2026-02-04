"""
工具函数模块 - 提供共享的工具函数
"""

import re
from typing import List, Dict, Callable, Any

# 标准以太坊地址格式：0x + 40个十六进制字符
ETH_ADDRESS_PATTERN = re.compile(r'^0x[a-fA-F0-9]{40}$', re.IGNORECASE)


def validate_eth_address(address: str) -> bool:
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
    return len(address) == 42 and bool(ETH_ADDRESS_PATTERN.match(address))


def deduplicate_records(
    records: List[Dict],
    key_extractor: Callable[[Dict], Any]
) -> List[Dict]:
    """
    通用去重函数

    根据 key_extractor 提取的键进行去重，结果按 time 字段排序

    Args:
        records: 原始记录列表
        key_extractor: 键提取函数，接收记录返回唯一键

    Returns:
        去重后的记录列表（按时间排序）
    """
    seen = set()
    unique = []

    for record in records:
        key = key_extractor(record)
        if key not in seen:
            seen.add(key)
            unique.append(record)

    # 按时间排序（确保数据顺序）
    unique.sort(key=lambda x: x.get('time', 0))

    return unique
