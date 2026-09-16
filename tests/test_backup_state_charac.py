"""backup_state.py characterization 用例（916p-a1-001）。

断言的是 main() 的四个分支行为（missing/copied/幂等/保留期剪枝）与退出码契约，
全部把仓根挪进 tmp_path（monkeypatch BASE），绝不触碰真实 backup/state/。
禁止断言任何资金/收益/统计数值（本文件无业务数值断言）。
可复跑：python -m pytest tests/test_backup_state_charac.py -q
"""
import re

import backup_state


SOURCES = backup_state.SOURCES


def _make_sources(base):
    """按 SOURCES 相对路径在 tmp 仓根造出全部源文件。"""
    for rel in SOURCES:
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")


def test_all_sources_missing_returns_1_and_counts_4(monkeypatch, tmp_path, capsys):
    """四源全缺 → 退出码 1 且 missing 计数=4：失败契约要求 copied=0 时 rc=1。"""
    monkeypatch.setattr(backup_state, "BASE", tmp_path)
    rc = backup_state.main()
    assert rc == 1
    out = capsys.readouterr().out
    assert "copied=0" in out and "missing=4" in out


def test_all_sources_present_copies_four_same_names(monkeypatch, tmp_path, capsys):
    """四源全在 → rc 0 且目标日目录出现 4 个同名文件（copy2 语义）。"""
    monkeypatch.setattr(backup_state, "BASE", tmp_path)
    _make_sources(tmp_path)
    rc = backup_state.main()
    assert rc == 0
    stamp = re.search(r"date=(\d{8})", capsys.readouterr().out).group(1)
    dest = tmp_path / "backup" / "state" / stamp
    names = {p.name for p in dest.iterdir()}
    assert names == {rel.split("/")[-1] for rel in SOURCES}


def test_same_day_rerun_overwrites_idempotent(monkeypatch, tmp_path, capsys):
    """同日重复执行 → 覆盖不报错仍 rc 0：幂等契约（in-place overwrite）。"""
    monkeypatch.setattr(backup_state, "BASE", tmp_path)
    _make_sources(tmp_path)
    assert backup_state.main() == 0
    (tmp_path / SOURCES[0]).write_text('{"v":2}', encoding="utf-8")
    assert backup_state.main() == 0
    stamp = re.search(r"date=(\d{8})", capsys.readouterr().out).group(1)
    assert (tmp_path / "backup" / "state" / stamp / "account_state.json").read_text(
        encoding="utf-8"
    ) == '{"v":2}'


def test_old_dated_dir_pruned(monkeypatch, tmp_path, capsys):
    """早于 cutoff 的 8 位日期目录 → 被 rmtree 剪枝（retention 主路径）。"""
    monkeypatch.setattr(backup_state, "BASE", tmp_path)
    state_root = tmp_path / "backup" / "state"
    (state_root / "20200101").mkdir(parents=True)
    (state_root / "20200101" / "x.json").write_text("{}", encoding="utf-8")
    assert backup_state.main() == 1  # 无源文件 → rc 1，但剪枝仍执行
    assert "20200101" in capsys.readouterr().out
    assert not (state_root / "20200101").exists()


def test_non_date_dir_never_pruned(monkeypatch, tmp_path, capsys):
    """非日期名目录（manual）→ 不得被删：fullmatch(r"\d{8}") 白名单语义。"""
    monkeypatch.setattr(backup_state, "BASE", tmp_path)
    state_root = tmp_path / "backup" / "state"
    (state_root / "manual").mkdir(parents=True)
    (state_root / "manual" / "keep.txt").write_text("keep", encoding="utf-8")
    backup_state.main()
    assert (state_root / "manual" / "keep.txt").exists()


def test_future_dated_dir_kept(monkeypatch, tmp_path, capsys):
    """晚于 cutoff 的 99991231 目录 → 保留（未到保留期不剪）。"""
    monkeypatch.setattr(backup_state, "BASE", tmp_path)
    state_root = tmp_path / "backup" / "state"
    (state_root / "99991231").mkdir(parents=True)
    backup_state.main()
    assert (state_root / "99991231").exists()
