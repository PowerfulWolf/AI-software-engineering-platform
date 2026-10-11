# Ownership
inspect_recovery_entry implements typed capture/proof/resolution/fencing/admission and focused tests.
Other worker owns runner._run_agent and agents live validation; do not overwrite it.
Root owns task/spec/UI/independent review/deployment and actual public recovery.
No production mutations, direct SQL edits or commits by workers.
