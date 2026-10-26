# 行意在线版

Sites / Cloudflare Workers / D1 / React。源码位于本地完整版的 online/，与 Python 版共用合成车源和公开实验结果。

## 本地验证

Node.js 24；npm ci 安装后：

- node --test tests/engine.test.mjs：工具证据、首付、条件更新、候选范围、拒绝联系和模型失败。
- npm run build：生成 Workers 产物。
- 执行 drizzle/0000_skinny_rumiko_fujikawa.sql 初始化本地 D1 后，npm start -- --port 8770 预览。
- 在父项目执行 python tests/online_http_smoke.py，验证构建后的访客隔离、跨站写入限制和会话持久化，不调用真实模型。

本地迁移命令：
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0000_skinny_rumiko_fujikawa.sql

Windows 如文件监听受到本地数据库/日志影响，可将预览的 --persist-to、WRANGLER_LOG_PATH 与 registry 路径指向项目外部；对应本地数据库须先执行同一迁移。

## 云端

.openai/hosting.json 仅存Site ID与DB绑定。通过Sites工具保存版本/部署；平台应用迁移。DEEPSEEK_API_KEY、DEEPSEEK_MODEL、SESSION_SECRET 仅放运行时秘密，不写入清单或源码。

每IP每天20次模型请求、全站每天120次；按UTC自然日计数，工具循环会消耗多次请求。失败预留不回退。创建对话每IP每天60次。额度由D1原子更新限制。

聊天与待办按访客存放在D1；匿名Cookie为HttpOnly/SameSite。公开API不返回内部模型messages。批量报告及人工备注在浏览器保存；逐条处理需页面保持打开。它不是本地Python后台批次的完全替代。

对照实验页明确展示已保存的真实实验；没有实时重跑。两组6/6通过，不声称Agent准确率更高。真实库存、CRM、客户消息和车商预约均未接入。
