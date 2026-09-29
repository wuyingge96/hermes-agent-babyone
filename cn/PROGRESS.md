# Hermes CN 覆盖层进度

## 1. 项目目标

本项目维护一条独立的 CN overlay 构建流程，把一个明确指定的 Hermes-agent
提交与客户端所需的 CN 能力组合成可交付的 runtime：

```text
指定 Hermes commit/tag
    -> 导出该版本源码
    -> 叠加 CN 能力清单
    -> 应用仍然需要的源码补丁
    -> 构建 PyInstaller runtime
    -> 生成 Electron manifest
    -> 启动冻结后的 runtime 做真实契约验证
```

产物供以下客户端使用：

```text
D:\BabybusFront\erp-assistant-electron
```

这里维护的是“指定 Hermes 版本 + 当前仍需要的 CN 能力 = 可复现 runtime”，
不是复制一份 Hermes 源码后长期手工合并。能力需求可以跨 Hermes 提交复用，
但每个新提交都必须重新审计能力状态和补丁必要性。

## 2. 当前基线

| 项目 | 当前值 |
| --- | --- |
| Overlay 仓库 | `D:\BabybusFront\hermes-agent-babyone` |
| 客户端仓库 | `D:\BabybusFront\erp-assistant-electron` |
| 当前分支 | `codex/cn-overlay-runtime` |
| 当前 Hermes commit | `d9d122a003633250d22f786bf3d2fa1b63d99e1d` |
| 构建 Python 策略 | CPython `>=3.14,<3.15` |
| PyInstaller | `6.22.3` |
| 当前补丁清单 | `cn/patches/manifest.json`，目前为空 |

## 3. 目录职责

所有 CN 自有内容集中在 `cn/`，避免把 overlay 逻辑散落到 Hermes 源码中：

- `cn/capabilities/`：客户端能力要求、能力清单和指定提交的审计证据。
- `cn/contracts/`：客户端边界说明、HTTP/WebSocket 契约探针和测试。
- `cn/docs/`：整体架构及操作说明。
- `cn/packaging/`：源码 staging、PyInstaller、manifest 和 runtime smoke 流程。
- `cn/patches/`：只有当前 Hermes 提交仍需要的源码补丁；每个补丁应有稳定 ID、
  适用能力和回归测试。

`.cn-build/` 只存 staging、构建环境、临时 runtime 和生成产物，已加入
`.gitignore`，不能提交。Electron 仓库已有的 `src/update/*` 改动不属于本项目，
后续操作必须保留。

## 4. 已完成

### 4.1 精确提交 staging

`cn/packaging/scripts/stage_source.py` 已支持：

- 接收 commit、tag 或其他 Git ref。
- 使用 `git archive` 导出精确版本，不修改当前 checkout。
- 将当前 `cn/` overlay 复制到 staging 源码中。
- 按 `cn/patches/manifest.json` 应用补丁。
- 写出 `cn-build-inputs.json`，记录 source commit、能力清单 SHA-256、
  packaging revision 和已应用补丁。

### 4.2 Windows x64 runtime 构建

`cn/packaging/scripts/build_runtime.py` 和 `cn/packaging/runtime.spec` 已支持：

- 构建前检查 Python 版本、Hermes 依赖、frozen imports 和资源目录。
- 构建 PyInstaller onedir runtime。
- 生成 ZIP 和 Electron manifest。
- runtime 版本携带 Hermes commit 前缀。

当前已生成并验证的产物目录：

```text
D:\BabybusFront\hermes-agent-babyone\.cn-build\runtime\artifacts
```

产物包括：

```text
hermes-agent-cn-runtime-win32-x64/
hermes-agent-cn-runtime-win32-x64.zip
stable-win32-x64.json
```

当前 runtime version：

```text
0.0.0-cn.d9d122a00363.r1
```

ZIP 根目录已符合 Electron 安装器预期，直接包含：

```text
hermes-agent-cn-runtime-win32-x64.exe
_internal/
```

不会再额外嵌套一层同名目录。

### 4.3 已完成的 runtime 契约验证

基础 frozen smoke 已验证：

- `GET /api/status` 返回 `200`。
- `GET /openapi.json` 返回 `200`。

Electron runtime 契约探针已验证：

- `/api/status` 和 `/openapi.json`。
- 无 token 时私有 REST 被拒绝。
- Bearer token 可以访问私有 REST。
- `/api/ws` 无 token 时被拒绝，带 token 可以连接。
- `gateway.ready`。
- `session.create` 和 `session.resume`。
- `commands.catalog`。
- `skills.reload`。
- `/api/config` 接受客户端形状的 SkillHub provider/model PUT，后续 GET 回读一致。
- `/api/sessions` 列表、消息读取和删除，在临时 home 中完成往返验证。

当前 Hermes 提交的工具目录差异已经记录：

```text
/api/tools          -> 404，允许
/api/tools/toolsets -> 200，必须
```

探针遵循 Electron 客户端已有的 fallback 逻辑，不强行要求旧接口存在。

### 4.4 已完成的打包契约测试

`cn/contracts/test_packaging_contract.py` 覆盖：

- staging 是否记录指定 commit。
- `cn/` overlay 是否进入 staging。
- manifest SHA-256 是否正确。
- manifest provenance 是否存在。
- 补丁列表是否正确。
- Electron ZIP 根布局是否正确。

已通过：

```powershell
python -m unittest cn.contracts.test_packaging_contract -v
```

结果：`Ran 3 tests`，`OK`。

真实冻结 runtime 测试也已通过：

