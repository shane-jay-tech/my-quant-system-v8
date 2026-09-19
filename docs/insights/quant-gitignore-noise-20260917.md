# 仓库卫生：backup/ 纳入忽略＋tmp/ 取舍说明（916p-a1-014，2026-09-17）

## 一、取证（改前，命令与输出同段）

```
$ git status --porcelain | grep -E '\?\? (backup|tmp)/'
?? backup/
?? tmp/
$ 文件计数：backup/ 52 个文件（backup/state/<YYYYMMDD>/ 日更，backup_state.py:25 持续产生）；
  tmp/ 9 个文件（含被 docs/insights/empty-remark-nan-repro-20260914.md（量化仓） 引用的 repro_5934.py，
  及 audit/、patches/、repro-env/ 等夜间任务工作目录）
$ git ls-files backup tmp → 空（两者均未被跟踪，忽略规则可生效）
```

## 二、判定与最小修复

- **backup/**：运行期日更产物、可再生 → 追加忽略行 `backup/`。
- **tmp/**：**保持现状（不忽略）＋取舍说明**——①内含被文档引用为「可重复运行」的
  `tmp/repro_5934.py`，整目录忽略会让对外命令失去可见锚点；②audit/、patches/ 等是
  夜间任务的备份/证据目录（历史单多次引用 tmp/ 备份作为回滚锚点），忽略即隐藏证据；
  ③未跟踪噪音行仅 1 行、无门禁影响。取舍：保留可见性优先于消除 status 噪音。
- `.gitignore` 仅追加 1 行（`backup/`），无删除、不动既有段、不改 .gitattributes。

## 三、复验（命令与数字同段）

```
$ git diff --numstat -- .gitignore
1       0       .gitignore                    ← 左列=0 删除 ✓ 仅新增
$ python -c "b=open('.gitignore','rb').read(); print(b[:3] != b'\xef\xbb\xbf', len(b))"
True 777                                 ← 无 BOM ✓
$ git status --porcelain | grep -c '?? backup/' → 0   ← ?? backup/ 行消失 ✓
$ ls backup/state → 在盘 True；$ ls tmp/repro_5934.py → 在盘 True  ← 忽略未丢文件 ✓
$ python -m pytest -q → 660 passed, 4 skipped, 2 xfailed（failed=0，零影响）✓
```

## 四、验收对照

- ✅ 改后 status 不再出现 ?? backup/（前后输出同段）。
- ✅ numstat 左列 0；编码无 BOM 自证 True。
- ✅ 被忽略目录/被引用脚本仍在磁盘。
- ✅ 全量 failed=0。不 push；精确路径提交。
