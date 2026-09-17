# quant coverage 两处过期锚点订正（n916d-18，q916-02 披露清偿）

- 班次：sweep-20260916-2300（9/17 08:1x 段）
- 结论：两处失效引用各落一行「订正：」注记（纯追加、原结论零改动）；rg 复跑命中 2 行

## 一、两处订正（file:行＋事实）

**① p913-48 结果**（`zcode-bridge/done/p913-48-quant-coverage-caliber-unify.result.md` :10 引用行）：
- 失效点：所引 `docs/insights/quant-coverage-caliber-20260914.md` 为根仓相对路径——根仓该路径不存在（`ls` 报 No such file）。
- 实际：文件在 `my-quant-system-v8/docs/insights/quant-coverage-caliber-20260914.md`（本仓，实存验证）。
- 落地：文件末尾追加 `> 订正：2026-09-17（n916d-18）……实际文件在 my-quant-system-v8/docs/insights/quant-coverage-caliber-20260914.md……原结论不变。`

**② d914-15 结果**（`zcode-bridge/done/d914-15-quant-coverage-caliber-doc.result.md` :10 引用行）：
- 失效点：「仓内无任何 pytest/coverage 配置文件」已被 p913-40 过期化。
- 实际：`my-quant-system-v8/pytest.ini` 现已存在（本班 `ls` 实存验证；p913-48 亦自证「无 --cov addopts，行为零影响」）。
- 落地：文件末尾追加 `> 订正：2026-09-17（n916d-18）……已被 p913-40 过期化……原结论在当日时点为真。`

## 二、复跑证明（命令在前）

```
$ grep -c "订正：" zcode-bridge/done/p913-48-quant-coverage-caliber-unify.result.md zcode-bridge/done/d914-15-quant-coverage-caliber-doc.result.md
zcode-bridge/done/p913-48-quant-coverage-caliber-unify.result.md:1
zcode-bridge/done/d914-15-quant-coverage-caliber-doc.result.md:1
（合计命中 2 行 ✓）
```

原结论零改动：订正为 `>>` 纯末尾追加（两文件原字节未动，订正行均显式标注行号出处与「原结论不变/当日时点为真」）。

## 三、备注

- 两份 result 文件位于 `zcode-bridge/done/`（归档区，不入 git 追踪）——订正直接落盘生效，无 git 操作。
- 本仓（my-quant-system-v8）产物仅本报告 1 文件；不重算覆盖率、不 push。
