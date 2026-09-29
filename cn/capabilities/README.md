# 能力清单

`catalog.yaml` 是 CN Desktop runtime 可复用的需求清单。它描述可观察的行为，
不是需要重放的一组历史 commit。

它与 `D:/BabybusFront/erp-assistant-electron` 对照维护。客户端证据路径说明桌面端实际使用的内容，
不表示当前 Hermes source commit 已经实现这些能力。需求可以跨 commit 复用，但必须针对每个精确
commit 重新审计实现状态。

对每个 Hermes source commit，记录实现状态：

- `native`：固定的 Hermes commit 已经提供所需行为。
- `configured`：现有 Hermes 行为通过运行时配置启用。
- `packaged`：行为已经存在，但必须加入独立 runtime 或在其中初始化。
- `patched`：需要登记过的 CN 源码补丁。
- `unsupported`：在此运行时版本中有意不提供。

每个非 `native` 决策都应关联源码位置或打包规则。每个面向客户端的能力都应关联契约测试或
smoke 测试。不能只因为找到了名称相近的路由或模块就把能力标记为已支持；必须通过客户端实际
启动的 runtime 验证行为。

清单中的 `client_status` 描述客户端当前的依赖和 fallback。`revision_status: audit-required`
表示选定的 Hermes source commit 尚未完成检查。每次构建的审计都应记录交付选择
（`native`、`configured`、`packaged`、`patched` 或 `unsupported`），关联契约测试，并在适用时
关联 patch ID。

清单同时包含 Core 行为、CN runtime 打包和客户端自有资产，便于评审区分各自的归属。特别是，
客户端的 CPython archive、managed skill venv、wheelhouse 和 managed plugins 不属于 Hermes Core
补丁集合。
