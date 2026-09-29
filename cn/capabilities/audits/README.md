# 按 commit 的能力审计

`audit_source.py` 为一个精确的 Hermes source commit 创建一份 JSON 报告：

```powershell
python cn/capabilities/scripts/audit_source.py `
  --source-commit d9d122a0
```

报告记录静态源码证据、完整 commit 和能力清单摘要。`evidence_status` 表示在该 commit 中找到了
预期的符号或路由；它不代表客户端契约已经正常工作。因此每一行都会先以
`status: audit-required` 开始。

真实契约测试和打包 runtime 测试通过后，将该行更新为 `native`、`configured`、`packaged`、
`patched` 或 `unsupported` 之一，关联测试名称；需要源码补丁时，再填写 patch ID。报告使用
完整 commit 命名，并应与使用它们的构建输入一起保留。
