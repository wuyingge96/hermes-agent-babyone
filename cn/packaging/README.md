# 独立 CN runtime 打包

此打包层用于独立 Hermes CN Desktop 客户端启动的 runtime。它与 `apps/desktop` 中的上游 Electron
桌面 bundle 及其发布流程相互独立。

构建输入必须是精确的 Hermes Git commit。输出应携带 source commit、runtime version、目标操作系统/架构、
artifact digest 以及客户端要求的 manifest 格式。包依赖和 frozen imports 必须通过启动构建产物检查，
不能只检查构建目录。

目前有意没有直接复制 Hermes-CN-Core 的打包实现。应先将该项目当前流程与桌面客户端的安装器/更新契约
对照整理，再只把仍然需要的构建逻辑移入此目录。生成文件应保存在被忽略的构建/输出目录中。

此层只负责 Hermes Core artifact。客户端会单独携带 CPython、managed skill venv、wheelhouse 和
managed plugins。将这些资产混入 PyInstaller runtime 会重复客户端的环境安装器，并使源码版本变化更难审计。

每次构建都必须记录完整的 Hermes source commit、capability catalog revision、已应用的 patch IDs、
packaging revision、runtime/kernel versions、目标平台和架构、artifact SHA-256 以及 source provenance。

计划中的目录布局：

```text
cn/packaging/
  README.md
  runtime.spec                 # PyInstaller onedir 入口
  scripts/                     # 构建、smoke、manifest 辅助脚本
  config/                      # 明确的 hidden-import 和 data-file 输入
```

第一个可执行步骤是 `scripts/stage_source.py`：

```powershell
python cn/packaging/scripts/stage_source.py `
  --source-commit d9d122a0 `
  --output .cn-build/staged-source
```

它会导出准确的 Git commit，复制当前 `cn/` 覆盖层，只应用 `cn/patches/manifest.json`，并写入
`.cn-build/staged-source/cn-build-inputs.json`。staging 目录是一次性构建输入，必须保持被忽略；
不会修改源码 checkout。除非提供 `--force`，否则已有输出会被拒绝。

## 构建与验证

先运行输入检查。该步骤会导出请求的 commit，并报告选定的 Python 是否已经安装 PyInstaller：

```powershell
python cn/packaging/scripts/build_runtime.py `
  --source-commit d9d122a0 `
  --platform win32 `
  --arch x64 `
  --check-only
```

选定的构建 Python 必须满足该版本的 frozen-import 策略（当前为 CPython 3.14），并包含 Hermes 基础
环境和 PyInstaller。对于使用 `uv` 的 checkout，可复现的设置方式是：

```powershell
uv pip install --python .cn-build/build-venv-314/Scripts/python.exe -e .
.cn-build/build-venv-314/Scripts/python.exe -m pip install PyInstaller==6.22.3
```

脚本会在冻结前检查必需的 imports。安装这些依赖后，去掉 `--check-only` 再运行同一命令。它会创建
一个 onedir executable 和一个 ZIP，ZIP 根目录直接位于 `.cn-build/runtime/artifacts/` 下并包含 runtime
executable。根据该 ZIP 生成安装器 manifest：

```powershell
python cn/packaging/scripts/write_manifest.py `
  --archive .cn-build/runtime/artifacts/hermes-agent-cn-runtime-win32-x64.zip `
  --staging-metadata .cn-build/runtime/staged-source/cn-build-inputs.json `
  --output .cn-build/runtime/artifacts/stable-win32-x64.json `
  --platform win32 --arch x64 `
  --runtime-version 0.0.0-cn.d9d122a00363.r1 `
  --kernel-version 0.0.0
```

最后使用隔离的 `HERMES_HOME` 启动 executable，并验证 Electron 客户端使用的相同 health 和 OpenAPI 探针：

```powershell
python cn/packaging/scripts/smoke_runtime.py `
  --executable .cn-build/runtime/artifacts/hermes-agent-cn-runtime-win32-x64/hermes-agent-cn-runtime-win32-x64.exe `
  --home .cn-build/runtime/smoke-home
```

第一阶段本地里程碑不会发布 artifact。它用于证明一个已记录的 source commit 可以被 staging、冻结、
检查并启动，同时附带 provenance。

## 目标平台

PyInstaller 会针对运行它的目标平台构建。因此 Windows x64、macOS arm64 和 macOS x64 必须使用独立的
构建机器或 CI runner、独立的 CPython 环境和独立的依赖安装。Windows 无法通过交叉编译生成有效的 macOS
冻结 runtime。每个目标都要独立生成自己的 ZIP、manifest 和 SHA-256；绝不能给为其他操作系统或架构构建的
runtime 重新贴标签。

在每个 macOS 目标上，使用选定 Hermes commit 的 runtime 依赖、`PyInstaller==6.22.3` 和契约依赖，
准备隔离的 CPython 3.14 环境。arm64 使用 arm64 interpreter，x64 使用 x86_64 interpreter（包括
Rosetta 下运行的情况）。构建助手会读取选定 interpreter 的进程架构，并在 staging 或冻结前拒绝不匹配的
`--platform` 或 `--arch` 值。

```bash
CN_PYTHON=.cn-build/build-venv-314/bin/python
CN_ARCH=arm64  # 在独立的 x86_64 运行中改为 x64
CN_COMMIT=d9d122a003633250d22f786bf3d2fa1b63d99e1d

"$CN_PYTHON" cn/packaging/scripts/build_runtime.py \
  --source-commit "$CN_COMMIT" --platform darwin --arch "$CN_ARCH" --check-only
"$CN_PYTHON" cn/packaging/scripts/build_runtime.py \
  --source-commit "$CN_COMMIT" --platform darwin --arch "$CN_ARCH" --force

CN_RUNTIME_EXECUTABLE="$(pwd)/.cn-build/runtime/artifacts/hermes-agent-cn-runtime-darwin-${CN_ARCH}/hermes-agent-cn-runtime-darwin-${CN_ARCH}" \
CN_CONTRACT_PYTHON="$CN_PYTHON" \
"$CN_PYTHON" -m unittest \
  cn.contracts.test_packaging_contract \
  cn.contracts.test_runtime_contract \
  cn.contracts.test_interaction_contract \
  cn.contracts.test_approval_fifo_contract \
  cn.contracts.test_session_header_contract -v
```

分别保存 arm64 和 x64 的 ZIP 与 manifest，然后将每个 manifest 的 `platform`、`arch`、`sourceCommit`、
`catalogSha256` 和 `sha256` 与其自身 archive 对照。managed SkillHub plugin 测试需要此仓库旁边的独立
Electron checkout；跳过测试不代表客户端资产已经通过验证。

如果使用 GitHub Actions，其可发现的 workflow 文件必须放在 `.github/workflows/` 下。该文件应只保留
触发逻辑，并将构建逻辑委托给 `cn/packaging/`。
