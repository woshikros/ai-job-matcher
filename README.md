# AI Job Matcher

一个只在本机运行的AI岗位匹配面板。它读取智联与猎聘的职位信息，根据本机简历进行评分、排序和去重，并保存历史记录、人工处理状态与投递统计。

本项目只检索和分析，不会自动投递、打招呼或发送消息。

投递状态刻意只保留“未处理、已投递、不考虑”三种，避免要求用户持续维护复杂流程。

## 主要功能

- 智联公开职位页与猎聘只读CLI的岗位读取
- 完整JD六维评分、硬性条件识别、评分依据和统一排序
- JD隐藏内容清理、可疑指令提示和不可信内容隔离
- 岗位截止日期、7天内截止提醒和已截止排除
- 75分以上岗位的可选Codex二阶段深度分析
- 最近5个工作日报的手动能力差距报告
- 统一的平台字段接口，便于增加新的只读职位来源
- 同平台重复过滤、跨平台重复标记
- SQLite本地历史记录与已投递/不考虑状态
- 岗位首次发现、最近发现、出现天数和当日新增筛选
- 今日、累计和最近14天投递统计
- 不含简历原文的历史备份与恢复
- 工作日定时生成HTML报告
- 可选的本地候选人事实配置与招呼语校验

硬性条件独立显示为“符合、需确认、明确不符”，不会增加投递状态。明确不符岗位保留在报告底部供核对，但不占推荐或补充名额。

工作日脚本先准备候选岗位和提示文件。Codex根据提示分别生成招呼语JSON与深度分析JSON，再执行：

```powershell
.\.venv\Scripts\python.exe -m job_matcher.daily_report `
  --candidates-json reports\YYYY-MM-DD-candidates.json `
  --greetings-json reports\YYYY-MM-DD-greetings.json `
  --deep-analysis-json reports\YYYY-MM-DD-deep-analysis.json `
  --output reports\YYYY-MM-DD.html `
  --report-date YYYY-MM-DD
```

发布前运行 `python tools/security_checks.py --release`；GitHub自动测试也会执行相同的隐私检查。

## 安装

需要 Python 3.11 或更高版本，以及能够在本机运行的 `liepin-cli`。本仓库不包含招聘平台账号、授权信息或第三方CLI。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

启动本机面板：

```powershell
uvicorn job_matcher.web:app --host 127.0.0.1 --port 8000
```

首次打开 <http://127.0.0.1:8000/> 会进入“我的求职档案”。上传简历，并填写工作城市、目标岗位方向、薪资、不考虑关键词以及可对外使用的真实能力。保存后，每日任务会直接读取本机档案，不需要再把简历路径写入脚本。简历和个人设置只保存在已被Git忽略的本机数据库与目录中。

## 本机候选人配置

复制示例文件，但不要提交填写后的真实资料：

```powershell
Copy-Item config\profile.example.json config\profile.local.json
$env:JOB_MATCHER_PROFILE = "config/profile.local.json"
```

`profile.local.json` 用于约束招呼语中允许出现的技术能力和真实成果，已被 `.gitignore` 排除。

## 每日报告

直接生成评分和历史报告，不生成招呼语：

```powershell
.\.venv\Scripts\python.exe -m job_matcher.daily_report `
  --resume "C:\path\to\your-resume.pdf" `
  --address 深圳 --pages 2 `
  --report-date 2026-01-01 `
  --output "reports\2026-01-01.html"
```

如果需要外部AI逐岗生成招呼语，可先使用 `--prepare-output` 生成候选JSON和提示文件，再通过 `--candidates-json`、`--greetings-json`、`--output` 完成严格校验后的渲染。个人事实始终来自本机配置。

## 工作日定时运行

运行脚本会在周末自动跳过：

```powershell
.\scripts\run-weekday.ps1
```

安装周一至周五上午9点的Windows计划任务：

```powershell
.\scripts\install-weekday-task.ps1
```

也可将 `config/automation-prompt.example.md` 用作本地自动化任务说明。不要把当前电脑的自动任务配置或简历路径提交到仓库。

## 可选AI分析

设置兼容OpenAI接口的环境变量后，评分结果可以附加AI分析。真实密钥只能设置在本机环境中：

```powershell
$env:LLM_BASE_URL = "https://your-service.example/v1"
$env:LLM_API_KEY = "your-local-key"
$env:LLM_MODEL = "your-model"
```

## 数据与隐私

以下内容默认不会进入Git：简历、数据库、报告、日志、平台授权、环境变量、候选人本机配置和虚拟环境。提交前建议运行测试和隐私扫描。

```powershell
python -m unittest discover -s tests -v
```
