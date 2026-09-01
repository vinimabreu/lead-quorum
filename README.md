<img src="assets/banner.png" width="100%" alt="lead-quorum: two models read each lead independently, agree and the score adds up, disagree and it abstains" />

# lead-quorum

<p>
<img src="https://img.shields.io/badge/license-MIT-6E56CF?style=flat-square" alt="MIT license">
<img src="https://img.shields.io/badge/python-3.12-6E56CF?style=flat-square&logo=python&logoColor=white" alt="Python 3.12">
<img src="https://img.shields.io/badge/tests-16%20passing-6E56CF?style=flat-square&logo=pytest&logoColor=white" alt="16 tests passing">
<img src="https://img.shields.io/badge/Google%20ADK-2.3-6E56CF?style=flat-square" alt="Google ADK 2.3">
<img src="https://img.shields.io/badge/A2A%20protocol-6E56CF?style=flat-square" alt="A2A protocol">
<img src="https://img.shields.io/badge/Cloud%20Run-ready-6E56CF?style=flat-square&logo=googlecloud&logoColor=white" alt="Cloud Run ready">
<img src="https://github.com/vinimabreu/lead-quorum/actions/workflows/ci.yml/badge.svg" alt="CI">
</p>

A distributed multi-agent lead qualifier built on Google's Agent Development Kit (ADK) and
the Agent2Agent (A2A) protocol. Two independent LLM readers, running **different models as
separate microservices**, extract the same lead from raw notes. Deterministic code scores
it with a reason that provably reconciles to the number. If the two readers disagree about
which scoring rules fire, the system **abstains** instead of guessing.

The model proposes, the code disposes, and no score ships unless two independent readings
agree it is real.

