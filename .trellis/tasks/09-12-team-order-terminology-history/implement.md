# Implementation checklist

- [x] Confirm durable role identities and current renderer behavior.
- [x] Introduce Team/Project/Requirement/Repository v0.2 domain contracts and target layout.
- [x] Rename Project Manager role and services to Manager without compatibility ambiguity.
- [x] Add stable explicit team member ordering and shuffled fixture assertions.
- [x] Replace Company/Requirement Project user-facing labels and APIs with Team/Project/Requirement.
- [x] Clarify merge-ready candidate branch wording without adding automatic merge behavior.
- [ ] Add a read-only legacy inventory and explicit migration/cleanup plan.
- [ ] Migrate the retained completed Requirement and remove only resolved non-DONE closures.
- [x] Update Web Console/live-view/workspace executable specs.
- [x] Add and document the background Web Console service lifecycle script.
- [x] Run focused frontend, service lifecycle and formatting checks.
- [ ] Inventory runtime history read-only and produce exact cleanup scope.
- [ ] Execute consistent unfinished-history cleanup only after targets are unambiguous.
