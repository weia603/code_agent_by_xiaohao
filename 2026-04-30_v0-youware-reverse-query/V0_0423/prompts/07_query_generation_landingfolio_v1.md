# Query Generation - Landingfolio v1 (Evidence-Driven)

你是一名资深增长落地页产品经理。根据 landingfolio 样本证据，逆向生成可执行需求。

## 数据特征
样本结构：`<slug>/index.html,index.json,resource_map.json,failed_urls.json`
`index.json` 常见字段：`title,url,slug,site_url,categories,analytics,screenshots`。

## 分类输出规则
必须输出：`category1`、`category2`、`category_decision_reason`。

允许集合：
- category1: ["工程级应用", "内容站点", "互动娱乐"]
- category2: ["AI前端应用", "中后台管理", "电商", "社区", "内容平台", "富文本编辑器应用", "图像编辑应用", "视频剪辑工具", "即时通讯", "低代码/流程引擎应用", "跨端应用", "桌面应用", "物联网和嵌入式", "博客/新闻", "营销/着陆页", "作品集/官网", "文档/维基", "单页工具", "小游戏", "互动媒体/艺术", "可视化", "SVG"]

一级二级映射（必须严格遵守）：
- 工程级应用 -> [AI前端应用, 中后台管理, 电商, 社区, 内容平台, 富文本编辑器应用, 图像编辑应用, 视频剪辑工具, 即时通讯, 低代码/流程引擎应用, 跨端应用, 桌面应用, 物联网和嵌入式]
- 内容站点 -> [博客/新闻, 营销/着陆页, 作品集/官网, 文档/维基]
- 互动娱乐 -> [单页工具, 小游戏, 互动媒体/艺术, 可视化, SVG]

## feature_query 要求（必须详细）
使用 `1. 2. 3. ...`，固定 10 条：
1. 目标受众与营销诉求（痛点-价值-行动）。
2. 首屏结构：标题、副标题、主 CTA、信任背书。
3. 功能/价值模块结构与字段（benefit、evidence、icon）。
4. 社会证明模块（客户logo、评价、案例指标）字段。
5. CTA 漏斗：多触点 CTA、表单字段、转化事件定义。
6. A/B 可测试点：文案、按钮、布局、价格卡位。
7. 资源与媒体策略：图片视频压缩、LCP 资源优先级。
8. 容错策略：failed_urls 触发的占位、兜底文案、监控。
9. SEO 与埋点：OG、schema、关键事件埋点。
10. 响应式与可访问性：移动优先、可读性、键盘操作。

## 输出格式
仅输出 JSON 对象，字段：
`product_query, feature_query, is_complete, reason, category1, category2, category_decision_reason, queries`
