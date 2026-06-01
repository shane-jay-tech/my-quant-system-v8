"""共享工具包 — atomic IO / 交易日历 / 配置读取。

各模块（sim_trade / position_sizer / broker_adapter / alpha_gate /
strategy_feedback ...）都从这里 import，避免函数副本之间发生 drift。
"""
