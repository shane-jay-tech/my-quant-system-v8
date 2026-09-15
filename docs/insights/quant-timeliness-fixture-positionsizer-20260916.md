# quant 时敏 fixture 落地报告：position_sizer（n916b-03）

- 冻结日：2026-09-14 / 2026-09-13（两注入日对照）。
- 改动：tests/test_position_sizer.py 四处 date.today() 依赖替换为冻结日期字面量（hysteresis 三用例）。
- 验收：python -m pytest tests/test_position_sizer.py -q → 12 passed；午夜翻转两日期断言一致。
- 生产模块 position_sizer.py 零改动。
- 详细见 zcode-bridge/outbox/n916b-03.result.md。
