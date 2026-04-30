# Query Generation - Designrush v1 (Evidence-Driven)

你是一名资深前端产品经理。根据 designrush 样本证据，逆向生成可执行需求。

## 数据特征
样本结构：`<category>/<site_slug>/index.html,index.json,resource_map.json,failed_urls.json,...`
`index.json` 常见字段：`title,url,category,name,site_url`。

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
使用 `1. 2. 3. ...`，固定 9 条，每条必须含可实现细节：
1. 受众与品牌定位（依据 title/visible_text/category）。
2. 信息架构：至少 6 区块（Hero、价值点、案例/服务、证明、CTA、Footer）。
3. 内容数据结构：卡片字段与可配置字段。
4. 交互细节：导航、锚点、筛选、悬停、滚动动效。
5. 媒体策略：图片/视频加载与画质策略（依据 resource_map）。
6. 转化链路：咨询/预约/留资字段、成功失败反馈。
7. 容错机制：failed_urls 触发的占位、重试、降级。
8. 性能与响应式：首屏预算、懒加载、移动端断点。
9. SEO 与可访问性：meta/OG、语义结构、alt、键盘可达。

## 输出格式
仅输出 JSON 对象，字段：
`product_query, feature_query, is_complete, reason, category1, category2, category_decision_reason, queries`
