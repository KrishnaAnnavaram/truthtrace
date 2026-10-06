# ASD-STE100 Simplified Technical English: the truthtrace writing standard

Use these rules for the truthtrace `README.md` and for this file. Section 3 gives the
**project vocabulary**: the technical names and the technical verbs of truthtrace. Each term has
only one meaning. Do not use the synonyms in the "Do not use" column.

## 1. The writing rules

### Words

1. Use one word for one meaning, and one meaning for one word. Do not use synonyms for variety.
2. Use a word only as one part of speech. For example, "test" is a noun or a verb, "check" is a verb.
3. Do not use phrasal verbs (`set up`, `carry out`, `find out`, `pick up`, `look up`, `come up with`).
   Use one verb: "prepare", "do", "find", "get", "make".
4. Do not use an "-ing" form as a noun or an adjective ("the running job", "after indexing").
   Exception: a technical name, a file name, a command or a status value.
5. Do not use contractions (`don't`, `it's`, `can't`). Do not use slang or idioms
   (`out of the box`, `under the hood`, `at a glance`, `gotcha`, `bells and whistles`).
6. Do not use `and/or`. Write "A, B or both".
7. Do not use `should`, `could`, `would` or `may` for instructions. Use "must" for a rule, the
   imperative for a step and "can" for a possibility.
8. Keep the articles "a", "an" and "the" in sentences.
9. Do not make a noun cluster of more than three words. A technical name is one word.

### Sentences

1. A procedural sentence (an instruction) has a maximum of **20 words**.
2. A descriptive sentence has a maximum of **25 words**.
3. Write one instruction in one sentence.
4. Use the imperative for an instruction: "Run the tests." Not `The tests should be run.`
5. Use the active voice. Use the passive voice only when the agent of the action is not important.
6. Use only the simple present, the simple past and the simple future.
7. Put a condition before the instruction: "If the index is stale, build it again."
8. Do not use semicolons in sentences. Write two sentences.

### Paragraphs, notes and warnings

1. A paragraph has one topic and a maximum of **6 sentences**. Start with the topic sentence.
2. A warning or a caution starts with a clear command. Then it gives the reason.
3. A note gives information. It does not give an instruction.
4. Use a vertical list for a sequence or a set of conditions. Each item of a numbered procedure is one step.

### Tables, headings and diagrams

1. A table cell can be a short phrase. If a cell has a sentence, the sentence obeys the rules.
2. A heading is a noun phrase ("The cost model") or an imperative ("Run the demo").
   Do not start a heading with an "-ing" form.
3. A diagram label is a short phrase. Use the same terms as the text.

### What STE does not change

Code, commands, file names, paths, field names, environment variables, status values, enum values,
product names and URLs stay exactly as they are. They are technical names. Put them in backticks.

## 2. General words to replace

| Do not use | Use |
|---|---|
| utilize, leverage | use |
| in order to | to |
| set up | prepare, install, configure |
| carry out, perform | do |
| make sure, ensure | make sure (allowed), or "check that" |
| a lot of, lots of | many, much |
| e.g., i.e. | for example, that is |
| should (instruction) | must (rule) / imperative (step) |
| might, may (possibility) | can |
| very, really, just, simply, easily | (delete) |
| seamless, robust, powerful, blazing | (delete or give a measured fact) |

## 3. Project vocabulary

### 3.1 Technical names (nouns)

