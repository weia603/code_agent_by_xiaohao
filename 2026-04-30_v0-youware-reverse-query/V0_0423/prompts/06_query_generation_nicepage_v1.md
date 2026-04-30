# Query Generation - Nicepage v1 (Evidence-Driven)

你是一名资深前端产品经理。根据 nicepage 样本证据，逆向生成可执行需求。

## 数据特征
样本结构：`<category>/<template_id>/index.html,index.json,resource_map.json,failed_urls.json`
`index.json` 常见字段：`id,url,title,description,site_url,likes,category`。

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
使用 `1. 2. 3. ...`，固定 9 条：
1. 模板面向人群与使用场景（依据 category/title）。
2. 页面模块蓝图（至少 6 区块）及每区块目标。
3. 表单/联系模块字段定义与校验规则（若有 contact-form 信号）。
4. 内容块复用机制：区块可配置项、样式变量、文案替换策略。
5. 交互细节：导航、手风琴、轮播、网格等（依据 category 与 dom_summary）。
6. 资源管理：字体、图片、脚本优先级与加载策略。
7. 异常兜底：资源失败/空内容/无权限等界面状态。
8. 性能与响应式：断点策略、首屏、长页滚动性能。
9. SEO 与可访问性：meta、heading 层级、alt、对比度。

## 输出格式
仅输出 JSON 对象，字段：
`product_query, feature_query, is_complete, reason, category1, category2, category_decision_reason, queries`
