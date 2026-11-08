# Decision model in the dispatch agent

The dispatch agent can ask a small local model, Jeffan 4B, to make two of its decisions:

- which **repair plan** the crew follows, and
- on which **channel** the crew is alerted about a turbine.

The model never plans and never computes. The code prepares every option, the model scores them,
and the code decides how far to trust the score. With the model off, which is the default, the
agent behaves as a plain rule-based pipeline and makes no HTTP call.

!!! note "What the tests show"
    On the test scenarios the model **ties** the rules; it does not beat them. For the alert
    channel (80 scenarios) it scored 0.938 against the rule's 0.925, and the bootstrap interval of
    that difference includes zero. For the repair plan (60 scenarios) it picked the exact optimum
    in 54 and a plan that saves fewer turbines in one, which the code check catches.
    The setup is worth having for the day the requests carry what code cannot compute, such as
    technicians' notes. Until then it is run in shadow mode, to see where it would differ.

## Where it sits in the graph

```
predict_maintenance -> triage_park -> check_failure_overlap
    -> [power_prioritization, only when failures overlap]
    -> schedule_repairs        the exact optimum, as before
    -> choose_repair_plan      the model picks among the optimum and alternatives
    -> rank_and_match_crews    turbines in the order of the chosen plan
    -> decide_and_dispatch_alerts   the model scores the channel of each turbine
```

Whether to call the wind power model (ML2) stays a rule: the models tested were far below it.
One fix went in with this change: a turbine ML1 expects to last the week (a lead time of
`NO_FAILURE_DAYS`, 8 days, or more, or none at all) has no failure day, so it can no longer make
two failures overlap by being given a made-up day.

## Settings

All read in `smarthack/config.py` and listed in `.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `DECISION_MODEL_ENABLED` | `false` | `1`, `true`, `yes` or `on` switch the model on. Anything else, a typo included, leaves it off. |
| `DECISION_MODEL_URL` | `http://127.0.0.1:8765` | Where the server listens. |
| `DECISION_MODEL_MODE` | `umbra` | `umbra` (shadow): the rule decides, the model's choice is only logged beside it. `activ`: the model decides, checked by the code. Anything else means `umbra`. |

The timeout is a constant (`DECISION_TIMEOUT_SECONDS`, 10 s, of which 2 s to connect), not a
setting: past it the rule decides, so waiting longer only delays the sweep.

## The repair plan

The code builds the plans a dispatcher would weigh, the exact optimum first:

- the optimum from `repair_scheduler`;
- most urgent first (earliest failure day, then higher output);
- highest output first;
- most distant first.

The three greedy plans give each turbine the earliest free day before its failure day. Identical
plans are kept once. Each plan is written in words: which turbine is repaired on which day, which
turbines are left to fail, how many are saved and the output lost on repair days (output times the
wind speed of the day). The options are named `plan_A`, `plan_B`, ... in an order shuffled from the
park and turbine ids: the same situation always gives the same request, and no plan keeps a letter.

The pick is the plan with the highest probability.

- In `umbra` the optimum is always used and the pick is logged.
- In `activ` the pick is used, except that it is **refused when it saves fewer turbines than the
  optimum**. A pick that saves as many turbines but loses more output is accepted: telling it
  apart from a better one would mean overriding the model whenever it differs, and then it would
  decide nothing. That is the known cost of letting it choose.

The model is not asked when:

- it is off, or already failed earlier in the run;
- there is no wind forecast (the plans would differ in nothing the model can see);
- no turbine has an output estimate, because the power model did not run (the plans could not be
  compared on output lost);
- all candidate plans are the same.

`rank_and_match_crews` then orders the turbines by repair day in the chosen plan, turbines that
cannot be saved last (higher output first), and hands out the crews in that order.

!!! warning "The candidate set differs from the tested one"
    The test used "the agent's old order" as one candidate. That order no longer exists, so
    "highest output first" takes its place. The 54 of 60 therefore describes a neighbouring
    setup, not this one exactly. Re-run `decision_model.priority` with the new set to measure it.

## The alert channel

One request per turbine, with the policy of the rule written into the question, built from the
same constants the rule reads (`CHANNEL_CALL_DAYS`, `CHANNEL_CALL_PROBABILITY`,
`CHANNEL_EMAIL_PROBABILITY`). Without the policy the model had to guess the thresholds, and its
accuracy on the test set fell to 0.60.

| Channel | Value | What is sent |
|---|---|---|
| `AlertChannel.VOICE_CALL` | `email_si_apel` | A phone call **and** an email: a call alone leaves the crew nothing written to act from. |
| `AlertChannel.EMAIL` | `doar_email` | An email. |
| `AlertChannel.NONE` | `nimic` | Nothing. |

A `CRITICAL` turbine always gets the call, whatever the model says. In `activ` the model is not
asked about it; in `umbra` it is, only so that the log shows when it disagrees (a warning).

## Failures

Any error from the model, whether it is down, too slow, answers with an error status or sends a
malformed answer (options that do not match, a probability outside 0 to 1, a sum that is not 1),
falls back to the optimum or the rule. The run is marked `decision_model_down`, and no later node
waits on the model again.

## What is logged and kept

Each plan decision and each channel decision is logged at `INFO` with the options, the
probabilities, the model's pick, what was used, who decided (`source`: `rule`, `model`,
`hard_rule` or `rule_fallback`) and the latency. A refused plan, a fallback, a model that is down
and a hard rule overriding the model are logged at `WARNING`. The same data is in the final graph
state: `repair_plan_choice`, `channel_decisions` and `decision_model_down`. `DispatchDecision` and
the API routes are unchanged apart from the three channel values above.

## Running the server

The model runs natively on the Mac, on MPS, about 9 GB. Not in Docker: Docker on a Mac cannot see
the Metal GPU.

```
make decision-server
```

It serves the System One format on `127.0.0.1` only. Nothing authenticates a caller, and the
requests carry turbine data.

```
POST /v1/systemone
{"state": {...}, "questions": {"q": {"type": "choice", "instructions": "...", "criteria": {"option": "description"}}}}

{"answers": {"q": {"probabilities": {"option": 0.9}}}}

GET /health
```

It answers 400 for a malformed body, 413 for one over a megabyte and 422 for a question that is
not a `choice`. Each question costs one forward pass, and passes run one at a time. The server
lives in `experiments/decision_model`, which has its own environment and imports nothing from
`smarthack`; the agent's half of the contract is `smarthack/clients/decision_client.py`.
