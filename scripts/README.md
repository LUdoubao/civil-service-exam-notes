# 真题采集工具

## 安装

在仓库根目录执行：

```powershell
python -m pip install -r scripts/requirements.txt
```

Python 3.12 为目标版本。脚本使用公开来源、缓存和限速请求，不绕过登录、验证码、访问控制或付费限制。

## 使用

```powershell
# 获取公考真题库的试卷索引（只缓存，不改题库）
python scripts/quiz_pipeline.py list --cls 行测 --province 浙江 --year 2024

# 按科目预览，默认不写入正式 Markdown
python scripts/quiz_pipeline.py fetch `
  --paper https://gwy.gkzhenti.cn/paper/<id> `
  --province 浙江 `
  --subject 言语理解与表达 `
  --question-type 逻辑填空 `
  --preview

# 明确写入题目、答案和图片
python scripts/quiz_pipeline.py fetch `
  --paper https://gwy.gkzhenti.cn/paper/<id> `
  --province 浙江 `
  --subject 言语理解与表达 `
  --question-type 逻辑填空 `
  --apply

# 校验题库
python scripts/quiz_pipeline.py validate --path 题库
```

`--proxy http://127.0.0.1:7897` 可用于本地代理环境；不要把账号、Cookie 或 Token 写入脚本和仓库。
图片下载默认并发数为 2，可通过 `--concurrency` 调整，单站点最高限制为 4，避免对来源站点造成突发压力。

## 输出与缓存

- 原始响应和结构化记录写入 `.cache/quiz/gkzhenti/`，该目录已被 Git 忽略。
- 正式题目按题型写入 `题库/题目/<大类>/<题型>/`，答案写入 `题库/答案/<大类>/<题型>/`。
- 图片写入 `题库/资源/图片/<题号>/`，题目使用相对路径。
- 目标网站没有答案时，答案字段留空、状态为“待核验”，题号和顺序保持不变。
- 试卷页面标注“网友回忆版”时，输出会保留该版本标识，不当作官方原卷。
- 每次 `list`/`fetch` 输出都会附带两类信息：内容估算 Token，以及对话实际 Token 状态。脚本不调用模型，因此 `conversation_token_usage` 默认是“不可读取”；这不能用内容估算值替代，实际对话 Token 需由调用平台提供。

示例：

```json
"content_token_estimate": {
  "question_tokens": 420,
  "answer_tokens": 96,
  "total_tokens": 516,
  "method": "ceil(UTF-8 bytes / 4); local script does not call a model"
},
"conversation_token_usage": {
  "input_tokens": null,
  "output_tokens": null,
  "total_tokens": null,
  "status": "不可读取"
}
```

## 开发测试

```powershell
python -m unittest discover -s scripts/tests -p 'test_*.py'
```
