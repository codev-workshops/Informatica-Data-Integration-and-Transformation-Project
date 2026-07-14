#!/usr/bin/env python3
"""Analyze Informatica PowerCenter metadata exports and build a transformation
logic inventory.

Produces (under docs/inventory/):
  - REUSABLE_LOGIC_INVENTORY.md : every distinct logic segment, where it lives,
                                  and its data dependencies.
  - DUPLICATE_LOGIC.md          : logic segments that appear in more than one
                                  place, with usage graphs.
  - MERGE_ANALYSIS.md           : logic that can be merged into shared/reusable
                                  components, a merging graph, and a complexity
                                  ranking for performing each merge.
  - *.dot / *.svg / *.png       : Graphviz renderings of the usage / merge graphs.

Stdlib only.  Run:  python3 tools/inventory_logic.py
"""
from __future__ import annotations

import html
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import OrderedDict, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROJ = os.path.join(ROOT, "ExploreInformatica Project")
MAP_XML = os.path.join(PROJ, "Mapping_ExploreInformatica.XML")
WF_XML = os.path.join(PROJ, "WorkFlow_ExploreInformatica.XML")
OUT_DIR = os.path.join(ROOT, "docs", "inventory")


# ---------------------------------------------------------------------------
# XML loading
# ---------------------------------------------------------------------------
def load_root(path: str) -> ET.Element:
    with open(path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("cp1252")
    text = re.sub(r"<!DOCTYPE[^>]*>", "", text, count=1)
    return ET.fromstring(text)


def norm(expr: str | None) -> str:
    """Canonicalise an expression for equality comparison."""
    if not expr:
        return ""
    s = html.unescape(expr)
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Ports/columns referenced inside an expression (best-effort identifier scan).
KEYWORDS = {
    "AND", "OR", "NOT", "TRUE", "FALSE", "NULL", "IIF", "DECODE", "SUM",
    "AVG", "MAX", "MIN", "COUNT", "ERROR", "ABORT", "TO_CHAR", "TO_DATE",
    "TO_DECIMAL", "TO_INTEGER", "LTRIM", "RTRIM", "UPPER", "LOWER", "CONCAT",
    "SUBSTR", "INSTR", "LENGTH", "ROUND", "TRUNC", "ISNULL", "IS", "IN",
}


def refs(expr: str) -> list[str]:
    if not expr:
        return []
    s = html.unescape(expr)
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", s)
    out = []
    for t in toks:
        if t.upper() in KEYWORDS:
            continue
        if t not in out:
            out.append(t)
    return out


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
class Segment:
    """A single unit of transformation logic."""

    def __init__(self, mapping, transformation, ttype, category, name, expr,
                 extra=None):
        self.mapping = mapping
        self.transformation = transformation
        self.ttype = ttype              # Informatica transformation type
        self.category = category        # e.g. "Output Expression", "Join Condition"
        self.name = name                # port / attribute name
        self.expr = norm(expr)
        self.extra = extra or {}
        self.refs = refs(expr)

    @property
    def key(self):
        """Identity used for duplicate detection: what the logic *does*."""
        return (self.category, self.expr)

    @property
    def template(self):
        """Structural signature: identifiers -> ID, numeric literals -> NUM.

        Groups near-duplicate logic that differs only by column/constant, i.e.
        logic that could be merged/parameterised into one shared component.
        """
        s = html.unescape(self.expr)
        s = re.sub(r"'[^']*'", "STR", s)
        s = re.sub(r"\b\d+(?:\.\d+)?\b", "NUM", s)

        def repl(m):
            tok = m.group(0)
            if tok in ("STR", "NUM") or tok.upper() in KEYWORDS:
                return tok
            return "ID"

        s = re.sub(r"[A-Za-z_][A-Za-z0-9_.]*", repl, s)
        s = re.sub(r"\s+", " ", s).strip()
        return (self.category, s)


def attrs(el, want):
    """Return {name: value} for TABLEATTRIBUTE children whose NAME in want."""
    out = {}
    for ta in el.findall("TABLEATTRIBUTE"):
        n = ta.get("NAME")
        if n in want:
            out[n] = ta.get("VALUE") or ""
    return out


def parse():
    root = load_root(MAP_XML)
    folder = root.find("REPOSITORY/FOLDER")

    sources = OrderedDict()
    targets = OrderedDict()
    for src in folder.findall("SOURCE"):
        sources[src.get("NAME")] = [f.get("NAME") for f in src.findall("SOURCEFIELD")]
    for tgt in folder.findall("TARGET"):
        targets[tgt.get("NAME")] = [f.get("NAME") for f in tgt.findall("TARGETFIELD")]

    mappings = OrderedDict()          # name -> dict
    segments: list[Segment] = []

    for m in folder.findall("MAPPING"):
        mname = m.get("NAME")
        mp = {
            "name": mname,
            "transformations": OrderedDict(),   # tname -> type
            "instances": [],
            "connectors": [],
            "sources": [],
            "targets": [],
        }

        for t in m.findall("TRANSFORMATION"):
            tname = t.get("NAME")
            ttype = t.get("TYPE")
            mp["transformations"][tname] = ttype

            # Port-level expressions (Expression / Aggregator / Rank / Router io)
            for f in t.findall("TRANSFORMFIELD"):
                e = f.get("EXPRESSION")
                port = f.get("PORTTYPE") or ""
                if e and norm(e) and norm(e) != f.get("NAME"):
                    # ignore pass-through where EXPRESSION == port name
                    cat = "Output Expression"
                    if "VARIABLE" in port:
                        cat = "Variable Expression"
                    segments.append(Segment(mname, tname, ttype, cat,
                                            f.get("NAME"), e))

            # Router / group conditions
            for g in t.findall("GROUP"):
                e = g.get("EXPRESSION")
                if e:
                    segments.append(Segment(mname, tname, ttype,
                                            "Router Group Condition",
                                            g.get("NAME"), e))

            # Attribute-based logic
            a = attrs(t, {
                "Filter Condition", "Join Condition", "Join Type",
                "Lookup condition", "Lookup Sql Override", "Lookup table name",
                "Sql Query", "Source Filter", "User Defined Join",
                "Start Value", "Increment By", "End Value",
            })
            if ttype == "Filter" and norm(a.get("Filter Condition")):
                segments.append(Segment(mname, tname, ttype, "Filter Condition",
                                        "Filter Condition", a["Filter Condition"]))
            if ttype == "Joiner":
                jc = a.get("Join Condition")
                if norm(jc):
                    segments.append(Segment(mname, tname, ttype, "Join Condition",
                                            "Join Condition", jc,
                                            {"join_type": a.get("Join Type", "")}))
            if ttype == "Lookup Procedure":
                if norm(a.get("Lookup condition")):
                    segments.append(Segment(mname, tname, ttype, "Lookup Condition",
                                            "Lookup Condition", a["Lookup condition"],
                                            {"table": a.get("Lookup table name", "")}))
                if norm(a.get("Lookup Sql Override")):
                    segments.append(Segment(mname, tname, ttype, "Lookup SQL Override",
                                            "Lookup Sql Override",
                                            a["Lookup Sql Override"]))
            if ttype == "Source Qualifier":
                for label, key in (("Source Qualifier SQL", "Sql Query"),
                                   ("Source Filter", "Source Filter"),
                                   ("User Defined Join", "User Defined Join")):
                    if norm(a.get(key)):
                        segments.append(Segment(mname, tname, ttype, label,
                                                key, a[key]))

        for inst in m.findall("INSTANCE"):
            rec = {
                "name": inst.get("NAME"),
                "kind": inst.get("TYPE"),
                "ttype": inst.get("TRANSFORMATION_TYPE"),
                "tname": inst.get("TRANSFORMATION_NAME"),
            }
            mp["instances"].append(rec)
            if rec["kind"] == "SOURCE":
                mp["sources"].append(rec["name"])
            elif rec["kind"] == "TARGET":
                mp["targets"].append(rec["name"])

        seen = set()
        for c in m.findall("CONNECTOR"):
            edge = (c.get("FROMINSTANCE"), c.get("TOINSTANCE"))
            if edge not in seen and edge[0] != edge[1]:
                seen.add(edge)
                mp["connectors"].append(edge)

        mappings[mname] = mp

    return sources, targets, mappings, segments


# ---------------------------------------------------------------------------
# Workflow / session / task parsing (for linkage of logic to execution)
# ---------------------------------------------------------------------------
def parse_workflows():
    root = load_root(WF_XML)
    folder = root.find("REPOSITORY/FOLDER")
    workflows = OrderedDict()
    sessions = OrderedDict()   # session name -> mapping name
    for wf in folder.findall("WORKFLOW"):
        wname = wf.get("NAME")
        tasks = []
        for ti in wf.findall("TASKINSTANCE"):
            tasks.append({"name": ti.get("TASKNAME"), "type": ti.get("TASKTYPE")})
        workflows[wname] = {"tasks": tasks}
    for s in folder.findall("SESSION"):
        sessions[s.get("NAME")] = s.get("MAPPINGNAME")
    # sessions may also be nested inside workflow TASK elements
    for s in folder.iter("SESSION"):
        if s.get("NAME") and s.get("MAPPINGNAME"):
            sessions[s.get("NAME")] = s.get("MAPPINGNAME")
    return workflows, sessions


# ---------------------------------------------------------------------------
# Graph rendering helper
# ---------------------------------------------------------------------------
def render(dot_path):
    base = os.path.splitext(dot_path)[0]
    for fmt in ("svg", "png"):
        try:
            subprocess.run(["dot", f"-T{fmt}", dot_path, "-o", f"{base}.{fmt}"],
                           check=True, capture_output=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! could not render {fmt}: {exc}")


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------------------
# Complexity model
# ---------------------------------------------------------------------------
# Base effort weight per transformation type (active/stateful transforms cost
# more to extract into a shared component than passive ones).
TYPE_WEIGHT = {
    "Expression": 1,
    "Filter": 1,
    "Router": 2,
    "Source Qualifier": 2,
    "Sequence": 2,
    "Rank": 3,
    "Normalizer": 3,
    "Aggregator": 3,
    "Joiner": 4,
    "Lookup Procedure": 4,
    "Custom Transformation": 5,
}


def instance_degree(mappings):
    """upstream/downstream instance connections per (mapping, instance)."""
    deg = defaultdict(lambda: {"in": 0, "out": 0})
    for mp in mappings.values():
        for a, b in mp["connectors"]:
            deg[(mp["name"], a)]["out"] += 1
            deg[(mp["name"], b)]["in"] += 1
    return deg


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    sources, targets, mappings, segments = parse()
    workflows, sessions = parse_workflows()
    deg = instance_degree(mappings)

    # mapping -> workflow/session linkage
    map_to_sessions = defaultdict(list)
    for sname, mname in sessions.items():
        map_to_sessions[mname].append(sname)

    # group segments by identity
    groups = defaultdict(list)   # key -> [Segment]
    for s in segments:
        groups[s.key].append(s)

    # -------------------------------------------------------------------
    # 1. Reusable logic inventory
    # -------------------------------------------------------------------
    lines = []
    L = lines.append
    L("# Reusable Transformation Logic Inventory\n")
    L("_Auto-generated by `tools/inventory_logic.py`. Do not edit by hand._\n")
    L(f"Source exports: `ExploreInformatica Project/Mapping_ExploreInformatica.XML`, "
      f"`WorkFlow_ExploreInformatica.XML`\n")
    L("## Scope\n")
    L(f"- Mappings analyzed: **{len(mappings)}**")
    total_tx = sum(len(m["transformations"]) for m in mappings.values())
    L(f"- Transformations analyzed: **{total_tx}**")
    L(f"- Distinct logic segments extracted: **{len(segments)}**")
    L(f"- Distinct logic *definitions* (after de-duplication): **{len(groups)}**")
    L(f"- Reusable/shared transformations (`REUSABLE=YES`): **0** "
      "(none defined in this repository)")
    L(f"- Mapplets: **0** (no `<MAPPLET>` objects exist in the export)\n")
    L("> Because the project contains **no mapplets and no reusable "
      "transformations**, every piece of logic below is currently embedded "
      "inline in a single mapping. 'Reusable logic' therefore means *logic "
      "that is a candidate to become reusable* — see `MERGE_ANALYSIS.md`.\n")

    # inventory grouped by category
    by_cat = defaultdict(list)
    for key, segs in groups.items():
        by_cat[key[0]].append((key, segs))

    L("## Logic segments by category\n")
    idx = 0
    seg_id = {}   # key -> Lxx id
    for cat in sorted(by_cat):
        L(f"### {cat}\n")
        L("| # | Logic | Occurrences | Mappings | Transformations | Depends on (ports) |")
        L("|---|-------|-------------|----------|-----------------|--------------------|")
        for key, segs in sorted(by_cat[cat], key=lambda x: -len(x[1])):
            idx += 1
            sid = f"L{idx:02d}"
            seg_id[key] = sid
            maps = sorted({s.mapping for s in segs})
            txs = sorted({s.transformation for s in segs})
            deps = segs[0].refs
            expr = key[1] or "(empty)"
            L(f"| {sid} | `{esc(expr)[:90]}` | {len(segs)} | "
              f"{', '.join(maps)} | {', '.join(txs)} | "
              f"{', '.join(deps[:8])} |")
        L("")

    # per-mapping dependency summary
    L("## Per-mapping logic & data dependencies\n")
    for mname, mp in mappings.items():
        L(f"### `{mname}`\n")
        sess = map_to_sessions.get(mname, [])
        L(f"- Executed by session(s): {', '.join(f'`{x}`' for x in sess) or '—'}")
        L(f"- Sources: {', '.join(f'`{x}`' for x in mp['sources']) or '—'}")
        L(f"- Targets: {', '.join(f'`{x}`' for x in mp['targets']) or '—'}")
        tx_list = ", ".join(f"`{n}` ({t})" for n, t in mp["transformations"].items())
        L(f"- Transformations: {tx_list}")
        msegs = [s for s in segments if s.mapping == mname]
        if msegs:
            L(f"- Logic segments:")
            for s in msegs:
                shared = len(groups[s.key]) > 1
                tag = " **[shared]**" if shared else ""
                L(f"  - `{s.transformation}` / {s.category} `{s.name}`: "
                  f"`{esc(s.expr)[:80]}`{tag}")
        L("")

    with open(os.path.join(OUT_DIR, "REUSABLE_LOGIC_INVENTORY.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")

    # -------------------------------------------------------------------
    # 2. Duplicate logic + usage graph
    # -------------------------------------------------------------------
    dups = {k: v for k, v in groups.items() if len(v) > 1}
    dlines = []
    D = dlines.append
    D("# Duplicate Logic Segments & Usage Graphs\n")
    D("_Auto-generated by `tools/inventory_logic.py`._\n")
    D(f"Duplicate logic definitions (used in >1 transformation): **{len(dups)}**\n")
    if not dups:
        D("No exact-duplicate logic segments were found.\n")
    for key, segs in sorted(dups.items(), key=lambda x: -len(x[1])):
        sid = seg_id[key]
        D(f"## {sid} — {key[0]}\n")
        D(f"```\n{key[1]}\n```\n")
        D(f"Used **{len(segs)}×** across "
          f"{len(set(s.mapping for s in segs))} mapping(s):\n")
        D("| Mapping | Transformation | Type | Port/Attr |")
        D("|---------|----------------|------|-----------|")
        for s in segs:
            D(f"| `{s.mapping}` | `{s.transformation}` | {s.ttype} | {s.name} |")
        D("")

    # usage graph dot: logic node -> transformation(mapping) nodes
    dot = ["digraph usage {", "  rankdir=LR;", "  node [fontname=Helvetica];",
           '  graph [fontname=Helvetica];']
    for key, segs in dups.items():
        sid = seg_id[key]
        dot.append(f'  "{sid}" [shape=box,style=filled,fillcolor="#ffe0b2",'
                   f'label="{sid}\\n{esc(key[0])}"];')
        for s in segs:
            node = f"{s.mapping}:{s.transformation}"
            dot.append(f'  "{node}" [shape=ellipse,style=filled,'
                       f'fillcolor="#bbdefb",label="{esc(s.transformation)}\\n({esc(s.mapping)})"];')
            dot.append(f'  "{sid}" -> "{node}";')
    dot.append("}")
    dot_path = os.path.join(OUT_DIR, "duplicate_usage.dot")
    with open(dot_path, "w") as fh:
        fh.write("\n".join(dot) + "\n")
    render(dot_path)
    D("## Usage graph\n")
    D("![Duplicate logic usage graph](duplicate_usage.svg)\n")

    with open(os.path.join(OUT_DIR, "DUPLICATE_LOGIC.md"), "w") as fh:
        fh.write("\n".join(dlines) + "\n")

    # -------------------------------------------------------------------
    # 3. Merge analysis: merging graph + complexity ranking
    # -------------------------------------------------------------------
    # Merge candidate = a duplicate logic definition that can be lifted into a
    # shared reusable transformation / mapplet.
    mlines = []
    M = mlines.append
    M("# Merge Analysis: Consolidation Candidates, Merging Graph & Complexity Ranking\n")
    M("_Auto-generated by `tools/inventory_logic.py`._\n")

    M("## Method\n")
    M("A **merge candidate** is a logic definition that occurs in two or more "
      "transformations. Merging it means extracting the logic once into a "
      "shared/reusable object (a reusable transformation or a mapplet) and "
      "referencing it from each mapping.\n")
    M("**Complexity score** estimates the effort/risk of performing the merge:\n")
    M("```\n"
      "complexity = type_weight\n"
      "           + (mappings_touched - 1) * 2      # coordination across mappings\n"
      "           + total_downstream_connectors      # blast radius / re-wiring\n"
      "           + total_upstream_connectors        # input dependencies to reconnect\n"
      "```\n")
    M("`type_weight`: " + ", ".join(f"{k}={v}" for k, v in TYPE_WEIGHT.items()) + ".\n")
    M("Higher score = harder/riskier merge. Active transforms (Joiner, Lookup, "
      "Aggregator) that sit deep in a pipeline score highest.\n")

    ranking = []
    for key, segs in dups.items():
        sid = seg_id[key]
        maps_touched = sorted({s.mapping for s in segs})
        tw = max(TYPE_WEIGHT.get(s.ttype, 2) for s in segs)
        down = up = 0
        for s in segs:
            d = deg.get((s.mapping, s.transformation), {"in": 0, "out": 0})
            up += d["in"]
            down += d["out"]
        score = tw + (len(maps_touched) - 1) * 2 + down + up
        ranking.append({
            "sid": sid, "cat": key[0], "expr": key[1], "type": segs[0].ttype,
            "occurrences": len(segs), "maps": maps_touched,
            "type_weight": tw, "up": up, "down": down, "score": score,
        })
    ranking.sort(key=lambda r: r["score"])

    M("## Complexity ranking (easiest → hardest to merge)\n")
    M("| Rank | Logic | Category | Type | Occ. | Mappings touched | Upstream | Downstream | Complexity |")
    M("|------|-------|----------|------|------|------------------|----------|------------|------------|")
    for i, r in enumerate(ranking, 1):
        M(f"| {i} | {r['sid']} | {r['cat']} | {r['type']} | {r['occurrences']} | "
          f"{len(r['maps'])} | {r['up']} | {r['down']} | **{r['score']}** |")
    M("")

    M("### Recommended order of work\n")
    for i, r in enumerate(ranking, 1):
        band = ("Low" if r["score"] <= 6 else "Medium" if r["score"] <= 12 else "High")
        M(f"{i}. **{r['sid']}** ({r['cat']}, {r['type']}) — complexity "
          f"**{r['score']} [{band}]**. Extract `{esc(r['expr'])[:70]}` into a "
          f"shared object; update {len(r['maps'])} mapping(s): "
          f"{', '.join('`'+m+'`' for m in r['maps'])}.")
    M("")

    # merging graph: mappings connected by shared logic
    pair_shared = defaultdict(list)   # (mapA, mapB) -> [sid]
    for key, segs in dups.items():
        maps_touched = sorted({s.mapping for s in segs})
        for i in range(len(maps_touched)):
            for j in range(i + 1, len(maps_touched)):
                pair_shared[(maps_touched[i], maps_touched[j])].append(seg_id[key])

    M("## Merging graph\n")
    M("Nodes are mappings; an edge means the two mappings share mergeable logic "
      "(edge label lists the shared logic IDs). Clusters of connected mappings "
      "are natural candidates for a **single shared mapplet**.\n")
    M("![Merging graph](merging_graph.svg)\n")

    if pair_shared:
        M("| Mapping A | Mapping B | Shared logic | Merge weight |")
        M("|-----------|-----------|--------------|--------------|")
        for (a, b), sids in sorted(pair_shared.items(), key=lambda x: -len(x[1])):
            M(f"| `{a}` | `{b}` | {', '.join(sids)} | {len(sids)} |")
        M("")

    dot = ["graph merging {", "  layout=neato;", "  overlap=false;",
           "  node [shape=box,style=filled,fillcolor=\"#c8e6c9\",fontname=Helvetica];",
           "  edge [fontname=Helvetica,fontsize=10];"]
    nodes = set()
    for (a, b), sids in pair_shared.items():
        nodes.add(a)
        nodes.add(b)
    for n in nodes:
        dot.append(f'  "{n}";')
    for (a, b), sids in pair_shared.items():
        dot.append(f'  "{a}" -- "{b}" [label="{",".join(sids)}",'
                   f'penwidth={min(1+len(sids),6)}];')
    dot.append("}")
    dot_path = os.path.join(OUT_DIR, "merging_graph.dot")
    with open(dot_path, "w") as fh:
        fh.write("\n".join(dot) + "\n")
    render(dot_path)

    # connected components of the merging graph -> mapplet clusters
    adj = defaultdict(set)
    for (a, b) in pair_shared:
        adj[a].add(b)
        adj[b].add(a)
    seen = set()
    clusters = []
    for n in adj:
        if n in seen:
            continue
        stack = [n]
        comp = []
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            comp.append(x)
            stack.extend(adj[x] - seen)
        clusters.append(sorted(comp))

    # near-duplicate (parameterizable) families
    tmpl = defaultdict(list)
    for s in segments:
        tmpl[s.template].append(s)
    families = []
    for t, segs in tmpl.items():
        exprs = sorted({s.expr for s in segs})
        if len(segs) >= 2 and len(exprs) >= 2:   # same shape, different constants
            families.append((t, segs, exprs))
    families.sort(key=lambda x: -len(x[1]))

    M("## Parameterizable logic families (near-duplicates)\n")
    M("These segments are **structurally identical** but differ only by column "
      "or constant. They can be merged into a single **parameterized** shared "
      "transformation/mapplet (using mapping parameters or a common expression "
      "template) rather than copied per mapping.\n")
    if not families:
        M("No near-duplicate families detected.\n")
    for i, (t, segs, exprs) in enumerate(families, 1):
        M(f"### Family F{i} — {t[0]}\n")
        M(f"Template: `{esc(t[1])}`  ({len(segs)} occurrences, "
          f"{len(exprs)} distinct variants)\n")
        M("| Variant | Mapping | Transformation |")
        M("|---------|---------|----------------|")
        for s in segs:
            M(f"| `{esc(s.expr)}` | `{s.mapping}` | `{s.transformation}` |")
        M("")

    M("## Suggested shared-mapplet clusters\n")
    if not clusters:
        M("No cross-mapping merge clusters (duplicates, if any, are within a "
          "single mapping).\n")
    for i, comp in enumerate(clusters, 1):
        sids = set()
        for (a, b), s in pair_shared.items():
            if a in comp and b in comp:
                sids.update(s)
        M(f"- **Cluster {i}**: {', '.join('`'+m+'`' for m in comp)} — "
          f"shared logic {', '.join(sorted(sids))}. Candidate for one common "
          "mapplet feeding all listed mappings.")
    M("")

    with open(os.path.join(OUT_DIR, "MERGE_ANALYSIS.md"), "w") as fh:
        fh.write("\n".join(mlines) + "\n")

    # -------------------------------------------------------------------
    # Index
    # -------------------------------------------------------------------
    ilines = [
        "# Transformation Logic Inventory\n",
        "_Auto-generated by `tools/inventory_logic.py` "
        "(run `python3 tools/inventory_logic.py` to regenerate)._\n",
        "Static analysis of the Informatica PowerCenter exports in "
        "`ExploreInformatica Project/`.\n",
        "## Contents\n",
        "1. [Reusable transformation logic inventory & dependencies]"
        "(REUSABLE_LOGIC_INVENTORY.md) — every distinct logic segment, where it "
        "lives, which session/workflow runs it, and its data (port) dependencies.",
        "2. [Duplicate logic segments & usage graphs](DUPLICATE_LOGIC.md) — "
        "logic copied verbatim across transformations, with a usage graph "
        "([svg](duplicate_usage.svg) / [png](duplicate_usage.png)).",
        "3. [Merge analysis](MERGE_ANALYSIS.md) — logic that can be merged into "
        "shared components, a merging graph ([svg](merging_graph.svg) / "
        "[png](merging_graph.png)), near-duplicate parameterizable families, and "
        "a complexity ranking for performing each merge.\n",
        "## Headline findings\n",
        f"- {len(mappings)} mappings, {total_tx} transformations, "
        f"{len(sessions)} sessions, {len(workflows)} workflows.",
        f"- {len(segments)} logic segments -> {len(groups)} distinct definitions.",
        f"- **{len(dups)} exact-duplicate** definitions and "
        f"**{len(families)} near-duplicate families** are merge candidates.",
        "- **0 mapplets / 0 reusable transformations** exist today — all logic "
        "is inlined, so every duplicate is a copy-paste that must be edited in "
        "each mapping independently.\n",
    ]
    with open(os.path.join(OUT_DIR, "README.md"), "w") as fh:
        fh.write("\n".join(ilines) + "\n")

    print(f"Wrote inventory to {OUT_DIR}")
    print(f"  segments={len(segments)} definitions={len(groups)} duplicates={len(dups)}")


if __name__ == "__main__":
    main()
