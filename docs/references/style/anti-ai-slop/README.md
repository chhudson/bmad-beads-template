<!-- Sources: https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing and https://gist.github.com/ossa-ma/f3baa9d25154c33095e22272c631f5a1 — copied 2026-09-01 -->

# Anti AI-slop — detecting and removing AI-sounding prose

Two vendored catalogues of the tells that mark text as LLM-generated, plus a short house
checklist (our synthesis, at the end) that a reviewer can run against a page of copy, a product
brief, a PRD or a README. The failure mode these references guard against is prose that reads as
generated even when a person wrote it.

## Files

| File | What | Upstream | Copied | Licence |
|---|---|---|---|---|
| `wikipedia-signs-of-ai-writing.md` (256 KB) | "Wikipedia:Signs of AI writing", the WikiProject AI Cleanup advice page. Descriptive catalogue of content, language, style, formatting and citation tells, each with real examples, plus caveats on detection tools, "signs of human writing", ineffective indicators and historical (model-era) indicators. 40 references, mostly peer-reviewed corpus studies. | https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing — permanent revision `oldid=1370403579` | 2026-09-01, Tavily extract (advanced depth) of the rendered page | CC BY-SA 4.0 (Wikipedia text licence, https://en.wikipedia.org/wiki/Wikipedia:Copyrights). Attribution: Wikipedia contributors; derivatives must carry the same licence. |
| `tropes-md-ossama-chaib.md` (18 KB) | `tropes.md`, "AI Writing Tropes to Avoid" — 33 named tropes across word choice, sentence structure, paragraph structure, tone, formatting and composition, each with three or so verbatim examples. Written to be dropped into an LLM system prompt. | https://gist.github.com/ossa-ma/f3baa9d25154c33095e22272c631f5a1 (raw file fetched); catalogue site https://tropes.fyi, author Ossama Chaib, https://ossama.is | 2026-09-01, `curl` of the raw gist, byte-for-byte | No formal licence. Author invites copying ("Copy it or download it", ossama.is/writing/tropes) and in the gist comments (2026-03-12) grants redistribution with attribution to tropes.fyi and himself. Treat as attribution-required; do not strip the source line. |

What was removed from the Wikipedia copy: site navigation, the table of contents, the 94
per-section `[edit]` links and the trailing "Wikipedia artificial intelligence" navbox. Body text,
tables, quoted examples, notes, references and external links are untouched. Image and some
intra-wiki links remain relative (`/wiki/...`, `//upload.wikimedia.org/...`) as Tavily returned
them; prefix `https://en.wikipedia.org` if you need to follow one.

Why two sources: Wikipedia is the evidence-based catalogue (dated, cited, notes which tells have
faded as models changed, and lists false positives under "Ineffective indicators"). `tropes.md` is
shorter, blunter, and better on the rhythm and structure tells that outlive any vocabulary list:
negative parallelism, tricolon abuse, fractal summaries, one-point dilution, false ranges,
"here's the kicker". Wikipedia's own External links section points to tropes.fyi.

## Considered and not vendored

- Charlie Guo, "The Field Guide to AI Slop", https://www.ignorance.ai/p/the-field-guide-to-ai-slop
  (2025-10-22). Good, and distinct in two ways: it names "yellow flags" that are *not* reliable
  tells (academic vocabulary, absence of typos, absence of contractions), and its positive advice
  is to cultivate specificity — write from particular knowledge and tangible experience. Not copied
  because it is © Charlie Guo, all rights reserved, with no reuse licence. Read it online.
- explainx.ai, worldcomgroup.com, makeuseof.com, LinkedIn/Facebook/Reddit posts: derivative
  summaries of the Wikipedia page, or listicles. Nothing they add is not in the two sources above.
- Anything selling a detector or a "humanizer". Wikipedia's Caveats section and Guo both note that
  automated detectors have false-positive rates that make them unusable on real copy.

## House checklist — our synthesis, not a quotation

Run this against a page before it ships. One hit is not a verdict; a cluster is. The sources agree
on that framing, and so do we.

1. Vocabulary. Delete or replace: delve, tapestry, landscape (abstract), realm, testament, pivotal,
   crucial, robust, vibrant, intricate, meticulous, seamless, leverage, harness, unlock, foster,
   underscore, showcase, boast, "deep dive", "navigate" (as metaphor), "ever-evolving".
2. "It's not X, it's Y" / "not just X but Y" / "not because X but because Y". Zero per page. Say Y.
3. Rule of three. If every list, triad of adjectives and set of examples lands on three, break it.
   Use two, four, or the one thing that matters.
4. Em dashes. Two or three per page is a lot. Prefer a full stop, a comma or a colon.
5. Openers and transitions that signal nothing: "In today's fast-paced world", "It's worth noting",
   "Importantly", "Here's the thing/kicker", "Let's break this down", "Imagine a world where".
6. Signposted conclusions ("In conclusion", "To sum up") and paragraphs that restate what the
   section already said. Cut them; the reader felt the ending.
7. Present-participle tails that fake analysis: "highlighting its importance", "reflecting broader
   trends", "underscoring the need for". Delete the clause or make it a full sentence with a claim.
8. Copula avoidance: "serves as", "stands as", "represents", "marks a". Use "is".
9. Stakes inflation and puffery: "transformative", "game-changing", "revolutionize", "seismic",
   "unprecedented". State what happened and let the reader judge the size.
10. Vague attribution: "experts say", "studies show", "industry reports", "widely regarded". Name
    the source and date, or drop the claim.
11. Hedge stacking and "despite these challenges" arcs: acknowledge-then-dismiss is a template.
    Either the problem matters (say so plainly) or it does not (leave it out).
12. Sycophantic or performative openers: "Great question", "You're absolutely right", fake
    vulnerability ("I'll be honest"). None in published copy.
13. Formatting tells: bold-first bullets, emoji as bullets, Title Case headings, headings that
    contain only more headings, horizontal rules between every section, curly quotes in code.
    Bullet-point bloat: if the bullets could be two sentences, write two sentences.
14. Metronome rhythm. Read it aloud. If every sentence is 12 to 18 words and every paragraph is
    three sentences, vary it. A fragment. Then a long sentence that earns its length.
15. False ranges ("from startups to enterprises", "from strategy to execution") with no meaningful
    middle. Name the actual things or drop the range.
16. Generic metaphor and analogy ("think of it as a Swiss army knife"). Cut unless it is specific
    to this reader's experience.
17. Invented concept labels ("the supervision paradox", "workload creep") used as if established.
    Make the argument instead of naming it.
18. The specificity test, the one positive check. Every paragraph should contain something only
    someone who did the work could write: a number with a source, a named process, a date, a
    concrete failure. If a paragraph would fit any company's site, it does not belong on ours.

## House banned words — fill in per project

List here the words and constructions your project bans outright, with the document they come
from (a message register, a brand voice guide). Keep it short enough to check by hand. Example
shape:

- Banned in all copy: *unlock, transformative, supercharge, seamless, game-changing, revolutionize,
  "reach out"*; unattributed statistics.
- Every number carries a source and a date.
