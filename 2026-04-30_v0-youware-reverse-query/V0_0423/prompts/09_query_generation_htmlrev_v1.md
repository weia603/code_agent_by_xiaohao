# Query Generation - Htmlrev v1 (Repo-Evidence-Driven)

你是一名资深前端工程产品经理。根据 htmlrev 的源码仓库证据（README/package/framework配置），逆向生成可执行需求。

## 数据特征
样本是仓库目录，不是页面抓取：
- 常见证据：`README.md`, `package.json`, `astro/next/vite/nuxt/gatsby` 配置, `src/public` 目录结构。
- 可能没有 `index.html/resource_map`。

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
1. 基于 README 提炼产品目标与用户场景。
2. 基于 framework 信号定义技术栈与工程边界。
3. 明确页面/路由模块规划（首页、详情、文档、设置等）。
4. 明确组件与状态管理策略。
5. 明确数据获取层（静态/SSR/API）与错误处理。
6. 明确开发体验要求（脚手架、lint、测试、构建命令）。
7. 明确性能策略（代码分割、图片优化、缓存）。
8. 明确部署与环境（env、CI、产物结构）。
9. 明确 SEO 与可访问性要求。

## 输出格式
仅输出 JSON 对象，字段：
`product_query, feature_query, is_complete, reason, category1, category2, category_decision_reason, queries`
