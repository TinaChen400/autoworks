可以。你在 VS Code 里先不要追求“真正自动调度多个 Agent”。**最容易开始的方法是：用同一个 Codex，但通过不同提示词、不同 Git 分支、不同文件权限，让它分别扮演 Architect / Builder / Reviewer。**

Codex IDE extension 可以在 VS Code 里并行使用，也可以把较大的任务委托到 Codex Cloud；Codex 本身支持读代码、改代码、运行代码、审查代码等工作流。([OpenAI 开发者][1]) Codex CLI 也支持本地代码 review、subagents、approval modes 等能力，后面可以再升级。([OpenAI 开发者][2])

下面你可以直接照着做。

---

# 第一步：先在 VS Code 建项目文件夹

在 Windows 上建立一个新文件夹，例如：

```text
C:\Projects\kvm_survey_agent
```

用 VS Code 打开这个文件夹。

然后在 VS Code 终端里运行：

```bash
git init
```

再建立基础目录：

```bash
mkdir app modules docs tests
mkdir modules\window_capture
mkdir modules\coordinate_mapper
mkdir modules\vision_parser
mkdir modules\ocr_helper
mkdir modules\knowledge_base
mkdir modules\answer_engine
mkdir modules\action_executor
mkdir modules\review_panel
mkdir tests\fixtures
mkdir tests\integration
```

你的初始结构应该是：

```text
kvm_survey_agent/
│
├── app/
├── modules/
│   ├── window_capture/
│   ├── coordinate_mapper/
│   ├── vision_parser/
│   ├── ocr_helper/
│   ├── knowledge_base/
│   ├── answer_engine/
│   ├── action_executor/
│   └── review_panel/
│
├── docs/
├── tests/
│   ├── fixtures/
│   └── integration/
└── README.md
```

---

# 第二步：安装 VS Code Codex 插件

在 VS Code 左侧打开 **Extensions**。

搜索：

```text
Codex
```

安装 OpenAI 的 Codex IDE extension。官方说明里，Codex VS Code extension 可以让你在 IDE 中直接和 Codex 一起写代码，也可以把任务交给 Codex Cloud。([OpenAI 开发者][1])

安装后，登录你的 ChatGPT / OpenAI 账号。

如果你更习惯命令行，也可以之后安装 Codex CLI：

```bash
npm install -g @openai/codex
```

官方文档说明 Codex CLI 可以本地运行，也支持 review、subagents、web search 等功能。([GitHub][3])

但你现在先用 VS Code 插件就够。

---

# 第三步：先创建 4 个控制文档

在 `docs/` 下面新建：

```text
docs/architecture.md
docs/module-boundaries.md
docs/api-contracts.md
docs/frozen-modules.md
```

先手动写入最小内容。

## `docs/frozen-modules.md`

```markdown
# Frozen Modules

This file controls which modules are frozen.

Rule:
- Frozen modules can be imported and read.
- Frozen modules must not be edited unless a new change request is approved.

## Current Status

| Module | Status | Editable |
|---|---|---|
| window_capture | planned | yes |
| coordinate_mapper | planned | yes |
| vision_parser | planned | yes |
| ocr_helper | planned | yes |
| knowledge_base | planned | yes |
| answer_engine | planned | yes |
| action_executor | planned | yes |
| review_panel | planned | yes |
```

## `docs/module-boundaries.md`

```markdown
# Module Boundaries

## window_capture
Purpose:
- Locate the Sunflower KVM remote window on computer A.
- Capture only the remote window area.

Must not:
- Call multimodal models.
- Decide answers.
- Move the mouse.

## coordinate_mapper
Purpose:
- Convert normalized coordinates from the model into real screen coordinates.

Must not:
- Capture screenshots.
- Call models.
- Click the mouse.

## vision_parser
Purpose:
- Send screenshots to a multimodal model such as Doubao.
- Return questions, options, input fields, buttons and coordinates.

Must not:
- Execute mouse actions.
- Directly submit forms.

## knowledge_base
Purpose:
- Retrieve local knowledge relevant to a question.

## answer_engine
Purpose:
- Decide the best answer using question data and knowledge context.

## action_executor
Purpose:
- Execute mouse and keyboard actions only after approval.

## review_panel
Purpose:
- Show detected questions and proposed answers for human confirmation.
```

## `docs/api-contracts.md`

````markdown
# API Contracts

All modules must communicate through explicit input/output contracts.

## WindowBox

