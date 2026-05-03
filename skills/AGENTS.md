# Instructions

- Skills here are installed independently into user environments. Treat each skill directory as the agent's whole available context; do not rely on examples, docs, sibling skills, or repo-root files unless they are copied into that skill.
- The target reader is a capable AI agent. Skip widely known background, including common Android implementation patterns, unless GlassKit uses them in a non-obvious way.
- Spend words on project-specific context an agent cannot reliably infer: what Rokid Glasses are, their HUD and input constraints, device setup quirks, camera/microphone/speaker caveats, and GlassKit-specific naming or workflows.
- If a skill needs reference material or example code to be understood, keep that material inside the skill directory and make it easy for the agent to find from `SKILL.md`.
- Commit messages for changes under this directory must start with `skills: `.
