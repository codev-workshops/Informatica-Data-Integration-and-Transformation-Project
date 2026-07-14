# Workflow / Session Task-Dependency Graph

Task-level orchestration for every workflow in the *Explore Informatica* folder, generated from `WorkFlow_ExploreInformatica.XML` by `tools/parse_lineage.py`.

Each workflow starts at the built-in **Start** task and links to its **Session** task via a conditional `WORKFLOWLINK`. The session then runs a mapping (see [`DEPENDENCY_LINEAGE.md`](DEPENDENCY_LINEAGE.md) for the data lineage).

![Workflow task-dependency graph](workflow_tasks.png)

## 1. Summary

- **Workflows:** 14
- **Task instances:** 28 (each workflow = 1 `Start` + 1 `Session`)
- **Task links (WORKFLOWLINK):** 14
- **Non-`Start`/`Session` task types** (Command, Decision, Timer, Control, Assignment, Event, Worklet): **none**
- **Schedule type:** all `ONDEMAND` (run manually / on demand)

> All links are **unconditional** (empty `CONDITION`), so each session runs whenever its workflow starts. Every workflow is an independent, single-session pipeline — there are no cross-workflow task dependencies in this folder.

## 2. Workflow → task links

| Workflow | Schedule | Link | Condition | Session reusable | Fail wf if session fails | Fail wf if session skipped |
|---|---|---|---|---|---|---|
| `wf_ROUTER_TRANS` | ONDEMAND | `Start` → `s_ROUTER_TRANS` | *(none)* | YES | YES | NO |
| `wf_FILTER_TRANSFORMATION` | ONDEMAND | `Start` → `s_FILTER_TRANSFORMATION` | *(none)* | YES | NO | NO |
| `wf_AGGREGATOR_TRANS` | ONDEMAND | `Start` → `s_AGGREGATOR_TRANS` | *(none)* | YES | NO | NO |
| `wf_MASTER_OUTER_JOIN` | ONDEMAND | `Start` → `s_MASTER_OUTER_JOIN` | *(none)* | YES | YES | YES |
| `wf_DETAILS_OUTER_JOIN` | ONDEMAND | `Start` → `s_DETAILS_OUTER_JOIN` | *(none)* | YES | NO | NO |
| `wf_FULL_OUTER_JOIN` | ONDEMAND | `Start` → `s_FULL_OUTER_JOIN` | *(none)* | NO | YES | NO |
| `wf_NORMAL_JOIN` | ONDEMAND | `Start` → `s_NORMAL_JOIN` | *(none)* | NO | YES | YES |
| `wf_RANK_TRANSFORMATION` | ONDEMAND | `Start` → `s_RANK_TRANSFORMATION` | *(none)* | NO | YES | NO |
| `wf_SEQUENC_TRANSFORMATION` | ONDEMAND | `Start` → `s_SEQUENC_TRANSFORMATION` | *(none)* | NO | YES | NO |
| `wf_LOOKUP_TRANSFORMATION` | ONDEMAND | `Start` → `s_LOOKUP_TRANSFORMATION` | *(none)* | NO | YES | YES |
| `wf_LOOKUP_UNCONNECTED` | ONDEMAND | `Start` → `s_LOOKUP_UNCONNECTED` | *(none)* | NO | YES | YES |
| `wf_UNION_TRANSFORMATION` | ONDEMAND | `Start` → `s_UNION_TRANSFORMATION` | *(none)* | NO | YES | YES |
| `wf_NORMALIZER_TRANSFORMATION` | ONDEMAND | `Start` → `s_NORMALIZER_TRANSFORMATION` | *(none)* | NO | YES | YES |
| `wf_CUSTOMERDETAILS` | ONDEMAND | `Start` → `s_CUSTOMERDETAILS` | *(none)* | YES | NO | NO |

## 3. Session target-load behaviour

From each session's writer extensions (truncate-before-load and load type per target).

| Session | Target | Load type | Truncate target |
|---|---|---|---|
| `s_ROUTER_TRANS` | `ORG_EMPLOYEE_DEPT1` | Normal | YES |
| `s_ROUTER_TRANS` | `ORG_EMPLOYEE_DEPT2` | Normal | YES |
| `s_ROUTER_TRANS` | `ORG_EMPLOYEE_DEPT3` | Normal | YES |
| `s_ROUTER_TRANS` | `ORG_EMPLOYEE_DEFAULT` | Normal | YES |
| `s_FILTER_TRANSFORMATION` | `ORG_EMPLOYEE_DATA` | Normal | YES |
| `s_AGGREGATOR_TRANS` | `DEPT_SALARY` | Normal | YES |
| `s_MASTER_OUTER_JOIN` | `students_rec` | Normal | YES |
| `s_DETAILS_OUTER_JOIN` | `students_rec` | Normal | YES |
| `s_FULL_OUTER_JOIN` | `students_rec` | Normal | YES |
| `s_NORMAL_JOIN` | `students_rec` | Normal | YES |
| `s_RANK_TRANSFORMATION` | `EMPLOYEE_RANK` | Normal | YES |
| `s_SEQUENC_TRANSFORMATION` | `EMPLOYEE_SEQUENCE_NUMBER` | Normal | YES |
| `s_LOOKUP_TRANSFORMATION` | `COUNTRY_DATA` | Normal | YES |
| `s_LOOKUP_UNCONNECTED` | `EMPLOYEE_DEPT` | Normal | YES |
| `s_UNION_TRANSFORMATION` | `EMPLOYEE_ALL` | Normal | YES |
| `s_NORMALIZER_TRANSFORMATION` | `STUDENTS_DETAILSHEET` | Normal | YES |
| `s_CUSTOMERDETAILS` | `CUSTOMERDETAILS` | Normal | NO |

