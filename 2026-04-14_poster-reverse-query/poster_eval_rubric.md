# poster_eval_rubric

## Goal

Use this rubric to review reverse-generated poster / infographic queries before scaling batch generation.

## Review dimensions

Score each dimension from 1 to 5.

### 1. Topic clarity
- 5: Clearly states what the design is about.
- 3: Topic is partially clear but vague or incomplete.
- 1: Hard to tell what the poster / infographic is actually about.

### 2. Design requirement completeness
Check whether the query covers enough of the following when supported by the schema:
- style
- tone / mood
- color direction
- layout / hierarchy
- content organization
- image/text relationship

Scoring:
- 5: Covers most important design requirements clearly.
- 3: Has some design direction but misses major parts.
- 1: Mostly topic-only, with little design guidance.

### 3. Naturalness
- 5: Feels like a real user request to a design model.
- 3: Understandable but somewhat stiff or templated.
- 1: Reads like schema notes or dataset annotation.

### 4. Non-leakage
Check that the query does not expose:
- exact coordinates
- bbox / crop values
- page pixel sizes
- internal field names
- asset ids / resource keys

Scoring:
- 5: No implementation leakage.
- 3: Minor leakage or borderline over-specificity.
- 1: Strong leakage of schema internals.

### 5. Specificity
- 5: Preserves sample-specific content and structure cues.
- 3: Generic but still usable.
- 1: Overly generic, could fit almost anything.

### 6. Training value
- 5: Strong candidate for schema ↔ query training.
- 3: Usable with caveats.
- 1: Poor alignment value.

## Common failure buckets

Tag each bad case with one or more buckets:
- topic_only
- style_missing
- layout_missing
- too_caption_like
- schema_leakage
- hallucinated_context
- too_generic
- too_long
- unnatural_cn
- over_templated
- weak_alignment

## Review template

```json
{
  "sample_id": "...",
  "scores": {
    "topic_clarity": 0,
    "design_requirement_completeness": 0,
    "naturalness": 0,
    "non_leakage": 0,
    "specificity": 0,
    "training_value": 0
  },
  "failure_buckets": [],
  "notes": ""
}
```

## Prompt iteration guidance

### If many outputs are `topic_only`
Strengthen the prompt to require:
- style
- color direction
- layout / hierarchy
- content organization

### If many outputs are `too_caption_like`
Strengthen the prompt to say:
- write as a user request
- do not describe the design as already finished
- start from intent, not observation

### If many outputs are `schema_leakage`
Add stricter negatives around:
- coordinates
- exact relative positions
- page size
- internal field names

### If many outputs are `hallucinated_context`
Strengthen:
- do not invent brand, client, organization, or campaign context unless supported

### If many outputs are `over_templated`
Strengthen:
- preserve sample-specific content
- vary expression based on sample structure
