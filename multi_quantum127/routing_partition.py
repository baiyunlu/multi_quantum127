"""量子线路逻辑比特分区与拓扑映射模块（由「代码/」项目融合而来）。

把原来命令行脚本里的逻辑比特分区 + 拓扑映射 + 传态代价算法，
封装成可供 Flask 应用直接调用的无副作用函数：

    run_routing(qasm_path, num_partitions=2, target_edges=None, search=False)

流程：
    1. QASM -> 门列表（transformqasm）
    2. 多起点贪心分区 + 门顺序优化，最小化隐形传态次数（codepractice，
       原函数名含 genetic 但实现为贪心多起点，非遗传算法）
    3. 构建分区交互完全图（边权 = 跨分区门数）
    4. 把分区枚举式地单射分配到目标芯片拓扑节点，最小化加权通信代价
    5. 输出分区方案、映射关系、代价，并绘制图保存为 PNG

关于原「代码/」项目的修正说明：
    - 原 main.py 里 `G.edges.items()` 在 networkx 3.x 中不存在（应为 `G.edges(data=True)`）。
    - 原「子图同构匹配」把完整图当作模式图去匹配目标拓扑，既要求目标图包含同规模团，
      又使总代价对所有映射都相等，实际上无法工作；本模块按原代价公式
      （直连 +w，多跳 +w*(10*d+2)）改写成「分区到芯片的单射分配 + 最小化加权距离」，
      这才是原代码想表达的语义。
    - 原远程 swap 优化位于被注释掉的字符串块中，且引用未定义变量，属未完成代码，故未纳入。
    - 原 codepractice.py 顶部未使用的 sklearn 导入已去除，避免新增依赖。
"""

from itertools import combinations, permutations
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")  # 禁用 Tkinter，适配服务器端无显示环境
matplotlib.rcParams["font.family"] = ["SimHei", "Microsoft YaHei", "sans-serif"]
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt

import networkx as nx
from qiskit import QuantumCircuit

import transformqasm
import codepractice


# ---------------------------------------------------------------------------
# 1. QASM 加载
# ---------------------------------------------------------------------------
def load_circuit(qasm_path):
    """读取 QASM 文件，返回 (比特数, 门列表)。"""
    circuit = QuantumCircuit.from_qasm_file(qasm_path)
    num_qubits, gates = transformqasm.generate_qc_list(circuit)
    return num_qubits, gates


# ---------------------------------------------------------------------------
# 2. 多起点贪心分区
# ---------------------------------------------------------------------------
def partition_circuit(qasm_path, num_partitions=2, search=False):
    """对线路逻辑比特做多起点贪心分区（search=True 时做 b1/b2 网格搜索）。

    返回 dict：
        partitions       每个分区的逻辑比特列表 [[q, ...], ...]
        gates            移除单比特门后的门列表
        teleportations   隐形传态次数
        global_gates     跨分区（全局）门数
        qubits           线路涉及的全部逻辑比特
        num_qubits       线路比特总数
        best_b1/best_b2  网格搜索得到的最优参数（仅 search=True 时非空）
    """
    num_qubits, original_gates = load_circuit(qasm_path)
    qubits = codepractice.calculate_qubits(original_gates)
    gates = codepractice.remove_single_qubit_gates(original_gates)

    if not gates or not qubits:
        raise ValueError("线路为空或只有单比特门，无法进行分区")

    if search:
        result, best_b1, best_b2 = codepractice.genetic_multi_partitioning(
            gates, qubits, num_partitions, search=True
        )
    else:
        result = codepractice.genetic_multi_partitioning(
            gates, qubits, num_partitions, search=False
        )
        best_b1, best_b2 = None, None

    if result is None:
        raise ValueError("未能找到有效分区方案")

    partitions, new_gates, teleportations, global_gates = result

    return {
        "partitions": [sorted(p) for p in partitions],
        "gates": new_gates,
        "teleportations": teleportations,
        "global_gates": global_gates,
        "qubits": qubits,
        "num_qubits": num_qubits,
        "best_b1": best_b1,
        "best_b2": best_b2,
    }


# ---------------------------------------------------------------------------
# 3. 分区交互完全图
# ---------------------------------------------------------------------------
def build_interaction_graph(partitions, gates):
    """构建分区交互完全图，边权 = 两分区之间的跨分区门数。"""
    qubit_to_partition = {}
    for pid, part in enumerate(partitions):
        for q in part:
            qubit_to_partition[q] = pid

    edge_costs = defaultdict(int)
    for gate in gates:
        if len(gate) <= 2:
            continue
        qubits = gate[1:]
        pids = {qubit_to_partition[q] for q in qubits}
        if len(pids) == 2:
            i, j = sorted(pids)
            edge_costs[(i, j)] += 1

    num_parts = len(partitions)
    for i, j in combinations(range(num_parts), 2):
        edge_costs[(i, j)] += 0  # 补全零权边，保证是完全图

    G = nx.Graph()
    for i in range(num_parts):
        G.add_node(f"P{i + 1}")
    for (i, j), w in edge_costs.items():
        G.add_edge(f"P{i + 1}", f"P{j + 1}", weight=w)

    return G, dict(edge_costs)


