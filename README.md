# 砺石精密 · 尺寸过程漂移复核

为砺石精密14人质量组固定单值测量基线，分别检查EWMA过程信号与工程规格越界，复核后导出完整控制序列。

## 场景与功能

上游 `shaft_diameter_202611.csv` 来自模拟轴径量测，三台机床各200次观测。质量组原先手工画图，基线随新数据反复变化、把规格界限当作控制界限、漂移发生后难以追溯。本工程替代测量核查、基线锁定、过程计算和偏差复核这一段，下游工艺师据此讨论调整设备与现场复测。全部数据模拟，不连接真实生产设备。

六实体：MeasurementDataset测量数据、BaselineWindow固定基线、ControlStudy控制方案、ControlRun计算运行、DeviationReview偏差复核、Report报告。六页：计量总览、单值测量、锁定基线、控制方案、漂移与能力、偏差复核。总览与结果共用真实ControlChart和CapabilityPanel。

## 快速启动

```sh
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```

前端 http://localhost:18216 ，后端 http://localhost:19216/docs ，PostgreSQL端口17716。五服务frontend/backend/worker/db/redis均配置健康检查，数据库/Redis/共享产物用命名卷。清理测试数据：`docker compose down -v --remove-orphans`。

| 账号 | 角色 | 权限 |
|---|---|---|
| admin@lishi.test | admin / 质量复核工程师 | 全实体、批准/退回、审计 |
| analyst@lishi.test | analyst / 计量分析员 | 导入、锁定基线、配置、运行、提交复核和生成报告 |
| viewer@lishi.test | viewer / 工艺观察员 | 六实体只读，下载批准报告 |

统一演示密码 `Gauge2026!`。PBKDF2密码哈希、JWT HS256、actor审计、全局错误恢复、运行队列配额10。匿名401，写入越权403，重复审批409。示例密钥通过JWT_SECRET配置。

## 一天的工作剧本

1. 08:30 分析员核查600次单值尺寸，确认LS-01/02/03机台及观测顺序。
2. 08:35 检查shaft_diameter_202611.csv的sample_id、machine、sequence、value列，单位mm。
3. 08:45 选择已人工检查稳定的LS-01第1—60次观测，锁定均值、样本标准差与样本快照。
4. 08:50 建立监控第61—200次的方案，λ=0.2、L=3，另填工程规格19.95—20.05mm。
5. 09:00 提交运行，Redis排队，独立Python worker计算并持久化PostgreSQL及共享结果文件。
6. 09:05 对照原始尺寸、EWMA、动态控制界限和工程规格；核查约第135次之后的模拟均值漂移及信号。
7. 09:15 分别检查实测超规格数与过程信号，不以漂移时的能力指数直接判定过程合格。
8. 09:25 提交偏差说明，质量工程师批准或退回；生成报告，工艺观察员下载完整控制序列CSV。

## 算法与口径

基线至少5个单值观测，σ使用样本标准差（分母n-1，ddof=1）。零方差/极小方差、非有限数、不足样本明确拒绝。基线实体保存原样本、均值和σ快照；监控起点必须严格在基线结束后。测量CSV同机台序号唯一、样本编号唯一，0<value≤1,000,000mm，最多5000行；空监控窗口在worker中明确记failed。

EWMA：Z₀=μ₀，Zₜ=λxₜ+(1-λ)Zₜ₋₁。随t变化的控制界限为 μ₀±Lσ₀√[λ/(2-λ)×(1-(1-λ)^(2t))]。每次是单个观测，不额外除sqrt(n)；t是监控区间的第t次实际观测，原始sequence保留。λ∈(0,1]，L>0。控制信号依据Z超动态界限，原始尺寸超规格依据x<LSL或x>USL，两类判据分别保存。

能力指数：Cp=(USL-LSL)/(6σ₀)，Cpk=min(USL-监控均值,监控均值-LSL)/(3σ₀)，固定使用锁定基线σ；同时保留监控实际标准差供诊断。仅在稳定、近正态、量测系统适用等条件下解释能力。检测到任一EWMA信号时，capability_interpretation_allowed=false，界面明确能力数值仅描述诊断。实测超规格数直接逐条计数，等于规格边界的不计越界；超规格率=实际越界数/监控样本数，未用正态尾概率替代。

结果保存全部原始尺寸、EWMA、μ/σ、控制与规格界限、两类标记、Cp/Cpk、实测计数、假设与输入SHA256。报告必须引用该运行已批准复核；CSV防公式前缀。

## 技术与目录

| 层 | 技术 |
|---|---|
| 前端 | React18 / TypeScript5.7 / Vite6 / Nginx1.28 |
| 后端 | Python3.12 / FastAPI / psycopg3 |
| 算法 | Python statistics/math标准库 |
| 持久化与异步 | PostgreSQL16 / Redis7.4 / 独立worker |

`backend/src/{routes,controllers,services,models,schemas,middlewares,utils,constants,config}` 与 `frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}` 分离职责，76个职责源文件。PostgreSQL每实体表使用TEXT主键和JSON文本payload，DDL在backend/migrations/001_initial.sql；事务级advisory lock保护backend/worker首次建表并发。

共享角色/运行/复核枚举：后端src/constants/enums.py；前端src/constants/enums.ts。类型在models/entities.py、schemas/entities.py及frontend/src/types/entities.ts中保持一致。

环境变量：DATABASE_URL、REDIS_URL、JWT_SECRET、SEED_DEMO、TASK_MODE、ARTIFACT_DIR、RUN_STALE_SECONDS（心跳超时判定中断，默认60秒）、HEARTBEAT_INTERVAL（心跳间隔，默认10秒）、RECOVERY_INTERVAL（中断运行扫描间隔，默认15秒）；Compose短名/端口/数据库口令见.env.example。SEED_DEMO默认true，失败记录日志不伪造结果；自然键insert-only，两次seed不新增、不覆盖手工修改。固定seed2207生成600观测，稳定基线与后段漂移。

运行生命周期测试无需第三方依赖：`cd backend && python -I tests/test_run_lifecycle.py`（38项状态机/快照/并发断言）与 `python -I tests/test_worker_e2e.py`（驱动真实worker循环的崩溃恢复与重复投递端到端断言）。

本地开发：安装backend/requirements.txt并配置PostgreSQL/Redis后，运行 `uvicorn src.main:app --reload`；frontend执行 `npm install && npm run dev`，通过生产Nginx或配置/api代理访问后端。

## 已知边界

基线窗口的“稳定”需要质量工程师人工核查，本项目不自动证明正态性与测量系统能力，也不实施完整控制图规则集。仅EWMA超界规则；不输出过程合格保证。运行出队后由worker用心跳维持“计算中”状态，进程中断（强杀/崩溃/断电）会在心跳超时后自动恢复，按排队时固化的测量数据、基线与方案快照重算；重复投递与多进程并发领取由数据库事务状态机串行化，同一运行只接受当前尝试的一份结果，旧进程迟到的结果不能覆盖新结果，恢复重投失败会在运行上写明原因。没有多人编辑乐观锁与迁移回滚。默认账号仅本地演示。

真实容器、HTTP、手算oracle、浏览器操作、1440×900及响应式截图均位于批次test-artifacts/gb-2207，不混入源码目录。

## License

MIT，见LICENSE。