## 4. Per-workflow task flow

### `wf_ROUTER_TRANS`

- Schedule: `ONDEMAND` · Valid: YES · Enabled: YES · Suspend on error: NO
- Runs mapping: `m_Router_transfromation`

```mermaid
flowchart LR
    wf_ROUTER_TRANS__Start(("Start"))
    wf_ROUTER_TRANS__s_ROUTER_TRANS["s_ROUTER_TRANS<br/><i>Session</i>"]
    wf_ROUTER_TRANS__Start --> wf_ROUTER_TRANS__s_ROUTER_TRANS
```

### `wf_FILTER_TRANSFORMATION`

- Schedule: `ONDEMAND` · Valid: YES · Enabled: YES · Suspend on error: NO
- Runs mapping: `m_FILTER_TRANSFORMATION`

```mermaid
flowchart LR
    wf_FILTER_TRANSFORMATION__Start(("Start"))
    wf_FILTER_TRANSFORMATION__s_FILTER_TRANSFORMATION["s_FILTER_TRANSFORMATION<br/><i>Session</i>"]
    wf_FILTER_TRANSFORMATION__Start --> wf_FILTER_TRANSFORMATION__s_FILTER_TRANSFORMATION
```

### `wf_AGGREGATOR_TRANS`

- Schedule: `ONDEMAND` · Valid: YES · Enabled: YES · Suspend on error: NO
- Runs mapping: `m_AGGREGATOR_TRANS`

```mermaid
flowchart LR
    wf_AGGREGATOR_TRANS__Start(("Start"))
    wf_AGGREGATOR_TRANS__s_AGGREGATOR_TRANS["s_AGGREGATOR_TRANS<br/><i>Session</i>"]
    wf_AGGREGATOR_TRANS__Start --> wf_AGGREGATOR_TRANS__s_AGGREGATOR_TRANS
```

### `wf_MASTER_OUTER_JOIN`

- Schedule: `ONDEMAND` · Valid: YES · Enabled: YES · Suspend on error: NO
- Runs mapping: `m_MASTER_OUTER_JOIN`

```mermaid
flowchart LR
    wf_MASTER_OUTER_JOIN__Start(("Start"))
    wf_MASTER_OUTER_JOIN__s_MASTER_OUTER_JOIN["s_MASTER_OUTER_JOIN<br/><i>Session</i>"]
    wf_MASTER_OUTER_JOIN__Start --> wf_MASTER_OUTER_JOIN__s_MASTER_OUTER_JOIN
```

### `wf_DETAILS_OUTER_JOIN`

- Schedule: `ONDEMAND` · Valid: YES · Enabled: YES · Suspend on error: NO
- Runs mapping: `m_DETAILS_OUTER_JOIN`

```mermaid
flowchart LR
    wf_DETAILS_OUTER_JOIN__Start(("Start"))
    wf_DETAILS_OUTER_JOIN__s_DETAILS_OUTER_JOIN["s_DETAILS_OUTER_JOIN<br/><i>Session</i>"]
    wf_DETAILS_OUTER_JOIN__Start --> wf_DETAILS_OUTER_JOIN__s_DETAILS_OUTER_JOIN
```

### `wf_FULL_OUTER_JOIN`

- Schedule: `ONDEMAND` · Valid: YES · Enabled: YES · Suspend on error: NO
- Runs mapping: `m_FULL_OUTER_JOIN`

```mermaid
flowchart LR
    wf_FULL_OUTER_JOIN__Start(("Start"))
    wf_FULL_OUTER_JOIN__s_FULL_OUTER_JOIN["s_FULL_OUTER_JOIN<br/><i>Session</i>"]
    wf_FULL_OUTER_JOIN__Start --> wf_FULL_OUTER_JOIN__s_FULL_OUTER_JOIN
```

### `wf_NORMAL_JOIN`

- Schedule: `ONDEMAND` · Valid: YES · Enabled: YES · Suspend on error: NO
- Runs mapping: `m_NORMAL_JOIN`

