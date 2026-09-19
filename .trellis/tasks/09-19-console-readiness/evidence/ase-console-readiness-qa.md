# Independent Console readiness QA

- task_id: `console-readiness`
- source_revision: `b8983b82fbc56c6b7d90dbc0c2722af835bee614`
- context_manifest_id: `console-readiness-20260919`
- QA agent: `/root/console_qa` (independent from implementation and Review)
- workspace: `/private/tmp/ase-console-readiness-20260919`
- conclusion: **PASS for the tested frontend regression scope**
- candidate identity: uncommitted worktree patch, bound to the app.js SHA-256 below.

This is an engineering QA report, not a runtime Artifact or a state-machine transition approval.
QA modified only `tests/team_view/readiness.test.cjs` and this report; no production code, rules,
production model, database, operation journal, approval, or queue was changed by QA.

## Evidence

| Evidence | SHA-256 |
| --- | --- |
| `src/ai_software_engineer/team_view/app.js` | `a1496d6bb47d510b3d95d55b7d6ab61a14ef18139e872705008908edda415c42` |
| `tests/team_view/readiness.test.cjs` | `c41cf36831a5f64efd4043275276f8103234c4a3f5f616052ab805448bd0e0fd` |
| `/private/tmp/ase-console-readiness-qa-tests.log` | `ef51206c4b431852df9eafb5dfff11cf685a7c5ceb6dc42643c1babba36e1796` |
| `/private/tmp/ase-console-readiness-baseline-tests.log` | `1d452f89694a46ee5518f695ea613520bf3f7bd081ad1e6e4442f1a94a04b427` |

## Commands and results

All commands ran in the workspace above.

1. `node --check src/ai_software_engineer/team_view/app.js`: exit 0.
2. `node --check tests/team_view/readiness.test.cjs`: exit 0.
3. `node --test tests/team_view/*.test.cjs`: exit 0, **17 tests passed**, none failed/skipped.
   This includes 11 new independent readiness cases and 6 existing UI contract tests.
4. `git diff --check`: exit 0.
5. `git show b8983b8:src/ai_software_engineer/team_view/app.js > /private/tmp/ase-console-readiness-baseline.js`:
   extracted the exact baseline application script without changing the candidate.
6. `ASE_READINESS_APP_JS=/private/tmp/ase-console-readiness-baseline.js node --test tests/team_view/readiness.test.cjs`:
   expected exit 1, **10 failed / 1 passed**. The identical harness and acceptance assertions were
   used against the baseline and candidate, with only the script path changed.

The first baseline failure directly reproduced the user's conflicting banners: the rendered Settings
content simultaneously contained “当前交付运行时尚未就绪；请检查下方配置，保存后按提示重启服务。” and
“配置已应用，Web Console 已使用保存的运行配置重新启动。” after a confirmed successful restart.
That assertion passes against the candidate.

## Acceptance coverage

| Scenario | Result |
| --- | --- |
| Apply confirms SUCCEEDED, Settings restart flag becomes false, and Console readiness becomes true | Setup warning disappears immediately; active-configuration badge renders. |
| Success lifetime expires after 5 seconds | Notification disappears and does not reappear on Settings reentry. |
| User closes success notification | It remains dismissed on Settings reentry. |
| Existing historical SUCCEEDED lifecycle is read during ordinary navigation | No new success notification starts. |
| User edits draft path and write-only password while apply is in flight | Successful reconnect preserves both unsaved values. |
| Team read fails after initial snapshot; user manually restarted service | Console and Settings still refresh; stale warning/restart badge clear; unsaved path/password survive; Team failure remains disclosed. |
| First Team read fails and no snapshot exists | Settings and Status render from their own authorities; snapshot stays null and connection failure remains visible. |
| Manual restart occurs with a save-result dialog still open | Dialog changes to “配置已生效”, removing stale apply/restart instructions; Settings also refreshes. |
| Status readiness/restart facts transition | Dependency view reloads; unchanged polling does not repeatedly probe dependencies. |
| Dependency remains unavailable while restart_required=false | Status shows the actual dependency failure and never recommends another restart. |
| Console or Status request fails | No true Console readiness or ready Status summary is fabricated. |
| Operations list request fails while Console remains ready | Runtime facts remain readable, delivery controls are disabled, and controls recover after Operations succeeds. |

## Findings and limits

QA identified the initial `snapshot=null` render guard as an additional failure mode during inspection
and reported it to the implementer. The implementer addressed it; the new independent regression passes.
No remaining blocker was found in the tested scope.

The harness executes the actual shipped script inside Node VM with DOM elements, navigation/input
events, fake HTTP responses, and controlled timers. It does not call real network services or a browser.
This report does **not** claim visual/layout acceptance, native browser focus/caret testing, full HTTP
transport integration, or production restart validation. Existing UI tests remain unchanged and pass.
Independent read-only Review is still required by the project workflow.

No production persisted facts require repair for this frontend patch. Existing apply lifecycle history
is intentionally retained; historical success is ignored as a new UI event. Deploy the verified frontend
asset and reload the existing browser page to read current Console/Settings/Status facts.
