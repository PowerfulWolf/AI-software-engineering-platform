# Implementation record

- New Darwin kernel observations query only fixed-size `kern.bootsessionuuid`, strictly
  validate NUL/ASCII/canonical UUID and publish its canonical hash with an explicit prefix.
- Added explicit optional `RecordedBootContinuity` to the read-side original-session check,
  retaining full birth/SID checks and a fresh final boot observation.
- Added `ScopedNativeStopVerifier` in trusted baseline composition. It reopens exact original
  native/capture witnesses and approved own/ancestor baseline anchors on every boundary read.
- Routed the three knowledge-proof readers after complete claim/context validation through
  the typed exact-receipt checker. Capture reconciliation receives an optional checker;
  default behavior remains strict and existing wire schemas remain byte-compatible.
- Added file-store anchor/recovery, receipt/capture-envelope, stable boundary, temporal
  contradiction, live-birth/SID and default strictness regression coverage. Test observers
  are explicit fixture seams; they do not assert any production stop.

The parent performs independent review, combined integration verification and actual public
stock-data recovery. This implementation does not change production stores or K1 source.
Final test results are appended to `verification.md`; no unrun check is reported as passed.
