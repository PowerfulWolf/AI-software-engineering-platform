# Design

Keep the seam inside `CodexCliAgentAdapter`: callers still receive one typed `AgentResult` and do not
learn Git finalization details. On a successful Coder provider response with unchanged HEAD and a
dirty worktree, treat the returned implementation report as provisional only when both revision
fields equal the immutable request source revision.

Before mutation, compute tracked and untracked changed paths, require exact equality with the report,
and authorize every path through `WorkspacePolicy`. Then use platform-owned fixed Git argv with hooks,
signing and interactive prompting disabled to stage only the validated paths and create one commit.
Replace only the two provisional revision fields with the observed final HEAD and run the existing
clean-worktree/diff/report validation unchanged.

Any error preserves the worktree and returns a non-transient policy failure. A model-created clean
commit follows the existing path without platform finalization.
