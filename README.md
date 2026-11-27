# Bridge/AI Obsidian Wiki Research Team (ADK 2.x + Gemini 4 Neon)

一个基于 **Google ADK 2.x 图工作流（Graph Workflow）** 与 **`gemini-4-neon`** 构建的生产级 5 智能体调研与知识入库团队。专为桥梁病害检测、无人机巡检与交通工程 AI 研究场景设计：你只需给出一个研究主题或本地规范/论文 PDF，团队便自动并行完成外部权威资料调研与本地 Obsidian Wiki 查重、撰稿、确定性代码校验、独立质检打分与最多 2 轮自动返工，并在写入正式知识库前硬暂停等你审批。

## 解决什么问题

- **消灭重复搬砖**：把每周高频的“查论文/规范 -> 核验出处 -> 整理 Markdown -> 维护 `index.md` / `log.md`”压缩成一条命令 + 2 分钟人工拍板。
- **杜绝幻觉与空双链**：采用 `WebScout`（外部多视角检索）与 `VaultMiner`（本地只读查重）并行扇出，经 `deterministic_linter` 自动还原原始深层 URL 并硬校验 YAML 与真实 `.md` 双链，再由 `Checker` 打分（>= 85 且零红线方可放行）。
- **持续自我进化**：每次运行写入 `logs/run_log.jsonl`，配合 `weekly_review.py` 每周统计首轮质检通过率、定位最弱智能体并提出 1 条待审批的提示词优化建议。

## 3 步安装指南

### 第 1 步：创建 Python 3.11+ 虚拟环境并安装依赖
```bash
cd agent_team
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
*(若 macOS 环境遇到 Keychain SSL 校验报错 `OSStatus -26276`，改用 `.venv/bin/pip install --use-deprecated=legacy-certs --cert /etc/ssl/cert.pem -r requirements.txt`。)*

### 第 2 步：配置环境变量（切勿提交到 Git）
在终端或本地 `agent_team/.env` 中设置：
```bash
export GEMINI_API_KEY="你的_Gemini_API_Key"
# 可选：指向你的真实 Obsidian 仓库（不设置则默认安全写入 vault_sandbox/）
export OBSIDIAN_VAULT_PATH="/path/to/your/obsidian/vault"
```

### 第 3 步：校验图结构并用一条命令运行团队
```bash
# 1) 静态校验 ADK 2.x 图结构（不消耗 Token）
.venv/bin/python run_team.py --validate-only

# 2) 运行一个真实调研任务（到达人工审批节点时终端会提示输入 APPROVE 或 REJECT）
SSL_CERT_FILE=/etc/ssl/cert.pem .venv/bin/python -u run_team.py --topic "你的桥隧或 AI 调研主题"
```

## 每周改进循环（只读建议，绝不擅自改提示词）
```bash
.venv/bin/python weekly_review.py
```

## 目录结构
- `bridge_wiki_team/agent.py`：ADK 2.x `Workflow` 图编排（含 `JoinNode`、2 轮质量循环与 `RequestInput` HITL 暂停节点）
- `bridge_wiki_team/tools.py`：本地只读查重、PDF 分页摘录、确定性 Linter、URL 还原、审批入库合并与日志写入
- `skills/*/SKILL.md`：5 个可直接复用的 Antigravity 智能体技能定义
- `memory/team_memory.md`：Lead 每次运行前必读的团队记忆
- `run_team.py` / `weekly_review.py`：单命令运行入口与每周日志复盘脚本
