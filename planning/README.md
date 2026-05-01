# Universal SQL — Planning

Operational artefacts: how the design in [`../design/`](../design/) gets
built. Both files target the **Execution Plan (15%)** rubric line.

| File | Audience | What's inside |
|---|---|---|
| [`02-execution-plan.md`](02-execution-plan.md) | Exec, GTM, hiring committee | North-star outcomes, engineering themes, 6-month milestones (M1–M6), team shape, risk register, budget assumptions |
| [`sprint_planning.md`](sprint_planning.md) | Engineering team, EM, PM | 12 × 2-week sprints with named tasks per role, deliverables, demos, dependency graph, sprint review template |
| [`gantt.png`](gantt.png) · [`gantt.svg`](gantt.svg) | Anyone in a meeting | Rendered Gantt chart — 5 themes × 25+ work items × 6 milestones |
| [`gantt.mmd`](gantt.mmd) | Engineering team | Editable Mermaid source for the Gantt; re-render with `mmdc` |

## How they relate

```
02-execution-plan.md   ←  strategic   →  refreshed quarterly
        │
        │ each milestone (M1–M6) =
        ▼ exactly 2 sprints in →
sprint_planning.md     ←  operational →  refreshed every sprint
```

The execution plan describes **what we're building** (themes →
milestones with measurable exit criteria). The sprint plan describes
**how the team builds it** (which engineer takes which task in which
2-week window, with explicit dependency chains and a Gantt).

## Companion folders

- [`../design/`](../design/) — System architecture, security, freshness, capacity sizing.
- [`../prototype/`](../prototype/) — Working M1 vertical slice with evidence.

## Reading order

- **Quarterly planning meeting:** `02-execution-plan.md` only.
- **Sprint planning meeting:** `sprint_planning.md` (current and next sprint).
- **New engineer onboarding:** both files in order, then `../prototype/ARCHITECTURE.md`.
