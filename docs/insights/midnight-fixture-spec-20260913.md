# 时敏 fixture 规范落位记录（d913a-39，2026-09-13，零写库零改码）

- **实况**：S5 设计稿（`D:/code/D:\code\docs\insights\quant-s5-test-design-20260912.md`，根仓）已由 9/13 晨间拍板执行追加「附录：时敏 fixture 规范」三条款（注入固定基准日选午间 / today±N 边界双时点 / 显式时区锚定）。
- 本单补充：按任务要求追加「高危未覆盖项·下批建议」小节，列满 **3 组**（newbie_protection / multi_strategy_main / position_sizer 时区），并把扫描报告中第 4 候选（bark parsers :82 竞态窗口窄）注记随批顺带；只追加未改既有正文。
- 依据：quant-midnight-timebomb-scan-20260913.md 判定表 + e4cc52b（h912-04 侧修先例）。
- 零写库、零改生产码 ✓；S5 文档旧内容零改动（diff=纯追加）✓。
