# Design

`PolicyBoundToolRegistry._read_file` already returns a typed `ToolRejectedResult` for non-UTF-8 bytes. The Responses adapter currently treats that result as a fatal `WorkspacePolicyError` before it sends the function-call output back to the model. Add only this refusal code to the adapter's existing nonfatal observation set, alongside `FILE_NOT_FOUND`. The rejected bytes remain unreadable, and the protocol still carries `status=REJECTED`; no permission broadening or schema change is required.

Good: an allowed binary file returns a typed rejection, then the Coder can proceed to another call. Base: an absent allowed file behaves as before. Bad: `PATH_DENIED`, `COMMAND_DENIED` or write refusal still ends the Run and does not send a continuation to the model. Keep the original blocked K1 Task immutable; use the existing exact recovery path or add a separately tested terminal source if its current contract cannot admit the successor.
