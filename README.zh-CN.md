# FairyView

[English](README.md) · **中文**

把数据集、清洗结果、benchmark 或多个模型的输出，生成一个可以离线打开的人工审阅 HTML 页面。不需要服务器，不需要前端构建，生成的是一个文件夹，双击就能打开。

```bash
pip install "fairyview[parquet] @ git+https://github.com/mindtravel/FairyView"
fairyview inspect --path data/my_dataset --out review.toml   # 读取 schema，生成配置
fairyview try     --config review.toml --limit 3             # 在终端预览 record
fairyview build   --config review.toml --out out/my_dataset  # 打开 out/my_dataset/index.html
```

---

## 工作方式

```
数据文件 ──view──► records ──renderer──► index.html
          （读取列）  （统一 schema）  （统一模板）
```

**一行数据变成一条 record，一组 record 变成一个页面。** 所有来源都产出同一种 record 结构（`fairyview/schema.py`），所以接入新数据集只需要写配置，不需要新页面。

每次 build 都遵守三条规则：

- **来源可追溯。** 每条 record 都带着来源文件和行号。页面顶部和 `manifest.json` 列出所有来源文件及其大小、修改时间。
- **以原始数据为主。** 面板显示字段的原始文本，不做改写；如果配置了截断，截断说明会直接写进文本里。
- **丢了就报错。** 缺少某一列时 build 直接失败，并列出可用的列。每一行没能生成 record 的数据都会按原因计数，写进 manifest 并打印到 stderr；设置 `on_drop = "error"` 时，任何丢行都会让 build 失败。

## 选择 view

`inspect` 会根据 schema 自动选择；需要时在 `[source]` 里用 `kind` 覆盖。

| `kind` | 数据形状 | 页面显示 |
|---|---|---|
| `auto` | 任意 | 和 `inspect` 的选择相同 |
| `chat_rows` | `messages` / `conversations` | 逐轮对话，参与训练的角色标为 loss |
| `hf_rows` | 单个文本列 | 文本和 facet |
| `columns_rows` | 指定的列（支持 `a.b`、`a[0].b`） | 每列一个面板 |
| `benchmark_rows` | 题目 + 参考答案 + 模型输出 | 题目、参考答案、各模型回答、分数 |
| `inference_rows` | 题目 + 模型输出 | 各模型输出并排 |
| `paired` | 两个按 key 关联的来源 | 处理前 / 处理后，以及丢弃原因 |
| `./file.py:func` | 其他任何形状 | 你的函数产出的 record |

## 配置

```toml
title = "GSM8K 审阅"
data_key = "gsm8k-2026-10"   # 浏览器里的标注决策按这个 key 保存
facets = ["split"]           # 筛选控件；数据里没有对应列时写 []
caveats = ["随机抽样，不是全量统计。"]
lang = "zh"                  # 页面语言：en / zh；读者可以在页面上切换

[sample]
n = 200
seed = 0
stratify = "split"           # 可选

[source]
kind = "benchmark_rows"
path = "data/gsm8k"          # 相对于这个配置文件
glob = "**/*.parquet"
```

**页面。** `panel_layout`（`side_by_side` / `stacked` / `toggle`），`blinded_default`（默认隐藏分数，读者点击后才显示），`max_inline_records`（超过这个数量就分片），`page_size`（每次"加载更多"渲染的卡片数，默认 100）。

**抽样。** 对流式索引做蓄水池抽样，`seed` 相同时结果相同。设置 `stratify` 后，名额在各层之间平均分配；某层的行数少于配额时整层收录，剩余名额再分给其他层。因此 `n` 大于等于总行数时会收录全部数据。

**来源字段。** 字段名由 `inspect` 自动填好，只有需要覆盖时才手动设置。

| 键 | 适用的 view |
|---|---|
| `messages_field`、`system_field` | `chat_rows` |
| `text_field`、`fields` | `hf_rows` |
| `panels = [{field, label}]`、`scores`、`auto_panels`、`skip_empty` | `columns_rows` |
| `prompt_field`、`gold_field`、`outputs_field`、`score_field`、`scoring` | `benchmark_rows`、`inference_rows` |
| `[source.left]`、`[source.right]`、`join_field`、`reason_field`、`fields` | `paired` |
| `id_field`、`on_drop`（`report` / `error`） | 全部 |

**Mask。** 高亮通过规则配置，不需要写代码：

```toml
[mask]
loss_roles = ["assistant"]          # 对话中参与训练的角色
prompt_roles = ["user", "system"]   # 对话中只作为上下文的角色
max_panel_chars = 20000             # 可选截断，截断说明写进文本

[[mask.rules]]                      # 正则 -> 高亮 span
pattern = "<think>.*?</think>"
kind = "loss"                       # loss / prompt / match / warning / custom
label = "reasoning"
```

规则作用于所有面板。规则之间重叠时，排在前面的规则生效。span 是字符偏移，不是 token。

**数据文件。** 只支持未压缩的 parquet、JSONL 和 JSON。压缩文件（`.gz`、`.bz2`、`.xz`、`.zst`）会被拒绝，需要先解压（`gunzip -k`）。JSONL 按字节偏移定位行，因此 build 过程中文件被修改会导致 build 失败。

## 页面功能

卡片和表格视图、facet 筛选、搜索、面板布局切换、span 高亮、分数条、盲审模式、中英文切换，以及"保留 / 剔除 / 存疑"标注（保存在浏览器中，可导出为 `decisions.jsonl`）。不同 `scale` 的分数不会合并显示。数据量大时自动分片，仍然可以通过 `file://` 直接打开。

## 自定义 adapter

```python
# my_adapter.py，放在配置文件旁边，不需要打包
from fairyview.schema import Panel, ReviewRecord

def make_records(cfg):
    for i, row in enumerate(load_rows(cfg["path"])):
        yield ReviewRecord(
            id=row["id"],
            facets={"source": row["source"]},
            panels=[Panel(role="text", label="body", text=row["text"])],
            provenance={"file": cfg["path"], "row": i},
        )
```

```toml
[source]
kind = "./my_adapter.py:make_records"
path = "data/"
```

## 命令行

| 命令 | 用途 |
|---|---|
| `inspect --path P [--out cfg.toml]` | 列出各列及其角色，生成可用的配置 |
| `try --config C --limit N` | 在终端打印 record；build 之前先跑这一步 |
| `build --config C --out DIR` | 生成页面 |
| `dump --config C --out DIR` | 输出 `records.jsonl` |
| `init --preset NAME` / `presets` | 从预设配置开始 |
| `adapters` / `describe` | 列出可用的 view；给 agent 用的机器可读说明 |

## 开发

```bash
pip install -e ".[test,parquet]"
pytest -q
```

代码结构和贡献规则见 [CONTRIBUTING.md](CONTRIBUTING.md)，给编程 agent 的说明见 [AGENTS.md](AGENTS.md)，变更记录见 [CHANGELOG.md](CHANGELOG.md)。

Apache-2.0。
