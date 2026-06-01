"""
交易行为分析器 v1 — 分析真实交易记录，生成智能提醒
"""
import pandas as pd
import numpy as np
import os, glob, json, re
from datetime import datetime, timedelta


def _load_real_trades(base_dir):
    """加载真实交易，过滤示例数据"""
    real_file = os.path.join(base_dir, 'real_trades.csv')
    if not os.path.exists(real_file):
        return None, 0
    df = pd.read_csv(real_file, dtype={'代码': str})
    if '备注' in df.columns:
        df = df[~df['备注'].str.contains('示例数据', na=False)]
    return df, len(df)


def _load_system_picks_all(base_dir):
    """加载所有历史系统选股"""
    files = sorted(glob.glob(os.path.join(base_dir, 'results', 'pick_*.md')))
    all_picks = []
    for fpath in files:
        date_match = re.search(r'pick_(\d{8})', os.path.basename(fpath))
        if not date_match:
            continue
        pick_date = date_match.group(1)
        with open(fpath, 'r', encoding='utf-8') as f:
            content = f.read()
        for line in content.split('\n'):
            if re.match(r'\|\s*\d+\s*\|\s*\d{6}\s*\|', line):
                parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(parts) < 7:
                    continue
                try:
                    # Handle both formats: with and without 板块 column
                    # Without 板块: 排名|代码|名称|最新价|涨跌|...
                    # With 板块: 排名|代码|名称|板块|最新价|涨跌|...
                    code = parts[1]
                    name = parts[2]
                    # Detect if column 3 is numeric (price) or string (sector)
                    try:
                        float(parts[3])
                        price = float(parts[3])
                    except ValueError:
                        price = float(parts[4]) if len(parts) > 4 else 0.0
                    all_picks.append({
                        '选股日期': pick_date,
                        '代码': code,
                        '名称': name,
                        '入场价': price,
                    })
                except (ValueError, IndexError):
                    continue
    return pd.DataFrame(all_picks) if all_picks else pd.DataFrame()


