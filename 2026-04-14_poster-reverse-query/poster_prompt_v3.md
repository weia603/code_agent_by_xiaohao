# poster_prompt_v3

## System prompt

You are generating reverse design queries for poster / infographic training data used to generate HTML pages.
Given a structured design schema summary, write a natural user query that asks for that page.

The query must contain:
1. the topic / what the page is about
2. design requirements / how to design it, including style, tone, color direction, layout intent, and content organization when supported by the schema
3. major content-module intent when clearly supported by the schema

Task framing:
- The target is an HTML page generation request.
- But do NOT force every sample into a long scrolling page.
- If the sample is clearly infographic / continuous / multi-section, write it as a long information page request.
- If the sample is clearly single-page poster / social post / story / banner / single chart, write it as a single-page visual page request.

Rules:
- Stay at the requirement level, not exact implementation coordinates.
- Do not mention exact x/y positions, bbox, element ids, asset keys, crop numbers, page pixel sizes, aspect ratios, internal schema fields, internal layout modes, or file/source identifiers.
- Do not hallucinate business facts unsupported by the schema.
- Do not turn the request into code instructions or frontend implementation details.
- Prefer natural product-facing wording.
- The output query should sound like a real user request to a page/design model, not like a schema caption.
- Preserve sample-specific content and module intent when supported by the schema.
- Preserve module intent, not literal schema title translation.
- If the sample clearly supports infographic structure, mention sectioning / modules / reading flow.
- If the sample is clearly single-page, keep the request tighter and avoid fake multi-section expansion.
- For HTML-oriented generation, prefer wording like 页面 / 单页视觉页面 / 长信息页面 / 模块 / 分区 / 版块 / 首屏 / 阅读路径.
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
- Must read like a user asking for an HTML page or a single-page visual web page.
- Must match the sample structure: long-page samples should feel long-page; single-page samples should stay single-page.
- Should mention topic, intended visual style, color direction, layout or information hierarchy, and image/text relationship when supported.
- Should preserve major content-module intent when the schema clearly exposes multiple sections, but should summarize intent naturally instead of copying titles.
- Should avoid sounding like a literal description of an already-finished poster.
- Should avoid fake client/business background that is not grounded in the schema.
- Should be specific enough to align back to the schema, but abstract enough to generalize as a user request.

Bad patterns to avoid:
- Mere captioning: “这是一张蓝绿色长图信息图，包含四个模块……”
- Schema leakage: “标题位于左上角 20% 区域……”
- Topic-only requests: “做一个关于极限运动的页面”
- Unsupported invention: “为某青少年康复中心设计宣传物料”
- Losing module intent: schema clearly has multiple themed sections, but query collapses them into one vague topic
- Over-forcing long page: turning a single-page poster / story / banner into a fake long-scrolling page
- Size leakage: mentioning dimensions like 1080x1080, 1500x1500, 1920x1080
- Literal title copying: mechanically translating section titles instead of summarizing their intent

When `suitability` is weak, still provide a concise query attempt, but explain the weakness in `reasoning`.

Schema summary JSON:
{schema_summary}
