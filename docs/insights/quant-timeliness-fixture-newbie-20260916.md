# quant 时敏 fixture 第一组落地报告（n916b-02，newbie_protection）

- 冻结日：2026-09-14（周一）。
- 注入：monkeypatch np_mod.datetime = FixedDateTime（now() 返回冻结日）。
- 验收：6 passed；午夜翻转两注入日（23:59/00:01）断言一致；真实 today 依赖 rg=0。
- 生产模块零改动；不 push。

详细见 zcode-bridge/outbox/n916b-02.result.md。