def analyze_current_positions(base_dir):
    """
    分析用户当前持仓，结合系统推荐生成操作建议。
    返回 dict: {positions, recommendations, summary}

    持仓合并规则：按股票代码 groupby，多笔买入累加股数、加权平均成本（含手续费）。
    盈亏拆分：
      - unrealized_pnl: 当前持仓浮盈/浮亏 = 现价×持仓 - 加权成本×持仓
      - realized_pnl:   已平仓部分实现盈亏 = 卖出回收(扣费) - 加权成本×已卖股数
      - total_pnl:      unrealized_pnl + realized_pnl
    """
    empty_summary = {
        'position_count': 0, 'total_cost': 0, 'total_market_value': 0,
        'unrealized_pnl': 0, 'unrealized_pnl_pct': 0,
        'realized_pnl': 0,
        'total_pnl': 0, 'total_pnl_pct': 0,
    }
    trades_df, real_count = _load_real_trades(base_dir)
    if trades_df is None or real_count == 0:
        return {'positions': [], 'recommendations': [
            {'type': 'info', 'icon': '📝', 'title': '无持仓数据',
             'message': '录入真实交易后，系统将自动分析你的持仓并给出操作建议。'}
        ], 'summary': empty_summary}

    trades_df['日期'] = pd.to_datetime(trades_df['日期'])
    trades_df['代码'] = trades_df['代码'].astype(str).str.zfill(6)
    buys = trades_df[trades_df['方向'] == '买入'].copy()
    sells = trades_df[trades_df['方向'] == '卖出'].copy()

    if len(buys) == 0:
        return {'positions': [], 'recommendations': [
            {'type': 'info', 'icon': '📝', 'title': '无买入记录',
             'message': '尚未录入买入交易。录入后系统将追踪持仓并给出操作建议。'}
        ], 'summary': empty_summary}

    current_prices = _load_current_prices(base_dir)
    today_picks = _load_today_picks(base_dir)
    today_pick_codes = set(p['代码'] for p in today_picks) if today_picks else set()

    # 按代码合并：累加股数、累加成交额、累加手续费、首笔买入日期算持有天数
    realized_total = 0.0
    positions = []

    all_codes = set(buys['代码']) | set(sells['代码'])
    for code in sorted(all_codes):
        code_buys = buys[buys['代码'] == code]
        code_sells = sells[sells['代码'] == code]

        buy_qty = int(code_buys['数量'].sum())
        buy_amount = float(code_buys['成交额'].sum())
        buy_fee = float(code_buys['手续费'].fillna(0).sum()) if '手续费' in code_buys.columns else 0.0
        buy_cost_total = buy_amount + buy_fee
        avg_cost = (buy_cost_total / buy_qty) if buy_qty > 0 else 0.0

        sell_qty = int(code_sells['数量'].sum()) if len(code_sells) else 0
        sell_amount = float(code_sells['成交额'].sum()) if len(code_sells) else 0.0
        sell_fee = float(code_sells['手续费'].fillna(0).sum()) if (len(code_sells) and '手续费' in code_sells.columns) else 0.0
        sell_revenue = sell_amount - sell_fee

        if sell_qty > 0:
            realized_total += sell_revenue - avg_cost * sell_qty

        net_qty = buy_qty - sell_qty
        if net_qty <= 0:
            continue

        first_buy = code_buys.iloc[0]
        first_buy_date = code_buys['日期'].min()

        price_info = current_prices.get(code, {})
        cur_price = float(price_info.get('price', 0))
        cur_name = price_info.get('name') or str(first_buy.get('名称', ''))

        position_cost = avg_cost * net_qty
        if cur_price > 0:
            market_value = cur_price * net_qty
            pnl_amount = market_value - position_cost
            pnl_pct = (cur_price / avg_cost - 1) * 100 if avg_cost > 0 else 0.0
        else:
            market_value = position_cost
            pnl_amount = 0.0
            pnl_pct = 0.0

        hold_days = (datetime.now() - first_buy_date).days

        positions.append({
            '代码': code,
            '名称': cur_name,
            '买入日期': first_buy_date.strftime('%Y-%m-%d'),
            '买入价': round(avg_cost, 4),
            '数量': net_qty,
            '成本': round(position_cost, 2),
            '当前价': cur_price if cur_price > 0 else None,
            '市值': round(market_value, 2),
            '盈亏%': round(pnl_pct, 2),
            '盈亏额': round(pnl_amount, 2),
            '持有天数': hold_days,
            '在今日推荐': code in today_pick_codes,
            '下单依据': str(first_buy.get('下单依据', '')),
            '买入笔数': len(code_buys),
        })

    recommendations = []
    if positions:
        _gen_position_recommendations(positions, recommendations)

    total_cost = sum(p['成本'] for p in positions)
    total_market = sum(p['市值'] for p in positions)
    unrealized_pnl = total_market - total_cost
    unrealized_pnl_pct = (total_market / total_cost - 1) * 100 if total_cost > 0 else 0.0
    total_pnl = unrealized_pnl + realized_total
    # 总盈亏百分比基准用累计总投入（含已平仓），分母不会随平仓收缩
    total_invested = float(buys['成交额'].sum()) + (float(buys['手续费'].fillna(0).sum()) if '手续费' in buys.columns else 0.0)
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0.0

    summary = {
        'position_count': len(positions),
        'total_cost': round(total_cost, 2),
        'total_market_value': round(total_market, 2),
        'unrealized_pnl': round(unrealized_pnl, 2),
        'unrealized_pnl_pct': round(unrealized_pnl_pct, 2),
        'realized_pnl': round(realized_total, 2),
        'total_pnl': round(total_pnl, 2),
        'total_pnl_pct': round(total_pnl_pct, 2),
    }

    return {'positions': positions, 'recommendations': recommendations, 'summary': summary}


def _load_current_prices(base_dir):
    """加载最新股票价格"""
    stock_files = sorted(glob.glob(os.path.join(base_dir, 'data', 'stock_*.csv')), reverse=True)
    if not stock_files:
        return {}
    df = pd.read_csv(stock_files[0], dtype={'代码': str})
    prices = {}
    for _, row in df.iterrows():
        code = str(row['代码']).zfill(6)
        prices[code] = {
            'name': str(row.get('名称', '')),
            'price': float(row.get('最新价', 0)),
        }
    return prices