| Term | Meaning | Do not use |
|---|---|---|
| **claim** | A statement that a user wants to check, or the statement that a fact-check checked | assertion, statement (for the user input) |
| **question** | A user message that asks for information and does not state a claim | query (for the message type) |
| **query** | The text that truthtrace searches with, after it removes a claim wrapper such as "Is it true that" | search string, prompt |
| **fact-check** | One article from a fact-checker about one topic or one claim (`Article`) | debunk, report, story |
| **fact-checker** | The organization that wrote a fact-check: PolitiFact or FactCheck.org | publisher (for the organization), checker |
| **source** | The name that truthtrace stores for the origin of a fact-check: `politifact`, `factcheck.org`, `import` or `demo` | site, provider (for papers) |
| **source adapter** | The module that reads the feeds and the pages of one fact-checker (`sources/politifact.py`, `sources/factcheck_org.py`) | scraper, crawler |
| **feed** | The RSS 2.0 or Atom file that lists new fact-checks | channel, stream |
| **rating** | The verdict text that the fact-checker wrote, for example `pants-fire` | score, grade |
| **label** | One value of the fixed verdict scale (`Label`), for example `mostly_false` | rating (for the scale), class |
| **verdict scale** | The six truth labels plus `unverifiable` | truth meter, score |
| **coarse group** | The three-way group of a label: `supported`, `mixed`, `refuted` (plus `unverifiable`) | polarity, category |
| **verdict** | The label that truthtrace gives a claim, with its method and citations | answer (for a claim), result |
| **method** | How truthtrace got the result: `matched_fact_check`, `llm_judgement`, `llm_answer`, `evidence_only` or `abstained` | mode (for the method), path |
| **abstention** | A result with the label `unverifiable` and the method `abstained`. truthtrace shows `Can't verify` | refusal, unknown |
| **evidence** | The retrieved fact-checks for one query, each with the best passage and scores (`Evidence`, `E1`, `E2`…) | sources (for evidence), context |
| **citation** | An evidence ID that the verdict or the answer uses | reference, footnote |
| **passage** | The text of the best chunk of one fact-check for one query | snippet, excerpt |
| **chunk** | One indexed text unit: one claim card or one body window (`ChunkRow`) | segment, block |
| **claim card** | The first chunk of a fact-check: title, claim, speaker, rating and summary | header chunk |
| **body window** | One part of the article body of 180 words with 40 words of overlap, after the title | slice, page |
| **index** | The chunks and their vectors in the database, and the in-memory BM25 and vector data | search engine |
| **index version** | A counter in the `meta` table. Each change of articles, chunks or vectors increases it | revision, generation |
| **embedder** | The model that changes a text into a vector (`hashing` or `sentence-transformers:<model>`) | encoder (alone), vectorizer |
| **reranker** | The model that gives a query and a text a relevance from 0 to 1 (`lexical` or `cross-encoder:<model>`) | scorer, ranker |
| **relevance** | The reranker score of the best of passage and claim, from 0 to 1 | confidence, probability |
| **similarity** | The reranker score between the user claim and the claim of one fact-check | match score |
| **match** | A fact-check whose claim has a similarity of at least the match threshold, with no negation or number problem | hit (for a match), duplicate |
| **conflict** | Two close matches whose labels are in the `supported` and `refuted` groups | disagreement (as a term) |
| **LLM** | The optional language model (Gemini or OpenAI) that judges a claim or answers a question with citations | model (alone), AI |
| **provider** | The LLM family in `TRUTHTRACE_LLM_PROVIDER`: `none`, `fake`, `gemini` or `openai` | backend, vendor |
| **store** | The SQLite database file with the tables `articles`, `chunks` and `meta` (`Store`) | DB (in prose), repository |
| **polite fetcher** | The HTTP client that obeys robots.txt, waits between requests and retries (`PoliteFetcher`) | crawler, downloader |
| **ingestion run** | One pass over all feeds of the selected sources | crawl, scrape |
| **time split** | An evaluation that tests on claims from on or after a cutoff date and searches only older fact-checks | holdout (alone) |
| **coverage** | The fraction of test claims that got a verdict (`matched_fact_check` or `llm_judgement`) | recall (for coverage), answer rate |

### 3.2 Technical verbs

| Verb | Meaning |
|---|---|
| **ingest** | Read the feeds, fetch the new fact-check pages, parse them and store them |
| **import** | Read fact-checks from a `.jsonl` or `.csv` file and store them |
| **fetch** | Get one URL with the polite fetcher |
| **parse** | Change a page, a feed or a file row into an `Article` or a `FeedItem` |
| **upsert** | Insert a fact-check by URL, or update it if its content hash changed |
| **sync** | Make the chunks of a fact-check equal to its current text, then embed the chunks without a current vector |
| **embed** | Change a chunk text or a query into a vector with the embedder |
| **retrieve** | Find the best chunks for a query with BM25 and vectors, and fuse the two rankings |
| **rerank** | Give each candidate a relevance with the reranker |
| **compare** | Calculate the similarity between the user claim and the claim of a rated fact-check |
| **judge** | Ask the LLM for a label, a rationale and citations for a claim |
| **validate** | Check that the LLM output has a label on the scale, a rationale and known citations |
| **abstain** | Give the label `unverifiable` and show the related fact-checks |
| **evaluate** | Run the verifier on labelled test claims and calculate the metrics |
