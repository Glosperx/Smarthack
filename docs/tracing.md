# Tracing with Langfuse

The dispatch agent can send a trace of every run to [Langfuse](https://langfuse.com), so a run can
be opened afterwards and each decision read in order. Tracing is a write-only side channel: it
changes nothing the agent decides, and it never stops a sweep.

## What a trace holds

- One root observation per run, `park-dispatch`, tagged `park:<id>`.
- Under it, every node of the graph with what it received and returned, recorded by Langfuse's
  LangGraph callback handler.
- One observation for each question put to the local decision model, `jev.repair_plan` and
  `jev.alert_channel`. Its input is the mode, the state and the options; its output is the record of
  the decision (probabilities, the model's pick, what was used, who decided). Its duration is the
  model's latency. See [Decision model](decision_model.md).

## Settings

All read in `smarthack/config.py` and listed in `.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `LANGFUSE_ENABLED` | `false` | `1`, `true`, `yes` or `on` switch tracing on. Anything else leaves it off. |
| `LANGFUSE_PUBLIC_KEY` | empty | Project public key. |
| `LANGFUSE_SECRET_KEY` | empty | Project secret key. |
| `LANGFUSE_BASE_URL` | `https://cloud.langfuse.com` | EU cloud; use `https://us.cloud.langfuse.com` for the US region, or your own server. |

Even when enabled, tracing does nothing without both keys, and does nothing, with a warning, when
the `monitoring` extra is not installed (`pip install -e ".[monitoring]"`). The keys are passed to
the SDK as arguments; nothing else reads them.

## What leaves the machine

Everything the SDK is about to send goes through `mask_sensitive` first. Three things become
`[masked]`:

- the value under a key that holds contact data or a name: `contact_phone`, `phone_number`,
  `contact_email`, `recipient_email`, `crew_name`, `assigned_crew_name`, ...;
- the names, phone numbers and email addresses of the crews the agent loaded for the park, wherever
  they turn up in text, in any format (a number kept as `0721 234 567` is hidden too). The agent
  registers them as soon as it reads the crews;
- anything shaped like an email address or an international (`+`) phone number.

The crew id stays, so a trace still says which crew was assigned. Turbine data, health status,
probabilities and wind forecasts are sent as they are.

Only dictionaries, lists and strings are looked into. Keep plain dictionaries in the graph state:
a model object (a pydantic instance, say) would go through unmasked. In the memory data source the
crew names are team names such as "Alpha Response Team" and are masked too; in the Supabase source
they are employees' full names, which is why they are.

Check this against your own rules before pointing a production sweep at a cloud project.

The free Hobby plan of the cloud service keeps 30 days and 50,000 units a month (checked
2026-11-08). A sweep of one park costs a handful of observations per node and per question.

## Tokens

Langfuse shows tokens and cost only for observations of type `generation` with `usage_details`,
and bills in units (traces, observations, scores), never in tokens. Two calls are generations:

- `jev.repair_plan` and `jev.alert_channel`, model `jeffan-4b`. The decision server counts the
  prompt of each question and returns it as `usage.prompt_tokens`; the client keeps it in
  `DecisionClient.last_prompt_tokens` and the decision sends it as `input` tokens. Jeffan writes no
  text, so `output` is 0, and it runs locally, so there is no cost. An older server that does not
  report the count leaves the observation without tokens.
- `gemini.alert_payload`, model `gemini-3.8-flash`, one per alert text. `input` is the prompt, `output`
  is the answer plus the thinking tokens, which Google bills as output. Gemini needs the `llm` extra
  (`google-genai`); without it, or without `GEMINI_API_KEY`, the templates are used and nothing is
  traced. Langfuse shows a cost only for a model it has a price for; add one under Settings, Models
  if `gemini-3.8-flash` has none.

## Failures

An error from the SDK is logged and swallowed, and so is an SDK that is installed but cannot be
imported (a dependency missing, a library that will not load): tracing goes off with a warning and
the sweep carries on. With the Langfuse server unreachable, a run is slowed by a few seconds while
the exporter gives up; it does not fail. An exception of the agent itself is never hidden: the
trace is closed and the exception goes on. At the end of every run the buffer is flushed, so a short
run does not end before its trace is out.
