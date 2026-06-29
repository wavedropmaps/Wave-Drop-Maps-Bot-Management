# Context: Vanity/Personal Roles Are Not Hierarchy Tiers

## The Symptom
"The Watcher" appeared as a **Founder** on the team page org chart despite not being a founder. The user was (rightfully) angry.

## The Root Cause
The TIER_ORDER board tier was defined as `['Fruss', 'Founder', 'Owner']`. The name `Fruss` was assumed to be a tier role because it appeared at the top of the org chart alongside Founder/Owner. In reality, `Fruss` is a **personal vanity role** named after the person Fruss — it is given to certain trusted individuals as a cosmetic/status role, NOT as an organisational tier. "The Watcher" had the Fruss vanity role, which matched the board tier, incorrectly placing them as a Founder.

## The Lesson Learned
**Rule: Never add a role to TIER_ORDER or _TEAM_SLOTS based on its name alone — verify it is an actual organisational tier, not a personal/vanity role.**

Signals that a role is a vanity/personal role (NOT a tier):
- Named after a specific person (e.g. "Fruss", "KingJixer")
- Only one or two people have it
- It doesn't correspond to a job function or reporting line

When in doubt, ask the user: "Is [role name] an organisational tier or a personal/vanity role?" before adding it to the hierarchy.
