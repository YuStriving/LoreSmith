from __future__ import annotations

from ainovel_py.domain.runtime import FlowState, Phase
from ainovel_py.store.store import Store


def build_resume_prompt(store: Store) -> tuple[str, str]:
    progress = store.progress.load()
    if progress is None:
        return "", ""
    if progress.phase == Phase.COMPLETE:
        return "", ""

    title = progress.novel_name.strip() or "当前小说"
    lines: list[str] = ["[恢复指令]", "", f"本书「{title}」"]

    completed = len(progress.completed_chapters)
    if completed > 0:
        msg = f"已完成 {completed} 章"
        if progress.total_chapters > 0:
            msg += f"（共 {progress.total_chapters} 章）"
        msg += f"，共 {progress.total_word_count} 字。"
        lines[-1] += msg

    label = "恢复"
    if progress.phase in {Phase.PREMISE, Phase.OUTLINE}:
        lines.append("上次在规划阶段中断。请检查当前基础设定状态并继续。")
        label = f"恢复：规划阶段（{progress.phase}）"
    elif progress.phase == Phase.WRITING:
        pending = store.signals.load_pending_commit()
        pending_checkpoint = store.signals.load_pending_checkpoint()
        latest = store.checkpoints.latest_global()

        if pending_checkpoint is not None:
            lines.append(f"已完成第 {pending_checkpoint.pause_after_chapter} 章，正在等待用户确认是否继续编写。")
            lines.append(f"确认后将从第 {pending_checkpoint.next_chapter} 章继续。")
            label = f"恢复：第 {pending_checkpoint.pause_after_chapter} 章检查点待确认"
        elif pending is not None:
            lines.append(f"第 {pending.chapter} 章提交中途中断（阶段：{pending.stage}）。请调用 writer 重新提交该章。")
            label = f"恢复：第 {pending.chapter} 章提交中断"
        elif progress.pending_rewrites:
            verb = "打磨" if progress.flow == FlowState.POLISHING else "重写"
            lines.append(
                f"有 {len(progress.pending_rewrites)} 章待{verb}：{progress.pending_rewrites}。原因：{progress.rewrite_reason}。"
            )
            lines.append(f"请逐章调用 writer 执行{verb}，全部完成后继续写新章节。")
            label = f"{verb}恢复：{len(progress.pending_rewrites)} 章待处理"
        elif progress.in_progress_chapter > 0:
            ch = progress.in_progress_chapter
            step = latest.step if latest and latest.scope.kind == "chapter" and latest.scope.chapter == ch else ""
            if step == "plan":
                lines.append(f"第 {ch} 章计划已完成，请调用 writer 继续写草稿（draft_chapter）。")
            elif step == "draft":
                lines.append(f"第 {ch} 章草稿已落盘。请调用 writer 继续一致性检查（read_chapter + check_consistency），然后 commit。")
            elif step == "consistency_check":
                lines.append(f"第 {ch} 章已完成一致性检查。请调用 writer 提交（commit_chapter）。")
            else:
                lines.append(f"第 {ch} 章正在进行中。请调用 writer 继续完成该章。")
            label = f"恢复：第 {ch} 章进行中（{step})"
        else:
            nxt = progress.next_chapter()
            lines.append(f"请从第 {nxt} 章继续写作。")
            if progress.total_chapters > 0:
                lines.append(f"总共需要写 {progress.total_chapters} 章。")
            label = f"恢复：从第 {nxt} 章继续"

    meta = store.run_meta.load()
    if meta and meta.pending_steer:
        lines.append("")
        lines.append("用户在停机期间留下了一条干预意见：")
        lines.append(f"「{meta.pending_steer}」")
        lines.append("请先评估影响范围，再决定是否微调规划。")

    lines.append("")
    lines.append("如需了解详情请调用 novel_context。")
    return "\n".join(lines), label
