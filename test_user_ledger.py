#!/usr/bin/env python3
"""
测试 user_non_funding_ledger_updates 接口
获取用户出入金记录（充值、提现、转账）
"""
import asyncio
import sys
from pathlib import Path
import time
from datetime import datetime
from collections import defaultdict

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from address_analyzer.api_client import HyperliquidAPIClient
from address_analyzer.data_store import get_store


async def test_user_ledger():
    """测试出入金接口"""

    print("=" * 80)
    print("user_non_funding_ledger_updates() 接口测试")
    print("出入金记录（充值、提现、转账）")
    print("=" * 80)

    # 初始化
    store = get_store()
    await store.connect()

    client = HyperliquidAPIClient(
        store=store,
        max_concurrent=5,
        rate_limit=10.0
    )

    # 测试地址（已知有数据）
    test_address = "0xcd87ea212314217b6aa64fdffb9954330db5de4f"

    # 获取所有历史记录（start_time = 0 表示从最早开始）
    start_time = 0
    current_time = int(time.time() * 1000)

    print(f"\n【测试参数】")
    print(f"  地址: {test_address}")
    print(f"  起始时间: 从最早记录开始")
    print(f"  结束时间: {datetime.fromtimestamp(current_time/1000).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  时间范围: 所有历史记录")

    # 获取数据
    print(f"\n【获取数据】")
    try:
        ledger_data = client.info.user_non_funding_ledger_updates(test_address, start_time)
    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        await store.close()
        return

    if not ledger_data:
        print("  ❌ 未获取到数据")
        await store.close()
        return

    print(f"  ✅ 成功获取 {len(ledger_data)} 条记录")

    # 数据分类
    print(f"\n【数据分类】")

    records_by_type = defaultdict(list)
    for record in ledger_data:
        record_type = record['delta']['type']
        records_by_type[record_type].append(record)

    for record_type, records in records_by_type.items():
        print(f"  • {record_type}: {len(records)} 条")

    # 资金流分析
    print(f"\n【资金流分析】")

    # 统计转账（send类型）
    send_records = records_by_type.get('send', [])
    if send_records:
        # 区分收入和支出
        incoming = []  # 该地址作为接收方
        outgoing = []  # 该地址作为发送方

        for record in send_records:
            delta = record['delta']
            destination = delta.get('destination', '').lower()
            user = delta.get('user', '').lower()

            if destination == test_address.lower():
                incoming.append(record)
            elif user == test_address.lower():
                outgoing.append(record)

        # 计算总额
        total_incoming = sum(float(r['delta'].get('amount', 0)) for r in incoming)
        total_outgoing = sum(float(r['delta'].get('amount', 0)) for r in outgoing)

        print(f"\n  转账统计 (send):")
        print(f"    收入: {len(incoming)} 笔，共 {total_incoming:,.2f} USDC")
        print(f"    支出: {len(outgoing)} 笔，共 {total_outgoing:,.2f} USDC")
        print(f"    净流入: {total_incoming - total_outgoing:,.2f} USDC")

    # 统计子账户转账
    sub_records = records_by_type.get('subAccountTransfer', [])
    if sub_records:
        # 区分收入和支出
        sub_incoming = []  # 该地址作为接收方
        sub_outgoing = []  # 该地址作为发送方

        for record in sub_records:
            delta = record['delta']
            destination = delta.get('destination', '').lower()
            user = delta.get('user', '').lower()

            if destination == test_address.lower():
                sub_incoming.append(record)
            elif user == test_address.lower():
                sub_outgoing.append(record)

        total_sub_in = sum(float(r['delta'].get('usdc', 0)) for r in sub_incoming)
        total_sub_out = sum(float(r['delta'].get('usdc', 0)) for r in sub_outgoing)

        print(f"\n  子账户转账 (subAccountTransfer):")
        print(f"    收入: {len(sub_incoming)} 笔，共 {total_sub_in:,.2f} USDC")
        print(f"    支出: {len(sub_outgoing)} 笔，共 {total_sub_out:,.2f} USDC")
        print(f"    净流入: {total_sub_in - total_sub_out:,.2f} USDC")

    # 统计其他类型
    other_types = [t for t in records_by_type.keys()
                   if t not in ['send', 'subAccountTransfer']]
    if other_types:
        print(f"\n  其他类型:")
        for record_type in other_types:
            records = records_by_type[record_type]
            print(f"    • {record_type}: {len(records)} 条")

    # 数据示例
    print(f"\n【数据示例】（前3条）")
    for i, record in enumerate(ledger_data[:3]):
        ts = record['time']
        dt = datetime.fromtimestamp(ts / 1000)
        delta = record['delta']
        record_type = delta['type']

        print(f"\n  --- 记录 {i+1} ({dt.strftime('%Y-%m-%d %H:%M:%S')}) ---")
        print(f"  类型: {record_type}")
        print(f"  哈希: {record.get('hash', 'N/A')}")

        if record_type == 'send':
            print(f"  发送方: {delta.get('user', 'N/A')}")
            print(f"  接收方: {delta.get('destination', 'N/A')}")
            print(f"  代币: {delta.get('token', 'N/A')}")
            print(f"  金额: {delta.get('amount', 'N/A')}")
            print(f"  手续费: {delta.get('fee', 'N/A')}")

        elif record_type == 'subAccountTransfer':
            print(f"  发送方: {delta.get('user', 'N/A')}")
            print(f"  接收方: {delta.get('destination', 'N/A')}")
            print(f"  金额: {delta.get('usdc', 'N/A')} USDC")

        else:
            # 显示所有字段
            for key, value in delta.items():
                print(f"  {key}: {value}")

    # 时间线分析
    print(f"\n【时间线分析】")

    # 按天统计
    daily_stats = defaultdict(lambda: {'in': 0.0, 'out': 0.0})

    for record in ledger_data:
        ts = record['time']
        date = datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d')
        delta = record['delta']
        record_type = delta['type']

        if record_type == 'send':
            amount = float(delta.get('amount', 0))
            if delta.get('destination', '').lower() == test_address.lower():
                daily_stats[date]['in'] += amount
            elif delta.get('user', '').lower() == test_address.lower():
                daily_stats[date]['out'] += amount

        elif record_type == 'subAccountTransfer':
            amount = float(delta.get('usdc', 0))
            if delta.get('destination', '').lower() == test_address.lower():
                daily_stats[date]['in'] += amount
            elif delta.get('user', '').lower() == test_address.lower():
                daily_stats[date]['out'] += amount

    # 显示活跃日期（有资金流动的日期）
    active_days = sorted(daily_stats.keys(), reverse=True)
    print(f"  活跃天数: {len(active_days)} 天")

    if active_days:
        print(f"\n  最近5天资金流:")
        for date in active_days[:5]:
            stats = daily_stats[date]
            net = stats['in'] - stats['out']
            print(f"    {date}: 流入 {stats['in']:>12,.2f}  流出 {stats['out']:>12,.2f}  净额 {net:>12,.2f}")

    # 统计信息
    stats = client.get_stats()
    print(f"\n【API 统计】")
    print(f"  总请求数: {stats['total_requests']}")
    print(f"  缓存命中: {stats['cache_hits']}")
    print(f"  命中率: {stats['cache_hit_rate']:.1%}")
    print(f"  错误次数: {stats['api_errors']}")

    # 清理
    await store.close()

    print("\n" + "=" * 80)
    print("✅ 测试完成")
    print("=" * 80)


