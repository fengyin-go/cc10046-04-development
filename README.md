# 网络数据采集与RPA自动化平台

面向网页数据采集、自动化流程编排、解析规则管理、代理池调度与采集结果校验的数据采集工程平台

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8010/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5174/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8010`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 爬虫配置 | `crawler_config` | 爬虫配置 | 配置标识、起始地址、页面编码 |
| 解析规则 | `parser_rule` | 解析规则 | 规则标识、目标页面、字段选择器 |
| 代理池 | `proxy_pool` | 代理节点 | 节点标识、代理地址、代理协议 |
| Cookie管理 | `cookie_mgr` | Cookie会话 | 会话标识、来源站点、Cookie内容 |
| 限速控制 | `rate_limiter` | 限速策略 | 策略标识、目标站点、请求频率 |
| 抽取模板 | `extraction_template` | 抽取模板 | 模板标识、适用站点、列表选择器 |
| 数据校验器 | `data_validator` | 校验规则 | 规则标识、校验字段、校验类型 |
| 采集调度 | `crawl_schedule` | 调度任务 | 任务标识、关联配置、调度周期 |
| 结果存储 | `result_store` | 存储批次 | 批次标识、来源配置、采集时间 |
| 去重引擎 | `dedup_engine` | 去重策略 | 策略标识、业务键列、排序字段 |
| 字段映射 | `field_mapper` | 映射方案 | 方案标识、来源字段、目标字段 |
| 异常重试 | `error_retry` | 重试策略 | 策略标识、错误类型、重试次数 |
| 批次追踪 | `batch_tracker` | 采集批次 | 批次标识、调度任务、开始时间 |
| 导出通道 | `export_channel` | 导出任务 | 任务标识、来源批次、导出格式 |
| 采集审计 | `crawl_audit` | 审计记录 | 记录标识、操作类型、操作对象 |
| 来源归属 | `source_attribution` | 来源归属记录 | 归属标识、批次标签、货号、来源方、收件人、原始行标识、确认状态 |
| 来源认证 | `source_auth` | 认证凭证 | 凭证标识、来源站点、认证方式 |
| HTML清洗 | `html_cleaner` | 清洗模板 | 模板标识、适用站点、标签过滤 |
| 增量同步 | `incremental_sync` | 同步水位 | 水位标识、来源配置、增量字段 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 来源归属与归属交付

采集审计过去只有批次标签，无法说明一条原始行属于哪个来源。来源归属模块
（`source_attribution`，服务 `app/services/source_attribution.py`）新增两层记录：

- 采集原始行（内存表 `source_row`）：来源方实际采到的报价行，含报价快照、来源凭据、采集时间；
- 来源归属记录（内存表 `source_attribution`）：把原始行按批次标签归属给收件人，
  状态为 `待确认 / 已确认 / 已撤回`。

业务规则：

1. 同一批次标签下不同来源对同一货号保留各自独立的原始行与归属记录；
2. 撤回只把归属标记为「已撤回」并保留全部历史，仅影响后续交付批次；
3. 同一原始行反复确认幂等，只算一次，确认时间不被覆盖；
4. 现场补发对凭据齐备（报价快照、来源凭据、采集时间齐全）的行可同时确认来源；
5. 收件方视图只返回当次已归属给自己的原始行；
6. 导出通道消费归属记录，交付批次只含已确认且未撤回的行，甲独有货号不会进入乙的批次；
7. 交付明细冻结当时的归属标识、确认状态与原始凭据，事后可按当时权限核对；
8. 已交付过的行不会再进入后续补发批次，同货号只出现一次。

专属接口前缀 `/api/attributions`：

| 接口 | 说明 |
| --- | --- |
| `POST /raw-rows` | 登记原始行并建立归属（重复登记幂等） |
| `POST /withdraw` | 撤回某来源在批次标签下的归属 |
| `POST /confirm` | 按原始凭据确认归属（迟到确认同样适用，幂等） |
| `POST /confirm-on-site` | 现场补发：凭据齐备时同时确认 |
| `GET /sku-status` | 查某货号在批次内各来源的确认状态 |
| `GET /recipient-view` | 收件方受限视图 |
| `POST /deliver` | 组装归属交付批次（导出通道） |
| `GET /deliveries` | 查交付批次及收件明细 |
| `GET /verify-line` | 按当时归属权限和原始凭据核对已交付行 |

通用资源接口 `/api/source_attribution` 仍可分页查询、导出和执行通用动作。

领域：数据工程
子方向：数据采集、爬虫与RPA
