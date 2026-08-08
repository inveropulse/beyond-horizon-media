---
name: beyond-horizon-carousels
description: Writes ready-to-post TikTok/Instagram photo carousels for Beyond Horizon, the South African personal finance app (Money Rhythm, statement insights, budgets, debt payoff). Produces slide-by-slide copy, caption, hashtags, a sound brief and optional rendered PNG slides, using the money-breakdown carousel format that works in the SA finance niche. Use this whenever the user wants social content, posts, carousels, slides, reels, TikToks, a content calendar, hooks, captions or a posting batch for Beyond Horizon / Horizon Pro / Inveropulse — including vague asks like "we need posts for this week", "give me content ideas", "what should we post about payday", or "make something about debt". Also use it when adapting an existing post, repurposing a blog or feature into social, or planning a week/month of posts.
---

# Beyond Horizon carousels

## What this skill is for

Beyond Horizon grows on short-form photo carousels — a stack of 8–16 image slides that walk through one person's real money situation, number by number. This skill turns a topic into a finished, postable carousel: every slide's copy, the caption, the hashtags, a sound brief, and (optionally) rendered PNGs.

Two things make this format work, and they are worth understanding before writing anything:

**Specificity is the whole product.** "How I spend my R28 000 p/m salary as a teacher" outperforms "5 budgeting tips" by an order of magnitude, because a real number attached to a real person is a thing the viewer can measure themselves against. The viewer isn't reading for advice — they're reading to find out whether they're normal. Every slide should give them another number to compare against. The moment a carousel drifts into generic advice, it dies.

**The app is the payoff, not the pitch.** The content earns attention by being useful and nosy; Beyond Horizon appears at the end as the thing that produced the numbers. A carousel that opens with the app is an ad. A carousel that ends with it is content.

Read `references/brand.md` before writing — it has the product facts, the voice, and the compliance lines you must not cross. Read `references/format-playbook.md` for the slide architecture and the performance evidence behind it.

## Workflow

**1. Establish the brief.** You need a subject (a salary level, a life event, a debt situation, a spending category) and a persona. If the user gave you a vague ask ("posts for this week"), propose 3–5 concrete angles and let them pick rather than guessing. When you are choosing the topic yourself, pull from the content wells in `references/format-playbook.md` — there are more than enough there for months of posting. **If a content well has already been assigned to the day you are writing** (the automated weekly run supplies a per-day `day=well` assignment from measured engagement), that assignment overrides this step: write in the well you were given and use the playbook only to understand what that well means editorially.

**2. Build the numbers before the words.** This is the step that's tempting to skip and shouldn't be. Write out the persona's full monthly budget as a table: income, every line item, what's left. Make it add up. South African readers will do the arithmetic in the comments, and a carousel where the numbers don't reconcile gets torn apart — which is engagement, but the wrong kind. Ground the figures in real SA costs (see the cost reference in `references/format-playbook.md`); rent in Sandton is not rent in Polokwane.

**3. Write the slides.** Follow the architecture in the playbook: hook → persona → line items → the reckoning → Beyond Horizon close. Each line-item slide is a category, an amount, an "Includes:" breakdown, and one line of first-person commentary that carries the personality. That commentary line is where the account's voice lives — it's the difference between a spreadsheet and a story.

**4. Write the caption and hashtags.** Short first-person hook, ideally a question. See the playbook for why questions matter and which hashtag mix to use.

**5. Offer to render.** Ask whether they want PNG slides. If yes, write the spec JSON and run:

```bash
python3 scripts/render_slides.py spec.json --out ./slides
```

This produces numbered 1080×1350 PNGs ready to upload. Run `python3 scripts/render_slides.py --example` to see the spec format.

**6. Deliver as a file.** Write the carousel to a markdown file rather than only into chat — the user posts from it, edits it, and hands it to a designer. One file per carousel, named by topic. If you produced a batch, also write a short index with the posting order.

## Output format

Use this structure for each carousel, because it maps to how the content actually gets posted — the person uploading works down the file in order:

```markdown
# [Working title — the hook in plain words]

**Angle:** [one line: who this persona is and why this post exists]
**Content well:** [which theme from the playbook]
**Target:** [what this post is trying to do — reach, saves, signups]

## The numbers
[table: income, every line item, total, what's left — it must reconcile]

## Slides
### Slide 1 — Hook
> [exact on-slide copy, line breaks as they should appear]
*Design note: [emphasis, what's biggest on the slide]*

### Slide 2 — Persona
...

## Caption
[exact caption text]

## Hashtags
[space-separated, 5 of them]

## Sound
[what kind of sound to use and why — see playbook]

## Posting notes
[best day/time, what to reply to in comments, what to pin]
```

## What separates a good carousel from a flat one

**The hook slide has one job: state the number.** "How I spend my R78 000 p/m salary" works. "Let's talk about budgeting" doesn't. If the hook doesn't contain a rand figure or a concrete situation, rewrite it.

**Every line item needs a human aside.** "Rent R9 000 p/m — currently living alone in a 1 bedroom, I know I could pay less with a roommate but I'd rather have the quiet." The number is the reason they stop; the aside is the reason they keep swiping.

**Include at least one number the persona is not proud of.** The R3 500 on eating out, the impulse buy, the subscription they forgot. Perfect budgets read as fiction and get no comments. The confession is what makes people reply with their own.

**Ask a real question at the end.** Not "what do you think?" — something specific enough to have sides: "Is R3 500 on transport mad or is that just Joburg?" Posts that ask something concrete get roughly double the engagement of ones that don't.

**Don't moralise.** The persona isn't a cautionary tale and you're not their financial adviser. Show the numbers, let the viewer judge. The moment copy starts saying "you should", it stops being content.

## Guardrails that matter

These aren't legal boilerplate — getting them wrong creates real problems for a financial app in South Africa. The full detail is in `references/brand.md`, but the short version:

- **Personas are illustrative, not customers.** Never present an invented person as a real Beyond Horizon user, and never invent a testimonial. If the user supplies genuinely anonymised real data, say so and confirm they have permission.
- **This is not financial advice.** No "you should invest in", no projected returns, no "this will make you rich". Describing what a fictional person spent is fine; telling the audience what to do with their money is regulated territory in SA.
- **Don't promise what the app doesn't do.** Check the feature list in `references/brand.md`. Beyond Horizon reads uploaded statements — it does not connect to bank accounts, and "no bank login required" is a deliberate selling point, not a limitation to hide.
- **Get the pricing right.** Free tier is Horizon. Paid is Horizon Pro at R89/month or R799/year.
- **Don't name competitors** in a knocking way. Comparative content invites a response you don't want and ages badly.

## Working in batches

For a week or month of content, vary three axes deliberately so the feed doesn't read as one post repeated: **income level** (mix below and above R40k — lower incomes are more relatable and tend to travel further), **life stage** (single, couple, family, student, retiree), and — **when you are choosing the topics yourself** — **content well** (don't post three salary breakdowns in a row).

**When a per-day well assignment is supplied, honour it exactly and do not vary the well.** The automated weekly run assigns wells from measured engagement (`python3 scripts/performance.py --plan`), deliberately concentrating four days on the best-performing well and two on a challenger, and `scripts/validate.py` checks each spec's `well` against that vocabulary. Four salary breakdowns in a week is then the correct output, not a mistake. Vary **persona, city, income level and hook** hard instead — same well must never mean same post.

Keep a running list of personas used so figures stay consistent if one recurs. If the user posts daily, batching 15–20 at a time is realistic; when you are picking the topics yourself, propose a posting order that alternates wells.
