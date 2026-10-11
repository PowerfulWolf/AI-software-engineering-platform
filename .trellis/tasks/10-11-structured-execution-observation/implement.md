# Implementation plan

1. Add red tests proving the subprocess bridge currently drops owned stop facts
   before TimeoutExpired and structured JSON rejection.
2. Add immutable observation models, hashing, strict Schema and context binding.
3. Route optional native observer through run_observed before bridge translation.
4. Bind every fallback route and publish separate synchronous HTTP receipts.
5. Validate real native success/timeout/nonzero, invalid JSON, unknown stop,
   publication failure, fallback, nested/thread contexts and Schema equality.
6. Record core contract, incremental commands/results and existing-data limits.