def _load_today_picks(base_dir):
    """加载最新系统选股"""
    files = sorted(glob.glob(os.path.join(base_dir, 'results', 'pick_*.md')), reverse=True)
    if not files:
        return []
    picks = []
    with open(files[0], 'r', encoding='utf-8') as f:
        content = f.read()
    for line in content.split('\n'):
        if re.match(r'\|\s*\d+\s*\|\s*\d{6}\s*\|', line):
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 7:
                try:
                    code = parts[1]
                    name = parts[2]
                    try:
                        price = float(parts[3])
                    except ValueError:
                        price = float(parts[4]) if len(parts) > 4 else 0.0
                    picks.append({'代码': code, '名称': name, '推荐价': price})
                except (ValueError, IndexError):
                    continue
    return picks


def _gen_position_recommendations(positions, recommendations):
    """为每个持仓生成操作建议"""
    risk_stocks = []
    profit_stocks = []
    old_stocks = []
    off_pick_stocks = []
    on_pick_stocks = []

    for p in positions:
        pnl = p['盈亏%']
        days = p['持有天数']
        name = p['名称']
        code = p['代码']

        if p['当前价'] is None:
            continue

        if pnl < -5:
            risk_stocks.append(f"{name}({code})跌{pnl:.1f}%")
        if pnl > 15:
            profit_stocks.append(f"{name}({code})涨{pnl:+.1f}%")
        if days > 8:
            old_stocks.append(f"{name}({code})持有{days}天")
        if not p['在今日推荐']:
            off_pick_stocks.append(name)
        else:
            on_pick_stocks.append(name)

    if risk_stocks:
        recommendations.append({
            'type': 'warning', 'icon': '⚠️', 'title': '持仓接近止损线',
            'message': '、'.join(risk_stocks) + '。跌幅超过5%，接近8%止损线。建议：① 检查该股是否仍在今日推荐中；② 如不在推荐中且无特殊理由，考虑止损离场；③ 不要补仓。'
        })

    if profit_stocks:
        recommendations.append({
            'type': 'success', 'icon': '💰', 'title': '持仓盈利丰厚，考虑止盈',
            'message': '、'.join(profit_stocks) + '。涨幅超过15%，建议卖出一半锁定利润，剩余让利润奔跑。系统止盈线为20%。'
        })

    if old_stocks:
        recommendations.append({
            'type': 'warning', 'icon': '⏰', 'title': '持有天数接近上限',
            'message': '、'.join(old_stocks) + '。系统建议最长持有10天。如无强势突破信号，建议准备在本周内退出。'
        })

    if off_pick_stocks:
        recommendations.append({
            'type': 'info', 'icon': '🔍', 'title': '部分持仓不在今日推荐中',
            'message': '、'.join(off_pick_stocks) + '未出现在今日系统推荐。系统每天重新扫描全市场，出榜可能意味着趋势减弱。建议关注这些股票的走势，如继续走弱则考虑替换为今日推荐。'
        })

    if on_pick_stocks:
        recommendations.append({
            'type': 'success', 'icon': '✅', 'title': '以下持仓仍在系统推荐中',
            'message': '、'.join(on_pick_stocks) + '仍在今日系统推荐榜单。趋势确认有效，建议继续持有，按系统信号操作。'
        })

    # Concentration check on current positions
    if len(positions) >= 2:
        amounts = {p['名称']: p['成本'] for p in positions}
        total = sum(amounts.values())
        top_name = max(amounts, key=amounts.get)
        top_pct = amounts[top_name] / total * 100
        if top_pct > 50:
            recommendations.append({
                'type': 'warning', 'icon': '⚠️', 'title': '持仓过于集中',
                'message': f'{top_name}占当前持仓{top_pct:.0f}%。单票重仓放大了个股风险。建议减仓至30%以下，将资金分配到今日推荐的其他股票。'
            })


