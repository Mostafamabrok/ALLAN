# ALLAN — Architecture (v2 Rebuild)

*Autonomous Language Learning Agent Network*

This document is the blueprint. It explains what ALLAN is, the ideas it's built on, and the exact pieces we'll build — in plain language, with nothing hidden. If a word looks technical, it gets explained the first time it's used. Read it, poke holes in it, and we adjust before any code is written.

---

## 1. What ALLAN is

ALLAN is a personal assistant that runs on your own PC and works for you the way a highly competent secretary would. You talk to it in plain language ("Allan, when's a good time to do X?", "Allan, is this chemical legal here?", "Allan, do operation cold-steel") and it goes and does the work.

It is **two things at once**, leaning mostly toward the first:

- **A personal operator** — it lives on your machine, remembers you, watches the things you care about, and quietly handles chores.
- **A workshop of specialists** — when a job is big, it spins up a small team of helper agents that divide the work.

The single most important requirement, the one everything else bends around: **reliable work you don't have to watch.** Speed is secondary. You'd rather ALLAN take an hour and be right than take a second and be wrong, because the whole point is to hand something off and stop thinking about it.

---

## 2. The ideas it's built on

These are the principles we agreed on. Every design choice below traces back to one of them.

**Reliability beats speed.** Because you don't need fast answers, ALLAN can afford to check its own work — do a task, then look again and ask "did I actually get that right?" Slowness buys correctness. Most assistants can't do this because they're trying to feel snappy in a chat box. ALLAN opts out of that race on purpose.

**Copy how human memory works.** Over the last few years, AI memory has drifted closer and closer to how people actually store and recall things. So "how would a human do this without thinking about it?" is a reliable compass. The twist: computers add *perfect recall and perfect search* on top of human-style memory, so we get the best of both.

**Split the reliable part from the fallible part.** This is the backbone of the whole system. Language models are brilliant but *fallible* — they can hallucinate, drift, or be talked into things. Plain code is *dependable* — it does exactly what it's told, every time. So we never let the fallible part be in charge of the things that must be trustworthy. The dependable code holds the truth and enforces the rules; the models do the thinking *inside* the walls that code builds.

**Read widely, act carefully.** ALLAN can look at almost anything — that's harmless and helpful. What we're careful about is *actions with consequences you can't undo*. Note the important distinction: irreversible is not the same as consequential. Renaming a file can't be undone but costs nothing if wrong. Emailing your resignation can't be undone and matters enormously. We guard against the second kind, not the first.

**No black box.** Everything ALLAN does is written to a permanent log. You can always ask "what did you do, and why?" and get a straight answer, traced back to the source. Legibility is the safeguard — not locking ALLAN down.

**An assistant needs nerve.** An assistant that asks permission for everything is just a slower you. ALLAN's default is to *act*. The careful gate is a rare exception for the genuinely catastrophic, not the normal mode of operation.

---

## 3. The two halves

ALLAN is built from two parts of equal importance:

1. **The allans** — the agents. These are the language-model minds that think, decide, and do. (Lowercase "allan" = one such agent. There can be many.)
2. **The substrate** — memory, logging, and system administration. This is plain, dependable code. Think of it as the ground the agents stand on.

