# Multi-agent collaboration

The bot can coordinate with neighbouring agents to split tasks and reach a
shared decision. This feature is disabled by default and can be toggled by
setting `ENABLE_MULTI_AGENT=true` in the environment.

## Configuration

```
ENABLE_MULTI_AGENT=true
AGENT_ID=alpha
AGENT_NEIGHBORS=beta=http://localhost:8081,gamma=http://localhost:8082
```

* `ENABLE_MULTI_AGENT` — master switch for the whole module. Set to `false` to
  roll back to the single-agent behaviour.
* `AGENT_ID` — the identifier that will be shown to other peers.
* `AGENT_NEIGHBORS` — comma separated list of `name=url` pairs. Every neighbour
  must expose the `/agent_exchange` endpoint.

When OpenAI credentials are present the agent will reuse the assistant model to
prepare its local answer. Without credentials a deterministic summary is
produced, so the consensus string is always the same across nodes.

## Runtime endpoints

* `POST /agent_exchange` — accepts envelopes described in
  `agents/protocol.py` and routes them through the consensus engine.

## Admin command

The `/agents` command is available to the admin account:

* `/agents` — show neighbour status and latest collaborative tasks.
* `/agents broadcast <text>` — send a task to all configured neighbours and
  wait for a consensus answer.

Example session:

```
/agents broadcast analyze latency
📡 Рассылаю задачу: analyze latency
✅ Консенсус достигнут
```

The consensus message is aggregated from the per-agent responses and is shared
with every participant.
