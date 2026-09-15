# Design: durable Product dialogue in Web Console

## Existing architecture

The joint Requirement runtime is already the write authority for Product discussion:

```text
ProductReplyIntent
  -> ManagerConsoleAdapter
  -> JointDeliveryService.reply
  -> append user DialogueMessage
  -> Product Agent
  -> append Product clarification, or publish ProductSpec
```

`JointCheckpoint.dialogue` is immutable, ordered and checkpoint-bound. The Web Console currently
projects ProductSpec but not dialogue, so the browser cannot render the Agent side of the exchange.

## Change

Add a read-only `DialogueTurnView` and `DialogueAttachmentView` to `RequestView`. The production
reader derives them from the exact current `JointCheckpoint.dialogue` prefix. It exposes only safe
text and attachment metadata, never filesystem paths or image bytes.

The request detail panel renders a chronological chat before the reply controls:

- user turns are labelled `你`;
- Product turns are labelled `Product Agent`;
- newlines are preserved and screenshot names are shown as attachment chips;
- empty dialogue stays hidden;
- `WAITING_PRODUCT_REPLY` keeps a `回复 Product Agent` composer;
- `WAITING_PRODUCT_APPROVAL` shows both exact approval and `继续讨论并修订`.
- the dialogue timeline, Product approval prompt and composer share one `detail-section`; the
  composer is subordinate content and cannot introduce a second divider;
- `PRODUCT_DISCOVERY` keeps the disabled composer visible. An active Operation says Product is
  replying; an interrupted state offers `继续需求讨论` through the existing continuation command.

No new command, provider call, state or store is introduced. Existing checkpoint fencing,
operation idempotency and ProductSpec invalidation remain authoritative.

## Data flow

```text
JointCheckpoint.dialogue
  -> ProductionTeamReader
  -> RequestView.dialogue
  -> team-snapshot.schema.json
  -> request detail chat timeline
```

## Test points

- reader preserves ordered user/Product turns and safe screenshot metadata;
- Schema remains exactly equal to the Pydantic read model;
- browser displays both speakers in order;
- Product clarification stage renders a reply composer;
- ProductSpec approval stage renders approve and continue-discussion choices;
- Product processing and interruption preserve the composer and discussion-specific status/action;
- no dialogue produces no empty chat panel;
- external text remains `textContent` only.
