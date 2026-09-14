# Design

Knowledge ownership is selected before content type:

```text
Knowledge module
  Team Knowledge
    +-- Background knowledge | Development Specs
  Project Knowledge
    +-- Project selector
    +-- Background knowledge | Development Specs | Learning improvements
```

This makes Team Knowledge independent of Project selection. Learning improvements are produced from
one Project's QA/Review evidence, so they are available only in Project Knowledge.

The global operation store remains unchanged. The browser continues loading it because Requirement
details use exact operation facts for approval and recovery, but the full operation-card region is
visible only on the Requirements page. This is a presentation boundary, not a loss of durable facts.

Project creation belongs to the Requirements workflow. Settings is limited to process/runtime
configuration; the existing typed Project administration endpoint is reused without changing its
contract.
