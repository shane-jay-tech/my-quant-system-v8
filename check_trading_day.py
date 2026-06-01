"""
交易日检测模块
判断今日是否为 A 股交易日，供流水线在非交易日自动跳过

检测逻辑：
1. 周末直接返回 False
2. 查询上证指数 000001 实时行情，若成交量 > 0 且数据时间戳为今日 → 交易日
3. 查询失败时保守返回 True（宁可在非交易日跑也不要漏掉交易日）
"""
import requests
import time
from datetime import datetime, date, timedelta


def _previous_weekday(today: date) -> date:
    """上一工作日：周一 → 上周五，其余 → 前一日。仅用于数据新鲜度启发式。"""
    return today - timedelta(days=3 if today.weekday() == 0 else 1)


def is_trading_day(today: date | None = None, request_get=None):
    """
    判断今天是否为 A 股交易日
    返回 (bool, str): (是否交易日, 判断依据)

    today / request_get 均可注入，便于测试；断网或无法解析时 fail-open 返回 True。
    """
    today = today or date.today()
    if hasattr(today, 'date') and not isinstance(today, date):
        today = today.date()
    if not isinstance(today, date):
        raise TypeError('today must be a date')
    get = request_get or requests.get

    # 规则1：周末不是交易日
    if today.weekday() >= 5:  # 5=Sat, 6=Sun
        return False, "周末"

    prev_weekday_str = _previous_weekday(today).strftime('%Y-%m-%d')

    # 规则2：查询实时行情验证（通过成交量确认市场活跃）
    # 用上证指数 000001 作为标尺
    url = "https://hq.sinajs.cn/list=sh000001"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.sina.com.cn/',
        'Connection': 'close',
    }

    for attempt in range(3):
        try:
            resp = get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                time.sleep(1)
                continue

            resp.encoding = 'gbk'
            text = resp.text

            # 解析上证指数数据
            # 格式: var hq_str_sh000001="上证指数,收盘,开盘,最高,最低,...成交量,成交额,...,日期,时间,..."
            match_start = text.find('"')
            match_end = text.rfind('"')
            if match_start == -1 or match_end == -1:
                time.sleep(1)
                continue

            data_str = text[match_start + 1:match_end]
            fields = data_str.split(',')

            if len(fields) < 32:
                time.sleep(1)
                continue

            # 字段索引：30=日期, 31=时间
            data_date = fields[30].strip()
            volume = float(fields[8]) if fields[8] and fields[8] != '' else 0

            today_str = today.strftime('%Y-%m-%d')

            # 计算行情日期与今天的天数差
            data_dt = datetime.strptime(data_date, '%Y-%m-%d').date()
            day_diff = (today - data_dt).days

            if data_date == today_str and volume > 0:
                return True, f"行情日期={data_date}, 成交量>0"
            elif day_diff <= 1 and volume > 0:
                # 行情日期是昨天但今天是工作日 → 今天可能是交易日（还没开盘）
                return True, f"最新行情={data_date}(-{day_diff}天), 工作日→假设交易日"
            elif data_date == prev_weekday_str and volume > 0:
                # 周一拿到上周五行情：day_diff=3 是普通周末，不是长假
                return True, f"最新行情={data_date}(上一工作日), 工作日→假设交易日"
            elif day_diff >= 3:
                # 上一工作日之后仍无更新（如周二仍停留在周五）→ 很可能遇到假日
                return False, f"最新行情={data_date}(-{day_diff}天), 数据过期→可能长假"
            elif data_date != today_str and volume == 0:
                return False, f"行情日期={data_date}, 成交量为0"

        except Exception as e:
            time.sleep(1)
            continue

    # 规则3：无法确定时保守返回 True（防止漏跑）
    return True, "无法确认（网络异常），保守按交易日处理"


def main():
    is_trade, reason = is_trading_day()
    status = "是" if is_trade else "否"
    print(f"今日({date.today()})是否为交易日：{status}")
    print(f"判断依据：{reason}")
    return 0 if is_trade else 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
