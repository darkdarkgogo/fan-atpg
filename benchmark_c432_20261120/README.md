# c432：FAN_ATPG 与 fault-reorder PODEM 实测

日期：2026-11-20。全程直接运行 C++ 命令行程序，没有启动 RL、模型推理或训练。

| 指标 | FAN_ATPG | fault-reorder PODEM |
|---|---:|---:|
| ATPG 核心耗时中位数 | 55.789 ms | 55.4311 ms |
| 核心耗时范围 | 55.075–58.349 ms | 53.2759–57.7381 ms |
| 整次进程耗时中位数 | 67.5571 ms | 58.2671 ms |
| 测试向量数 | 78 | 87 |
| 独立统一故障仿真覆盖率 | 1611/1662 = 96.9314% | 1611/1662 = 96.9314% |

结论：这个 c432 实例上核心速度几乎相同，范围重叠，不支持 FAN 明显更快。PODEM 端到端耗时低约 13.75%，FAN 向量数少约 10.34%。仅代表此电路与本组设置。

## 条件

- Intel Core i7-9750H，WSL2 Ubuntu，g++ 15.2.0，两边均为 C++11、-O3。
- 使用同一个二输入门版本的 c432，36 PI、7 PO、288 逻辑门。来源是 fault-reorder/artifacts/backtrack3000/bench-default/c432_binary.bench。
- FAN 输入是该 BENCH 的逐门 Verilog 转写，每个库单元仅有一个逻辑原语，不做额外综合。FAN 的解析器仅实现命名端口连接，因此使用 .A0(...) / .Z(...)。
- 使用 verify_coverage.py，以 1024 个固定随机输入验证该结构与原始 c432.bench 的输出一致。
- 单 stuck-at、1-detect；静态和动态压缩均关闭；X 位填充开启；原生故障排序，不使用 SCOAP 或 RL 排序。
- FAN 使用源代码自带 BACKTRACK_LIMIT=500；PODEM 显式 -bt 500 -seed 0。两边搜索、重试和原生故障排序机制保持各自实现。
- 编译产物放在 Linux 用户主目录，两个原始源码仓库未修改。PODEM 只在复制出来的 main.cpp 中添加 steady_clock 计时，包围 atpg.test()，不修改算法；修改过程在 prepare_build.py 中可查。
- 两边各预热一次，正式交替运行 11 次，取中位数。计时使用 Linux 本地文件，包含故障仿真。核心时间不含输入解析；整次耗时从子进程启动到退出，包含解析、日志、向量输出及 FAN 向量文件写入，不包含编译和 WSL 启动。
- FAN 核心时间来自其原有的 Finished pattern generation 计时。PODEM 核心时间来自新增的 [BENCH] ATPG seconds 标记。

## 覆盖率口径

两个程序原生故障提取不同，不能直接比较其原生覆盖率：FAN 报告全故障 1662、折叠后 1086、96.93%；PODEM 报告全故障 1192、折叠后 616、96.06%。因此额外使用独立位并行故障仿真器，对两个向量集在同一故障集合上重算覆盖率。

统一集合包含所有 PI 与门输出的 stem 故障、所有逻辑门输入 pin 故障，以及 PO 连接 pin 故障，每个位置均有 sa0/sa1，共 1662 个。两组向量均检测到 1611 个。覆盖率核验不计入 ATPG 耗时。原生搜索实际处理的折叠故障列表依然不同，所以这是两个工具完整默认搜索流程在统一电路、相同压缩设置下的对比，不是同一个目标故障序列的纯求解器对比。

## 复现及文件

在 Ubuntu WSL 中执行（需要 g++、make、flex、bison、python3）：

```sh
python3 /mnt/e/桌面/fan-atpg/benchmark_c432_20261120/prepare_build.py
python3 /mnt/e/桌面/fan-atpg/benchmark_c432_20261120/run_benchmark.py
python3 /mnt/e/桌面/fan-atpg/benchmark_c432_20261120/verify_coverage.py
```

环境中原先缺少 flex/bison，本次已安装。

- timings.csv：22 次正式运行的逐次数据。
- summary.json：原始计时和程序原生覆盖率汇总。
- independent_coverage.json：独立统一覆盖率结果。
- FAN_ATPG_0.log / PODEM_0.log：正式运行日志，其余重复也分别保留。
- fan.pat：FAN 输出向量，PODEM 向量包含在其日志的 T'...' 行。
- input_info.json：电路规模、BENCH SHA-256 和 Linux 工作目录。
- prepare_build.py / run_benchmark.py / verify_coverage.py：构建、计时和独立核验脚本。
