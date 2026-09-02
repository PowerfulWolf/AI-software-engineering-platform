"""Render a small local dashboard from the immutable projection read model."""

from __future__ import annotations

import html
import json
from typing import Final

from ai_software_engineer.projection.models import (
    AgentProjection,
    LeaseProjection,
    LeaseProjectionStatus,
    ProjectionSnapshot,
    TaskProjection,
    TimelineEntry,
)
from ai_software_engineer.read_api import ReadOnlyProjectionApi

DashboardSource = ProjectionSnapshot | ReadOnlyProjectionApi


class DashboardRenderer:
    """Build deterministic JSON and self-contained HTML without mutation capability."""

    title: Final[str] = "ai-software-engineer · Agent dashboard"

    def build_data(self, source: DashboardSource) -> dict[str, object]:
        snapshot = source.snapshot if isinstance(source, ReadOnlyProjectionApi) else source
        timeline = sorted(
            [entry for task in snapshot.tasks for entry in task.timeline]
            + [entry for run in snapshot.runs for entry in run.timeline],
            key=lambda item: (item.occurred_at, item.id, item.kind.value),
        )
        return {
            "schema_version": "v0.1",
            "read_only": True,
            "task_board": [self._task_card(task) for task in snapshot.tasks],
            "run_timeline": [self._timeline_entry(item) for item in timeline],
            "agents": [self._agent_card(agent, snapshot.leases) for agent in snapshot.agents],
            "human_inbox": self._human_inbox(snapshot.tasks),
        }

    def render_json(self, source: DashboardSource) -> str:
        return json.dumps(
            self.build_data(source), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    def render_html(self, source: DashboardSource) -> str:
        payload = self.render_json(source)
        safe_payload = (
            payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        )
        return _HTML_TEMPLATE.replace("__TITLE__", html.escape(self.title, quote=True)).replace(
            "__DATA__", safe_payload
        )

    @staticmethod
    def _task_card(task: TaskProjection) -> dict[str, object]:
        return {
            "task_id": task.task_id,
            "project_id": task.project_id,
            "title": task.title,
            "status": task.status.value,
            "attempts": task.attempts,
            "state_revision": task.state_revision,
            "work_item_status": task.work_item_status.value if task.work_item_status else None,
            "candidate_revision": task.candidate_revision,
            "qa_status": task.qa_status,
            "review_verdict": task.review_verdict,
            "run_ids": list(task.run_ids),
            "artifact_ids": list(task.artifact_ids),
            "evidence_ids": list(task.evidence_ids),
            "handoff_id": task.handoff_id,
        }

    @staticmethod
    def _timeline_entry(entry: TimelineEntry) -> dict[str, object]:
        return {
            "id": entry.id,
            "kind": entry.kind.value,
            "occurred_at": entry.occurred_at.isoformat(),
            "task_id": entry.task_id,
            "run_id": entry.run_id,
            "role": entry.role.value if entry.role else None,
            "summary": entry.summary,
            "source_uri": entry.source_uri,
            "source_sha256": entry.source_sha256,
            "details": entry.details,
        }

    @staticmethod
    def _agent_card(
        agent: AgentProjection, leases: tuple[LeaseProjection, ...]
    ) -> dict[str, object]:
        own = tuple(item for item in leases if item.agent_id == agent.agent_id)
        active = tuple(item for item in own if item.status is LeaseProjectionStatus.ACTIVE)
        return {
            "agent_id": agent.agent_id,
            "display_name": agent.display_name,
            "active": agent.active,
            "eligible_roles": [role.value for role in agent.eligible_roles],
            "run_ids": list(agent.run_ids),
            "lease_ids": list(agent.lease_ids),
            "models": list(agent.models),
            "active_lease_count": len(active),
            "active_capacity_units": sum(item.capacity_units for item in active),
            "capacity_known": False,
        }

    @staticmethod
    def _human_inbox(tasks: tuple[TaskProjection, ...]) -> list[dict[str, object]]:
        inbox: list[dict[str, object]] = []
        for task in tasks:
            waiting = (
                task.work_item_status is not None and task.work_item_status.value == "WAITING_HUMAN"
            )
            if not waiting and task.status.value != "BLOCKED":
                continue
            latest = task.timeline[-1] if task.timeline else None
            reason = latest.details.get("reason") if latest is not None else None
            if not isinstance(reason, str) or not reason:
                reason = latest.summary if latest is not None else "Human decision required"
            inbox.append(
                {
                    "task_id": task.task_id,
                    "title": task.title,
                    "status": task.status.value,
                    "work_item_status": task.work_item_status.value
                    if task.work_item_status
                    else None,
                    "reason": reason,
                    "evidence_ids": list(task.evidence_ids),
                    "handoff_id": task.handoff_id,
                    "read_only": True,
                }
            )
        return inbox


_HTML_TEMPLATE = """<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>__TITLE__</title><style>body{font-family:system-ui;background:#111827;color:#e5e7eb;margin:0}main{max-width:1280px;margin:auto;padding:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}section{background:#1f2937;border:1px solid #374151;border-radius:10px;padding:16px}.card{border:1px solid #374151;border-radius:8px;padding:10px;margin:8px 0;background:#111827}.muted{color:#9ca3af;font-size:.85rem}.pill{display:inline-block;border-radius:999px;background:#374151;padding:2px 8px;margin:2px;font-size:.75rem}.timeline{max-height:420px;overflow:auto}</style></head><body><main><h1>__TITLE__</h1><p class=\"muted\">Read-only projection. No state, verdict, command, or merge actions are available here.</p><div class=\"grid\"><section><h2>Task board</h2><div id=\"tasks\"></div></section><section><h2>Agent capacity / detail</h2><div id=\"agents\"></div></section><section><h2>Human inbox</h2><div id=\"inbox\"></div></section><section><h2>Run timeline</h2><div id=\"timeline\" class=\"timeline\"></div></section></div></main><script type=\"application/json\" id=\"projection-data\">__DATA__</script><script>const data=JSON.parse(document.getElementById('projection-data').textContent);const text=v=>v===null||v===undefined?'—':String(v);const add=(p,v,c)=>{const n=document.createElement('div');n.textContent=text(v);if(c)n.className=c;p.appendChild(n);return n};const pill=(p,v)=>add(p,v,'pill');for(const t of data.task_board){const c=document.createElement('div');c.className='card';add(c,t.title);pill(c,t.status);if(t.work_item_status)pill(c,t.work_item_status);add(c,t.task_id+' · attempts '+t.attempts,'muted');add(c,'candidate: '+text(t.candidate_revision),'muted');document.getElementById('tasks').appendChild(c)}for(const a of data.agents){const c=document.createElement('div');c.className='card';add(c,a.display_name||a.agent_id);add(c,a.agent_id,'muted');add(c,'active capacity units: '+a.active_capacity_units,'muted');for(const r of a.eligible_roles)pill(c,r);for(const m of a.models)pill(c,m);document.getElementById('agents').appendChild(c)}for(const i of data.human_inbox){const c=document.createElement('div');c.className='card';add(c,i.title);pill(c,i.status);add(c,i.reason);add(c,i.task_id,'muted');document.getElementById('inbox').appendChild(c)}for(const i of data.run_timeline){const c=document.createElement('div');c.className='card';add(c,i.summary);add(c,i.occurred_at+' · '+i.kind,'muted');add(c,i.task_id||i.run_id||i.id,'muted');document.getElementById('timeline').appendChild(c)}if(!data.task_board.length)add(document.getElementById('tasks'),'No tasks');if(!data.agents.length)add(document.getElementById('agents'),'No agents');if(!data.human_inbox.length)add(document.getElementById('inbox'),'No human action required');if(!data.run_timeline.length)add(document.getElementById('timeline'),'No timeline entries');</script></body></html>"""  # noqa: E501

__all__ = ["DashboardRenderer"]