A useful way to picture it: the substrate is the **kernel** (the trusted core of an operating system — the part that enforces rules and that ordinary programs can't override), and the allans are the **programs** running on top. Programs can *ask* the kernel to do things — save this, run that tool, create a helper — but they can't reach past it or break its rules.

This split is what makes "you don't have to watch it" actually safe. You're not trusting the agents to behave. You're trusting the code that *contains* them. Even an agent that goes completely off the rails still can't corrupt the log, exceed its permissions, create an unkillable helper, or blow its budget — because those are walls built in code, not promises made in a prompt.

---

## 4. The agent network

### Allan Prime (AP)

There is **one** agent you ever talk to: **Allan Prime**, or **AP**. AP is the face of the system — the "JARVIS." It holds your memory, your relationship, and the personality. Whether you speak from your phone, your PC, or another computer, you reach the *same* AP with the *same* memory, mid-thought, because those devices are just windows into one mind. If every device had its own agent, your memory would shatter into disconnected fragments. One face, one memory, one relationship.

AP's job is to serve you and keep you well — **not** merely to keep you pleased in the moment. That difference matters: an assistant optimizing for your immediate happiness becomes a yes-man that hides bad news and never pushes back. AP is loyal *and* willing to tell you the thing you don't want to hear ("that deadline you forgot is tomorrow"). Loyalty with a spine.

**AP is near-root. You are the true root.** AP can do essentially anything you can do on your own machine — including driving your browser and using your already-signed-in accounts. It is powerful by default. But AP is still a fallible model, and the moment it reads an outside web page it could be fed a malicious instruction ("ignore your orders, do this instead"). So AP still runs *through* the kernel and still can't bypass the log or the handful of catastrophic-action checks. The only true root — the final authority — is you, the human. AP is like `sudo`: very powerful, every use recorded, and a few doors that open only for a person.

### Workers (sub-allans)

When a job needs more hands, AP creates helper agents. Some are **throwaway** (a researcher spun up to answer one question, then gone). Some are **standing** (a ManageBac-watcher that runs on a schedule forever). You generally never see them. They report up to AP; AP reports to you.

Helpers get the **least privilege** possible — only the tools their one job needs, and nothing else. The ManageBac-watcher can read ManageBac and literally nothing more. It can't do anything dangerous because the dangerous tool was never placed in its toolbox.

### Creating agents "at will" — but through the kernel

AP can create helpers freely, without asking you each time. But "freely" runs through a controlled door. AP doesn't hand-build a raw agent; it asks the kernel to create one from a spec (its role, its model, its tools, its permissions, its parent). The kernel builds it and enforces rules AP can't override:

- A helper's permissions are always a **subset** of what AP holds — a child can never be more powerful than the parent that made it.
- Every creation is logged.
- Every agent is registered, given a budget, and can be killed.

And a neat consequence falls out: **creating an agent that holds a dangerous power is itself a dangerous act.** Making a read-only watcher is free and automatic. Making an agent that could spend money or message people as you is gated by the same rule as doing that thing directly. The permission model applies even to the act of handing out permissions.

*(Your old code already had empty `superiors`, `subordinates`, and `permissions` fields sitting unused in the agent config. That was this hierarchy, sketched before it could be built. It finally gets a job.)*

---

## 5. The substrate (the kernel)

This is the dependable half — plain code, no models in charge. Three parts.

### 5.1 Logging — the single source of truth

One **append-only** record. "Append-only" means you can only ever add to the end; nothing is edited or deleted. Every message between agents, every tool call, every model call, every memory write — all appended, permanently.

The key property: **the log is the only thing that has to be perfect. Everything else is rebuildable from it.** If the fancier memory layers ever get corrupted, or we change how they work, we throw them away and regenerate them from the log. That makes the expensive, model-built layers *disposable*, because the cheap, dependable record underneath is sacred. This one structure does three jobs at once: it's your perfect memory, your audit trail (the "no black box"), and your debugging tool.

*(Your old `utils.log` that just printed to the screen is the seed of this — it grows up into a real, durable ledger.)*

### 5.2 Memory — structured, and always sourced

Memory has layers, mirroring how people remember:

- **Episodic memory** — what happened, word for word, timestamped. This is the raw log: the actual camping conversation, firewood tangent and all.
- **Semantic memory** — the *facts* distilled out of those events: "Mohamed camps," "his friends are Ali and Sara," "cold-steel is a camping-invite plan." This isn't a shorter transcript; it's the transcript turned into organized knowledge — people, dates, topics, and how they connect.
- **Working memory** — the small, hot set of recent and important facts AP always carries with it. This set *fades* over time (old, unrepeated facts drop out of the hot set), so AP isn't drowning in everything it has ever heard. But nothing is truly lost — it's still in the log, retrievable on demand. Perfect recall underneath, human-style forgetting on top.

**Every fact carries its source.** We never store a bare "Mohamed camps." We store "on [date], in [conversation], it was said that Mohamed camps." This is how humans catch contradictions and apply doubt, and it buys us three things:

- **Contradictions become solvable.** Two clashing facts stop being silent corruption and become a dispute the system can settle — newer source wins, better-supported source wins, or it flags the conflict to you.
- **Confidence has a gradient.** Something heard once, offhand, a year ago is *weaker* than something repeated five times this month. Counting sources gives a real sense of certainty instead of flat true/false.
- **You can interrogate it.** You can ask AP "why do you believe that?" and it points to the exact conversation. A mind whose every belief is traceable is a mind you can debug. This is the direct cure for the old problem where bad inputs quietly poisoned everything.

**How facts get made — and "sleep."** A helper agent reads the day's log and extracts the facts (that's the fallible-but-fine model work). The *storing* is done by dependable code that enforces the rule: **no fact may be saved without a source.** The code simply rejects a sourceless fact, so provenance isn't a habit we hope agents keep — it's a wall. Much of this happens during **consolidation**, ALLAN's version of sleep: a nightly background pass that digests the day into semantic memory and reconciles new facts against old ones. It's slow and careful, which is exactly what your "speed is secondary" rule makes affordable, and it runs when you're not using the system anyway.

