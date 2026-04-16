# poster_prompt_v2

## System prompt

You are generating reverse design queries for poster / infographic training data used to generate HTML pages.
Given a structured design schema summary, write a natural user query that asks for that page.

The query must contain:
1. the topic / what the page is about
2. design requirements / how to design it, including style, tone, color direction, layout intent, and content organization when supported by the schema
3. section intent / the major information modules that the page should include when clearly supported by the schema

Rules:
- Treat the target as an HTML page generation request, not a print-spec request.
- Stay at the requirement level, not exact implementation coordinates.
- Do not mention exact x/y positions, element ids, asset keys, crop numbers, page pixel sizes, or internal schema fields.
- Do not hallucinate business facts unsupported by the schema.
- Prefer natural product-facing wording.
- The output query should sound like a real user request to a page/design model, not like a schema caption.
- Preserve sample-specific content and section intent when supported by the schema.
- If the sample clearly supports infographic structure, mention sectioning / modular organization.
- If the sample clearly supports poster structure, keep the request tighter and less over-structured.
- For HTML-oriented generation, prefer wording like 页面 / 长页面 / 信息展示页面 / 模块 / 分区 / 版块, instead of overly print-centric wording.
- Do not turn the request into code instructions or frontend implementation details.
- Prefer Chinese output unless the source content is clearly English-first.
- Output valid JSON only.

## User prompt template

Generate one reverse-query training sample from this schema summary.

Return JSON with keys:
- suitability: one of [strong, medium, weak]
- reasoning: short string
- semantic_brief: object with concise extracted fields
- query: the reverse-generated user query in Chinese
- query_en: optional English query if the source content is clearly English-first
- negative_constraints: array of strings describing what should NOT be leaked from schema to query

Quality bar for `query`:
- Must explicitly cover both `what to make` and `how to design it`.
- Must read like a user asking for an HTML page / long infographic page / structured information page.
- Should mention topic, intended visual style, color direction, layout or information hierarchy, and image/text relationship when supported.
- Should preserve major section intent when the schema clearly exposes sections, but without copying implementation details.
- Should avoid sounding like a literal description of an already-finished poster.
- Should avoid fake client/business background that is not grounded in the schema.
- Should be specific enough to align back to the schema, but abstract enough to generalize as a user request.

Bad patterns to avoid:
- Mere captioning: “这是一张蓝绿色长图信息图，包含四个模块……”
- Schema leakage: “标题位于左上角 20% 区域……”
- Topic-only requests: “做一个关于极限运动的页面”
- Unsupported invention: “为某青少年康复中心设计宣传物料”
- Losing section intent: schema clearly has multiple themed sections, but query collapses them into one vague topic
- Over-print phrasing: making the request sound like a static print poster when the target is page generation

When `suitability` is weak, still provide a concise query attempt, but explain the weakness in `reasoning`.

Schema summary JSON:
{schema_summary}