> Recognized by DEV's *Build Multi-Agent Systems with ADK* education track (Cloud Run Badge).
> [Read the writeup, with a live interactive Cloud Run demo you can paste your own notes into.](https://dev.to/vinimabreu/lead-quorum-a-multi-agent-lead-qualifier-that-refuses-to-guess-adk-a2a-5dom)

## Why this exists

Lead scoring is usually one big prompt: paste the lead, ask for a number. Three things
break in production:

1. **The score is opaque.** Nobody can answer "why is this a 60 and not a 40?"
2. **The explanation drifts.** The reason text is generated separately from the scoring
   logic, so when a threshold changes, the number moves and the story stays put.
3. **Confidently wrong on thin input.** A single model always returns a number, even when
   the notes do not support one.

This system attacks all three by construction.

## Architecture

```mermaid
flowchart TD
    N["raw lead notes"] --> O["orchestrator (SequentialAgent)"]
    O --> P["ParallelAgent: two independent readers"]
    P --> A["enrichment reader<br/>gemini-flash-latest<br/>A2A microservice"]
    P --> B["rederive reader<br/>gemini-2.5-flash-lite<br/>A2A microservice"]
    A --> S["ScoringAgent<br/>deterministic, no LLM<br/>reason built where points are added"]
    S --> C["CorroborationAgent<br/>deterministic, score-space compare"]
    B --> C
    C --> V1["CONFIRMED<br/>score + reconciling reason"]
    C --> V2["REVIEW<br/>score stands, drift flagged"]
    C --> V3["EXCLUDED<br/>abstain, flipped rule named"]

    style A fill:#6E56CF,color:#fff
    style B fill:#6E56CF,color:#fff
    style V1 fill:#1f9d55,color:#fff
    style V2 fill:#c98a00,color:#fff
    style V3 fill:#c1121f,color:#fff
```

- **Two readers, two models, two services.** Each reader is exposed over A2A with
  `to_a2a()` and consumed with `RemoteA2aAgent`, so corroboration is genuinely
  cross-model and cross-process, not one model agreeing with itself.
- **Scoring is pure code** (`core/scoring.py`). Every rule grants its points and writes
  its reason on the same branch, so the explanation cannot drift from the number. A test
  parses the reason and asserts the named points sum to the score.
- **Corroboration is compared in score-space** (`core/corroboration.py`). Value noise on
  the same side of every threshold is drift (verdict REVIEW, score stands, flagged).
  A disagreement that flips a rule would change the score itself, so the verdict is
  EXCLUDED and the system abstains, naming the rule that flipped and both readings.
- **Exactly two LLM calls per lead**, both in parallel, temperature 0. Everything else is
  deterministic Python. Multi-agent done naively is slower and pricier than one prompt;
  this is engineered to be cheaper per unit of trust.

## What a run looks like

Clear notes, both models agree:

```
CONFIRMED  60/100: +35 team of 30 seats >= 25; +15 reachable decision maker (vp);
           +10 renewed at least once
```

Ambiguous notes ("they mentioned possibly renewing"), the models read it differently:

```
EXCLUDED   readings disagree on which signals fire (prior_relationship: False vs True);
           abstaining instead of scoring a contradiction
```

That second answer is the point. One reader took "possibly renewing" as a renewal, the
other did not, the score would differ, so no number is shown. A defensible abstention
beats a fake-precise score built on a contradiction.

Both, live in the web UI (the whole audit trail on screen, not just a number):

<p align="center">
  <img src="assets/shot-confirmed.png" width="49%" alt="CONFIRMED: score 60 with the reason that adds up, both readings agreeing on every field">
  <img src="assets/shot-excluded.png" width="49%" alt="EXCLUDED: no score, the flipped rule named, the disagreeing rows highlighted in red">
</p>

## Run it

```bash
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
cp .env.example .env   # add your free Gemini API key (aistudio.google.com/apikey)

# single-process pipeline + web UI
.venv/bin/uvicorn web.app:app --port 8000

# the distributed proof: two A2A services + remote orchestrator, local
.venv/bin/python scripts/demo_distributed.py

# tests (deterministic core needs no key; one live test uses it if present)
.venv/bin/python -m pytest tests/ -q
```

The web UI shows the verdict badge, the score with its reconciling reason, and the two
readings side by side with disagreements highlighted.

## Ota

This repository includes an [`ota.yaml`](./ota.yaml) contract for deterministic verification, the
local web runtime, the distributed A2A demo, and the Dockerfile-owned verification image. Install
Ota from the [official installation guide](https://ota.run/docs/install), then inspect the
contract-owned task surface before choosing a lane.

```bash
# validate the contract, inspect readiness, and list human and safe-agent commands
ota validate .
ota doctor
ota tasks --use
ota tasks --safe --use

# run deterministic verification in the native repo-local virtual environment
ota up --workflow verify

# run deterministic verification in the repository Dockerfile image
ota up --workflow verify:container

# start the local web UI and prove its health endpoint
ota up --workflow app
```

The `live` and `distributed` workflows require the external Gemini path. Inspect their effects
and inputs with `ota tasks --use` before running them.

## Deploy (Cloud Run)

One image, role picked by env var. See `DEPLOY.md` for the exact commands: two reader
services (`SERVICE=a2a`, `AGENT=enrichment|rederive`), one web/orchestrator service wired
to their agent-card URLs.

## Layout

```
core/        pure logic: scoring rubric, score-space corroboration, schemas (no ADK, no LLM)
agents/      ADK layer: LlmAgent readers, deterministic BaseAgents, pipelines, A2A server
web/         FastAPI frontend
scripts/     reproducible distributed demo
tests/       16 tests: reconciliation, abstention, agent wiring, live end to end
```

## Honest limitations

- The rubric is a demo rubric (four rules). The point is the harness around it: swap in
  your own rules and the reconciliation test and corroboration keep holding.
- **Reader independence is nominal until measured.** The two readers here are Gemini flash
  and flash-lite, one lineage, so they can fail the same way, and they correlate hardest on
  exactly the hedged inputs where you most wanted a second opinion. The A2A card is what
  makes real independence reachable (the second reader can be any vendor or framework
  without touching the pipeline), but it is not cashed in with two same-family models. Treat
  independence as a measured quantity, not an assumption: run both readers on a labeled
  ambiguous set and check that they actually disagree when they should.
- **A low EXCLUDED rate is not a health signal.** Score-space corroboration compares reader
  against reader, which is orthogonal to whether the rubric is right. Both readers run the
  same rubric, so a rubric that over-scores yields agreement, a low EXCLUDED rate, and a
  CONFIRMED bucket nobody audits, all of which looks healthy from the outside. Corroboration
  cannot catch this because the rubric sits upstream of both readers; auditing the rubric
  takes a different instrument (calibration against labeled outcomes: is a CONFIRMED lead
  actually a good lead), not a second reader. Both this and the independence limit above
  were sharpened by ANP2 Network in the comments.
- ADK's A2A support is marked experimental by Google (2.3.0); pin versions.

MIT license.
