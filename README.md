# Tibo 的 Codex 额度重置微信监控

GitHub Actions 每 15 分钟检查第三方公开数据源，用 push+ 发到你的微信。无需购买 X API，无需填写 X 密码或 Cookie，无需电脑保持开机，也无需在你的大陆 Windows 服务器上安装任何程序。

**部署完成的判断：你收到测试微信、手动 `check` 运行成功、随后至少出现一次自动运行。**

## 先了解它能做什么

- 识别重置预告、意向、预计时间、完成表述、延期和更正，以及 banked reset。
- 同时检查信号帖子和上下文帖子，避免漏掉只写 `Done` 的回复。关联明确才列为确认；缺少直接关联时标为“待核实”。
- 首次 `check` 建立云端自己的基线，部署之前的历史消息不会批量补发。后续正常运行只推送新相关记录。
- 根据帖子 ID、文本指纹和事件阶段去重。同一帖从预告变成确认、已见旧帖出现文本修改，都可分别通知。
- 状态保存在同一仓库的 `monitor-state` 分支，不依赖容易失效的 Actions 缓存。任务重启不丢基线；普通安静检查不反复提交状态。
- 数据源连续三轮不可用时通知一次；恢复后通知一次。推送请求明确失败时保留待发队列。
- 不使用收费模型；中文说明由规则生成，保留英文原文供核对。
- 显示时间统一标注为 **北京时间（UTC+8）**。原文美国时间能确定日期和时区时，另附对应的北京时间；`PT/ET/CT/MT` 按日期处理美国夏令时。

**限制：** 免费数据源是独立站 `codex-reset.com` 的公开收录，并非 X/OpenAI 官方服务，可能遗漏、延迟或停更。程序不会把站方预测、其他人的账户到账截图或“预计时间已过”当成 Tibo 已确认。自然语言规则也可能误判复杂表达，所以通知会附原文链接及来源说明。

## 第 1 步：准备 push+