def analyze_trade_behavior(base_dir):
    """
    分析真实交易行为，生成智能提醒列表。
    返回 list[dict]，每项包含 type/icon/title/message。
    """
    insights = []
    trades_df, real_count = _load_real_trades(base_dir)

    if trades_df is None or real_count == 0:
        return [{'type': 'info', 'icon': '📝', 'title': '暂无交易数据',
                 'message': '录入真实交易后，系统将自动生成智能交易提醒。点击上方表单录入第一笔交易吧。'}]

    if real_count < 3:
        return [{'type': 'info', 'icon': '📊', 'title': '交易数据不足',
                 'message': f'当前仅 {real_count} 笔交易记录。需要至少 5 笔交易才能生成有意义的分析。继续录入，系统会在数据充足后自动分析。'}]

    _analyze_hold_duration(trades_df, insights)
    _analyze_trade_frequency(trades_df, base_dir, insights)
    _analyze_off_system(trades_df, base_dir, insights)
    _analyze_follow_vs_solo(trades_df, base_dir, insights)
    _analyze_chasing(trades_df, base_dir, insights)
    _analyze_concentration(trades_df, insights)
    _analyze_sell_timing(trades_df, insights)
    _analyze_trade_notes(trades_df, insights)
    _analyze_positive(trades_df, base_dir, insights)

    if not insights:
        insights.append({'type': 'info', 'icon': '✅', 'title': '交易行为良好',
                         'message': '未发现明显的交易行为问题。保持纪律，继续按系统信号操作。'})

    return insights


def _analyze_hold_duration(trades_df, insights):
    """持有天数分析"""
    buys = trades_df[trades_df['方向'] == '买入'].copy()
    sells = trades_df[trades_df['方向'] == '卖出'].copy()
    if len(buys) == 0 or len(sells) == 0:
        return

    buys['日期'] = pd.to_datetime(buys['日期'])
    sells['日期'] = pd.to_datetime(sells['日期'])

    hold_days = []
    for _, sell in sells.iterrows():
        code_buys = buys[(buys['代码'] == sell['代码']) & (buys['日期'] < sell['日期'])]
        if len(code_buys) > 0:
            last_buy = code_buys.iloc[-1]
            days = (sell['日期'] - last_buy['日期']).days
            if 0 <= days <= 60:
                hold_days.append(days)

    if len(hold_days) >= 2:
        median_hold = np.median(hold_days)
        if median_hold < 5:
            insights.append({
                'type': 'warning', 'icon': '⏰', 'title': '持有时间偏短',
                'message': f'完成交易的持有天数中位数仅 {median_hold:.0f} 天，系统建议 10 天。过早卖出可能错失趋势利润。尝试让盈利的股票多跑几天。'
            })
        elif median_hold < 7:
            insights.append({
                'type': 'tip', 'icon': '⏰', 'title': '持有时间可延长',
                'message': f'持有天数中位数 {median_hold:.0f} 天，接近但略低于系统建议的 10 天。如果趋势未破，可考虑延长持有。'
            })


def _analyze_trade_frequency(trades_df, base_dir, insights):
    """交易频率 vs 系统推荐"""
    buys = trades_df[trades_df['方向'] == '买入']
    if len(buys) == 0:
        return

    buys['日期'] = pd.to_datetime(buys['日期'])
    week_ago = datetime.now() - timedelta(days=7)
    weekly_buys = buys[buys['日期'] >= week_ago]
    weekly_count = len(weekly_buys)

    # Count system picks this week
    picks_df = _load_system_picks_all(base_dir)
    system_weekly = 0
    if len(picks_df) > 0:
        picks_df['选股日期'] = pd.to_datetime(picks_df['选股日期'])
        system_weekly = len(picks_df[picks_df['选股日期'] >= week_ago])

    if system_weekly > 0 and weekly_count > system_weekly * 2:
        insights.append({
            'type': 'warning', 'icon': '📈', 'title': '交易频率偏高',
            'message': f'本周交易 {weekly_count} 笔（买入）vs 系统推荐 {system_weekly} 只。过度交易会增加手续费和决策疲劳。建议减少自主交易，跟随系统信号。'
        })


def _analyze_off_system(trades_df, base_dir, insights):
    """检测系统外交易"""
    buys = trades_df[trades_df['方向'] == '买入']
    if len(buys) == 0:
        return

    picks_df = _load_system_picks_all(base_dir)
    if len(picks_df) == 0:
        return

    system_codes = set(picks_df['代码'].unique())
    buy_codes = set(buys['代码'].unique())
    off_system = buy_codes - system_codes
    off_count = len(buys[buys['代码'].isin(off_system)])
    off_pct = off_count / len(buys) * 100

    if off_pct > 30:
        insights.append({
            'type': 'warning', 'icon': '🔍', 'title': '系统外交易偏多',
            'message': f'有 {off_count} 笔交易（{off_pct:.0f}%）的股票不在系统推荐中。自主选股风险较高，建议优先跟随系统信号。'
        })
    elif off_pct > 0 and off_pct <= 30:
        insights.append({
            'type': 'info', 'icon': '🔍', 'title': '少量系统外交易',
            'message': f'有 {off_count} 笔交易（{off_pct:.0f}%）为自主选股。保持关注，确保自主交易也有明确依据。'
        })


