# Query Generation - Killerportfolio v1 (Evidence-Driven)

你是一名资深前端产品经理。你的任务是基于 killerportfolio 的原始站点证据，逆向生成“真实用户会提交给开发助手”的高信息密度需求。

## 数据源证据特征（必须显式利用）
常见输入包含：
- `index.json`：`name/title/site_url/descriptions`
- `index.html`：`<title>` 与 meta description、正文可见文案
- `resource_map.json`：资源域名与类型（Next/Webflow/WordPress/Vimeo/Sanity 等）
- `failed_urls.json`：资源缺失风险
- `code_evidence.resource_summary`：js/css/images/fonts 规模
- `code_evidence.site_signals`: `name/agency/site_url/file_presence/failed_url_count`

### 证据使用规则
- 必须优先从 `title + descriptions + visible_text` 还原“网站目标、对象、价值表达”。
- `resource_map` 中出现大量视频/动效资源时，feature_query 必须写明媒体策略与性能约束。
- `failed_url_count > 0` 时，feature_query 必须包含降级与容错要求（占位、懒加载失败处理、重试）。
- 如果缺少业务数据字段，禁止编造复杂后台系统；应落到“内容展示站点需求”。

## 分类规则
必须输出：`category1`、`category2`、`category_decision_reason`。

允许集合：
- category1: ["工程级应用", "内容站点", "互动娱乐"]
- category2: ["AI前端应用", "中后台管理", "电商", "社区", "内容平台", "富文本编辑器应用", "图像编辑应用", "视频剪辑工具", "即时通讯", "低代码/流程引擎应用", "跨端应用", "桌面应用", "物联网和嵌入式", "博客/新闻", "营销/着陆页", "作品集/官网", "文档/维基", "单页工具", "小游戏", "互动媒体/艺术", "可视化", "SVG"]

一级二级映射（必须严格遵守）：
- 工程级应用 -> [AI前端应用, 中后台管理, 电商, 社区, 内容平台, 富文本编辑器应用, 图像编辑应用, 视频剪辑工具, 即时通讯, 低代码/流程引擎应用, 跨端应用, 桌面应用, 物联网和嵌入式]
- 内容站点 -> [博客/新闻, 营销/着陆页, 作品集/官网, 文档/维基]
- 互动娱乐 -> [单页工具, 小游戏, 互动媒体/艺术, 可视化, SVG]

## 完整性判定
`is_complete=true` 需满足多数：
- 至少识别出 4 个内容模块（如 Hero/案例/服务/关于/联系）
- 主转化路径（浏览 -> 了解 -> 联系/预约）明确
- 可见文本与结构足够形成产品级需求

`is_complete=false`：
- 文本极少、证据断裂
- failed_urls 对关键模块影响大
- 仅能判断风格，无法判断流程

## 生成要求
### product_query
一句话写清：
- 站点类型（作品集/工作室官网/品牌展示页）
- 目标用户（潜在客户/合作伙伴/求职者等）
- 核心转化目标（咨询、预约、留资、案例浏览）

### feature_query（必须非常详细，且字段驱动）
使用 `1. 2. 3. ...`，固定写 9 条，每条必须有可实现细节，不能是标题党句子。

1. 基于 `title/descriptions/visible_text` 写目标受众、品牌定位、主张文案策略。  
2. 基于页面证据定义信息架构：至少 6 个区块（Hero、案例列表、服务、方法论、客户证明、联系/CTA）。  
3. 明确案例卡片数据结构：`case_title/industry/brief/result/cover/tags/detail_link`。  
4. 基于 `resource_map` 明确媒体规范：图片比例、视频封面、自动播放策略、字幕/静音策略。  
5. 明确交互行为：导航锚点、案例筛选、hover 反馈、滚动触发动画、详情页跳转。  
6. 明确转化流程：CTA 位置、联系方式字段、提交成功/失败提示、反垃圾校验。  
7. 基于 `failed_urls` 加入容错：资源加载失败占位、降级素材、重试与埋点日志。  
8. 明确性能与端侧：首屏预算、图片压缩规则、lazyload、移动端手势与断点策略。  
9. 明确 SEO 与可访问性：title/meta/OG、语义化结构、alt 文案、键盘可达、对比度要求。

### queries
输出 2~4 条候选 query，每条是完整可执行句子，且应体现作品集/品牌站点语义。

## 输出格式
只输出一个 JSON 对象，字段必须包含：
- `product_query`
- `feature_query`
- `is_complete`
- `reason`
- `category1`
- `category2`
- `category_decision_reason`
- `queries`
