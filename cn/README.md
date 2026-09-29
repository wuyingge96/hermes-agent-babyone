# Hermes CN 覆盖层

此目录包含本 fork 维护的下游集成内容。这里集中保存 CN 能力决策、兼容性记录、
客户端契约和独立运行时打包层，不复制 Hermes 源码树。

## 边界

- `capabilities/` 描述客户端需要的行为，以及选定的 Hermes commit 是否已经提供这些行为。
- `patches/` 记录无法通过现有配置、插件或打包方式交付的源码变更。每个源码补丁都应
  保持小而明确，并关联一个能力和一个聚焦的回归测试。
- `contracts/` 记录并验证独立 Hermes CN Desktop 客户端使用的 API/runtime 行为。
- `packaging/` 根据明确选择的 Hermes 源码 commit，为该客户端构建独立运行时产物。
- `docs/` 记录此覆盖层的架构和操作流程。

`apps/desktop` 下的上游 Hermes Electron 应用有自己的打包流程。它不是 CN Desktop
客户端使用的独立 PyInstaller runtime。除非客户端架构发生变化，否则不要耦合这两条发布流程。

## 适配 Hermes 版本

1. 在运行时构建请求中固定完整的 Hermes source commit。
2. 对照该 commit 检查 `capabilities/catalog.yaml`。
3. 将能力标记为 `native`、`configured`、`packaged`、`patched` 或 `unsupported`，并关联证据和测试。
4. 只应用该版本仍然需要的补丁。某项能力可能已经被上游实现，或自上一次构建后被其他方案替代。
5. 发布前运行客户端契约测试和打包运行时 smoke 测试。

能力需求可以跨 commit 复用。补丁片段和打包假设必须针对每个 commit 重新验证。

## 源码归属

当 Hermes 提供可用的集成点时，将新的 CN 自有实现放在此目录中。某些行为可能需要
修改上游拥有的模块。在这种情况下，应把代码变更保留在负责该行为的模块中，并在
`patches/` 中登记；把所有代码移出所属模块会形成第二条实现路径并使控制流难以追踪。