def _analyze_follow_vs_solo(trades_df, base_dir, insights):
    """跟随系统 vs 自主交易的胜率对比"""
    sells = trades_df[trades_df['方向'] == '卖出']
    buys = trades_df[trades_df['方向'] == '买入']
    if len(sells) < 3 or len(buys) == 0:
        return

    picks_df = _load_system_picks_all(base_dir)
    system_codes = set(picks_df['代码'].unique()) if len(picks_df) > 0 else set()

    follow_wins = solo_wins = follow_total = solo_total = 0
    for _, sell in sells.iterrows():
        code = sell['代码']
        code_buys = buys[(buys['代码'] == code) & (pd.to_datetime(buys['日期']) < pd.to_datetime(sell['日期']))]
        if len(code_buys) == 0:
            continue
        avg_entry = code_buys['价格'].mean()
        pnl = (float(sell['价格']) / avg_entry - 1) * 100
        if code in system_codes:
            follow_total += 1
            if pnl > 0:
                follow_wins += 1
        else:
            solo_total += 1
            if pnl > 0:
                solo_wins += 1

    if follow_total >= 3 and solo_total >= 3:
        follow_wr = follow_wins / follow_total * 100
        solo_wr = solo_wins / solo_total * 100
        if follow_wr > solo_wr + 15:
            insights.append({
                'type': 'success', 'icon': '🎯', 'title': '跟随系统明显更优',
                'message': f'跟随系统的交易胜率 {follow_wr:.0f}% vs 自主交易胜率 {solo_wr:.0f}%。系统信号有明显的统计优势，建议增加系统跟随比例。'
            })
        elif solo_wr > follow_wr + 10:
            insights.append({
                'type': 'tip', 'icon': '💡', 'title': '自主交易表现不错',
                'message': f'自主交易胜率 {solo_wr:.0f}% vs 跟随系统 {follow_wr:.0f}%。你的选股能力不错，但仍建议用系统信号做交叉验证。'
            })


def _analyze_chasing(trades_df, base_dir, insights):
    """追高检测：买入价 vs 系统推荐价"""
    buys = trades_df[trades_df['方向'] == '买入'].copy()
    if len(buys) == 0:
        return

    picks_df = _load_system_picks_all(base_dir)
    if len(picks_df) == 0:
        return

    buys['日期'] = pd.to_datetime(buys['日期'])
    picks_df['选股日期'] = pd.to_datetime(picks_df['选股日期'])

    chase_count = 0
    total_matched = 0
    for _, buy in buys.iterrows():
        code = buy['代码']
        buy_date = buy['日期']
        buy_price = float(buy['价格'])
        # Find picks for this code within 3 days before buy
        relevant = picks_df[(picks_df['代码'] == code) &
                            (picks_df['选股日期'] >= buy_date - timedelta(days=3)) &
                            (picks_df['选股日期'] <= buy_date)]
        if len(relevant) > 0:
            sys_price = relevant.iloc[-1]['入场价']
            total_matched += 1
            if buy_price > sys_price * 1.03:
                chase_count += 1

    if total_matched >= 3 and chase_count > 0:
        chase_pct = chase_count / total_matched * 100
        if chase_pct > 40:
            insights.append({
                'type': 'warning', 'icon': '🏃', 'title': '追高交易较多',
                'message': f'{chase_count}/{total_matched} 笔匹配交易买入价高于系统建议 3%+（{chase_pct:.0f}%）。追高买入压缩了盈利空间，建议在回踩均线时入场。'
            })


def _analyze_concentration(trades_df, insights):
    """仓位集中度检测"""
    buys = trades_df[trades_df['方向'] == '买入']
    if len(buys) < 3:
        return

    code_amounts = buys.groupby('代码')['成交额'].sum().sort_values(ascending=False)
    total_amount = code_amounts.sum()
    top_amount = code_amounts.iloc[0]
    top_code = code_amounts.index[0]
    top_name = buys[buys['代码'] == top_code].iloc[0]['名称']
    top_pct = top_amount / total_amount * 100

    if top_pct > 50:
        insights.append({
            'type': 'warning', 'icon': '⚠️', 'title': '仓位过于集中',
            'message': f'{top_name}（{top_code}）占总成交额 {top_pct:.0f}%。单只股票占比过高会放大个股风险，建议单票不超过总仓位的 30%。'
        })