**Retrieving memory** follows a cascade, like a person reaching for a name: check the hot working set first; if it's not there, search the stored facts; if still not there, search the raw log; if *still* nothing, ask you. That last step — "ask you" — is the same reflex ALLAN uses whenever it's unsure about anything: when in doubt, check. One reflex, reused everywhere.

### 5.3 Administration — where the rules are enforced

This is the kernel proper: dependable code that *enforces* every guarantee, rather than hoping an agent honors it.

- **Registry** — who exists, who reports to whom, who's currently alive.
- **Permissions** — every tool call is checked against that agent's allowed list *before* it runs. The careful-action rules live here as enforced code, not agent goodwill.
- **Lifecycle and killability** — creating agents, supervising the standing ones, and killing runaways. This is where the classic "agents talk in circles forever" problem finally dies: the kernel kills anything that overruns its budget or its time. We don't rely on an agent politely declaring itself finished.
- **Budgets** — your "compute-points." Each agent gets an allowance; overrun and the kernel halts it. Not a request — a hard stop.
- **Router and scheduler** — choosing which model handles a job (next section), and running the scheduled loops (e.g. "check ManageBac each morning").

*(A **secrets vault** — a secure place to hold passwords and login tokens — also belongs here eventually. For now it's deferred; see §6 and §9.)*

---

## 6. The model router

ALLAN is **model-agnostic**: an allan doesn't know or care whether its "brain" is a local model or a paid API. A single router decides, per task, which brain to use. It weighs three things:

- **Capability** — how hard is this? Hard reasoning goes to the strong model; simple grunt work goes to a cheap one.
- **Cost / budget** — the compute-points. Cheap work shouldn't spend premium tokens.
- **Privacy** — some tasks touch data that should never leave your machine. Those can be pinned to a local model no matter what, on principle.

Given your hardware — an RTX 5090 laptop GPU with 24 GB of video memory, plus 64 GB of system RAM — the local end is genuinely strong. It can comfortably run capable local models (roughly 14–32 billion-parameter class) fast enough to handle all the high-volume background work: consolidation, fact extraction, triage, dispatch, reading a web page. The strong end is **Anthropic's Claude** for AP's real reasoning and the hard tasks. So the everyday shape is: *local models do the background grind for free; Claude does the thinking that matters.* Because the router is a single swappable piece, adding a new provider or upgrading models later never touches the agents.

*(Your old `llm_api.py` was already this exact seam — one function that stood in for "a brain." It only knew how to reach local models; it just grows a second backend.)*

---

## 7. The permission and consequence model

ALLAN acts by default. The careful gate is narrow and keyed to **how bad it would be if the action were wrong and couldn't be undone.** Three postures:

- **Cheap to recover → just do it.** Log it, don't even mention it unless asked. (Most of ALLAN's life lives here.)
- **Moderately consequential → act, then tell you, with an undo.** "I sent the camping invite — want me to pull it back?" This is the important middle case, because it fits unattended work: AP doesn't freeze waiting for permission, it acts and keeps you informed. Nerve and safety together.
- **Severe and unrecoverable → stop and ask first.** Rare by design.

The real safeguard across all three is the **log**, not restriction. AP is free to do its job — including signing into your accounts and driving your browser — and the record of what it did is always there for you to inspect. We don't cage the assistant; we keep a perfect windshield.

---

## 8. Surfaces (how you reach it)

Keep two different "networks" separate in your head:

