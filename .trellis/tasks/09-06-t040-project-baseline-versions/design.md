# Bug analysis and versioning contract

## Cause

B/E: project identity was treated as one permanent immutable baseline, so advancing source main
made new intake collide with `project-profile.json`. Real production create reproduced this with
Git/MySQL in 0.82s. Permissions and corrupt input were ruled out by the isolated clean fixture.

## Decision

Keep Project ID, Company module, store paths and canonical models unchanged. Production opts into
content-addressed profile/binding files and profile-scoped preparation stores. Legacy low-level
defaults remain supported. Matching legacy baselines replay exact timestamps without rewrites.
New records use exclusive publication to preserve a concurrent first winner.

## Gates and validation

| Input | Result |
|---|---|
| Same facts across restart | Exact first record/timestamps |
| New source/native profile, new request | New baseline records, same project ID |
| Old request after source update | Existing revision/preparation drift rejection |
| Old Product context against new preparation | ProjectPreparationDrift |
| Corrupt/symlink requested snapshot | Error, no fallback to another snapshot |
| Legacy immutable bytes | Never migrated/replaced/deleted |

Production `_facts` loads by preparation.profile hash. Runtime binding validation loads its exact
profile/binding hash and still rediscovers current project facts. No mutable latest pointer or
approval migration is introduced. Platform/company rule drift within the same profile retains the
existing rejection behavior; this task does not implement general policy-version migration.

## Knowledge capture

Updated production-team-host and company-workspace specs with filenames, signatures, test points
and drift boundaries. No spec-template mirror exists. This is Astra repair, not feature delivery.
