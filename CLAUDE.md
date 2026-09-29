# CLAUDE.md

**Read [`AGENTS.md`](AGENTS.md) first.** It is the authoritative contract for all agents
working in this repository, and everything in it applies to you. This file only adds what
is specific to Claude Code.

## Claude Code specifics

**CodeScene.** The CodeScene MCP server (`cs-mcp`) exposes `code_health_review`,
`code_health_score` and `pre_commit_code_health_safeguard`. If those tools are present,
use them. If they are not, the server is not configured for your profile - that is not a
reason to skip measurement: `python3 tools/ch.py` drives the same `cs-mcp` binary over
stdio and gives the same scores and findings. `CS_ACCESS_TOKEN` must be set in the
environment.

**Record the tool versions.** Scores move between CodeScene versions. The committed
baseline records `cs-mcp` and `cs` versions; a score you compare against it should come
from the same versions, or say that it does not.

## Refactoring campaign

Because you can reason about data flow, you are the right harness for the recipes that
need judgement: Recipe E (extract function), which must decide what crosses the
boundary, and any extraction inside an OpenMP loop body, where the playbook's rule about
which variables a block may write has to be checked by reading, not by a tool.

## Reminders that matter here

- **The oracle is cheap now - use it on every commit.** `tools/oracle/oracle.py run
  --function <Function>` runs only the cases that reach the function, usually in seconds.
  The whole catalogue (about 2 minutes warm) runs before a branch is pushed.
- **Check protection before you start, not after.** A function that no case executes, or
  whose mutants mostly survive, is not protected by a green oracle run. The backlog's
  readiness column and `docs/refactoring/MUTATION.md` say which files are ready.
- **A Code Health score of 4.00 is a milestone, not the finish line.** It marks leaving
  the Red band. Keep applying the closed catalogue until no legal recipe raises the score
  further, then report where the file plateaued and why. The target is 10.00.
- **The 3SX campaign is the model.** Its playbook, in the Street Fighter III repository,
  holds many more recipes, each measured. When a file here plateaus, look there for a
  recipe that fits before inventing one, and propose it for this catalogue rather than
  applying it unannounced.
