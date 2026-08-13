# NBDpsy 品牌矢量 Logo（skill 内置资产）

本目录 6 个 SVG 为品牌 logo 矢量真源副本（贝塞尔路径，任意分辨率无损），视频片头/收尾、图片合成、水印一律从这里取，**禁止再用 JPEG 位图 logo 抠图**。

| 文件 | 内容 | 何时用 |
|---|---|---|
| nbdpsy-logo-full.svg | 竖版全标（渐变金徽记+酒红字） | 浅底/白底主用 |
| nbdpsy-emblem.svg | 仅徽记，渐变金 | 头像位、片头印章、水印 |
| nbdpsy-emblem-gold-flat.svg | 仅徽记，纯金 #C9A961 | 小尺寸、单色场景 |
| nbdpsy-logo-mono-burgundy.svg | 全标单色酒红 #8B2942 | 单色浅底 |
| nbdpsy-logo-mono-gold.svg | 全标单色金 #B8995E | 中性深浅底 |
| nbdpsy-logo-reversed.svg | 全标反白 #FFF9EF | 深色底（酒红/深棕/夜景） |

## 品牌色
酒红 #8B2942 ｜ 金(扁平) #B8995E / #C9A961 ｜ 渐变金 #D2B071→#BD985E ｜ 反白奶油 #FFF9EF ｜ 暖米底 #FFFCF5

## 使用规则
- 深色底用 reversed 或渐变金徽记，**不要**把彩色版直接压深底（酒红字会消失）
- 安全空间：四周 ≥ 徽记高度 1/4；最小尺寸：全标屏幕 ≥96px 高、徽记 ≥24px
- 视频/图片管线取用：SVG 直接喂 Chromium/ffmpeg overlay，或按需转 PNG：`python3 -c "..."` / rsvg；**不要拉伸变形、不要改色、不要加描边阴影**
- 印刷格式（PDF/EPS）与完整规格 README 在主仓 `NBDpsy/frontend/marketing-web/public/brand/`，公网 https://www.nbdpsy.com/brand/svg/nbdpsy-emblem.svg 等同路径可直取

## 分享图铁律（2026-08-13 老板拍板，全平台强制）
小红书/小程序/服务号等一切**对外分享位**的品牌图，一律用标准锁定版式分享卡（本目录
`nbdpsy-share-card.svg` 矢量母版 / `nbdpsy-share-square-1080.png` 1:1 成品）：
暖米 #FFFCF5 底 + 渐变金徽记 + 酒红「NBDpsy / 心理咨询工作室」双行名。
**禁**纯徽记单独作分享图（logo 传达不了任何信息）、**禁**酒红满版底作分享图。
其他尺寸成品公网直取：www.nbdpsy.com/brand/share/（square-1080 / mp-520x416 / og-1200x630）。
