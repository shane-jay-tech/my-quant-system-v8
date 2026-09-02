# my-quant-system-v8

本地优先的量化研究与交易辅助系统，面向小资金 A 股场景，用于数据抓取、策略研究、回测、组合风控、模拟交易和结果复盘。

## 能做什么

- 抓取并校验 A 股、指数和 ETF 数据
- 计算趋势、动量、波动率和因子信号
- 运行多策略回测、Walk-Forward 和蒙特卡洛分析
- 生成选股、出场、仓位和成本分析结果
- 提供 Alpha Gate、组合风险、交易日和成本门等保护机制
- 通过 Streamlit 仪表盘查看策略与系统健康状态
- 支持 Bark 推送，但推送凭据必须放在本地环境变量中

## 技术栈

Python · pandas · NumPy · SciPy · AKShare · Streamlit · Plotly

## 本地运行

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/health_check.py
streamlit run app.py
```

## 目录说明

- `app/`：仪表盘页面与数据加载
- `core/`：配置、流水线和共享基础逻辑
- `tests/`：单元测试和回归测试
- `scripts/`：数据、健康检查和维护脚本
- `books/`：策略与数据工程笔记

运行时数据目录、交易记录、心理日志、订单、报告和模拟账户结果不会进入公开仓库。首次使用时请根据本地配置创建 `data/` 和环境变量，不要提交 API key、推送 token 或真实交易数据。

## 风险声明

这是研究和纪律训练工具，不构成投资建议，也不能保证盈利。任何真实交易决定都必须由使用者独立判断，并自行承担风险。