async def test_full_workflow():
    """测试完整工作流：数据获取 → 保存 → 统计 → 指标计算"""

    print("\n" + "=" * 80)
    print("完整工作流测试")
    print("=" * 80)

    # 初始化
    store = get_store()
    await store.connect()

    client = HyperliquidAPIClient(
        store=store,
        max_concurrent=5,
        rate_limit=10.0
    )

    test_address = "0x162cc7c861ebd0c06b3d72319201150482518185"

    print(f"\n步骤1: 获取完整数据（包含 ledger）")
    try:
        data = await client.fetch_address_data(test_address, save_to_db=True)
        print(f"  ✅ 数据获取成功")
        print(f"     - fills: {len(data.get('fills', []))} 条")
        print(f"     - state: {'✅' if data.get('state') else '❌'}")
        print(f"     - funding: {len(data.get('funding', []))} 条")
        print(f"     - ledger: {len(data.get('ledger', []))} 条")

        assert 'ledger' in data, "数据中应包含 ledger 字段"
        assert isinstance(data['ledger'], list), "ledger 应为列表"

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        import traceback
        traceback.print_exc()
        await store.close()
        return

    print(f"\n步骤2: 验证 transfers 表已保存")
    try:
        transfer_stats = await store.get_net_deposits(test_address)
        print(f"  ✅ 出入金统计:")
        print(f"     - 总充值: ${transfer_stats['total_deposits']:,.2f}")
        print(f"     - 总提现: ${transfer_stats['total_withdrawals']:,.2f}")
        print(f"     - 净充值: ${transfer_stats['net_deposits']:,.2f}")

        assert 'net_deposits' in transfer_stats, "统计中应包含 net_deposits"
        assert 'total_deposits' in transfer_stats, "统计中应包含 total_deposits"
        assert 'total_withdrawals' in transfer_stats, "统计中应包含 total_withdrawals"

    except Exception as e:
        print(f"  ❌ 获取统计失败: {e}")
        import traceback
        traceback.print_exc()
        await store.close()
        return

    print(f"\n步骤3: 计算指标（使用出入金数据）")
    try:
        from address_analyzer.metrics_engine import MetricsEngine

        metrics = MetricsEngine.calculate_metrics(
            address=test_address,
            fills=data['fills'],
            state=data['state'],
            transfer_data=transfer_stats
        )

        print(f"  ✅ 指标计算完成:")
        print(f"     - 地址: {metrics.address}")
        print(f"     - 总交易数: {metrics.total_trades}")
        print(f"     - 胜率: {metrics.win_rate:.1f}%")
        print(f"     - 净充值: ${metrics.net_deposits:,.2f}")
        print(f"     - 旧版ROI: {metrics.roi:.2f}%")
        print(f"     - 实际初始资金: ${metrics.actual_initial_capital:,.2f}")
        print(f"     - 校准ROI: {metrics.corrected_roi:.2f}%")
        print(f"     - 总PNL: ${metrics.total_pnl:,.2f}")

        # 验证新字段
        assert hasattr(metrics, 'net_deposits'), "应有 net_deposits 字段"
        assert hasattr(metrics, 'actual_initial_capital'), "应有 actual_initial_capital 字段"
        assert hasattr(metrics, 'corrected_roi'), "应有 corrected_roi 字段"
        assert metrics.actual_initial_capital > 0, "实际初始资金应大于0"

        # 如果有出入金，两种ROI应该不同
        if abs(metrics.net_deposits) > 1:
            print(f"\n  验证: 有出入金时，旧版ROI 与 校准ROI 应不同")
            roi_diff = abs(metrics.roi - metrics.corrected_roi)
            print(f"     - ROI差异: {roi_diff:.2f}%")
            if roi_diff < 0.01:
                print(f"     ⚠️  差异很小，可能出入金金额较小或计算有问题")

    except Exception as e:
        print(f"  ❌ 指标计算失败: {e}")
        import traceback
        traceback.print_exc()
        await store.close()
        return

    print(f"\n步骤4: 验证数据库 metrics_cache 表")
    try:
        await store.save_metrics(test_address, {
            'total_trades': metrics.total_trades,
            'win_rate': metrics.win_rate,
            'roi': metrics.roi,
            'total_pnl': metrics.total_pnl,
            'net_deposit': metrics.net_deposits
        })
        print(f"  ✅ metrics_cache 表已更新（包含 net_deposit 字段）")

    except Exception as e:
        print(f"  ❌ 保存指标失败: {e}")
        import traceback
        traceback.print_exc()

    # 清理
    await store.close()

    print("\n" + "=" * 80)
    print("✅ 完整工作流测试通过")
    print("=" * 80)


