# Code Review

## Task

Review **$task** thoroughly. Trace through all logic paths until you have the complete picture. Find:

- **Dead/unused code** - functions, imports, variables, files with no callers
- **Dangling references** - broken imports, missing deps, orphaned calls after refactors
- **Stale/outdated content** - docs, comments, naming that doesn't match current code
- **Redundancy** - DRY violations, duplicate logic that should be consolidated
- **Over-complexity** - anything that could be simplified while maintaining functionality
- **Backwards Compatibility** - look for legacy/compatibility only things that can be cleaned up

For each finding, note: what, where (file:line), and why it's an issue.

## Output

Present a categorized summary of issues found:

- Group by category, not by file
- Prioritize by severity (critical → minor)
- Surface any questions needing clarification

Do not implement fixes yet - findings only for review and approval. Thanks!