```json
{
  "x": 0,
  "y": 0,
  "width": 1280,
  "height": 720
}
````

## Model Click Coordinate

Use normalized coordinates:

```json
{
  "click_norm": [0.5, 0.6]
}
```

## Parsed Question

```json
{
  "id": "q1",
  "text": "Question text",
  "type": "single_choice",
  "options": [
    {
      "id": "q1_a",
      "text": "Option text",
      "click_norm": [0.2, 0.4]
    }
  ]
}
```

## Answer Decision

```json
{
  "question_id": "q1",
  "action": "select",
  "target_option_id": "q1_a",
  "confidence": 0.9,
  "need_human_review": false
}
```

````

## `docs/architecture.md`

```markdown
# Architecture

This project is a Windows-based KVM visual survey assistant.

Computer A:
- Windows main control computer.
- Runs Python.
- Captures the Sunflower KVM remote window.
- Sends screenshots to a multimodal model.
- Receives question and coordinate data.
- Uses local knowledge base to decide answers.
- Executes mouse and keyboard actions after confirmation.

Computer B:
- Remote controlled computer shown inside the KVM window.
- The system has no DOM access.
- The system only sees pixels through the remote window.

Core pipeline:

1. Locate KVM window.
2. Capture screenshot.
3. Parse page with multimodal model.
4. Use OCR only as auxiliary verification.
5. Retrieve local knowledge.
6. Decide answer.
7. Map coordinates.
8. Show human confirmation.
9. Execute mouse or keyboard action.
10. Verify result.
````

---

# 第四步：在 VS Code 里创建“3 个 Agent 提示词文件”

新建文件夹：

```text
docs/agent-prompts/
```

然后建 3 个文件：

```text
docs/agent-prompts/architect-agent.md
docs/agent-prompts/builder-agent.md
docs/agent-prompts/reviewer-agent.md
```

## Architect Agent 提示词

```markdown
# Architect Agent Prompt

You are the Architect Agent.

You must:
- Read docs/architecture.md
- Read docs/module-boundaries.md
- Read docs/api-contracts.md
- Read docs/frozen-modules.md

You must not write implementation code unless explicitly asked.

Your job:
1. Check whether a planned module fits the architecture.
2. Define clean interfaces.
3. Prevent cross-module pollution.
4. Decide whether a module can be frozen.
5. Update architecture documents only when asked.

When reviewing a task, return:
- Approved or not approved
- Required files
- Allowed files to edit
- Forbidden files to edit
- Interface contract
- Test requirement
```

## Builder Agent 提示词

```markdown
# Builder Agent Prompt

You are the Builder Agent.

Before coding, you must read:
- docs/architecture.md
- docs/module-boundaries.md
- docs/api-contracts.md
- docs/frozen-modules.md

Rules:
1. Only edit files explicitly allowed in the task.
2. Do not edit frozen modules.
3. Do not change public interfaces unless approved.
4. Add tests or a manual test script.
5. Keep changes small.
6. Report changed files at the end.

Output:
- What changed
- How to run
- How to test
- Known limitations
```

## Reviewer Agent 提示词

```markdown
# Reviewer Agent Prompt

You are the Reviewer Agent.

You must review code only. Do not implement changes unless explicitly asked.

Check:
1. Did the Builder edit forbidden files?
2. Did the Builder modify frozen modules?
3. Did the code break API contracts?
4. Are there hardcoded local paths?
5. Are secrets or API keys exposed?
6. Is error handling acceptable?
7. Are tests included?
8. Is the module still independent?

Return:
- PASS or FAIL
- Blocking issues
- Non-blocking suggestions
- Files that should not have been changed
```

这三个文件就是你的“多 Agent 设置”。

---

# 第五步：你在 VS Code 里怎么实际使用 Codex

你不需要真的开三个插件。你可以开三个不同的 Codex 对话窗口，分别粘贴不同角色提示词。

## 对话 1：Architect

粘贴：

```text
Read docs/agent-prompts/architect-agent.md and act as Architect Agent.

Task:
Review the current project structure and tell me whether it is ready to implement the first module: window_capture.

Do not write code.
```

Architect 会告诉你模块边界和文件是否合理。

---

## 对话 2：Builder

等 Architect 同意后，再开一个新 Codex 对话，粘贴：

