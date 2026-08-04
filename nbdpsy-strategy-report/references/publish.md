# HTML 转换、发布与验证

## 自包含 HTML 的硬性要求

报告在管理后台 /strategy 页以 iframe（sandbox="allow-scripts"，srcdoc）渲染，宿主页会在正文后
注入划线批注脚本（W3C TextQuote 锚点）。因此：

- 单文件自包含：`<title>` + `<style>` + 正文 +（可选）结尾一个轻交互 `<script>`（TOC 高亮/平滑滚动）。
  **无任何外部资源引用**（无 CDN/字体/图片外链），图表全部内联 SVG。
- **正文保持普通文本节点**——批注锚点依赖选中文字，不要把正文塞进 canvas/图片/伪元素。
- 明暗双主题：`prefers-color-scheme` + `:root[data-theme=...]` 双轨（后台有主题切换）。
- 移动端：表格一律包 `overflow-x:auto` 容器，页面本体不得横向滚动。
- 体量 80~140KB，上限 2M 字符（服务端校验按字符数）。

## 设计体系基准

沿用库内已有战略报告的 CSS 作底（CSS 变量、衬线标题、卡片/表格/callout/SVG 图表组件、双主题）。
取基准：`SELECT content_html FROM strategy_reports WHERE id = <已有战略报告id>` 导出到本地做参照。
把「基准 HTML + 正文定稿」交给执行代理转换，明确要求：数字零改动、内容全覆盖、
【图 N｜so what】标注必须转成真实图表+图题+强调样式的 so-what 行，不得原样残留。

## 转换后自检（你自己做，不信任转换代理的自查）

1. grep 抽查 15+ 个关键数字全部在；
2. 无 markdown 残留（`**`、`|---`、`##`、`【图`）；
3. `grep -o '(src|href)="https?://'` 零命中（无外链资源）；
4. `<h2>` 清单 = 全部章节；`<svg>` 数量 = 图表数。

## 本地目视（发布前必做）

Playwright 打不开 file:// 时起临时 HTTP 服务：
`python3 -m http.server <端口> --bind 127.0.0.1`（在 HTML 所在目录）。
桌面 1440 宽 + 移动 390 宽各截图检查：SCQA 版块、核心图表、行动表；
`document.body.scrollWidth > clientWidth` 必须为 false（无横向溢出）。
注意杀进程时别用会匹配到自己命令行的 pkill 模式（用 `lsof -t -i :端口` 取 PID）。

## 发布 API

`POST /api/admin/strategy-reports`（生产上从 ssh 内打 localhost:8083，绕开外网 TLS/代理问题）：

```json
{
  "slug": "strategy-YYYYMM",     // 战略报告必须显式给 slug；命名沿用 strategy-202607 惯例
  "title": "NBDpsy YYYY年M月战略报告",
  "version_label": "v1",          // 改版递增 v1.1 / v2
  "content_html": "<完整HTML>",
  "report_type": "strategy"      // 必填显式："strategy"（仅admin可见）或 "operation"（运营可见）
}
```

- **同 slug 覆盖发布是安全路径**：服务端是 `ON CONFLICT DO UPDATE`，划线批注保留、id 不变。
  发布后必查 `SELECT id, slug, version_label, length(content_html) FROM strategy_reports WHERE slug=...`
  确认 id 未变、版本正确——slug 打错会静默新建一份。
- 大体积 JSON 走「本地生成 payload.json → scp 到生产 /tmp → 生产上 curl --data @file → 用完删除」，
  避免本地网络截断 POST 正文的历史坑。

## 铸 admin JWT（发布凭据）

后端 Claims 四个非 Optional 字段：`sub`(**i64 数字，字符串会 401**) / `role`(String) / `exp` / `iat`
（缺 iat 同样 401，且错误信息与密钥错完全相同，极易误判）。HS256 手工铸（勿用 PyJWT，其新版强制
sub 为字符串）：

```python
import base64, hashlib, hmac, json, time
def b64(x): return base64.urlsafe_b64encode(x).rstrip(b"=").decode()
now = int(time.time())
h = b64(json.dumps({"alg":"HS256","typ":"JWT"}, separators=(",",":")).encode())
p = b64(json.dumps({"sub":1,"role":"admin","exp":now+3600,"iat":now}, separators=(",",":")).encode())
sig = b64(hmac.new(SECRET.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
token = f"{h}.{p}.{sig}"
```

`SECRET` 从生产 `.env` 取：`ssh nbdpsy "grep -m1 '^JWT_SECRET=' /home/ubuntu/NBDpsy/.env | cut -d= -f2-"`。
sub=1 是管理员账号。token 短时（1h）用完即弃，SECRET 不回显不入库不进 git。

## 生产端最终目视

后台读 `localStorage.getItem('token')` 做鉴权：Playwright 先开 `https://manage.nbdpsy.com/login`
（拿 origin），`localStorage.setItem('token', '<铸的JWT>')`，再进 `/strategy`——确认报告出现在
「战略报告」tab、默认选中最新版、iframe 内标题/卡片/图表渲染正常、批注侧栏在。
截图放 scratchpad 或 `.playwright-mcp/`，用完即删，不落仓库。

## 归档

底稿 markdown（去掉「给转换者」的注记行）写入 NBDpsy 仓库 `docs/战略报告-<年月>-底稿.md`，
commit（`docs(strategy): ...`）+ push；push 后看一眼远程部署日志（docs-only 不触发重建属预期）。
底稿是下一期报告的基线来源——下一期不必再从库里扒 HTML。
