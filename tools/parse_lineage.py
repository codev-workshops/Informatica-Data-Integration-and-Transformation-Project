#!/usr/bin/env python3
"""Parse Informatica PowerCenter metadata exports (mapping + workflow XML) and
generate a dependency / lineage analysis: source -> transformation -> target.

Outputs (under docs/lineage/):
  - DEPENDENCY_LINEAGE.md  : full inventory + per-mapping Mermaid flowcharts + overall lineage
  - lineage.dot            : Graphviz representation of the end-to-end flow
  - lineage_overview.dot   : condensed source->mapping->target overview

The parser relies only on the Python standard library.
"""
from __future__ import annotations

import html
import os
import re
import xml.etree.ElementTree as ET
from collections import OrderedDict, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROJ = os.path.join(ROOT, "ExploreInformatica Project")
MAP_XML = os.path.join(PROJ, "Mapping_ExploreInformatica.XML")
WF_XML = os.path.join(PROJ, "WorkFlow_ExploreInformatica.XML")
OUT_DIR = os.path.join(ROOT, "docs", "lineage")


def load_root(path: str) -> ET.Element:
    """Load a POWERMART XML, stripping the DOCTYPE that references a missing DTD."""
    with open(path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("cp1252")
    text = re.sub(r"<!DOCTYPE[^>]*>", "", text, count=1)
    # ElementTree wants no explicit unresolved entities; powrmart exports are clean.
    return ET.fromstring(text)


# ---------------------------------------------------------------------------
# Mapping metadata
# ---------------------------------------------------------------------------
class Mapping:
    def __init__(self, name):
        self.name = name
        self.transformations = OrderedDict()   # name -> type
        self.instances = OrderedDict()          # name -> dict(type, transformation_name, kind)
        self.connectors = []                    # dicts
        self.load_order = []                    # list of target instance names (ordered)
        self.sources = []                       # source instance names
        self.targets = []                       # target instance names


def parse_mappings(root):
    folder = root.find("REPOSITORY/FOLDER")
    sources = OrderedDict()   # name -> [fields]
    targets = OrderedDict()   # name -> [fields]
    mappings = OrderedDict()

    for src in folder.findall("SOURCE"):
        fields = [f.get("NAME") for f in src.findall("SOURCEFIELD")]
        sources[src.get("NAME")] = {
            "dbtype": src.get("DATABASETYPE"),
            "owner": src.get("OWNERNAME"),
            "fields": fields,
        }
    for tgt in folder.findall("TARGET"):
        fields = [f.get("NAME") for f in tgt.findall("TARGETFIELD")]
        targets[tgt.get("NAME")] = {
            "dbtype": tgt.get("DATABASETYPE"),
            "fields": fields,
        }

    for m in folder.findall("MAPPING"):
        mp = Mapping(m.get("NAME"))
        for t in m.findall("TRANSFORMATION"):
            mp.transformations[t.get("NAME")] = t.get("TYPE")
        for inst in m.findall("INSTANCE"):
            kind = inst.get("TYPE")  # SOURCE / TARGET / TRANSFORMATION
            mp.instances[inst.get("NAME")] = {
                "type": inst.get("TRANSFORMATION_TYPE"),
                "transformation_name": inst.get("TRANSFORMATION_NAME"),
                "kind": kind,
            }
            if kind == "SOURCE":
                mp.sources.append(inst.get("NAME"))
            elif kind == "TARGET":
                mp.targets.append(inst.get("NAME"))
        for c in m.findall("CONNECTOR"):
            mp.connectors.append({
                "from_inst": c.get("FROMINSTANCE"),
                "from_field": c.get("FROMFIELD"),
                "from_type": c.get("FROMINSTANCETYPE"),
                "to_inst": c.get("TOINSTANCE"),
                "to_field": c.get("TOFIELD"),
                "to_type": c.get("TOINSTANCETYPE"),
            })
        for lo in m.findall("TARGETLOADORDER"):
            mp.load_order.append((int(lo.get("ORDER")), lo.get("TARGETINSTANCE")))
        mp.load_order.sort()
        mappings[mp.name] = mp

    return sources, targets, mappings


def instance_edges(mp: Mapping):
    """Collapse field-level connectors into unique instance-level edges (ordered)."""
    seen = set()
    edges = []
    for c in mp.connectors:
        key = (c["from_inst"], c["to_inst"])
        if key in seen:
            continue
        seen.add(key)
        edges.append(key)
    return edges


# ---------------------------------------------------------------------------
# Workflow metadata
# ---------------------------------------------------------------------------
def parse_workflows(root):
    folder = root.find("REPOSITORY/FOLDER")
    sessions = OrderedDict()   # name -> dict(mapping, reusable, connections)
    workflows = OrderedDict()  # name -> dict(tasks, links, sessions)

    for s in folder.iter("SESSION"):
        conns = []
        for cr in s.iter("CONNECTIONREFERENCE"):
            conns.append({
                "name": cr.get("CONNECTIONNAME"),
                "type": cr.get("CONNECTIONTYPE"),
                "subtype": cr.get("CONNECTIONSUBTYPE"),
                "variable": cr.get("VARIABLE"),
            })
        # target load behaviour from writer session extensions
        writers = []
        for ext in s.iter("SESSIONEXTENSION"):
            if ext.get("TYPE") != "WRITER":
                continue
            attrs = {a.get("NAME"): a.get("VALUE") for a in ext.findall("ATTRIBUTE")}
            load = attrs.get("Target load type", "")
            ops = [k.split()[0] for k in ("Update as Update", "Update as Insert",
                    "Update else Insert", "Delete") if attrs.get(k) == "YES"]
            writers.append({
                "target": ext.get("SINSTANCENAME"),
                "load": load,
                "truncate": attrs.get("Truncate target table option", "NO"),
            })
        sessions[s.get("NAME")] = {
            "mapping": s.get("MAPPINGNAME"),
            "reusable": s.get("REUSABLE"),
            "connections": conns,
            "writers": writers,
        }

    for w in folder.iter("WORKFLOW"):
        task_insts = []
        for ti in w.findall("TASKINSTANCE"):
            task_insts.append({
                "name": ti.get("NAME"),
                "taskname": ti.get("TASKNAME"),
                "type": ti.get("TASKTYPE"),
                "enabled": ti.get("ISENABLED"),
                "fail_parent_if_fails": ti.get("FAIL_PARENT_IF_INSTANCE_FAILS"),
                "fail_parent_if_not_run": ti.get("FAIL_PARENT_IF_INSTANCE_DID_NOT_RUN"),
                "input_link_and": ti.get("TREAT_INPUTLINK_AS_AND"),
            })
        links = [(l.get("FROMTASK"), l.get("TOTASK"), l.get("CONDITION"))
                 for l in w.findall("WORKFLOWLINK")]
        sched = w.find("SCHEDULER")
        sched_type = None
        if sched is not None:
            si = sched.find("SCHEDULEINFO")
            sched_type = si.get("SCHEDULETYPE") if si is not None else None
        workflows[w.get("NAME")] = {
            "tasks": task_insts,
            "links": links,
            "scheduler": sched.get("SCHEDULERNAME") if sched is not None else None,
            "scheduler_type": sched_type,
            "suspend_on_error": w.get("SUSPEND_ON_ERROR"),
            "valid": w.get("ISVALID"),
            "enabled": w.get("ISENABLED"),
        }

    return sessions, workflows


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
SHAPE = {
    "SOURCE": ("[(", ")]"),        # cylinder-ish
    "TARGET": ("[(", ")]"),
    "TRANSFORMATION": ("[", "]"),
}


def mmid(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def mermaid_for_mapping(mp: Mapping, sources, targets):
    lines = ["```mermaid", "flowchart LR"]
    # declare nodes
    for iname, meta in mp.instances.items():
        nid = mmid(iname)
        ttype = meta["type"] or meta["kind"]
        if meta["kind"] == "SOURCE":
            lines.append(f'    {nid}[("SRC: {iname}")]')
        elif meta["kind"] == "TARGET":
            lines.append(f'    {nid}[("TGT: {iname}")]')
        else:
            lines.append(f'    {nid}["{iname}<br/><i>{ttype}</i>"]')
    for a, b in instance_edges(mp):
        lines.append(f"    {mmid(a)} --> {mmid(b)}")
    lines.append("```")
    return "\n".join(lines)


def build_dot(sources, targets, mappings, sessions, workflows):
    L = ['digraph lineage {', '  rankdir=LR;', '  splines=true;', '  node [fontname="Helvetica"];',
         '  graph [fontname="Helvetica"];', '  edge [color="#555555"];']
    # cluster per mapping
    session_by_mapping = defaultdict(list)
    for sname, s in sessions.items():
        session_by_mapping[s["mapping"]].append(sname)
    wf_by_session = defaultdict(list)
    for wname, w in workflows.items():
        for ti in w["tasks"]:
            if ti["type"] == "Session":
                wf_by_session[ti["taskname"]].append(wname)

    for i, (mname, mp) in enumerate(mappings.items()):
        L.append(f'  subgraph cluster_{i} {{')
        L.append(f'    label="MAPPING: {mname}"; style="rounded"; color="#3367d6"; fontcolor="#3367d6";')
        for iname, meta in mp.instances.items():
            nid = f'"{mname}::{iname}"'
            if meta["kind"] == "SOURCE":
                L.append(f'    {nid} [label="{iname}", shape=cylinder, style=filled, fillcolor="#e8f0fe"];')
            elif meta["kind"] == "TARGET":
                L.append(f'    {nid} [label="{iname}", shape=cylinder, style=filled, fillcolor="#fce8e6"];')
            else:
                L.append(f'    {nid} [label="{iname}\\n({meta["type"]})", shape=box, style="rounded,filled", fillcolor="#fef7e0"];')
        for a, b in instance_edges(mp):
            L.append(f'    "{mname}::{a}" -> "{mname}::{b}";')
        L.append('  }')

    L.append('}')
    return "\n".join(L)


def build_overview_dot(sources, targets, mappings, sessions, workflows):
    session_by_mapping = defaultdict(list)
    for sname, s in sessions.items():
        session_by_mapping[s["mapping"]].append(sname)
    wf_by_session = defaultdict(list)
    for wname, w in workflows.items():
        for ti in w["tasks"]:
            if ti["type"] == "Session":
                wf_by_session[ti["taskname"]].append(wname)

    L = ['digraph overview {', '  rankdir=LR;', '  node [fontname="Helvetica", fontsize=10];',
         '  ranksep=1.2; nodesep=0.25;']
    # node groups
    src_nodes, tgt_nodes = set(), set()
    for mname, mp in mappings.items():
        for s in mp.sources:
            src_nodes.add(s)
        for t in mp.targets:
            tgt_nodes.add(t)
    for s in sorted(src_nodes):
        L.append(f'  "SRC:{s}" [label="{s}", shape=cylinder, style=filled, fillcolor="#e8f0fe"];')
    for t in sorted(tgt_nodes):
        L.append(f'  "TGT:{t}" [label="{t}", shape=cylinder, style=filled, fillcolor="#fce8e6"];')
    for mname, mp in mappings.items():
        transforms = [meta["type"] for iname, meta in mp.instances.items()
                      if meta["kind"] == "TRANSFORMATION"]
        tlabel = mname + "\\n[" + ", ".join(sorted(set(transforms))) + "]"
        L.append(f'  "MAP:{mname}" [label="{tlabel}", shape=box, style="rounded,filled", fillcolor="#fef7e0"];')
        wfs = set()
        for sname in session_by_mapping.get(mname, []):
            for wf in wf_by_session.get(sname, []):
                wfs.add((wf, sname))
        for wf, sname in sorted(wfs):
            wid = f'"WF:{wf}"'
            L.append(f'  {wid} [label="{wf}\\n(session {sname})", shape=box, style=filled, fillcolor="#e6f4ea"];')
            L.append(f'  {wid} -> "MAP:{mname}" [style=dashed, color="#188038", label="runs"];')
        for s in mp.sources:
            L.append(f'  "SRC:{s}" -> "MAP:{mname}";')
        for t in mp.targets:
            L.append(f'  "MAP:{mname}" -> "TGT:{t}";')
    L.append('}')
    return "\n".join(L)


def build_workflow_dot(sessions, workflows, mappings):
    """Workflow/session task-dependency graph: per-workflow Start -> task links."""
    L = ['digraph workflow_tasks {', '  rankdir=LR;', '  compound=true;',
         '  node [fontname="Helvetica", fontsize=10];',
         '  graph [fontname="Helvetica"];']
    for i, (wname, w) in enumerate(workflows.items()):
        L.append(f'  subgraph cluster_wf_{i} {{')
        L.append(f'    label="{wname}  (schedule: {w.get("scheduler_type") or "?"})";'
                 ' style="rounded"; color="#188038"; fontcolor="#188038";')
        for ti in w["tasks"]:
            nid = f'"{wname}::{ti["name"]}"'
            if ti["type"] == "Start":
                L.append(f'    {nid} [label="{ti["name"]}", shape=circle, style=filled, fillcolor="#188038", fontcolor=white, width=0.5];')
            else:
                mp = sessions.get(ti["taskname"], {}).get("mapping", "")
                reuse = "reusable" if sessions.get(ti["taskname"], {}).get("reusable") == "YES" else "non-reusable"
                L.append(f'    {nid} [label="{ti["name"]}\\n({ti["type"]}, {reuse})\\nmapping: {mp}", '
                         'shape=box, style="rounded,filled", fillcolor="#e6f4ea"];')
        for frm, to, cond in w["links"]:
            # find target task instance to annotate fail-propagation
            to_ti = next((t for t in w["tasks"] if t["name"] == to), None)
            elabel = cond if cond else ""
            if to_ti and to_ti.get("fail_parent_if_fails") == "YES":
                elabel = (elabel + "  " if elabel else "") + "[fails→wf fails]"
            L.append(f'    "{wname}::{frm}" -> "{wname}::{to}" [label="{elabel}"];')
        L.append('  }')
    L.append('}')
    return "\n".join(L)


# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    mroot = load_root(MAP_XML)
    wroot = load_root(WF_XML)
    sources, targets, mappings = parse_mappings(mroot)
    sessions, workflows = parse_workflows(wroot)

    # cross indexes
    session_by_mapping = defaultdict(list)
    for sname, s in sessions.items():
        session_by_mapping[s["mapping"]].append(sname)
    wf_by_session = defaultdict(list)
    for wname, w in workflows.items():
        for ti in w["tasks"]:
            if ti["type"] == "Session":
                wf_by_session[ti["taskname"]].append(wname)

    # DOT files
    with open(os.path.join(OUT_DIR, "lineage.dot"), "w") as fh:
        fh.write(build_dot(sources, targets, mappings, sessions, workflows))
    with open(os.path.join(OUT_DIR, "lineage_overview.dot"), "w") as fh:
        fh.write(build_overview_dot(sources, targets, mappings, sessions, workflows))
    with open(os.path.join(OUT_DIR, "workflow_tasks.dot"), "w") as fh:
        fh.write(build_workflow_dot(sessions, workflows, mappings))

    # ---- Workflow / session task-dependency doc ----
    wm = []
    W = wm.append
    W("# Workflow / Session Task-Dependency Graph\n")
    W("Task-level orchestration for every workflow in the *Explore Informatica* folder, generated "
      "from `WorkFlow_ExploreInformatica.XML` by `tools/parse_lineage.py`.\n")
    W("Each workflow starts at the built-in **Start** task and links to its **Session** task via a "
      "conditional `WORKFLOWLINK`. The session then runs a mapping (see "
      "[`DEPENDENCY_LINEAGE.md`](DEPENDENCY_LINEAGE.md) for the data lineage).\n")
    W("![Workflow task-dependency graph](workflow_tasks.png)\n")

    W("## 1. Summary\n")
    n_links = sum(len(w["links"]) for w in workflows.values())
    n_tasks = sum(len(w["tasks"]) for w in workflows.values())
    W(f"- **Workflows:** {len(workflows)}")
    W(f"- **Task instances:** {n_tasks} (each workflow = 1 `Start` + 1 `Session`)")
    W(f"- **Task links (WORKFLOWLINK):** {n_links}")
    W("- **Non-`Start`/`Session` task types** (Command, Decision, Timer, Control, Assignment, Event, Worklet): **none**")
    W(f"- **Schedule type:** all `{sorted({w.get('scheduler_type') for w in workflows.values()})[0]}` (run manually / on demand)\n")
    W("> All links are **unconditional** (empty `CONDITION`), so each session runs whenever its "
      "workflow starts. Every workflow is an independent, single-session pipeline — there are no "
      "cross-workflow task dependencies in this folder.\n")

    W("## 2. Workflow → task links\n")
    W("| Workflow | Schedule | Link | Condition | Session reusable | Fail wf if session fails | Fail wf if session skipped |")
    W("|---|---|---|---|---|---|---|")
    for wname, w in workflows.items():
        sess = [t for t in w["tasks"] if t["type"] == "Session"]
        for frm, to, cond in w["links"]:
            to_ti = next((t for t in w["tasks"] if t["name"] == to), {})
            reuse = sessions.get(to_ti.get("taskname"), {}).get("reusable", "")
            W(f"| `{wname}` | {w.get('scheduler_type')} | `{frm}` → `{to}` | "
              f"{cond or '*(none)*'} | {reuse} | {to_ti.get('fail_parent_if_fails','')} | "
              f"{to_ti.get('fail_parent_if_not_run','')} |")
    W("")

    W("## 3. Session target-load behaviour\n")
    W("From each session's writer extensions (truncate-before-load and load type per target).\n")
    W("| Session | Target | Load type | Truncate target |")
    W("|---|---|---|---|")
    for sname, s in sessions.items():
        if not s.get("writers"):
            continue
        for wr in s["writers"]:
            W(f"| `{sname}` | `{wr['target']}` | {wr['load'] or 'Normal'} | {wr['truncate']} |")
    W("")

    W("## 4. Per-workflow task flow\n")
    for wname, w in workflows.items():
        sess = next((t for t in w["tasks"] if t["type"] == "Session"), None)
        mp = sessions.get(sess["taskname"], {}).get("mapping") if sess else None
        W(f"### `{wname}`\n")
        W(f"- Schedule: `{w.get('scheduler_type')}` · Valid: {w.get('valid')} · "
          f"Enabled: {w.get('enabled')} · Suspend on error: {w.get('suspend_on_error')}")
        W(f"- Runs mapping: `{mp}`" + ("" if mp in mappings else " ⚠️ *(mapping not in export)*"))
        W("")
        W("```mermaid")
        W("flowchart LR")
        for ti in w["tasks"]:
            nid = mmid(wname) + "__" + mmid(ti["name"])
            if ti["type"] == "Start":
                W(f'    {nid}(("{ti["name"]}"))')
            else:
                W(f'    {nid}["{ti["name"]}<br/><i>{ti["type"]}</i>"]')
        for frm, to, cond in w["links"]:
            fid = mmid(wname) + "__" + mmid(frm)
            tid = mmid(wname) + "__" + mmid(to)
            arrow = f'-- "{cond}" -->' if cond else "-->"
            W(f"    {fid} {arrow} {tid}")
        W("```")
        W("")

    with open(os.path.join(OUT_DIR, "WORKFLOW_TASKS.md"), "w") as fh:
        fh.write("\n".join(wm) + "\n")

    # Markdown
    md = []
    A = md.append
    A("# Informatica Dependency / Lineage Graph\n")
    A("End-to-end **source → transformation → target** lineage for the *Explore Informatica* "
      "repository folder, generated automatically from the PowerCenter metadata exports "
      "(`Mapping_ExploreInformatica.XML`, `WorkFlow_ExploreInformatica.XML`).\n")
    A("> Regenerate with `python3 tools/parse_lineage.py`. Mermaid diagrams render natively on GitHub; "
      "`docs/lineage/*.dot` can be rendered with Graphviz (`dot -Tpng`/`-Tsvg`).\n")

    # Summary counts
    A("## 1. Inventory summary\n")
    A("| Object type | Count |")
    A("|---|---|")
    A(f"| Source definitions | {len(sources)} |")
    A(f"| Target definitions | {len(targets)} |")
    A(f"| Mappings | {len(mappings)} |")
    A(f"| Sessions | {len(sessions)} |")
    A(f"| Workflows | {len(workflows)} |")
    total_tr = sum(1 for mp in mappings.values() for m in mp.instances.values() if m['kind'] == 'TRANSFORMATION')
    A(f"| Transformation instances | {total_tr} |")
    A("| Mapplets | 0 (none defined in this folder) |")
    A("| Reusable (shared) transformations | 0 (all transformations are mapping-local) |\n")

    # Sources
    A("## 2. Sources\n")
    A("| Source | DB type | Owner | Fields |")
    A("|---|---|---|---|")
    for name, s in sources.items():
        A(f"| `{name}` | {s['dbtype']} | {s['owner'] or ''} | {len(s['fields'])} |")
    A("")

    # Targets
    A("## 3. Targets\n")
    A("| Target | DB type | Fields |")
    A("|---|---|---|")
    for name, t in targets.items():
        A(f"| `{name}` | {t['dbtype']} | {len(t['fields'])} |")
    A("")

    # Workflow -> session -> mapping
    A("## 4. Workflow → Session → Mapping execution map\n")
    A("| Workflow | Session (task) | Reusable | Mapping | Sources | Targets |")
    A("|---|---|---|---|---|---|")
    for wname, w in workflows.items():
        sess_tasks = [ti for ti in w["tasks"] if ti["type"] == "Session"]
        if not sess_tasks:
            A(f"| `{wname}` | *(no session)* | | | | |")
        for ti in sess_tasks:
            sname = ti["taskname"]
            s = sessions.get(sname, {})
            mname = s.get("mapping")
            mp = mappings.get(mname)
            mlabel = f"`{mname}`" if mp else f"`{mname}` ⚠️ *(not in export)*"
            srcs = ", ".join(mp.sources) if mp else ""
            tgts = ", ".join(mp.targets) if mp else ""
            A(f"| `{wname}` | `{sname}` | {s.get('reusable','')} | {mlabel} | {srcs} | {tgts} |")
    A("")

    # Missing mapping definitions referenced by sessions
    missing = sorted({s["mapping"] for s in sessions.values()
                      if s["mapping"] and s["mapping"] not in mappings})
    if missing:
        A("> ⚠️ **Cross-reference gap:** the following mapping(s) are referenced by a session but are "
          "**not defined** in `Mapping_ExploreInformatica.XML` (defined in another folder/export): "
          + ", ".join(f"`{m}`" for m in missing) + ".\n")

    # Database connections
    A("### Session database connections\n")
    A("| Session | Connection | Type | Subtype |")
    A("|---|---|---|---|")
    conn_rows = set()
    for sname, s in sessions.items():
        for c in s["connections"]:
            conn_rows.add((sname, c["name"], c["type"], c["subtype"]))
    for sname, cname, ctype, csub in sorted(conn_rows):
        A(f"| `{sname}` | `{cname}` | {ctype} | {csub} |")
    A("")

    # Orphans
    mapped = {s["mapping"] for s in sessions.values()}
    orphan_maps = [m for m in mappings if m not in mapped]
    sess_in_wf = {ti["taskname"] for w in workflows.values() for ti in w["tasks"] if ti["type"] == "Session"}
    orphan_sess = [s for s in sessions if s not in sess_in_wf]
    if orphan_maps or orphan_sess:
        A("### Unlinked objects\n")
        if orphan_maps:
            A("- Mappings with **no session**: " + ", ".join(f"`{m}`" for m in orphan_maps))
        if orphan_sess:
            A("- Sessions **not referenced by any workflow**: " + ", ".join(f"`{s}`" for s in orphan_sess))
        A("")

    # Overall lineage mermaid (source -> mapping -> target, with workflow)
    A("## 5. Overall lineage graph\n")
    A("Workflow (green) runs a session that executes a mapping (yellow), which reads sources "
      "(blue) and writes targets (red).\n")
    A("Rendered Graphviz overview (also available as "
      "[`lineage_overview.svg`](lineage_overview.svg) / "
      "[`lineage.dot`](lineage.dot) detailed field-instance version):\n")
    A("![Source → mapping → target overview](lineage_overview.png)\n")
    A("> Note: an **unconnected Lookup** (e.g. `lkp_DEPARTMENT_NAME` in `m_LOOKUP_UNCONNECTED`) appears "
      "as an isolated node — it is invoked from an expression via `:LKP`, so it has no pipeline "
      "connectors, which is expected.\n")
    A("```mermaid")
    A("flowchart LR")
    declared = set()
    def decl(nid, label):
        if nid not in declared:
            declared.add(nid)
            return label
        return None
    for mname, mp in mappings.items():
        mnid = "MAP_" + mmid(mname)
        transforms = sorted({meta["type"] for _, meta in mp.instances.items() if meta["kind"] == "TRANSFORMATION"})
        d = decl(mnid, f'    {mnid}["{mname}<br/><i>{", ".join(transforms)}</i>"]')
        if d: A(d)
        # workflow nodes
        wfs = set()
        for sname in session_by_mapping.get(mname, []):
            for wf in wf_by_session.get(sname, []):
                wfs.add((wf, sname))
        for wf, sname in sorted(wfs):
            wnid = "WF_" + mmid(wf)
            d = decl(wnid, f'    {wnid}(["{wf}<br/>session {sname}"])')
            if d: A(d)
            A(f"    {wnid} -. runs .-> {mnid}")
        for s in mp.sources:
            snid = "SRC_" + mmid(s)
            d = decl(snid, f'    {snid}[("{s}")]')
            if d: A(d)
            A(f"    {snid} --> {mnid}")
        for t in mp.targets:
            tnid = "TGT_" + mmid(t)
            d = decl(tnid, f'    {tnid}[("{t}")]')
            if d: A(d)
            A(f"    {mnid} --> {tnid}")
    A("    classDef src fill:#e8f0fe,stroke:#3367d6;")
    A("    classDef tgt fill:#fce8e6,stroke:#c5221f;")
    A("    classDef wf fill:#e6f4ea,stroke:#188038;")
    src_ids = " ".join("SRC_" + mmid(s) for s in sorted({x for mp in mappings.values() for x in mp.sources}))
    tgt_ids = " ".join("TGT_" + mmid(t) for t in sorted({x for mp in mappings.values() for x in mp.targets}))
    wf_ids = " ".join("WF_" + mmid(w) for w in workflows)
    if src_ids: A(f"    class {src_ids} src;")
    if tgt_ids: A(f"    class {tgt_ids} tgt;")
    if wf_ids: A(f"    class {wf_ids} wf;")
    A("```")
    A("")

    # Per-mapping detail
    A("## 6. Per-mapping field-flow lineage\n")
    for mname, mp in mappings.items():
        A(f"### 6.{list(mappings).index(mname)+1} `{mname}`\n")
        # session/workflow
        smeta = []
        for sname in session_by_mapping.get(mname, []):
            wfs = ", ".join(f"`{w}`" for w in wf_by_session.get(sname, [])) or "*(no workflow)*"
            smeta.append(f"`{sname}` (workflow: {wfs})")
        A(f"- **Sources:** {', '.join('`'+s+'`' for s in mp.sources) or '—'}")
        A(f"- **Targets:** {', '.join('`'+t+'`' for t in mp.targets) or '—'}")
        transforms = [(iname, meta['type']) for iname, meta in mp.instances.items() if meta['kind']=='TRANSFORMATION']
        A(f"- **Transformations ({len(transforms)}):** " +
          (", ".join(f"`{n}` ({t})" for n, t in transforms) or "—"))
        A(f"- **Session(s):** {', '.join(smeta) or '—'}")
        if mp.load_order:
            A(f"- **Target load order:** " + " → ".join(f"{o}. `{t}`" for o, t in mp.load_order))
        A("")
        A(mermaid_for_mapping(mp, sources, targets))
        A("")

    with open(os.path.join(OUT_DIR, "DEPENDENCY_LINEAGE.md"), "w") as fh:
        fh.write("\n".join(md) + "\n")

    print("mappings:", len(mappings), "sessions:", len(sessions), "workflows:", len(workflows))
    print("sources:", list(sources), "\ntargets:", list(targets))
    print("orphan mappings:", orphan_maps, "orphan sessions:", orphan_sess)
    for mname, mp in mappings.items():
        print(f"  {mname}: src={mp.sources} tgt={mp.targets} tr={[m['type'] for i,m in mp.instances.items() if m['kind']=='TRANSFORMATION']}")


if __name__ == "__main__":
    main()