```text
Read docs/agent-prompts/builder-agent.md and act as Builder Agent.

Task:
Implement only the window_capture module.

Allowed to edit:
- modules/window_capture/*
- tests/fixtures/*
- tests/integration/* only if needed

Forbidden to edit:
- modules/coordinate_mapper/*
- modules/vision_parser/*
- modules/answer_engine/*
- modules/action_executor/*
- docs/frozen-modules.md
- docs/api-contracts.md

Requirements:
1. Locate a Windows application window by title keyword.
2. Return window x, y, width, height.
3. Capture only that window area.
4. Save screenshot to tests/fixtures/latest_capture.png.
5. Add a simple manual test script.

Target window title keyword:
Sunflower or 向日葵

Do not implement OCR, Doubao, answer logic, or mouse clicking.
```

---

## 对话 3：Reviewer

Builder 完成后，再开一个新 Codex 对话：

```text
Read docs/agent-prompts/reviewer-agent.md and act as Reviewer Agent.

Review the current changes.

Check:
1. Did the Builder only edit allowed files?
2. Does window_capture stay independent?
3. Are there hardcoded paths?
4. Is the output compatible with docs/api-contracts.md?
5. Can this module be frozen?

Do not modify code.
Return PASS or FAIL.
```

---

# 第六步：用 Git 保护每个模块

在 VS Code 终端：

```bash
git add .
git commit -m "initial project structure"
```

开发第一个模块前，建分支：

```bash
git checkout -b feature/window-capture
```

Builder 完成后：

```bash
git status
git diff
git add .
git commit -m "implement window capture module"
```

Reviewer 通过后，合并回 main：

```bash
git checkout main
git merge feature/window-capture
```

然后把模块状态改为 frozen。

在 `docs/frozen-modules.md` 改成：

```markdown
| window_capture | frozen | no |
```

再提交：

```bash
git add docs/frozen-modules.md
git commit -m "freeze window_capture module"
```

以后任何 Agent 都必须读取这个文件。
这样它就知道：

```text
window_capture 只能读取，不能修改。
```

---

# 第七步：每开发一个模块都重复这个流程

顺序建议如下：

```text
1. window_capture
2. coordinate_mapper
3. vision_parser
4. knowledge_base
5. answer_engine
6. review_panel
7. action_executor
```

每个模块都这样：

```text
Architect 审任务
↓
Builder 写代码
↓
Reviewer 检查
↓
你确认
↓
Git commit
↓
冻结模块
```

---

# 第八步：你现在第一条 Codex 指令可以直接复制这个

你现在在 VS Code 里打开 Codex，直接输入：

```text
You are the Architect Agent.

Please create the initial architecture control files for this project.

Project:
A Windows-based KVM visual survey assistant.

Context:
Computer A is a Windows control machine.
Computer A connects to remote computer B through a Sunflower KVM remote window.
The system has no browser DOM access.
It can only capture the remote window image, send screenshots to a multimodal model such as Doubao, parse questions/options/input fields/click positions, use OCR only as auxiliary verification, use a local knowledge base for answer generation, and execute mouse/keyboard actions only after human confirmation.

Create or update these files:
- docs/architecture.md
- docs/module-boundaries.md
- docs/api-contracts.md
- docs/frozen-modules.md
- docs/agent-prompts/architect-agent.md
- docs/agent-prompts/builder-agent.md
- docs/agent-prompts/reviewer-agent.md

Do not implement any Python code yet.

The documents must define:
1. Module boundaries.
2. Allowed and forbidden dependencies.
3. Frozen module rules.
4. JSON contracts.
5. The development workflow using Architect Agent, Builder Agent and Reviewer Agent.
```

这一步完成后，不要马上让它写全部代码。
下一步只做 `window_capture`。

---

# 我的建议

你先不要考虑复杂的 subagents 或 MCP。Codex 确实有 subagents、review、Cloud task 等能力，但你现在最容易成功的方式是：

```text
VS Code + Codex 插件
+
Git 分支
+
3 个 Agent 提示词文件
+
模块冻结文档
+
每次只开发一个模块
```

你的真正起点是：

```text
先让 Codex 创建 docs 和 agent-prompts。
然后只开发 window_capture。
```

这样你不会乱。

[1]: https://developers.openai.com/codex/ide?utm_source=chatgpt.com "Codex IDE extension"
[2]: https://developers.openai.com/codex/cli?utm_source=chatgpt.com "Codex CLI"
[3]: https://github.com/openai/codex?utm_source=chatgpt.com "openai/codex: Lightweight coding agent that runs in your ..."
