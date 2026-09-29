# CN-Core 补丁对照整理

这是一份审计记录，不是应用每个历史 fork 补丁的指令。每个 source commit 都必须重新检查，之后才
能将条目加入 `manifest.json`。

| 历史条目 | 当前对覆盖层的决定 | 原因 |
| --- | --- | --- |
| P-002 upload endpoint | 仅当客户端仍调用 `/api/upload` 时重新审计 | 当前 Electron 契约使用 `file.attach` 和图片附件 RPC；在发现客户端调用前，旧 upload 路由是多余的。 |
| P-003 WebSocket gate | 针对选定 commit 重新审计 | 当前源码的静态审计已经发现 `/api/ws`。如果上游已经提供该路由，不要继续携带旧的 gate 移除补丁。 |
| P-014 MCP frozen imports | 打包要求，暂不作为源码补丁 | 如果选定客户端暴露 MCP，则将 SDK 加入构建环境，并加入明确的 frozen import/data 检查。不要把它改成 Core 源码修改。 |
| P-015 desktop backend extra | 打包要求，暂不作为源码补丁 | 冻结二进制无法在运行时修复缺失的可选依赖。具体 extras 必须根据选定 commit 和客户端功能集确定。 |
| P-026 managed cache paths | 候选源码补丁 | 只有选定 commit 缺少桌面进程所需的 managed-runtime cache 隔离时才应用。先验证环境契约。 |
| P-056 request validation | 候选上游补丁 | 重新检查当前 gateway request models，只为缺失的校验添加聚焦的契约测试。 |
| P-057 frozen memory discovery | 候选打包/源码补丁 | 只有当选定 commit 仍仅从文件系统 manifests 发现 provider，且客户端启用了这些 provider 时才应用。 |
| P-059 media file/range support | 针对当前媒体路由重新审计 | 当前客户端要求保留 `MEDIA:` 响应；视频流是独立需求，不能仅根据该文本协议推断已经支持。 |
| P-063 Moss plugin | 默认不要导入 Core runtime | 它是第三方服务插件，不属于当前 Electron Core 契约；如有需要，应放入 managed plugin package。 |
| P-066 frozen packaging gates | 转换为构建检查 | runtime plugin collection、鉴权/图片 smoke 检查和固定 artifact labels 属于打包流程；源码变更需要独立证据。 |

初始的 `manifest.json` 有意保持为空。只有源码审计发现真实缺口，并且契约测试在选定 Hermes commit
上证明该行为确实存在时，补丁才可以加入其中。
