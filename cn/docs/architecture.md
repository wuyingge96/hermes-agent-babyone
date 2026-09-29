# CN 覆盖层架构

## 目标

根据一个选定的 Hermes source commit，以及该 commit 仍然需要的 CN Desktop 能力，
构建独立 runtime。

## 构建身份

每次构建都由以下四项组成：

```text
Hermes source commit + capability catalog revision + patch set + packaging revision
```

将四项全部记录在构建元数据中。只有明确这些输入，发布才可复现。不要使用会移动的分支名作为构建身份。

Electron 客户端当前已验证的 runtime 记录在 `erp-assistant-electron/docs/hermes-core-migration.md`。
其中的 source commit 是客户端契约的证据，不是此 fork 的默认源码版本。每次构建都必须先选择并
记录自己的完整 Hermes commit，再进行能力审计。

## 适配流程

```text
Hermes commit
    -> 能力审计
    -> 配置 / 打包 / 源码补丁
    -> 客户端契约测试
    -> 独立 runtime 构建
    -> artifact smoke 测试和 manifest
```

优先使用 Hermes 现有的扩展点。独立的 CN 自有逻辑放在 `cn/` 中；如果配置或打包层可以提供所需
行为，就使用配置或打包层。当必须修改 Hermes 内部行为时，将代码保留在所属模块旁，并在此处登记
补丁。只有 Hermes 提供稳定的加载集成点时，才适合使用完全独立的覆盖层模块。

客户端边界由四部分组成：

1. Core HTTP 和 WebSocket 行为：status、authentication、sessions、prompts、approvals、attachments、
   config 和 tool discovery。
2. 响应行为：保留 `MEDIA:<absolute path>` 输出，供 Electron Main 进程校验并通过不透明句柄暴露。
3. CN runtime 打包：PyInstaller 产物及其 provenance manifest。
4. 客户端自有资产：CPython、skill venv、wheelhouse 和 managed plugins。这些资产必须与 Core 兼容，
   但不属于 Core 补丁集合。

对于选定的 commit，工具清单契约是 `/api/tools/toolsets`。由于 Electron 客户端已经 fallback 到
toolset 路由，探针允许旧的 `/api/tools` 请求返回 404。这说明即使复用了能力清单，每个 Hermes
commit 仍然需要重新进行契约审计。

能力清单记录上述四部分，便于发布评审区分缺失的 Core 功能和缺失的客户端资产。

## 保持版本变更可理解

- 每个 source commit 都要重新审计能力；需求可以持续复用，但状态不能直接沿用。
- 为每个源码补丁提供稳定 ID 和测试。
- 记录补丁何时被上游吸收或替代。
- 将 runtime artifact 版本与 Hermes 源码版本分开。
- 只从已记录的 source commit 和已测试的构建中发布产物。

## 第一阶段实现里程碑

1. 将能力清单与当前 CN Desktop 客户端及 CN-Core 记录对照整理。
2. 选择一个 Hermes commit，并为清单中的每项能力标记证据。
3. 将现有 runtime 流程移入 `cn/packaging/`，只保留符合当前客户端契约的打包逻辑。
4. 为启动、必需 API 和 frozen imports 添加真实进程 smoke 测试。
5. 在添加自动发布触发器之前，先生成一个本地 runtime 产物。
