# 桌面客户端契约

此目录保存独立 Hermes CN Desktop 客户端依赖的行为测试。在可行时，测试应使用临时 Hermes home
和非生产凭据，直接运行真实路由或 runtime 进程。

应先从客户端实际代码提取契约：端点路径、请求和响应结构、鉴权、WebSocket 传输、媒体处理、
启动参数以及 runtime manifest 校验。不能只根据旧 CN-Core 的实现细节推断契约。

每个测试都应关联 `../capabilities/catalog.yaml` 中的 capability ID。

## 必需的契约分组

第一组契约测试应按以下顺序覆盖这些分组：

- 进程启动、`/api/status`、`/openapi.json` 和 session-token 鉴权；
- `/api/ws` JSON-RPC session create/resume、prompt 事件和中断；
- approval 请求/响应 FIFO 行为，以及文档中说明的稳定 approval request ID 缺失；
- 已暂存的文件/图片附件方法；
- REST sessions、config 和带 legacy toolset fallback 的工具清单；
- 保留 `MEDIA:` 响应产物；
- 冻结 executable 启动，以及 manifest digest/provenance 校验。

## 运行真实 runtime 探针

`scripts/probe_runtime.py` 检查公开健康路由、私有 REST 鉴权、WebSocket token 鉴权、
`gateway.ready`，以及 `session.create` / `session.resume` / `commands.catalog` /
`skills.reload` JSON-RPC 调用。它还会写入并重新读取 Electron 形状的 SkillHub provider 配置，
然后通过 REST 列出、读取并删除一个预置 session。临时 provider token 只是占位值，不会发起模型调用。

针对已经启动的 runtime 运行：

```powershell
python cn/contracts/scripts/probe_runtime.py `
  --base-url http://127.0.0.1:18767 `
  --token cn-contract-token
```

启用的 runtime unittest 会自行启动和停止冻结 executable。交互契约使用
`scripts/fake_provider.py` 中的标准库 fake provider，因此结果确定且不需要生产凭据。请使用
包含 `websockets` 依赖的同一个 Python 环境：

```powershell
$env:CN_RUNTIME_EXECUTABLE = ".cn-build/runtime/artifacts/hermes-agent-cn-runtime-win32-x64/hermes-agent-cn-runtime-win32-x64.exe"
$env:CN_CONTRACT_PYTHON = ".cn-build/build-venv-314/Scripts/python.exe"
& $env:CN_CONTRACT_PYTHON -m unittest cn.contracts.test_runtime_contract -v
```

验证模型边界和已暂存附件时，单独运行交互契约：

```powershell
& $env:CN_CONTRACT_PYTHON -m unittest cn.contracts.test_interaction_contract -v
```

`test_interaction_contract.py` 声明 `client.capabilities`，验证
`prompt.submit` -> `message.delta` -> `message.complete` 流，检查
`file.attach`、`image.attach`、`image.attach_bytes`，并保留
`MEDIA:<absolute path>` 响应产物。它还通过 `approval.respond` 完成一次精确的 approval
server-request 往返，并检查 pending queue 和被拒绝的 tool result。fake provider 只针对测试 prompt
发出会产生 approval 的 tool call，使 runtime 测试保持离线且可复现。

该冻结测试覆盖一次完整的 approval request/deny 交换。使用以下命令运行独立的源码队列契约：

```powershell
& $env:CN_CONTRACT_PYTHON -m unittest cn.contracts.test_approval_fifo_contract -v
```

它验证在响应没有 request ID 时，两个不同的 pending request 是否按 FIFO 顺序结算。它不会通过
冻结 WebSocket gateway 验证两个并发请求。上游
`tests.e2e.core.terminal.test_interactive_roundtrip` 套件覆盖交互往返，但不能证明这个多请求
FIFO 场景。

当此仓库旁边存在独立 Electron checkout 时，使用以下命令运行 managed SkillHub plugin 契约：

```powershell
& $env:CN_CONTRACT_PYTHON -m unittest cn.contracts.test_session_header_contract -v
```

它会把客户端插件复制到临时 Hermes home，检查真实插件发现和 request middleware，但不会发送生产请求。
冻结交互契约会另外将同一个插件的固定 URL 重定向到离线 fake provider，并验证实际 provider request
携带 `session.create` 返回的持久 `stored_session_id`。

独立的 CPython archive、skill venv、wheelhouse 和 managed plugins 由客户端仓库验证。这里最多添加
一个小型隔离测试，用于证明 Core artifact 不会静默吸收这些客户端资产。