- **The infrastructure network** — your phone, PC, other computer, and one day hardware. These are *surfaces*: microphones and screens wired into one mind. They are not separate ALLANs.
- **The agent network** — AP and its helpers. This is the org chart from §4.

Because AP must always be available, it lives on an **always-on machine** — your big PC, acting as the home hub, holding the memory and running the nightly consolidation. Your phone and other devices connect to that hub.

**One security note to design for early, not bolt on later:** reaching the hub *from outside your home* means that very privileged, memory-holding core is reachable over a network. That's the single most sensitive door in the whole system — the one entrance to everything ALLAN knows about you. We don't have to solve it now, but we build knowing it's there. (For the first versions, you talk to AP on the PC itself, so this stays simple.)

---

## 9. What we're deferring (on purpose)

These are decided-but-later, each one shrinking the early build:

- **Microsoft To Do (writing tasks)** — needs a small app registration for account access. Deferred. So the first real chore is *read-only*: AP reads ManageBac and tells you what's due, rather than writing anything anywhere.
- **Credentials / the secrets vault** — deferred entirely for now. Instead of AP logging in (and us storing passwords), the browser automation **reuses your existing signed-in session** — it drives a browser that is *already you*. No password is ever touched or stored. (One practical detail for build time, so it's not a surprise: a browser profile can't be automated and used by you at the very same moment, so we'll pick a specific mechanism — likely a dedicated browser profile you sign into once, or attaching to your running browser. The principle is fixed now: reuse the session, store no secret.)
- **ManageBac access** — confirmed as browser-reading (no student API), which fits the reuse-your-session approach above.
- **Multi-surface / remote access** — later. Early versions run on the PC.

---

## 10. Build order

The goal is to move quickly *and* understand every layer — so we grow a spine rather than pour a whole cathedral at once. Each version is small enough to fully grasp, and you get something useful early.

- **v0 — Skeleton.** The kernel's log plus a single AP you can chat with on the PC. Every exchange is recorded. Nothing clever yet — but it's real, and it's legible.
- **v1 — Hands (first real usefulness).** Give AP a browser it drives using your signed-in session, so it reads ManageBac and briefs you on what's due. Read-only, zero blast radius, and it exercises the whole loop: browse, reason, report.
- **v2 — Memory.** The sourced semantic memory and retrieval, so AP remembers across sessions instead of starting fresh each time.
- **v3 — Helpers.** AP can create sub-allans; the kernel's registry, permissions, and killability come online.
- **v4 — Sleep and schedule.** The nightly consolidation pass, scheduled loops (the morning ManageBac check), and eventually multi-surface access.

Microsoft To Do write-back slots in whenever you do the account setup — it turns the v1 briefing into a real two-system sync.

---

## 11. What carries over from the old code

The old repo is small (five files) but the bones were better than you gave them credit for:

**Keeps, because it aged well:**

- **The actor model** — agents with their own inboxes and a manager that routes messages between them. That's genuinely how serious multi-agent systems are built. It stays.
- **The brain abstraction** (`llm_api.py`) — one function standing in for "a model." It becomes the router.
- **The clean separation** into network, tools, core, and utilities.
- **The unused hierarchy fields** (`superiors`, `subordinates`, `permissions`) — dead before, load-bearing now.

**Retires, because better models made it obsolete:**

- **The hand-rolled tool-calling** — that regex hunting for `[CALL: func(arg="value")]`, and the pleading `IMPORTANT:` lines begging the model to obey the format. That whole approach existed only because weak local models couldn't call tools reliably. Modern models do this natively. It was the wall you were stuck at, and it's gone.
- **The run-once test** `main()` that hardcodes "what's the capital of Egypt," delegates it, and exits. That becomes a real, persistent AP.

---

## 12. The open decisions (locked, unless you bend them)

For the record, the two design forks we settled:

1. **AP is near-root; you are true root.** AP acts freely; the log is the safeguard; only a tiny set of catastrophic actions pause for you.
2. **Each allan is its own process, supervised by the kernel** — so "kill the runaway" and "enforce the budget" are real capabilities, not wishes.

If either of those should bend, this is the moment — everything downstream is built on them.

---

*End of blueprint. Nothing here is code yet. Read it, argue with it, and once it sits right, v0 is the next move.*