async def test_pagination():
    """测试分页功能和数据完整性"""

    print("\n" + "=" * 80)
    print("分页功能测试")
    print("=" * 80)

    # 初始化
    store = get_store()
    await store.connect()

    client = HyperliquidAPIClient(
        store=store,
        max_concurrent=5,
        rate_limit=10.0
    )

    # 测试地址（已知有较多数据）
    test_address = "0x162cc7c861ebd0c06b3d72319201150482518185"

    print(f"\n【测试1】启用分页（默认行为）")
    try:
        result = await client.get_user_ledger(test_address, use_cache=False)
        print(f"  ✅ 获取 {len(result)} 条记录")

        # 验证数据结构
        assert isinstance(result, list), "返回值应为列表"
        if result:
            assert 'time' in result[0], "记录应包含 time 字段"
            assert 'hash' in result[0], "记录应包含 hash 字段"
            assert 'delta' in result[0], "记录应包含 delta 字段"
            print(f"  ✅ 数据结构验证通过")

    except Exception as e:
        print(f"  ❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n【测试2】禁用分页")
    try:
        result_no_page = await client.get_user_ledger(
            test_address,
            use_cache=False,
            enable_pagination=False
        )
        print(f"  ✅ 获取 {len(result_no_page)} 条记录（单次查询）")

        # 如果数据量大，分页版本应该获取更多数据
        if len(result_no_page) >= 448:
            print(f"  ⚠️  单次查询达到 API 上限 (~448 条)，可能有数据截断")
            if len(result) > len(result_no_page):
                print(f"  ✅ 分页版本获取了更多数据: {len(result)} vs {len(result_no_page)}")

    except Exception as e:
        print(f"  ❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n【测试3】去重验证")
    try:
        # 检查是否有重复记录
        hashes = [r['hash'] for r in result if r.get('hash')]
        unique_hashes = set(hashes)

        print(f"  总记录数: {len(result)}")
        print(f"  唯一哈希数: {len(unique_hashes)}")

        if len(hashes) == len(unique_hashes):
            print(f"  ✅ 无重复记录")
        else:
            duplicates = len(hashes) - len(unique_hashes)
            print(f"  ⚠️  发现 {duplicates} 条重复记录（已自动去重）")

    except Exception as e:
        print(f"  ❌ 测试失败: {e}")

    print(f"\n【测试4】时间范围查询")
    try:
        # 查询最近 30 天
        now = int(time.time() * 1000)
        thirty_days_ago = now - (30 * 24 * 60 * 60 * 1000)

        recent_result = await client.get_user_ledger(
            test_address,
            start_time=thirty_days_ago,
            use_cache=False
        )
        print(f"  ✅ 最近30天: {len(recent_result)} 条记录")

        # 验证时间范围
        if recent_result:
            earliest = min(r['time'] for r in recent_result)
            latest = max(r['time'] for r in recent_result)
            print(f"     时间范围: {datetime.fromtimestamp(earliest/1000).strftime('%Y-%m-%d')} "
                  f"到 {datetime.fromtimestamp(latest/1000).strftime('%Y-%m-%d')}")

            # 验证所有记录都在时间范围内
            out_of_range = [r for r in recent_result if r['time'] < thirty_days_ago]
            if out_of_range:
                print(f"  ⚠️  发现 {len(out_of_range)} 条记录超出时间范围")
            else:
                print(f"  ✅ 所有记录都在时间范围内")

    except Exception as e:
        print(f"  ❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n【测试5】数据完整性验证")
    try:
        # 验证数据按时间排序
        times = [r['time'] for r in result]
        sorted_times = sorted(times)

        if times == sorted_times:
            print(f"  ✅ 数据已按时间升序排序")
        else:
            print(f"  ⚠️  数据未正确排序")

        # 验证字段完整性
        required_fields = ['time', 'hash', 'delta']
        missing_fields = []
        for i, record in enumerate(result[:10]):  # 检查前10条
            for field in required_fields:
                if field not in record:
                    missing_fields.append((i, field))

        if not missing_fields:
            print(f"  ✅ 必需字段完整")
        else:
            print(f"  ⚠️  发现缺失字段: {missing_fields}")

    except Exception as e:
        print(f"  ❌ 测试失败: {e}")

    print(f"\n【测试6】缓存机制验证")
    try:
        # 第一次查询（从 API）
        start = time.time()
        result1 = await client.get_user_ledger(test_address, use_cache=True)
        time1 = time.time() - start

        # 第二次查询（从缓存）
        start = time.time()
        result2 = await client.get_user_ledger(test_address, use_cache=True)
        time2 = time.time() - start

        print(f"  第1次查询（API）: {len(result1)} 条, 耗时 {time1:.2f}s")
        print(f"  第2次查询（缓存）: {len(result2)} 条, 耗时 {time2:.2f}s")

        if time2 < time1 * 0.5:  # 缓存应该快至少2倍
            print(f"  ✅ 缓存有效（加速 {time1/time2:.1f}x）")
        else:
            print(f"  ⚠️  缓存可能未生效")

        # 验证数据一致性
        if len(result1) == len(result2):
            print(f"  ✅ 缓存数据一致")
        else:
            print(f"  ⚠️  缓存数据不一致: {len(result1)} vs {len(result2)}")

    except Exception as e:
        print(f"  ❌ 测试失败: {e}")

    # 清理
    await store.close()

    print("\n" + "=" * 80)
    print("✅ 分页功能测试完成")
    print("=" * 80)


