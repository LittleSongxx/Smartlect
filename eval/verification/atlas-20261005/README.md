# 架构图集交付证据（2026-10-05）

对应改动记录：[docs/改动记录/2026-10-05/架构图图集.md](../../../docs/改动记录/2026-10-05/架构图图集.md)；
图集本体在仓库根目录 `架构图/`。

## 文件

| 文件 | 说明 |
| --- | --- |
| `citation-audit.txt` | 13 份候选里的全部 111 条唯一 `sources` 锚点，逐条取 `git show HEAD:<path>` 核对路径与行号范围（0 条越界）。 |
| `index-desktop-1440.png` | 导航站首页在 1440×1000 的渲染截图（总览图 iframe 正常）。 |
| `page-11-rag-430.png` | 说明页在 430×932 的窄屏截图（页面重排正常）。 |
| `cards-04-backend-2x.png` | 后端图卡片区 2× 放大截图：修复长斜杠串溢出后的状态。 |

## 逐图四门收据

每张图最后一次通过 `finalize` 的收据在 `架构图/diagrams/review-<n>/<name>.finalize-summary.json`
（完整收据为同名 `.finalize.json`）。四门状态、spec/artifact 的 sha256 汇总见
[架构图/README.md](../../../架构图/README.md#图集与校验状态)。

复现：

```bash
export ARCHIFY_CHROME="$HOME/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome"
node "$HOME/.zcode/skills/archify/bin/archify.mjs" finalize <type> \
  架构图/candidates/<name>.json 架构图/diagrams/<name>.html \
  --repo-root . --quality showcase --json --out-dir 架构图/diagrams/review-<n>
```
