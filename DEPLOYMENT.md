# 部署与访问架构说明

> 回答核心问题：**代码层的改动不需要改回来。** 本轮对 portfolio / quant-web 源码的修改是把"硬编码根路径"改成"相对前缀（BASE_URL）"，这是标准的可移植写法，部署到任何服务器、任何路径、任何域名都自适应。真正和 Tailscale/Caddy 绑定的只有**环境层配置**（Caddyfile、tailscale funnel、dev server 启动方式），换环境时换的是这些，不是代码。

## 1. 当前访问链路（Tailscale Funnel 方案）

```
浏览器
  → https://goldmac-mini.tail81369e.ts.net/...   (Tailscale Funnel, TLS 由 tailscale 终结)
  → 127.0.0.1:8080                                (Caddy 路径分发, 配置: ../Caddyfile)
      /resume/*        → 127.0.0.1:4321  Astro dev server (portfolio, base='/resume')
      /src /node_modules /@* → 4321            (Astro dev 模式的根相对资源)
      /quant/*         → 127.0.0.1:5273  Vite dev server (quant-web, base='/quant/', 前缀不剥)
      /api/*  /ws*     → 127.0.0.1:8000  Flask 后端
      其余             → 404
```

外网可用是因为 Tailscale Funnel 把域名暴露到公网（无需对方装 Tailscale）。

## 2. 改动分类：哪些不用改回，哪些换环境要改

### 2.1 代码层（可移植，部署到服务器【不用改回】）

| 文件 | 改动 | 为什么不用改回 |
|---|---|---|
| portfolio 全部页面/组件 | 硬编码 `/xxx` 资源与链接 → `` `${import.meta.env.BASE_URL}/xxx` `` | BASE_URL 随 astro.config 的 `base` 自动变化；挂根路径时它就是 `/`，产物与原写法等价 |
| portfolio `astro.config.mjs` | `base: '/resume'` + vite `server.allowedHosts` | `base` 是部署参数，换环境改这一个值即可；`allowedHosts` 仅 dev server 生效，不影响生产构建 |
| quant-web `vite.config.ts` | `base: '/quant/'` + `allowedHosts` | 同上 |
| quant-web 前端 `/api`、同源 `/ws` | 未改动（本来就正确） | 相对路径天然跟随当前域名 |

关键点：之前"图片展示不出来"不是 Tailscale 造成的，是**硬编码根路径在子路径部署下本来就断**（本地直接访问 4321 端口没事，但任何反代子路径都会断）。本轮修改是修 bug，不是加绑定。

### 2.2 环境层（Tailscale/Caddy 专属，换环境【替换这些】）

| 项 | 位置 | 说明 |
|---|---|---|
| Caddyfile | `/Users/gold/.openclaw/workspace/Caddyfile` | 站点地址必须是 `:8080`（不能写 host，funnel 转发来的 Host 是域名不是 localhost） |
| funnel 配置 | `tailscale funnel 8080`（持久化在 tailscaled） | 把 443 → 本机 8080 |
| dev server 启动 | 见 §4 | 当前是临时 nohup 启动，重启 Mac 后需手动拉起 |

## 3. 部署到正式服务器时的两种方案

### 方案 A：子路径部署（代码零改动，推荐）

保留 `base` 不动，服务器上用任意反代（nginx/caddy）按同样规则分发：

```nginx
location /resume/  { proxy_pass http://127.0.0.1:4321; }   # 或托管 astro build 产物
location /quant/   { proxy_pass http://127.0.0.1:5273; }
location /api/     { proxy_pass http://127.0.0.1:8000; }
location /ws       { proxy_pass http://127.0.0.1:8000; upgrade; }
# astro dev 模式才需要 /src /node_modules /@* 规则；生产构建后可删
```

portfolio 生产建议 `astro build` 后直接托管 `dist/`（纯静态），连 node 进程都省了。

### 方案 B：整站挂根路径（各一个域名/端口）

只需改两个值，其余代码零改动：
- `astro.config.mjs`：`base` 删掉（或改 `'/'`），`site` 换成正式域名
- `vite.config.ts`：`base: '/'`（或删掉）

前端所有 `${BASE_URL}/...` 引用会自动变成根路径，无需逐处回改。

## 4. 本机当前进程与启动命令

| 服务 | 端口 | 启动命令 | 日志 |
|---|---|---|---|
| Caddy | 8080 | `caddy start --config /Users/gold/.openclaw/workspace/Caddyfile` | — |
| Astro (portfolio) | 4321 | `cd project/portfolio && nohup node node_modules/.bin/astro dev --host 0.0.0.0 --port 4321 &` | /tmp/astro-dev.log |
| Vite (quant-web) | 5273 | `cd project/quant-web && nohup node node_modules/.bin/vite --host 0.0.0.0 --port 5273 &` | /tmp/vite-dev.log |
| Flask 后端 | 8000 | launchd `com.quant.backend`（开机自启） | — |

注意：
- Caddy / Astro / Vite 目前是**临时进程**，Mac 重启后需手动拉起（可按需注册 launchd）。
- 本机 shell 有 `http_proxy=127.0.0.1:7897`，curl 测试本机服务时务必加 `--noproxy '*'`，否则请求绕道 clash 得到假结果。

## 5. 故障排查速查

| 症状 | 检查 |
|---|---|
| 两个站都打不开 | `pgrep caddy`；`curl --noproxy '*' -I http://127.0.0.1:8080/resume/` |
| 页面 200 但空白 | 看响应 body 是否为空 —— 曾因 Caddyfile 写了 `http://localhost:8080` 导致 host 不匹配返回空 200 |
| 单站 403 "Blocked request" | dev server 的 `allowedHosts` 没加当前域名（astro 在 astro.config 的 `vite.server.allowedHosts`） |
| 页面能开但图片/样式 404 | 该资源引用是根相对硬编码，改成 `${import.meta.env.BASE_URL}/...`；或 Caddyfile 缺对应路径规则 |
| 改了 astro.config / vite.config 不生效 | dev server 不会热载配置，需重启进程 |
