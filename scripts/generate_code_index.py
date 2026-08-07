"""从 docs/architecture/CODE_INDEX.yaml 生成 CODE_INDEX.md（不两处人工维护）。

Single Source of Truth：YAML 是唯一事实源，MD 是派生产物，禁止手工编辑 MD。
反向依赖（consumers/upstream）由生成器计算，不人工双写。

用法：
    python scripts/generate_code_index.py
"""
import yaml

SRC = "docs/architecture/CODE_INDEX.yaml"
DST = "docs/architecture/CODE_INDEX.md"


def main():
    with open(SRC, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    modules = data["modules"]

    # 计算反向依赖（consumers）：谁消费我
    consumers: dict[str, list[dict]] = {}
    for mid in sorted(modules):
        for dep in modules[mid].get("dependencies", []):
            target = dep["module"]
            consumers.setdefault(target, []).append({
                "from": mid,
                "type": dep["type"],
                "direction": dep["direction"],
                "reason": dep["reason"],
            })

    out = []
    out.append("<!-- GENERATED FILE - 从 docs/architecture/CODE_INDEX.yaml 生成，禁止手工编辑 -->")
    out.append("# auto_wechat 机器代码索引（CODE_INDEX）")
    out.append("")
    sb = data["project"]["source_baseline"]
    out.append("> 本文档从 `CODE_INDEX.yaml` 自动生成，**禁止手工编辑**。YAML 是唯一事实源。")
    out.append(f"> source_baseline: `{sb['git_commit']}` | last_verified_at: {data['project']['last_verified_at']} | schema_version: {data['schema_version']}")
    out.append("")

    out.append("## 平台公共底座（跨所有模块）")
    out.append("")
    for k, v in data["project"]["platform_shared"].items():
        out.append(f"- **{k}**: {v}")
    out.append("")

    out.append("## 领域共享能力（客户/线索领域，非平台基础设施）")
    out.append("")
    for k, v in data["project"]["domain_shared"].items():
        out.append(f"- **{k}**: {v}")
    out.append("")

    out.append("## 数据库")
    out.append("")
    out.append(f"- 主库: {data['project']['database']['primary']}")
    out.append(f"- RAG 库: {data['project']['database']['rag']}")
    out.append("")

    out.append("## 依赖语义说明")
    out.append("")
    out.append("- `dependencies` 只记录**当前模块主动依赖/消费谁**，单向维护，反向关系由本生成器计算。")
    out.append("- `type`: runtime（运行时调用）/ data（跨模块读写表）/ shared_implementation（共用代码，解耦候选）/ integration（边界集成）")
    out.append("- `lifecycle_candidates`: 未定性候选（UNKNOWN ≠ LEGACY，正式定性见 1A.5）")
    out.append("")

    for mid in sorted(modules):
        m = modules[mid]
        out.append("---")
        out.append("")
        status = m.get("status", "")
        out.append(f"## {mid} {m['name']} (`{status}`)")
        out.append("")
        fe = m.get("frontend", {})
        if fe:
            out.append("### 前端")
            if fe.get("routes"):
                out.append(f"- 路由: {' / '.join(fe['routes'])}")
            if fe.get("nav_ids"):
                out.append(f"- nav_ids: {', '.join(fe['nav_ids'])}")
            if fe.get("feature_dir"):
                out.append(f"- feature 目录: `{fe['feature_dir']}`")
            if fe.get("pages"):
                out.append("- 页面:")
                for p in fe["pages"]:
                    out.append(f"  - `{p}`")
            out.append("")
        be = m.get("backend", {})
        if be:
            out.append("### 后端")
            if be.get("routers"):
                out.append("- routers:")
                for r in be["routers"]:
                    out.append(f"  - `{r}`")
            if be.get("services"):
                out.append("- services:")
                for s in be["services"]:
                    out.append(f"  - `{s}`")
            if be.get("entrypoints"):
                out.append(f"- 入口函数: {', '.join(be['entrypoints'])}")
            if be.get("subapp"):
                sa = be["subapp"]
                out.append(f"- 子应用 `{sa['path']}`:")
                if sa.get("routers"):
                    out.append(f"  - routers: {', '.join(sa['routers'])}")
                if sa.get("services"):
                    out.append(f"  - services: {', '.join(sa['services'])}")
                if sa.get("entrypoints"):
                    out.append(f"  - 入口: {', '.join(sa['entrypoints'])}")
            out.append("")
        if m.get("workers"):
            out.append("### workers")
            for w in m["workers"]:
                out.append(f"- {w}")
            out.append("")
        if m.get("external_services"):
            out.append(f"### 外部依赖: {', '.join(m['external_services'])}")
            out.append("")
        if m.get("tables"):
            out.append("### 数据表")
            for t in m["tables"]:
                out.append(f"- `{t}`")
            out.append("")
        if m.get("config"):
            out.append("### 配置项")
            for c in m["config"]:
                out.append(f"- `{c}`")
            out.append("")
        if m.get("tests"):
            out.append("### 测试")
            for t in m["tests"]:
                out.append(f"- `{t}`")
            out.append("")

        # 依赖（主动方向）
        deps = m.get("dependencies", [])
        if deps:
            out.append("### 依赖（主动方向，单向维护）")
            out.append("")
            out.append("| 目标 | type | direction | reason |")
            out.append("|---|---|---|---|")
            for d in deps:
                out.append(f"| {d['module']} | {d['type']} | {d['direction']} | {d['reason']} |")
            out.append("")
        else:
            out.append("### 依赖（主动方向）")
            out.append("")
            out.append("无主动上游依赖。")
            out.append("")

        # 反向消费者（生成器计算）
        cons = consumers.get(mid, [])
        if cons:
            out.append(f"### 被消费方（生成器计算，反向）")
            out.append("")
            out.append("| 来源 | type | direction | reason |")
            out.append("|---|---|---|---|")
            for c in cons:
                out.append(f"| {c['from']} | {c['type']} | {c['direction']} | {c['reason']} |")
            out.append("")

        lc = m.get("lifecycle_candidates", [])
        if lc:
            out.append("### lifecycle_candidates（UNKNOWN ≠ LEGACY，正式定性见 1A.5）")
            out.append("")
            for c in lc:
                out.append(f"- `{c['path']}` — {c['note']} (`{c['lifecycle']}`)")
            out.append("")

    out.append("---")
    out.append("")
    out.append("## 平台公共底座测试")
    out.append("")
    for k, v in data.get("platform_tests", {}).items():
        out.append(f"- **{k}**: {', '.join(v)}")
    out.append("")

    with open(DST, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"生成成功: {DST}（从 {SRC}）")


if __name__ == "__main__":
    main()