def _analyze_sell_timing(trades_df, insights):
    """卖出时机分析"""
    sells = trades_df[trades_df['方向'] == '卖出'].copy()
    buys = trades_df[trades_df['方向'] == '买入'].copy()
    if len(sells) < 3 or len(buys) == 0:
        return

    loss_sells = 0
    profit_sells = 0
    for _, sell in sells.iterrows():
        code = sell['代码']
        sell_price = float(sell['价格'])
        code_buys = buys[(buys['代码'] == code) & (pd.to_datetime(buys['日期']) < pd.to_datetime(sell['日期']))]
        if len(code_buys) == 0:
            continue
        avg_entry = code_buys['价格'].mean()
        pnl_pct = (sell_price / avg_entry - 1) * 100
        if pnl_pct < -3:
            loss_sells += 1
        elif pnl_pct > 10:
            profit_sells += 1

    total = loss_sells + profit_sells
    if total >= 3 and loss_sells > profit_sells:
        insights.append({
            'type': 'tip', 'icon': '🔪', 'title': '卖出多发生在亏损区',
            'message': f'{loss_sells} 笔卖出处于亏损（-3%以下）vs {profit_sells} 笔盈利卖出（+10%以上）。检查止损是否设得过紧，或被市场噪音提前震出。'
        })