```mermaid
flowchart LR
    wf_NORMAL_JOIN__Start(("Start"))
    wf_NORMAL_JOIN__s_NORMAL_JOIN["s_NORMAL_JOIN<br/><i>Session</i>"]
    wf_NORMAL_JOIN__Start --> wf_NORMAL_JOIN__s_NORMAL_JOIN
```

### `wf_RANK_TRANSFORMATION`

- Schedule: `ONDEMAND` · Valid: YES · Enabled: YES · Suspend on error: NO
- Runs mapping: `m_RANK_TRANSFORMATION`

```mermaid
flowchart LR
    wf_RANK_TRANSFORMATION__Start(("Start"))
    wf_RANK_TRANSFORMATION__s_RANK_TRANSFORMATION["s_RANK_TRANSFORMATION<br/><i>Session</i>"]
    wf_RANK_TRANSFORMATION__Start --> wf_RANK_TRANSFORMATION__s_RANK_TRANSFORMATION
```

### `wf_SEQUENC_TRANSFORMATION`

- Schedule: `ONDEMAND` · Valid: YES · Enabled: YES · Suspend on error: NO
- Runs mapping: `m_SEQUENC_TRANSFORMATION`

```mermaid
flowchart LR
    wf_SEQUENC_TRANSFORMATION__Start(("Start"))
    wf_SEQUENC_TRANSFORMATION__s_SEQUENC_TRANSFORMATION["s_SEQUENC_TRANSFORMATION<br/><i>Session</i>"]
    wf_SEQUENC_TRANSFORMATION__Start --> wf_SEQUENC_TRANSFORMATION__s_SEQUENC_TRANSFORMATION
```

### `wf_LOOKUP_TRANSFORMATION`

- Schedule: `ONDEMAND` · Valid: YES · Enabled: YES · Suspend on error: NO
- Runs mapping: `m_LOOKUP_TRANSFORMATION`

```mermaid
flowchart LR
    wf_LOOKUP_TRANSFORMATION__Start(("Start"))
    wf_LOOKUP_TRANSFORMATION__s_LOOKUP_TRANSFORMATION["s_LOOKUP_TRANSFORMATION<br/><i>Session</i>"]
    wf_LOOKUP_TRANSFORMATION__Start --> wf_LOOKUP_TRANSFORMATION__s_LOOKUP_TRANSFORMATION
```

### `wf_LOOKUP_UNCONNECTED`

- Schedule: `ONDEMAND` · Valid: YES · Enabled: YES · Suspend on error: NO
- Runs mapping: `m_LOOKUP_UNCONNECTED`

```mermaid
flowchart LR
    wf_LOOKUP_UNCONNECTED__Start(("Start"))
    wf_LOOKUP_UNCONNECTED__s_LOOKUP_UNCONNECTED["s_LOOKUP_UNCONNECTED<br/><i>Session</i>"]
    wf_LOOKUP_UNCONNECTED__Start --> wf_LOOKUP_UNCONNECTED__s_LOOKUP_UNCONNECTED
```

### `wf_UNION_TRANSFORMATION`

- Schedule: `ONDEMAND` · Valid: YES · Enabled: YES · Suspend on error: NO
- Runs mapping: `m_UNION_TRANSFORMATION`

```mermaid
flowchart LR
    wf_UNION_TRANSFORMATION__Start(("Start"))
    wf_UNION_TRANSFORMATION__s_UNION_TRANSFORMATION["s_UNION_TRANSFORMATION<br/><i>Session</i>"]
    wf_UNION_TRANSFORMATION__Start --> wf_UNION_TRANSFORMATION__s_UNION_TRANSFORMATION
```

### `wf_NORMALIZER_TRANSFORMATION`

- Schedule: `ONDEMAND` · Valid: YES · Enabled: YES · Suspend on error: NO
- Runs mapping: `m_NORMALIZER_TRANSFORMATION`

```mermaid
flowchart LR
    wf_NORMALIZER_TRANSFORMATION__Start(("Start"))
    wf_NORMALIZER_TRANSFORMATION__s_NORMALIZER_TRANSFORMATION["s_NORMALIZER_TRANSFORMATION<br/><i>Session</i>"]
    wf_NORMALIZER_TRANSFORMATION__Start --> wf_NORMALIZER_TRANSFORMATION__s_NORMALIZER_TRANSFORMATION
```

### `wf_CUSTOMERDETAILS`

- Schedule: `ONDEMAND` · Valid: YES · Enabled: YES · Suspend on error: NO
- Runs mapping: `m_CUSTOMERDETAILS` ⚠️ *(mapping not in export)*

```mermaid
flowchart LR
    wf_CUSTOMERDETAILS__Start(("Start"))
    wf_CUSTOMERDETAILS__s_CUSTOMERDETAILS["s_CUSTOMERDETAILS<br/><i>Session</i>"]
    wf_CUSTOMERDETAILS__Start --> wf_CUSTOMERDETAILS__s_CUSTOMERDETAILS
```