1. 打开 [push+ 官网](https://www.pushplus.plus/)，用微信扫码登录。
2. 按页面提示关注、绑定“pushplus 推送加”公众号，完成实名认证。
3. 在个人中心找到用于推送的 Token。用户 Token 或可用于给自己推送的消息 Token 均可。
4. 复制 Token，下一步存进 GitHub Secret。**不要写进 `config.json`、代码、README 或聊天。**

本项目只用微信免费渠道。当前官方文档列出实名用户微信日请求额度 200 次；程序按命中批量推送，不是每次检查都发消息。不需要为这个项目先购买会员。

## 第 2 步：新建 GitHub 仓库

1. 登录 GitHub，打开 [新建仓库](https://github.com/new)。
2. Repository name 填 `tibo-codex-monitor`，也可以自行命名。
3. 选择 **Public**，使用标准 GitHub 托管执行器可免费运行。代码和运行记录将公开；Token 仍只放在 Secrets。
4. 可以勾选 Add a README file，创建仓库。后续用本项目的 README 替换即可。

这里用的是 **GitHub Actions 云端定时执行**，不是 GitHub Pages，也不是你的大陆服务器或本地执行器。

## 第 3 步：上传项目文件

解压 `tibo-codex-monitor.zip`，进入其中的 `tibo-codex-monitor` 文件夹。上传的是**里面的内容**，不要在仓库顶层再套一层同名文件夹，也不要只上传 ZIP 文件。

在仓库 Code 页面选择 **Add file → Upload files**，拖入文件，提交到默认分支（通常是 `main`）。最终至少应有：

```text
仓库根目录
├── monitor.py
├── time_display.py              # 北京时间显示及美国时间换算
├── config.json
├── README.md
├── workflow.yml                 # 工作流内容的可见备份，方便网页复制
├── tests/
│   └── test_monitor.py
└── .github/
    └── workflows/
        └── monitor.yml          # 只有放在这个路径，GitHub 才会定时执行
```

### 网页上传时看不到 `.github` 文件夹怎么办

Mac 可以按 `Command + Shift + .` 显示隐藏文件。更简单的替代方法是：

1. 先上传可见文件以及 `tests` 文件夹，提交。
2. 打开本项目可见的 `workflow.yml` 文件，复制全部内容。
3. 回到仓库，选择 **Add file → Create new file**。
4. 文件名输入 **`.github/workflows/monitor.yml`**。
5. 粘贴刚才复制的内容，选择 **Commit changes**，提交到默认分支。

仓库根目录的 `workflow.yml` 只是备份，不会自己运行。如果 `.github/workflows/monitor.yml` 已经上传，不用再创建一次。日后改执行时间时修改 `.github/workflows/monitor.yml` 即可。

## 第 4 步：把 Token 放入 GitHub Secrets

1. 打开仓库 **Settings**。
2. 左侧选择 **Secrets and variables → Actions**。
3. 点击 **New repository secret**。
4. Name 填 **`PUSHPLUS_TOKEN`**，大小写按这里填写。
5. Secret 粘贴第 1 步取得的 Token，注意没有空格或换行。
6. 点击 **Add secret**。

**只需手动添加这一个 Secret。** `GITHUB_TOKEN` 由 Actions 自动生成，不需要你申请或另存一个 GitHub 个人 Token。本项目不需要 X Bearer Token。

## 第 5 步：先发一条微信测试

1. 打开仓库顶部 **Actions**。
2. 如果出现启用工作流的提示，选择允许启用。
3. 左侧选择 **Tibo Codex Monitor**。
4. 点击右侧 **Run workflow**，Branch 选默认分支 `main`。
5. mode 选 **`test`**，点击绿色 **Run workflow**。
6. 打开新出现的运行记录，等待完成，然后检查手机微信。

应收到标题类似“**Tibo 监控 · 微信推送测试**”的消息。这条测试不是额度重置公告。

工作流显示“push+ 已受理”只表示服务端接受了推送请求，不能证明微信最终送达。**这一步以手机实际看到测试消息为准。** Token 有效但没收到时，去 push+ 消息记录查看发送结果，并确认微信允许公众号通知。

## 第 6 步：建立基线，开始定时监控

1. 再次点击 **Run workflow**，这次 mode 选择 **`check`**。
2. 运行成功后打开 **Summary**，应看到“已建立初始基线”。
3. 仓库会自动出现 `monitor-state` 分支，其中的 `state/monitor.json` 保存去重、上下文和待重试记录。
4. 保持默认分支仍是 `main`。**不要把 `monitor-state` 设置成默认分支，也不要删除其状态文件。**
5. 等待后续的自动运行。默认计划是每小时第 **7、22、37、52 分钟**，计划间隔 15 分钟；上游同步和 GitHub 排队还会带来额外延迟。

首次基线建立后，不会发送例行“检查完成”微信。下一条相关公告出现之前，没有微信通知是正常情况。

`preview` 模式可以手动查看最近 72 小时可能匹配的帖子，不发送微信，也不改基线。它可能显示部署前的历史记录；这不代表这些旧记录会补发。

## 第 7 步：确认云端运行

- Actions 列表中出现一次触发方式为 **schedule** 的自动运行，并正常完成。
- 能在 Summary 看到最新检查时间。数据源异常会单独显示，不会被写成“没有新消息”。
- 这时电脑可以关机，任务由 GitHub 继续执行。无需运行 Codex、Render 或大陆 Windows 服务器。
- 本聊天之前创建的 Codex 本地监控是另一个独立任务。GitHub 上线后可要求 Codex 停掉旧任务，避免两条通道各自通知；本项目不会擅自改动它。

## 常见问题

| 现象 | 处理 |
|---|---|
| Actions 中看不到工作流 | 检查路径是否为 `.github/workflows/monitor.yml`，以及是否提交到了默认分支。不能只上传 ZIP。 |
| 没有 Run workflow 按钮 | 检查工作流是否在默认分支、Actions 是否启用，以及账号是否有仓库写权限。 |
| 缺少 PUSHPLUS_TOKEN | 按第 4 步配置 Repository Secret；不是变量 Variables。 |
| push+ 错误码 903 | 检查 Token 是否复制正确、是否带空格或换行。 |
| push+ 错误码 905 | 去 push+ 完成实名认证。 |
| 已受理但微信没收到 | 查看 push+ 消息记录、公众号绑定、账号额度和手机通知设置。普通模板可能需要点击查看详情。 |
| GitHub HTTP 403 / 状态写入失败 | 到 Settings → Actions → General → Workflow permissions，允许 Read and write permissions 并保存。若组织策略禁止写入，需由管理员允许。不要申请多余的 PAT。 |
| GitHub HTTP 409 / 422 | 检查 `monitor-state` 是否受分支规则限制；只从默认分支运行。保留现有状态，排查冲突后重试。 |
| 数据源过期或连接失败 | 程序按计划重试；连续三轮后只提醒一次。无需把 X 账号密码交给任何服务。 |
| 时间到了却没有“已重置” | 预告不是确认；程序不会根据时钟自动宣布重置。 |
| 测试成功，之后没有微信 | 首次运行只建基线；后面没有新相关信息就保持安静。查看 Actions 的 Summary 确认是否在运行。 |
| 偶尔比 15 分钟更晚 | GitHub 调度可能延迟，队列繁忙时甚至可能丢弃本轮；下轮回看补查，但超过数据源保留范围的内容仍可能遗漏。 |
| 想暂停 | Actions → Tibo Codex Monitor → 右上角菜单 → Disable workflow；恢复时 Enable workflow。 |

## 免费运行的边界

- 推荐 **Public 仓库 + `ubuntu-latest` 标准托管执行器**；不要改成收费的 Larger runner。
- 私有仓库有每月免费分钟配额。15 分钟一次的持续任务可能超过免费配额，所以不把“私有仓库也必定免费”作为前提。
- GitHub 可能对连续 60 天没有仓库活动的公开仓库停用定时工作流。请定期查看 Actions 是否仍有自动运行；停用后进入 Actions 重新启用。本程序不保证消除平台停用条件。
- 免费源和 GitHub 都没有为本项目提供实时到达保证；这是一套尽力监控方案。

## 调整提醒范围

编辑 `config.json`，然后提交到默认分支：

| 配置 | 默认 | 用途 |
|---|---|---|
| `include_teasers` | `true` | 包含重置相关讨论或意向；想更少通知可改成 `false`。 |
| `include_ambiguous_confirmations` | `true` | 对附近有重置预告但缺少直接关联的简短完成帖，标为“待核实”；改成 `false` 可关闭。 |
| `max_feed_age_minutes` | `45` | 数据源刷新超过此分钟数，按数据源异常处理；不是用“最后发帖多久以前”判断失效。 |
| `lookback_hours` | `72` | 回看帖子和上下文的时间范围，补查延迟收录。 |
| `failure_alert_after` | `3` | 连续读取失败多少轮后发一次告警。 |
| `max_posts_per_message` | `10` | 一次消息最多合并几条动态，减少微信请求；剩余队列留到后续运行。 |

修改频率需要编辑 `.github/workflows/monitor.yml` 的 `cron`。默认值 `7,22,37,52 * * * *` 表示每小时这些分钟运行。不要为了更快提醒而高频请求第三方源。

## 开发与运行说明

运行依赖仅为 Python 标准库。Actions 使用 Python 3.12 和 Ubuntu 自带的 IANA 时区数据库。完整时间换算和测试需要 Python 3.9+；Windows 本地若没有 IANA 数据，可安装免费的 `tzdata` 包。GitHub 托管执行器无需额外安装。

```sh
python -m unittest discover -s tests -v
python monitor.py --mode preview
```

本地需要真实测试时，从终端环境变量传入 `PUSHPLUS_TOKEN`，再执行 `python monitor.py --mode test`。若在本地运行监控，必须显式设置 `--local-state local-state.json`，避免误用云端状态。

`check` 会先持久化待发队列，再调用 push+；HTTP/业务错误不删除队列，后续重试。`code=200` 和返回流水号只标记“已受理”，不标记“微信送达”。只用一个推送 Token 时不查询开放接口的最终送达状态。如果请求已经被服务端接收，但客户端在收到响应前断线，或受理后保存状态失败，后续重试仍可能产生重复；没有承诺跨服务严格一次送达。

代码不会把 Token 写入状态文件，也不会输出完整 HTTP 请求或原始错误响应。公开的状态分支包含公开帖子上下文、消息流水号和检查状态，不要自行往其中加入私人资料。

时间处理：所有展示的时间均明确标注 **北京时间（UTC+8）**，包括推文发布时间、通知生成时间和可确定的预计执行时间。原推文保持原样，在“原文时间对应的北京时间”中列出每一处可识别的时间表达及换算结果。

- `within 2 hours` 等相对时间以推文发布时间为起点；`in 2 hours` 显示预计时点，`within/next/over` 显示预计窗口。
- `today/tomorrow/yesterday` 按原文时区里的发帖日期解释，不能直接套用北京时间的日期。
- `PST/PDT/EST/EDT/MST/MDT/CDT` 按原文明确缩写的固定偏移换算；`PT/ET/CT/MT` 根据日期使用美国夏令时规则。
- 支持有日期锚点的 12 小时制、24 小时制和多处时间表达，例如 `today at 6pm PT`、`2026-10-19 at 18:00 PT`。
- `CST` 可能指不同时区：只有原文明确美国中部语境时才按美国中部时间换算。
- 日期、年份、时区缺失，或者 `EOD` 边界不明时，明确显示“北京时间（UTC+8）：无法唯一确定”。不猜测 `23:59`，也不因为预告时间过去而宣布完成。
- 美国夏令时跳时造成不存在的本地时间时，注明无法换算；回拨造成两个对应时刻时，列出两个北京时间，不擅自选一个。
- 推文发布时间不等于每个账户的实际恢复时刻。完成通知未给独立的到账时间时，会明确说明。

## 通知状态与模板

以下是消息格式说明，不是当前真实公告。打开仓库中的 `notification_samples.html` 可以查看 **13 种虚构示例的完整正文**；页面使用与真实推送相同的渲染函数生成。

| 状态 | 消息标题/状态 | 主要含义 |
|---|---|---|
| 意向或讨论 | 重置相关意向｜尚未确认 | 提及可能重置，并未承诺执行。 |
| 重置预告 | 重置预告｜待执行 | 预告会重置，尚未确认完成。 |
| 预计时间 | 重置时间更新｜仍为预告 | 保留原文时间，附对应北京时间；到点不会自动转成确认。 |
| 执行中 | 重置执行中｜尚未确认全部完成 | 原文明确表示正在执行。 |
| 完成确认 | 重置确认｜原文称已完成 | 原文包含完成表述；个人账户实际到账仍看客户端。 |
| 延期 | 重置延期｜尚未确认完成 | 展示延期说明和新的时间换算。 |
| 取消 | 重置取消｜以原文为准 | 原文明确取消或说明不会执行。 |
| 更正 | 重置更正｜以最新原文为准 | 展示范围或时间更正，保留最新原文。 |
| banked reset | 储存重置额度｜状态以原文为准 | 展示额度发放信息及原文是否说明需要手动使用。 |
| 上下文不足 | 疑似完成消息｜待核实 | 简短完成帖缺乏直接关联，不当成已证实的重置。 |
| 数据源失败 | Tibo 监控数据源受阻 | 连续三轮无法读取可信数据后通知一次。 |
| 数据源恢复 | Tibo 监控数据源恢复 | 之前已告警的数据源恢复后通知一次。 |

原文时刻无法精确换算时另有一个示例，明确展示“无法唯一确定”的样式。每条正文包含：状态、摘要、推文发布时间（北京时间）、适用范围、是否需手动使用、原文时间换算、英文原文和原推文链接。

本地重新生成模板预览（**不会发微信、不会读取密钥、不会改监控状态**）：

```sh
python preview_notifications.py
```

升级已有部署时，把新增的 `time_display.py` 与新版 `monitor.py` 一起提交到默认分支，保留原有 `PUSHPLUS_TOKEN` 和 `monitor-state` 分支，无需重建基线。合并本次 PR 后，下次定时运行自动使用新格式。

## 依据与数据来源

- [公开数据源](https://codex-reset.com/api/feed)：按账号、规范 X 链接、原帖 ID 和发布时间校验；同时读取 `tweets` 与 `radar_context`。忽略站方的预测和账户观测，不把其 `events` 标注当成 Tibo 原文。
- [GitHub 定时工作流](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)：默认分支、调度延迟和停用规则。
- [GitHub Actions 计费](https://docs.github.com/en/billing/concepts/product-billing/github-actions)：公开仓库标准执行器的免费条件。
- [GitHub Secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)：仓库密钥配置。
- [push+ 消息接口](https://www.pushplus.plus/doc/guide/api.html)：受理与最终发送结果的区别。
- [push+ 额度](https://pushplus.plus/doc/guide/use.html)：实名与免费微信请求额度。
- [Python zoneinfo 官方文档](https://docs.python.org/3/library/zoneinfo.html)：美国夏令时与 IANA 时区数据库。

本项目与 OpenAI、X、Tibo 或数据源维护者没有隶属关系。
