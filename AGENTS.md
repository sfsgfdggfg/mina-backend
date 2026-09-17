# MINAI Repository Working Rules

## Chat / Session Scope and Timeout Prevention

- Use one ChatGPT conversation for one main work topic.
- The assistant is responsible for detecting when the current main topic has reached a natural stopping point; the user should not have to track this manually.
- Before starting a different main topic, the assistant must recommend opening a new ChatGPT conversation.
- Directly connected small follow-up tasks may stay in the same conversation when they are part of the same main topic.
- If the conversation becomes unusually long, tool output grows large, or timeout risk starts increasing, the assistant should recommend an earlier handoff even if the topic is not fully exhausted.
- Before a conversation handoff, the assistant must provide a concise copy-paste handoff containing, when applicable: current release/head, branch/worktree, completed work, open work, the next single task, and critical safety/operational constraints.
- Within a conversation, keep unfinished technical work atomic: complete and verify one task before moving to the next.

This is a development-collaboration rule. It does not change MINAI product behavior or operational business rules.
