# How tiers work

Every permission request gets a **tier** from rules alone, from the real command and where it
runs. No model decides a tier.

| Tier | What it covers | How you answer |
| --- | --- | --- |
| 1 | Reads and edits inside the project, and commands a rule knows are routine (running tests, a build) | Say **yes** (or nod, if you switched nods on) |
| 2 | Anything outside the project, installs, commands no rule matches, edits to build or test config | Say **approve** and the fresh word it asks for, in your voice |
| 3 | Secrets, the agent's or Earshot's own settings, force pushes and pushes to the default branch, recursive deletes, piping into a shell, deploys, and anything Earshot can't read with certainty | **Never by voice.** It goes to the screen |

There is no tier 0: nothing is approved without an answer.

- **Doubt raises the tier.** A command Earshot can't parse, or that builds its program at run
  time (`bash -c "$(…)"`, `python -c`), is tier 3.
- **A risk gate can only raise a tier.** A score of 0.5 or more makes it tier 2, 0.85 or more
  tier 3, and a gate that fails or is slow changes nothing.
- **Earshot reads out the details that matter.** Each critical field of the real command (the
  package, the branch, the path) is in what you hear, and a checker refuses a sentence that
  drops or invents one.
- **Your policy file** can make rules stricter or add trusted places; see `earshot policy check`
  to dry-run a saved request. It can't make tier 3 approvable.

The full attack table, with what was tried and what's still a limit, is in
[redteam.md](redteam.md).