# ---------------------------------------------------------------------------
# 4. 拓扑解析与分区 -> 芯片分配
# ---------------------------------------------------------------------------
def parse_target_topology(edges):
    """把 0 起始的边列表 [(u, v), ...] 转成节点名为 T1..Tn 的图。"""
    target_G = nx.Graph()
    for u, v in edges:
        target_G.add_edge(f"T{u + 1}", f"T{v + 1}")
    return target_G


def match_topology(partitions, edge_costs, target_graph):
    """把每个分区单射地分配到一个芯片，最小化加权通信代价。

    代价沿用原项目的公式：分区 i、j 之间的跨分区门数为 w，
    若两者芯片直接相邻（距离 1）计 w，否则按多跳计 w*(10*d+2)。

    返回 (best_mapping, min_cost)：
        best_mapping  {芯片节点 "Tn": 分区节点 "Pm"}
        min_cost      最优代价
    无法分配（芯片数不足 / 拓扑不连通）时返回 (None, None)。
    """
    n = len(partitions)
    nodes = list(target_graph.nodes())
    m = len(nodes)
    if m < n:
        return None, None

    # 预计算目标图所有点对最短距离
    try:
        lengths = dict(nx.all_pairs_shortest_path_length(target_graph))
    except nx.NetworkXError:
        lengths = {}

    def distance(a, b):
        if a == b:
            return 0
        return lengths.get(a, {}).get(b)

    best_cost = float("inf")
    best_mapping = None

    # 枚举分区到芯片的单射分配：先选 n 个芯片，再对 n 个分区做全排列
    if m == n:
        chip_choices = list(permutations(nodes))
    else:
        chip_choices = []
        for combo in combinations(nodes, n):
            chip_choices.extend(permutations(combo))

    for chips in chip_choices:  # chips[k] = 分配给分区 k 的芯片
        cost = 0.0
        valid = True
        for i in range(n):
            for j in range(i + 1, n):
                w = edge_costs.get((i, j), 0)
                if w == 0:
                    continue
                d = distance(chips[i], chips[j])
                if d is None:
                    valid = False
                    break
                if d == 1:
                    cost += w
                else:
                    cost += w * (10 * d + 2)
            if not valid:
                break

        if valid and cost < best_cost:
            best_cost = cost
            best_mapping = {chips[k]: f"P{k + 1}" for k in range(n)}

    if best_mapping is None:
        return None, None
    return best_mapping, best_cost


# ---------------------------------------------------------------------------
# 5. 可视化（保存 PNG，不弹窗）
# ---------------------------------------------------------------------------
def render_interaction_graph(complete_graph, save_path="partition_graph.png"):
    pos = nx.circular_layout(complete_graph)
    plt.figure(figsize=(7, 6))
    nx.draw(complete_graph, pos, with_labels=True, node_size=900,
            node_color="#00a8ff", font_size=12, font_color="white")
    edge_labels = nx.get_edge_attributes(complete_graph, "weight")
    nx.draw_networkx_edge_labels(complete_graph, pos, edge_labels=edge_labels)
    plt.title("Partition Interaction Graph")
    plt.tight_layout()
    plt.savefig(save_path, dpi=110, bbox_inches="tight")
    plt.close()
    return save_path


def render_mapping(target_graph, mapping, cost, save_path="mapping.png"):
    """在目标拓扑上标注每个芯片承载的分区。mapping: {chip -> partition}。"""
    plt.figure(figsize=(7, 6))
    pos = nx.circular_layout(target_graph)
    labels = {n: f"{n}\n{mapping.get(n, '')}" for n in target_graph.nodes()}
    nx.draw(target_graph, pos, with_labels=False, node_color="#e84118",
            node_size=1100, edge_color="#6c5ce7", width=2)
    nx.draw_networkx_labels(target_graph, pos, labels=labels, font_size=10,
                            font_color="white")
    plt.title(f"Partition -> Chip Mapping (cost={cost})")
    plt.tight_layout()
    plt.savefig(save_path, dpi=110, bbox_inches="tight")
    plt.close()
    return save_path


# ---------------------------------------------------------------------------
# 6. 顶层入口
# ---------------------------------------------------------------------------
def run_routing(qasm_path, num_partitions=2, target_edges=None, search=False):
    """执行完整的分区 + 拓扑映射流程，返回 JSON 可序列化的 dict。"""
    result = partition_circuit(qasm_path, num_partitions=num_partitions, search=search)
    partitions = result["partitions"]
    gates = result["gates"]

    complete_graph, edge_costs = build_interaction_graph(partitions, gates)
    graph_image = render_interaction_graph(complete_graph)

    out = dict(result)
    out["edge_costs"] = {f"{i},{j}": w for (i, j), w in edge_costs.items()}
    out["graph_image"] = graph_image
    out["mapping"] = None
    out["partition_to_chip"] = None
    out["mapping_cost"] = None
    out["mapping_image"] = None

    if target_edges:
        target_graph = parse_target_topology(target_edges)
        mapping, cost = match_topology(partitions, edge_costs, target_graph)
        if mapping is not None:
            partition_to_chip = {part: chip for chip, part in mapping.items()}
            mapping_image = render_mapping(target_graph, mapping, cost)
            out["mapping"] = mapping
            out["partition_to_chip"] = partition_to_chip
            out["mapping_cost"] = cost
            out["mapping_image"] = mapping_image

    return out