async def test_data_integrity():
    """验证数据完整性（对比分段查询）"""

    print("\n" + "=" * 80)
    print("数据完整性验证测试")
    print("=" * 80)

    # 初始化
    store = get_store()
    await store.connect()

    client = HyperliquidAPIClient(
        store=store,
        max_concurrent=5,
        rate_limit=10.0
    )

    test_address = "0x162cc7c861ebd0c06b3d72319201150482518185"

    print(f"\n【方法1】完整查询（分页）")
    try:
        full_result = await client.get_user_ledger(test_address, use_cache=False)
        print(f"  ✅ 获取 {len(full_result)} 条记录")
    except Exception as e:
        print(f"  ❌ 查询失败: {e}")
        await store.close()
        return

    print(f"\n【方法2】分段查询（按月）")
    try:
        segments = []
        now = int(time.time() * 1000)

        # 查询最近 6 个月，每个月单独查询
        for i in range(6):
            month_start = now - ((i + 1) * 30 * 24 * 60 * 60 * 1000)
            month_end = now - (i * 30 * 24 * 60 * 60 * 1000)

            segment = await client.get_user_ledger(
                test_address,
                start_time=month_start,
                end_time=month_end,
                use_cache=False
            )
            segments.extend(segment)

            month_name = datetime.fromtimestamp(month_start/1000).strftime('%Y-%m')
            print(f"  月份 {month_name}: {len(segment)} 条")

            await asyncio.sleep(0.5)  # 避免限流

        print(f"  总计: {len(segments)} 条记录（分段）")

        # 去重
        segments_dedup = client._deduplicate_ledger(segments)
        print(f"  去重后: {len(segments_dedup)} 条记录")

    except Exception as e:
        print(f"  ❌ 查询失败: {e}")
        import traceback
        traceback.print_exc()
        await store.close()
        return

    print(f"\n【对比分析】")
    try:
        # 提取哈希集合
        full_hashes = set(r['hash'] for r in full_result if r.get('hash'))
        segment_hashes = set(r['hash'] for r in segments_dedup if r.get('hash'))

        # 计算差异
        only_in_full = full_hashes - segment_hashes
        only_in_segment = segment_hashes - full_hashes
        common = full_hashes & segment_hashes

        print(f"  完整查询: {len(full_result)} 条, {len(full_hashes)} 个唯一哈希")
        print(f"  分段查询: {len(segments_dedup)} 条, {len(segment_hashes)} 个唯一哈希")
        print(f"  共同记录: {len(common)} 条")

        if only_in_full:
            print(f"  ⚠️  仅在完整查询中: {len(only_in_full)} 条")
        if only_in_segment:
            print(f"  ⚠️  仅在分段查询中: {len(only_in_segment)} 条")

        # 判断一致性
        coverage = len(common) / max(len(full_hashes), len(segment_hashes)) * 100
        print(f"\n  数据覆盖率: {coverage:.1f}%")

        if coverage >= 95:
            print(f"  ✅ 数据完整性良好（≥95%）")
        else:
            print(f"  ⚠️  数据完整性需要关注（<95%）")

    except Exception as e:
        print(f"  ❌ 对比失败: {e}")

    # 清理
    await store.close()

    print("\n" + "=" * 80)
    print("✅ 数据完整性验证完成")
    print("=" * 80)


if __name__ == '__main__':
    asyncio.run(test_user_ledger())
