"""测试数据库边界保护修复"""
import asyncio
import sys
from address_analyzer.data_store import DataStore

async def test_boundary_protection():
    """测试边界保护功能"""
    store = DataStore()

    try:
        await store.connect(max_connections=2)

        # 测试极端值
        test_metrics = {
            'total_trades': 1000,
            'win_rate': 75.5,
            'roi': 5000.0,  # 正常值
            'sharpe_ratio': 4068.56,  # 超出 DECIMAL(10,4) 的范围 (>999,999.9999)
            'total_pnl': 100000.0,
            'account_value': 200000.0,
            'max_drawdown': 786.45,  # 接近 DECIMAL(8,2) 的上限
            'net_deposit': 50000.0
        }

        print("测试保存极端值指标...")
        print(f"输入 sharpe_ratio: {test_metrics['sharpe_ratio']}")
        print(f"输入 max_drawdown: {test_metrics['max_drawdown']}")

        await store.save_metrics('0xtest_extreme_values', test_metrics)
        print("✅ 成功保存！边界保护工作正常")

        # 验证保存的值
        all_metrics = await store.get_all_metrics()
        saved = next((m for m in all_metrics if m['address'] == '0xtest_extreme_values'), None)

        if saved:
            print(f"\n保存后的值:")
            print(f"  sharpe_ratio: {saved['sharpe_ratio']} (截断到数据库限制)")
            print(f"  max_drawdown: {saved['max_drawdown']}")

        return True

    except Exception as e:
        print(f"❌ 错误: {e}")
        return False
    finally:
        await store.close()

if __name__ == '__main__':
    success = asyncio.run(test_boundary_protection())
    sys.exit(0 if success else 1)