```powershell
$env:CN_RUNTIME_EXECUTABLE = ".cn-build/runtime/artifacts/hermes-agent-cn-runtime-win32-x64/hermes-agent-cn-runtime-win32-x64.exe"
$env:CN_CONTRACT_PYTHON = ".cn-build/build-venv-314/Scripts/python.exe"
& $env:CN_CONTRACT_PYTHON -m unittest cn.contracts.test_runtime_contract -v
```

结果：`Ran 1 test`，`OK`。

### 4.5 已完成的冻结 runtime 交互契约

`cn/contracts/test_interaction_contract.py` 使用标准库 fake provider 启动同一个
Windows x64 冻结 runtime，并验证客户端实际使用的交互边界：

- 通过 `client.capabilities` 声明接收 server request。
- `session.create` 后提交 prompt，收到 `message.delta` 和 `message.complete`。
- fake provider 收到客户端 prompt，响应中的 `MEDIA:C:\contract\media.png` 保持在
  完整消息文本中。
- `file.attach`、`image.attach`、`image.attach_bytes` 都使用临时 fixture 验证。
- 在独立 approval session 中收到完整 `approval` server request，使用
  `approval.respond` 发送 `deny`，确认 `approval.pending` 清空、危险命令没有执行，
  且模型收到包含拒绝结果的 tool 消息。

当前冻结契约覆盖一个完整 approval request/deny 往返。
`cn/contracts/test_approval_fifo_contract.py` 另在源码队列层验证两个不同请求的
无 ID 回答按 FIFO 逐个结算，且第二个请求在第一次回答后仍待处理。上游
`tests.e2e.core.terminal.test_interactive_roundtrip` 覆盖交互往返，但没有证明
这个多请求 FIFO 场景。冻结 runtime 的双请求 WebSocket 路径尚未验证。

`cn/contracts/test_session_header_contract.py` 在临时 Hermes home 中复制客户端
受管 SkillHub 插件，验证真实插件发现和 `llm_request` middleware 仅对指定
SkillHub URL 注入 `X-Session-ID`。冻结交互契约还将该 URL 重定向到本地 fake
provider，并确认实际请求头中的 `X-Session-ID` 等于 `session.create` 返回的
持久 `stored_session_id`，因此 `model.session_header` 已完成当前 runtime 审计。

## 5. 当前构建身份和 manifest

每次发布必须同时记录以下四类输入：

```text
Hermes source commit
+ capability catalog revision
+ applied patch set
+ packaging revision
```

manifest 目前包含：

```text
schemaVersion
runtimeVersion
kernelVersion
runtimeFlavor
runtimeRevision
platform
arch
sha256
sourceRepo
sourceCommit
catalogSha256
packagingRevision
patches
```

这使客户端可以核对 runtime 来源、目标平台、产物摘要以及是否使用了预期的
能力清单和补丁集合。

## 6. 尚未完成

### 下一阶段：能力和平台覆盖

1. **补充冻结 runtime approval FIFO 测试**：源码队列 FIFO 已通过独立契约；
   当前 commit 的同一工具调用批次按顺序执行，两个并发 WebSocket approval 不是可达路径，
   审计中已记录这一边界。
2. **完善 capability catalog 审计**：为 `cn/capabilities/catalog.yaml` 中每项能力
   补充当前 Hermes commit 的证据、状态（`native`、`configured`、`packaged`、
   `patched` 或 `unsupported`）和对应测试；上游已吸收的能力要记录替代关系。
   `model.session_header` 的冻结 provider 请求闭环已通过；后续只需在真实
   Passport/SkillHub 环境做人工联调。
3. **跨平台构建**：目前只真实构建和验证了 Windows x64。macOS arm64 与 macOS
   x64 必须在对应 runner 或机器上分别构建，PyInstaller 不能从 Windows 交叉构建
   有效的 macOS runtime。构建入口现已按所选 Python 的进程架构校验目标标签；
   两种架构的执行命令和验证清单见 `cn/packaging/README.md`。

### 后续发布能力

4. **自动发布流程**：还没有 GitHub Actions、artifact 发布位置、manifest 下载地址、
   Electron 自动更新接入、runtime 回滚流程或版本兼容矩阵。应先完成本地构建和契约
   测试，再设计自动发布。

## 7. 推荐后续顺序

1. 补充冻结 runtime 的多请求 approval FIFO 测试。
2. 按当前 Hermes commit 完成 capability catalog 逐项证据审计。
3. 在 macOS arm64 和 macOS x64 runner 上执行同一组构建和契约测试。
4. 设计 GitHub Actions、artifact 发布和 Electron 更新接入。
5. 全部验证通过后再 commit、push 和创建 PR。

## 8. 维护规则

- 新构建必须使用完整 Hermes commit，不使用未记录的移动分支作为发布依据。
- 能力清单可以跨 commit 复用，但能力状态、接口路径和补丁必要性必须逐 commit
  重新确认。
- 不要机械复制旧 CN-Core 补丁；先检查上游是否已经实现或替代该能力。
- 源码补丁应保持小而明确，并在 `cn/patches/manifest.json` 登记。
- 生成文件只放在 `.cn-build/`，不要提交本地 runtime、构建环境或临时日志。
- 修改客户端时保留 `D:\BabybusFront\erp-assistant-electron` 中与本任务无关的既有改动。
- 完成每个仓库的实现后，分别执行该仓库要求的校验，再提交、推送并观察 CI。

## 9. 相关入口

- 总览：`cn/README.md`
- 架构：`cn/docs/architecture.md`
- 能力清单：`cn/capabilities/catalog.yaml`
- 能力审计：`cn/capabilities/audits/README.md`
- 客户端契约：`cn/contracts/README.md`
- 打包说明：`cn/packaging/README.md`
- 补丁登记：`cn/patches/manifest.json`

