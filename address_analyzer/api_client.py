"""
Hyperliquid API 客户端 - 封装 API 调用，处理并发、限流、缓存
"""

import asyncio
import logging
import re
from typing import Optional, List, Dict, Any
import aiohttp
from aiolimiter import AsyncLimiter
from hyperliquid.info import Info

from .data_store import DataStore

logger = logging.getLogger(__name__)

# 标准以太坊地址格式：0x + 40个十六进制字符
ETH_ADDRESS_PATTERN = re.compile(r'^0x[a-fA-F0-9]{40}$', re.IGNORECASE)


class HyperliquidAPIClient:
    """Hyperliquid API 客户端，支持并发、限流、缓存"""

    BASE_URL = "https://api.hyperliquid.xyz"

    def __init__(
        self,
        store: DataStore,
        max_concurrent: int = 10,
        rate_limit: float = 50.0,  # 请求/秒（支持小数）
        cache_ttl_hours: int = 1
    ):
        """
        初始化 API 客户端

        Args:
            store: 数据存储实例
            max_concurrent: 最大并发请求数
            rate_limit: 速率限制（请求/秒，支持小数如0.1）
            cache_ttl_hours: 缓存过期时间（小时）
        """
        self.store = store
        self.info = Info(skip_ws=True)  # Hyperliquid SDK Info 客户端

        # 并发控制
        self.semaphore = asyncio.Semaphore(max_concurrent)

        # 速率限制（令牌桶算法）
        # AsyncLimiter(max_rate, time_period) = 在time_period秒内最多max_rate个请求
        if rate_limit >= 1:
            # 例如: rate_limit=10 -> AsyncLimiter(10, 1) = 每秒10个请求
            self.rate_limiter = AsyncLimiter(rate_limit, 1)
        else:
            # 例如: rate_limit=0.1 -> AsyncLimiter(1, 10) = 每10秒1个请求
            self.rate_limiter = AsyncLimiter(1, 1 / rate_limit)

        # 缓存配置
        self.cache_ttl_hours = cache_ttl_hours

        # 统计信息
        self.stats = {
            'total_requests': 0,
            'cache_hits': 0,
            'api_errors': 0
        }

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        retry_count: int = 3
    ) -> Optional[Dict]:
        """
        内部方法：发送 HTTP 请求（带重试）

        Args:
            method: HTTP 方法
            endpoint: API 端点
            params: 请求参数
            retry_count: 重试次数

        Returns:
            响应数据或None
        """
        url = f"{self.BASE_URL}/{endpoint}"

        for attempt in range(retry_count):
            try:
                # 速率限制
                async with self.rate_limiter:
                    # 并发控制
                    async with self.semaphore:
                        async with aiohttp.ClientSession() as session:
                            async with session.request(method, url, json=params) as resp:
                                resp.raise_for_status()
                                data = await resp.json()
                                self.stats['total_requests'] += 1
                                return data

            except aiohttp.ClientError as e:
                self.stats['api_errors'] += 1
                logger.warning(f"API 请求失败 (尝试 {attempt + 1}/{retry_count}): {e}")

                if attempt < retry_count - 1:
                    # 指数退避
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"API 请求最终失败: {url}")
                    return None

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
        return bool(ETH_ADDRESS_PATTERN.match(address))

    async def get_user_fills(
        self,
        address: str,
        use_cache: bool = True
    ) -> List[Dict]:
        """
        获取用户完整交易历史（支持分页）

        注意：user_fills() 有限制（通常2000条），需要分页获取全部历史

        Args:
            address: 用户地址
            use_cache: 是否使用缓存

        Returns:
            交易记录列表
        """
        # 验证地址格式
        if not self._validate_address(address):
            logger.error(f"无效的地址格式: {address}")
            return []

        cache_key = f"user_fills:{address}"

        # 检查缓存
        if use_cache:
            cached = await self.store.get_api_cache(cache_key)
            if cached:
                self.stats['cache_hits'] += 1
                logger.debug(f"缓存命中: {cache_key}")
                return cached

        # 获取完整交易历史（分页）
        # 修复说明：user_fills_by_time 返回的是 [start_time, end_time] 区间内最旧的 2000 条
        # 因此需要逐步增大 start_time 来获取完整数据，而不是减小 end_time
        try:
            all_fills = []
            page_size = 2000  # API单次返回限制

            # 第一次调用获取最新记录 - 应用速率限制
            async with self.rate_limiter:
                async with self.semaphore:
                    fills = self.info.user_fills(address)

            if not fills:
                logger.info(f"地址无交易记录: {address[:10]}...")
                return []

            latest_fills = fills
            all_fills.extend(latest_fills)
            latest_count = len(latest_fills)

            logger.info(f"获取交易记录第1页（最新）: {address[:10]}... ({latest_count} 条)")

            # 如果返回的记录数达到限制，说明可能还有更多历史记录
            if latest_count >= page_size:
                # 获取最新批次的最早时间，作为向前分页的目标
                latest_min_time = min(fill.get('time', 0) for fill in latest_fills)
                target_end_time = latest_min_time - 1  # 到最新批次的前一毫秒

                # 从 start_time=0 开始，逐步向新推进，直到接近 target_end_time
                current_start_time = 0
                page_num = 2
                historical_fills = []  # 存储历史数据

                while current_start_time <= target_end_time:
                    # 获取更早的记录 - 应用速率限制
                    async with self.rate_limiter:
                        async with self.semaphore:
                            older_fills = self.info.user_fills_by_time(
                                address,
                                start_time=current_start_time,
                                end_time=target_end_time
                            )

                    if not older_fills:
                        logger.info(f"第{page_num}页: 无更多历史数据")
                        break

                    # 这批数据的时间范围
                    batch_max_time = max(fill.get('time', 0) for fill in older_fills)

                    historical_fills.extend(older_fills)
                    logger.info(f"获取交易记录第{page_num}页（历史）: {address[:10]}... (+{len(older_fills)} 条)")

                    # 如果这批数据少于 2000，说明已经获取完了
                    if len(older_fills) < page_size:
                        logger.info(f"第{page_num}页: 已获取完整区间数据（< {page_size} 条）")
                        break

                    # 更新 start_time 为这批数据的最新时间+1，继续向新推进
                    current_start_time = batch_max_time + 1

                    # 检查是否已经接近目标时间
                    if current_start_time > target_end_time:
                        logger.info(f"第{page_num}页: 已到达目标时间")
                        break

                    page_num += 1

                    # 避免无限循环（最多获取100页）
                    if page_num > 100:
                        logger.warning(f"达到最大分页限制(100页): {address[:10]}...")
                        break

                # 合并数据：历史数据（旧→新）+ 最新数据
                all_fills = historical_fills + latest_fills
                logger.info(f"合并数据: 历史 {len(historical_fills)} 条 + 最新 {latest_count} 条")

            logger.info(f"获取完整交易记录: {address[:10]}... (总计 {len(all_fills)} 条)")

            # 更新缓存
            if use_cache and all_fills:
                await self.store.set_api_cache(cache_key, all_fills, self.cache_ttl_hours)

            return all_fills

        except Exception as e:
            logger.error(f"获取 user_fills 失败: {address[:10]}... - {e}")
            return []

    async def get_user_state(
        self,
        address: str,
        use_cache: bool = True
    ) -> Optional[Dict]:
        """
        获取账户状态（user_state API）

        Args:
            address: 用户地址
            use_cache: 是否使用缓存

        Returns:
            账户状态数据
        """
        # 验证地址格式
        if not self._validate_address(address):
            logger.error(f"无效的地址格式: {address}")
            return None

        cache_key = f"user_state:{address}"

        # 检查缓存
        if use_cache:
            cached = await self.store.get_api_cache(cache_key)
            if cached:
                self.stats['cache_hits'] += 1
                logger.debug(f"缓存命中: {cache_key}")
                return cached

        # 使用 Hyperliquid SDK - 应用速率限制
        try:
            async with self.rate_limiter:
                async with self.semaphore:
                    state = self.info.user_state(address)
            logger.info(f"获取账户状态: {address[:10]}...")

            # 更新缓存
            if use_cache and state:
                await self.store.set_api_cache(cache_key, state, self.cache_ttl_hours)

            return state

        except Exception as e:
            logger.error(f"获取 user_state 失败: {address[:10]}... - {e}")
            return None

    async def get_user_fills_by_time(
        self,
        address: str,
        start_time: int,
        end_time: Optional[int] = None
    ) -> List[Dict]:
        """
        获取指定时间段的交易记录（分页查询）

        Args:
            address: 用户地址
            start_time: 开始时间（毫秒时间戳）
            end_time: 结束时间（毫秒时间戳，可选）

        Returns:
            交易记录列表
        """
        try:
            # Hyperliquid SDK 的 user_fills_by_time 方法 - 应用速率限制
            async with self.rate_limiter:
                async with self.semaphore:
                    fills = self.info.user_fills_by_time(address, start_time, end_time)
            logger.info(f"获取时间段交易: {address[:10]}... ({len(fills)} 条)")
            return fills

        except Exception as e:
            logger.error(f"获取 user_fills_by_time 失败: {address[:10]}... - {e}")
            return []

    async def get_user_funding(self, address: str) -> List[Dict]:
        """
        获取用户资金费率历史

        Args:
            address: 用户地址

        Returns:
            资金费率记录
        """
        # 验证地址格式
        if not self._validate_address(address):
            logger.error(f"无效的地址格式: {address}")
            return []

        try:
            # 检查方法是否存在
            if hasattr(self.info, 'user_funding'):
                # 应用速率限制
                async with self.rate_limiter:
                    async with self.semaphore:
                        funding = self.info.user_funding(address)
                logger.info(f"获取资金费率: {address[:10]}... ({len(funding)} 条)")
                return funding
            else:
                logger.debug(f"user_funding 方法不可用，跳过")
                return []

        except Exception as e:
            logger.warning(f"获取 user_funding 失败: {address[:10]}... - {e}")
            return []

    async def fetch_address_data(
        self,
        address: str,
        save_to_db: bool = True
    ) -> Dict[str, Any]:
        """
        获取地址的完整数据（交易历史 + 账户状态）

        Args:
            address: 用户地址
            save_to_db: 是否保存到数据库

        Returns:
            {
                'fills': [...],
                'state': {...},
                'funding': [...]
            }
        """
        logger.info(f"开始获取地址数据: {address}")

        # 并发获取多个 API
        fills_task = self.get_user_fills(address)
        state_task = self.get_user_state(address)
        funding_task = self.get_user_funding(address)

        fills, state, funding = await asyncio.gather(
            fills_task,
            state_task,
            funding_task,
            return_exceptions=True
        )

        # 处理异常
        if isinstance(fills, Exception):
            logger.error(f"获取 fills 异常: {fills}")
            fills = []

        if isinstance(state, Exception):
            logger.error(f"获取 state 异常: {state}")
            state = None

        if isinstance(funding, Exception):
            logger.error(f"获取 funding 异常: {funding}")
            funding = []

        # 保存到数据库
        if save_to_db and fills:
            await self.store.save_fills(address, fills)

        return {
            'address': address,
            'fills': fills,
            'state': state,
            'funding': funding
        }

    async def batch_fetch_addresses(
        self,
        addresses: List[str],
        progress_callback: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """
        批量获取多个地址的数据

        Args:
            addresses: 地址列表
            progress_callback: 进度回调函数

        Returns:
            数据列表
        """
        tasks = []
        for i, addr in enumerate(addresses):
            task = self.fetch_address_data(addr)
            tasks.append(task)

        results = []
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            result = await coro
            results.append(result)

            # 进度回调
            if progress_callback:
                progress_callback(i + 1, len(addresses))

        return results

    def get_stats(self) -> Dict:
        """
        获取统计信息

        Returns:
            {
                'total_requests': 100,
                'cache_hits': 50,
                'cache_hit_rate': 0.5,
                'api_errors': 2
            }
        """
        total = self.stats['total_requests']
        hits = self.stats['cache_hits']

        return {
            'total_requests': total,
            'cache_hits': hits,
            'cache_hit_rate': hits / total if total > 0 else 0,
            'api_errors': self.stats['api_errors']
        }


async def test_api_client():
    """测试 API 客户端"""
    from .data_store import get_store

    # 初始化数据存储
    store = get_store()
    await store.connect()

    # 创建 API 客户端
    client = HyperliquidAPIClient(store)

    # 测试地址（从日志中提取的最活跃地址）
    test_address = "0xc1914d36a60e299ba004bac2c9edcb973c988ef37"

    # 获取数据
    data = await client.fetch_address_data(test_address)

    print(f"\n{'='*60}")
    print(f"API 客户端测试结果")
    print(f"{'='*60}")
    print(f"地址: {data['address']}")
    print(f"交易记录: {len(data['fills'])} 条")
    print(f"账户状态: {'✓' if data['state'] else '✗'}")
    print(f"资金费率: {len(data['funding'])} 条")

    # 统计信息
    stats = client.get_stats()
    print(f"\nAPI 统计:")
    print(f"  总请求数: {stats['total_requests']}")
    print(f"  缓存命中: {stats['cache_hits']}")
    print(f"  命中率: {stats['cache_hit_rate']:.1%}")
    print(f"  错误次数: {stats['api_errors']}")

    # 关闭连接
    await store.close()


if __name__ == '__main__':
    asyncio.run(test_api_client())
