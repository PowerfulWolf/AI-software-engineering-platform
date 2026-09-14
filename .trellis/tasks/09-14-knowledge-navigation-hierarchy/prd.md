# Knowledge navigation hierarchy

## Goal

Make the Knowledge Console understandable without requiring users to infer the difference between a
content type and its ownership scope. Remove successful Requirement operation cards from unrelated
pages.

## Requirements

- Render `团队知识库 / 项目知识库` as independent primary modules.
- Render `背景知识 / 开发规范` inside either module; render `学习改进` only inside Project Knowledge.
- Show a Project selector only inside Project Knowledge. Team Knowledge must not look duplicated under
  every Project.
- Keep full Console operation cards on `需求与交付`; do not repeat them on Team, Knowledge, Settings
  or Status pages.
- Move Project creation from Settings into `需求与交付`.
- Preserve the existing Knowledge, Spec and Learning APIs and data contracts.

## Acceptance Criteria

- [ ] Team Knowledge and Project Knowledge are visibly independent modules.
- [ ] The two navigation levels have visible headings, distinct styles and accessible tab semantics.
- [ ] The selected Project name appears only inside Project Knowledge.
- [ ] Learning appears only inside Project Knowledge.
- [ ] A successful Create Requirement card is hidden outside `需求与交付` and remains available there.
- [ ] Project creation appears in `需求与交付` and not in Settings.
- [ ] Focused JavaScript syntax and DOM interaction tests pass.

## Out of Scope

- Changing Knowledge/Spec/Learning persistence or activation behavior.
- Adding a new backend API or changing Project selection.
- Redesigning the full Web Console navigation.