def _analyze_trade_notes(trades_df, insights):
    """分析用户交易备注，生成个性化反馈（v2新增）"""
    if '备注' not in trades_df.columns:
        # 如果用户一条备注都没填过，给出提示
        insights.append({
            'type': 'tip', 'icon': '📝', 'title': '试试记录交易理由',
            'message': '你还没有在任何交易中填写备注。试着记录你的交易原因（如"跟单系统""觉得要涨""怕回调"），系统能更好地帮你复盘。录入时在"备注"栏填写即可，完全可选。',
        })
        return

    notes = trades_df['备注'].dropna()
    # 过滤掉空字符串和纯空格
    notes = notes[notes.str.strip().str.len() > 0]
    if len(notes) == 0:
        insights.append({
            'type': 'tip', 'icon': '📝', 'title': '试试记录交易理由',
            'message': '试着记录你的交易原因（如"跟单系统""觉得要涨""怕回调"），系统能更好地帮你复盘。录入时在"备注"栏填写即可，完全可选。',
        })
        return

    # 1. 恐惧模式检测
    fear_keywords = ['害怕', '怕', '恐惧', '回调', '跌了', '恐慌', '担心', '不敢', '赶紧卖', '扛不住']
    fear_notes = notes[notes.str.contains('|'.join(fear_keywords), na=False)]
    if len(fear_notes) >= 2:
        # Check if these were losing trades
        sells = trades_df[trades_df['方向'] == '卖出'].copy()
        fear_sells = sells[sells['备注'].str.contains('|'.join(fear_keywords), na=False)]
        loss_count = 0
        if len(fear_sells) > 0 and '盈亏' in fear_sells.columns:
            loss_count = (fear_sells['盈亏'] < 0).sum() if '盈亏' in fear_sells.columns else 0
        elif len(fear_sells) > 0:
            # 尝试从价格计算
            buys = trades_df[trades_df['方向'] == '买入']
            for _, sell in fear_sells.iterrows():
                code_buys = buys[buys['代码'] == sell['代码']]
                if len(code_buys) > 0 and '价格' in sell.index:
                    avg_entry = code_buys['价格'].astype(float).mean()
                    if float(sell['价格']) < avg_entry:
                        loss_count += 1

        insights.append({
            'type': 'warning', 'icon': '🧠', 'title': '情绪化卖出模式检测到',
            'message': f'你最近{len(fear_notes)}次在备注中提到恐惧/担心等情绪。{f"其中{loss_count}次卖出发生在亏损状态。" if loss_count > 0 else ""}系统建议回顾心理学课程：趋势跟踪靠少数大赢家填补小亏损，恐惧性止损会破坏策略的盈亏比优势。记住：系统已设好止损线，让规则而非情绪来决策。',
        })

    # 2. 跟单系统正面强化
    follow_keywords = ['跟单系统', '跟单', '系统推荐', '系统信号', '跟随系统', '按系统']
    follow_notes = notes[notes.str.contains('|'.join(follow_keywords), na=False)]
    if len(follow_notes) >= 2:
        # Check profitability of followed trades
        sells = trades_df[trades_df['方向'] == '卖出'].copy()
        follow_sells = sells[sells['备注'].str.contains('|'.join(follow_keywords), na=False)]
        if len(follow_sells) >= 2:
            profit_count = 0
            buys = trades_df[trades_df['方向'] == '买入']
            for _, sell in follow_sells.iterrows():
                code_buys = buys[buys['代码'] == sell['代码']]
                if len(code_buys) > 0 and '价格' in sell.index:
                    avg_entry = code_buys['价格'].astype(float).mean()
                    if float(sell['价格']) > avg_entry:
                        profit_count += 1
            if profit_count >= len(follow_sells) * 0.5:
                insights.append({
                    'type': 'success', 'icon': '🎯', 'title': '跟单纪律帮你赚到了！',
                    'message': f'你在{len(follow_sells)}笔卖出交易中备注了跟随系统，其中{profit_count}笔盈利。做得好，跟单纪律正在帮你稳定盈利。继续保持！',
                })
            else:
                insights.append({
                    'type': 'tip', 'icon': '🎯', 'title': '坚持跟单，让统计优势发挥作用',
                    'message': f'你已跟随系统交易{len(follow_notes)}次。虽然短期有波动，但系统回测的统计优势需要足够样本才能体现。继续跟单，不要因短期结果动摇。',
                })

    # 3. 空备注提醒
    total_trades = len(trades_df)
    if total_trades > 0 and len(notes) < total_trades * 0.5:
        insights.append({
            'type': 'tip', 'icon': '📝', 'title': '更多备注 = 更好复盘',
            'message': f'{total_trades - len(notes)}笔交易未填写备注（共{total_trades}笔）。试着记录每笔交易的原因，哪怕只写几个词。下周回顾时你会感谢现在的自己。完全可选，不填系统也正常运行。',
        })

    # 4. 手滑/失误检测
    mistake_keywords = ['手滑', '点错', '误操作', '下错', '打错']
    mistake_notes = notes[notes.str.contains('|'.join(mistake_keywords), na=False)]
    if len(mistake_notes) >= 2:
        insights.append({
            'type': 'warning', 'icon': '⚠️', 'title': '操作失误较多',
            'message': f'检测到{len(mistake_notes)}次操作失误（手滑/误操作）。建议在下单前核对代码和价格，尤其是使用券商APP下单时。可以先用系统模拟订单练习下单流程。',
        })


def _analyze_positive(trades_df, base_dir, insights):
    """积极反馈：表现良好时给予肯定"""
    sells = trades_df[trades_df['方向'] == '卖出'].copy()
    buys = trades_df[trades_df['方向'] == '买入'].copy()
    if len(sells) < 5:
        return

    wins = 0
    total = 0
    for _, sell in sells.iterrows():
        code = sell['代码']
        sell_price = float(sell['价格'])
        code_buys = buys[(buys['代码'] == code) & (pd.to_datetime(buys['日期']) < pd.to_datetime(sell['日期']))]
        if len(code_buys) == 0:
            continue
        avg_entry = code_buys['价格'].mean()
        total += 1
        if sell_price > avg_entry:
            wins += 1

    if total >= 5:
        wr = wins / total * 100
        picks_df = _load_system_picks_all(base_dir)
        system_codes = set(picks_df['代码'].unique()) if len(picks_df) > 0 else set()
        follow_buys = buys[buys['代码'].isin(system_codes)]
        follow_pct = len(follow_buys) / len(buys) * 100 if len(buys) > 0 else 0

        if wr > 55 and follow_pct > 60:
            insights.append({
                'type': 'success', 'icon': '🌟', 'title': '交易纪律良好！',
                'message': f'胜率 {wr:.0f}%，系统跟随率 {follow_pct:.0f}%。你在正确的轨道上——坚持系统信号，让统计优势为你工作。'
            })
