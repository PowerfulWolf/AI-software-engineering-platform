# Implementation

- Added typed `DialogueTurnView` and `DialogueAttachmentView` to the Requirement read model.
- Restricted durable joint dialogue speakers to the actual `user | product` union.
- Projected exact current checkpoint dialogue through `ProductionTeamReader`, including redacted text
  and safe screenshot metadata without paths or bytes.
- Added a chronological chat timeline to Requirement detail.
- Fixed Requirement selection so the entire card, not only its title, opens the exact detail; added
  keyboard activation, focus styling and `aria-current` selection state.
- Kept the reply composer available for Product clarification and for revising an unapproved
  ProductSpec; only the explicit approval control advances delivery.
- Unified dialogue history, approval guidance and composer in one Requirement detail section.
  Product processing keeps a disabled composer; interrupted processing is labelled
  `继续需求讨论` instead of the implementation-oriented `继续交付`.
- Updated the Requirement and Team snapshot wire schemas and user/developer documentation.

No new write service, state, model invocation or persistence location was introduced.
