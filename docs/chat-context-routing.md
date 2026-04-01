# Chat Context Routing

This document summarizes the chat-context changes added for the tutoring flow.

## What Changed

- Chat messages are now grouped into `topic_blocks` instead of using a flat recent-history window.
- Each incoming chat query is routed to:
  - the active block
  - a reopened recent block
  - or a brand-new block
- Every routing decision is logged in `topic_routing_decisions` for debugging.
- Follow-up simplification requests like `explain simply` and `explain it simply` override normal similarity checks.
- Contextual follow-ups skip the global semantic cache so they cannot be hijacked by an unrelated cached answer.
- Assistant responses are persisted synchronously in the chat request path so the very next follow-up sees the latest answer immediately.

## Current Follow-Up Rules

The router treats the latest user message as a follow-up when:

- it explicitly references a prior step or value
- it requests continuation
- it asks for a simpler re-explanation
- or it has strong similarity to the active block

For simplify-style follow-ups, the router adds an extra system instruction telling the model:

- the message refers to the previous topic/answer
- not to the assistant's response format
- and the reply should be shorter and more beginner-friendly

## Schema Additions

The change adds:

- `messages.block_id`
- `topic_blocks`
- `topic_routing_decisions`
- `user_mistake_patterns`

## Operational Notes

- Existing databases need the topic-block migration applied before chat works.
- Local machines that cannot reach the direct Supabase Postgres host should use the Supabase pooler connection string in `DATABASE_URL`.
- The chat UI may need a hard refresh after backend restarts so stale in-memory state does not mask backend fixes.
