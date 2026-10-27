import json
import os
import time
import random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import networkx as nx
import numpy as np
from qiskit import transpile, QuantumCircuit, QuantumRegister
from qiskit_aer import Aer, AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error, thermal_relaxation_error, ReadoutError, pauli_error
# 修改为 FakeBrisbane
from qiskit_ibm_runtime.fake_provider import FakeBrisbane
import matplotlib
matplotlib.use("Agg") # ✅ 禁用 Tkinter
matplotlib.rcParams['font.family'] = ['SimHei'] # ✅ 中文字体
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import glob

def cleanup_visualizations():
    """删除上一次生成的GIF和PNG可视化文件"""
    patterns = ["*.gif", "*.png"] # 可按需添加其他类型
    for pattern in patterns:
        for filepath in glob.glob(pattern):
            try:
                os.remove(filepath)
                print(f"已删除旧文件: {filepath}")
            except Exception as e:
                print(f"删除失败 {filepath}: {e}")

def animate_partitions(G, partitions, save_path="partitions.gif"):
    """动态展示分区过程，输出 GIF"""
    pos = nx.spring_layout(G, seed=42)
    fig, ax = plt.subplots(figsize=(12, 10)) # 增大图形尺寸以适应更多量子比特
    colors = ["red", "blue", "green", "orange", "purple", "cyan", "magenta", "yellow", "brown", "pink"]
    node_color_map = {n: "lightgray" for n in G.nodes()}
    frames = []
    for i, part in enumerate(partitions):
        for node in part:
            node_color_map[node] = colors[i % len(colors)]
        frames.append(node_color_map.copy())
    def update(frame):
        ax.clear()
        nx.draw(G, pos, ax=ax, node_color=[frame[n] for n in G.nodes()], with_labels=True, node_size=300, font_size=8) # 调整节点大小和字体
        ax.set_title("动态分区过程 - FakeBrisbane")
    ani = animation.FuncAnimation(fig, update, frames=frames, repeat=False)
    ani.save(save_path, writer="pillow", fps=1)
    plt.close()

def animate_mapping(G, layout, partition, circuit_name="", save_path="mapping.gif"):
    """动态展示逻辑比特到物理比特的映射（基于分区），输出 GIF"""
    subG = G.subgraph(partition)
    pos = nx.spring_layout(subG, seed=42)
    fig, ax = plt.subplots(figsize=(8, 6))
    frames = []
    mapped_nodes = set()
    for lq, pq in layout.items():
        if pq in partition:
            mapped_nodes.add(pq)
    frames.append(mapped_nodes.copy())
    def update(frame):
        ax.clear()
        node_colors = ["red" if n in frame else "lightgray" for n in subG.nodes()]
        nx.draw(subG, pos, ax=ax, node_color=node_colors, with_labels=True, node_size=500, font_size=8)
        ax.set_title(f"线路：{circuit_name} | 分区 {sorted(partition)}", fontsize=10)
    ani = animation.FuncAnimation(fig, update, frames=frames, repeat=False)
    ani.save(save_path, writer="pillow", fps=1)
    plt.close()

def plot_results(circuits, psts, depths, save_path="results.png"):
    """静态图表展示结果"""
    fig, ax1 = plt.subplots(figsize=(12, 6))
    names = [c.name for c in circuits]
    ax1.bar(names, psts, alpha=0.7)
    ax1.set_ylabel("PST 值")
    ax1.set_ylim(0, 1)
    for i, d in enumerate(depths):
        ax1.text(i, psts[i] + 0.02, f"depth={d}", ha="center", rotation=45)
    plt.title("并行执行结果 - FakeBrisbane")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(save_path)
    plt.close()

def build_crosstalk_heatmap(G, gamma_file="gamma_zz_hz.json", srb_file="srb_amplification.json"):
    with open(gamma_file, "r") as f:
        gamma_data = json.load(f)
    with open(srb_file, "r") as f:
        srb_data = json.load(f)
    heatmap = {}
    for u, v in G.edges():
        # 归一化ZZ相互作用强度（0-1范围）
        gamma_key = f"{min(u, v)},{max(u, v)}"
        gamma_val = gamma_data.get(gamma_key, gamma_data["default"])
        gamma_norm = gamma_val / gamma_data["default"] # 以默认值为基准
        # 归一化SRB放大系数
        srb_key = f"{u},{v}" if f"{u},{v}" in srb_data else f"{v},{u}"
        srb_val = srb_data.get(srb_key, DEFAULT_SRB_AMP)
        srb_norm = srb_val / DEFAULT_SRB_AMP
        heatmap[(u, v)] = 0.6 * gamma_norm + 0.4 * srb_norm
    return heatmap

# ------------------------------------------------------------

# SRB 并行放大系数字典（从生成的 Brisbane 文件加载）
with open("srb_amplification.json", "r") as _f:
    _srb_amp_raw = json.load(_f)
# 统一转成 tuple-key 方便查询
SRB_AMP_DICT = {tuple(map(int, k.split(","))): v for k, v in _srb_amp_raw.items()}
DEFAULT_SRB_AMP = 1.28 # 若某条 CX 没测到，仍用论文默认值

# ── ZZ-interaction γ_ij (Hz) ───────────────────────────────
with open("gamma_zz_hz.json", "r") as _f:
    _gamma_raw = json.load(_f)
# 单独处理 default
DEFAULT_GAMMA_ZZ_HZ = _gamma_raw.get("default", 15000)
# 其余键才解析为 (ctrl,tgt)
GAMMA_ZZ_HZ_DICT = {
    tuple(sorted(map(int, k.split(",")))): v
    for k, v in _gamma_raw.items() if k != "default"
}

# ── spectator-idle error dictionary ─────────────
with open("idt_error_dict.json", "r") as _f:
    _idt_raw = json.load(_f)
# 解析成 { (driver_pair, spectators_tuple): QuantumError }
IDT_ERROR_DICT = {}
for k, pauli_map in _idt_raw.items():
    driver_str, spectator_str = k.split("->")
    driver = tuple(sorted(eval(driver_str))) # (0,1)
    spectators = tuple(eval(spectator_str)) # (2,) 或 (3,4)
    # 目前每条只给一个 Pauli；若有多项可按需要组合
    for plabel, p in pauli_map.items():
        chan = pauli_error([(plabel, p), ("I" * len(spectators), 1 - p)])
        IDT_ERROR_DICT[(driver, spectators)] = chan

def preprocess_coupling_graph(G, backend, node_percentile=85, edge_percentile=85):
    """预处理耦合图，移除高错误率的节点和边"""
    properties = backend.properties()
    config = backend.configuration()
    print(f"预处理耦合图: {config.n_qubits} 量子比特, {len(config.coupling_map)} 条边")

    # 1. 收集所有节点的读出错误率
    node_errors = {}
    for qubit in range(config.n_qubits):
        try:
            readout_error = properties.readout_error(qubit)
            node_errors[qubit] = readout_error
        except:
            node_errors[qubit] = 1.0
            print(f"节点 {qubit}: 读出错误率无法获取，设置为 1.0")

    # 2. 收集所有边的两量子比特门错误率 - 注意 Brisbane 使用 ecr 门
    edge_errors = {}
    for u, v in config.coupling_map:
        try:
            # 首先尝试获取 ecr 门错误率
            gate_error = properties.gate_error('ecr', [u, v])
            edge_errors[(u, v)] = gate_error
        except:
            try:
                # 如果 ecr 不存在，尝试 cx
                gate_error = properties.gate_error('cx', [u, v])
                edge_errors[(u, v)] = gate_error
            except:
                edge_errors[(u, v)] = 1.0
                print(f"边 ({u},{v}): 门错误率无法获取，设置为 1.0")

    # 3. 计算分位数阈值 - 对于 Brisbane 使用更宽松的阈值
    if node_errors:
        node_threshold = np.percentile(list(node_errors.values()), node_percentile)
    else:
        node_threshold = 0.1
    if edge_errors:
        edge_threshold = np.percentile(list(edge_errors.values()), edge_percentile)
    else:
        edge_threshold = 0.1
    print(f"节点错误率阈值: {node_threshold:.4f}")
    print(f"边错误率阈值: {edge_threshold:.4f}")

    # 4. 标记高错误率的节点和边
    high_error_nodes = set()
    high_error_edges = set()
    for node, error in node_errors.items():
        if error >= node_threshold:
            high_error_nodes.add(node)
    for edge, error in edge_errors.items():
        if error >= edge_threshold:
            high_error_edges.add(edge)
    print(f"找到 {len(high_error_nodes)} 个高错误率节点")
    print(f"找到 {len(high_error_edges)} 个高错误率边")

    # 5. 创建过滤后的耦合图
    filtered_G = G.copy()
    # 移除高错误率的节点（及其相连的边）
    filtered_G.remove_nodes_from(high_error_nodes)
    # 移除高错误率的边
    for u, v in high_error_edges:
        if filtered_G.has_edge(u, v):
            filtered_G.remove_edge(u, v)
    print(f"过滤后: {filtered_G.number_of_nodes()} 节点, {filtered_G.number_of_edges()} 边")
    return filtered_G

def load_qasm_circuits(qasm_dir, selected_files=None):
    """加载QASM文件并提取线路特征（新增交互频率统计）"""
    circuits = []
    for filename in os.listdir(qasm_dir):
        if filename.endswith(".qasm") and (selected_files is None or filename in selected_files):
            try:
                filepath = os.path.join(qasm_dir, filename)
                qc = QuantumCircuit.from_qasm_file(filepath)
                qc.name = filename
                # 提取线路特征
                qc.depth = qc.depth()
                # 统计所有两量子比特门（包括 cx 和 ecr）
                qc.original_cx_count = sum(1 for inst in qc.data if inst.operation.name in ['cx', 'ecr'])
                qc.cx_count = qc.original_cx_count
                qc.cx_density = qc.cx_count / qc.num_qubits if qc.num_qubits > 0 else 0
                # 新增：统计逻辑量子比特交互频率
                interaction_count = defaultdict(int)
                for inst in qc.data:
                    if inst.operation.name in ['cx', 'ecr']: # 包括 ecr 门
                        q0 = inst.qubits[0]._index
                        q1 = inst.qubits[1]._index
                        interaction_count[(min(q0, q1), max(q0, q1))] += 1
                # 构建逻辑交互图
                qc.interaction_graph = nx.Graph()
                for (u, v), count in interaction_count.items():
                    qc.interaction_graph.add_edge(u, v, weight=count)
                circuits.append(qc)
                print(
                    f"加载: {filename}, 深度: {qc.depth}, 原始两量子比特门数: {qc.original_cx_count}, 门密度: {qc.cx_density:.2f}")
            except Exception as e:
                print(f"加载失败 {filename}: {str(e)}")
    return circuits

def get_partition_coupling_map(G, partition):
    """提取分区的耦合图"""
    subgraph = G.subgraph(partition)
    coupling_map = []
    for u, v in subgraph.edges():
        coupling_map.append([u, v])
        coupling_map.append([v, u]) # 双向耦合
    return coupling_map

# ==================== 新增/重写的算法核心部分 ====================
def evaluate_partition_quality(G, partitions):
    """
    论文中的分区方案总体质量函数。
    """
    if not partitions:
        return 0.0

    total_quality = 0.0
    crosstalk_heatmap = build_crosstalk_heatmap(G)

    # 1. 内部凝聚力
    for part in partitions:
        subgraph = G.subgraph(part)
        if not nx.is_connected(subgraph):
            return 0.0  # 不连通分区质量为0

        # 边质量: 基于 improved_weight
        internal_edges = list(subgraph.edges(data=True))
        if internal_edges:
            max_improved_weight = max(d['improved_weight'] for _, _, d in internal_edges)
            edge_quality = sum(1 - d['improved_weight'] / max_improved_weight for _, _, d in internal_edges)
        else:
            edge_quality = 0.0

        # 节点质量: 基于 fidelity
        node_quality = sum(G.nodes[n]['fidelity'] for n in part)

        # 拓扑惩罚: 基于直径和平均最短路径
        D = nx.diameter(subgraph)
        L_avg = nx.average_shortest_path_length(subgraph) if subgraph.number_of_nodes() > 1 else 1
        topology_penalty = (D * len(part)) / L_avg if L_avg != 0 else float('inf')

        cohesion = (edge_quality + node_quality) / (topology_penalty + 1e-9) # 避免除零
        total_quality += cohesion

    # 2. 分区间隔离度 (分离度)
    separation = 0.0
    if len(partitions) > 1:
        total_crosstalk = 0.0
        for i in range(len(partitions)):
            for j in range(i + 1, len(partitions)):
                cut_edges = list(nx.edge_boundary(G, partitions[i], partitions[j]))
                if cut_edges:
                    crosstalk_sum = sum(crosstalk_heatmap.get((min(u, v), max(u, v)), 0) for u, v in cut_edges)
                    total_crosstalk += crosstalk_sum
        max_possible_crosstalk = sum(crosstalk_heatmap.values())
        separation = 1 - (total_crosstalk / max_possible_crosstalk) if max_possible_crosstalk > 0 else 1.0

    alpha, beta = 0.5, 0.5
    quality = alpha * total_quality + beta * separation
    return quality

def dynamic_partition_disconnected(G, circuits=None):
    """
    论文算法1: 动态分区算法。
    """
    components = list(nx.connected_components(G))
    print(f"\n找到 {len(components)} 个连通分量")

    all_partitions = []
    min_size = 5  # 论文中的 MIN_SIZE
    delta_q0 = 1e-6  # 终止条件阈值 ΔQ0
    limit = 5  # TopEdges 的数量 LIMIT

    for component in components:
        if len(component) < min_size:
            all_partitions.append(component)
            continue

        subgraph = G.subgraph(component)
        current_partitions = [set(subgraph.nodes)]
        improvement = True

        while improvement:
            best_gain = 0.0
            best_new_partitions = current_partitions.copy()

            for idx, part in enumerate(current_partitions):
                if len(part) < 2 * min_size:
                    continue

                subgraph_part = subgraph.subgraph(part)
                # 构建基于 'improved_weight' 的 MST
                mst = nx.minimum_spanning_tree(subgraph_part, weight='improved_weight')
                # 获取MST中权重最高的若干条边 (根据论文定理1)
                candidate_edges = sorted(
                    mst.edges(data=True),
                    key=lambda x: x[2]['improved_weight'],
                    reverse=True
                )[:limit]

                for u, v, d in candidate_edges:
                    temp_mst = mst.copy()
                    temp_mst.remove_edge(u, v)
                    new_parts = list(nx.connected_components(temp_mst))

                    # 检查新分区大小是否满足 min_size
                    if any(len(p) < min_size for p in new_parts):
                        continue

                    # 构建新的分区方案
                    temp_partitions = current_partitions.copy()
                    temp_partitions.pop(idx)
                    temp_partitions.extend(new_parts)

                    # 计算质量增益
                    old_quality = evaluate_partition_quality(subgraph, [part])
                    new_quality = evaluate_partition_quality(subgraph, new_parts)
                    gain = new_quality - old_quality

                    if gain > best_gain:
                        best_gain = gain
                        best_new_partitions = temp_partitions

            if best_gain > delta_q0:
                current_partitions = best_new_partitions
            else:
                improvement = False

        all_partitions.extend(current_partitions)

    return all_partitions

def merge_partitions_for_circuit(circuit, available_partitions, used_qubits, G_full):
    """
    论文算法2中的 MergePartitions 子过程。
    尝试合并邻近的未使用分区以满足线路需求。
    """
    needed_qubits = circuit.num_qubits
    available_qubits = set()
    for p in available_partitions:
        available_qubits.update(p)
    available_qubits -= used_qubits

    if len(available_qubits) < needed_qubits:
        return None  # 总可用量子比特不足

    # 构建可用分区的邻接图
    partition_graph = nx.Graph()
    for i, p1 in enumerate(available_partitions):
        for j, p2 in enumerate(available_partitions):
            if i >= j:
                continue
            # 检查两个分区在完整图G_full中是否相邻
            if any(G_full.has_edge(n1, n2) for n1 in p1 for n2 in p2):
                partition_graph.add_edge(i, j)

    # 尝试通过BFS/DFS找到一组连通的分区，其总大小足够
    for start_idx in range(len(available_partitions)):
        visited = set()
        queue = [(start_idx, available_partitions[start_idx].copy())]
        while queue:
            current_idx, merged_set = queue.pop(0)
            if len(merged_set) >= needed_qubits:
                # 检查合并后的集合在G_full中是否连通
                merged_subgraph = G_full.subgraph(merged_set)
                if nx.is_connected(merged_subgraph):
                    # 成功找到，返回新的分区列表
                    new_partitions = [p for i, p in enumerate(available_partitions) if i not in visited]
                    new_partitions.append(merged_set)
                    return new_partitions
            visited.add(current_idx)
            for neighbor_idx in partition_graph.neighbors(current_idx):
                if neighbor_idx not in visited:
                    new_merged_set = merged_set.union(available_partitions[neighbor_idx])
                    queue.append((neighbor_idx, new_merged_set))

    return None  # 无法找到合适的合并方案

def generate_initial_layout_greedy(circuit, partition, G):
    """
    论文3.2.1节: 交互感知的贪心启发式初始布局。
    """
    num_qubits_needed = circuit.num_qubits
    partition_qubits = list(partition)
    if len(partition_qubits) < num_qubits_needed:
        return None

    physical_subgraph = G.subgraph(partition_qubits)
    layout = {}
    used_physical_qubits = set()

    # 1. 识别核心逻辑量子比特 (按交互总次数+度排序)
    logical_degrees = {}
    for lq in range(num_qubits_needed):
        total_weight = 0
        degree = 0
        if hasattr(circuit, 'interaction_graph'):
            neighbors = list(circuit.interaction_graph.neighbors(lq))
            degree = len(neighbors)
            for n in neighbors:
                total_weight += circuit.interaction_graph[lq][n].get('weight', 1)
        logical_degrees[lq] = (total_weight, degree)

    sorted_logical = sorted(logical_degrees.keys(), key=lambda x: logical_degrees[x], reverse=True)

    # 2. 确定核心物理量子比特 (分区内度最高且保真度最高)
    physical_degrees = {pq: physical_subgraph.degree(pq) for pq in partition_qubits}
    max_degree = max(physical_degrees.values())
    candidates = [pq for pq, deg in physical_degrees.items() if deg == max_degree]
    if len(candidates) > 1:
        # 选择保真度最高的
        best_pq = max(candidates, key=lambda pq: G.nodes[pq]['fidelity'])
    else:
        best_pq = candidates[0]

    # 3. 分层贪心扩展
    layout[sorted_logical[0]] = best_pq
    used_physical_qubits.add(best_pq)

    for lq in sorted_logical[1:]:
        # 找到与lq交互最多的已映射逻辑比特
        best_mapped_lq = None
        max_interaction = -1
        for mapped_lq in layout:
            if circuit.interaction_graph.has_edge(lq, mapped_lq):
                weight = circuit.interaction_graph[lq][mapped_lq].get('weight', 1)
                if weight > max_interaction:
                    max_interaction = weight
                    best_mapped_lq = mapped_lq

        candidate_physical = set()
        if best_mapped_lq is not None:
            mapped_pq = layout[best_mapped_lq]
            # 第一层：种子比特的未占用邻居
            for neighbor in physical_subgraph.neighbors(mapped_pq):
                if neighbor in partition_qubits and neighbor not in used_physical_qubits:
                    candidate_physical.add(neighbor)

        if not candidate_physical:
            # 第二层：已分配区域中未占用的邻居
            for used_pq in used_physical_qubits:
                for neighbor in physical_subgraph.neighbors(used_pq):
                    if neighbor in partition_qubits and neighbor not in used_physical_qubits:
                        candidate_physical.add(neighbor)

        if not candidate_physical:
            # 最后手段：任意未使用的物理比特
            remaining = set(partition_qubits) - used_physical_qubits
            if remaining:
                candidate_physical = remaining
            else:
                return None  # 无可用物理比特

        # 从候选者中选择综合保真度最高的
        best_candidate = max(candidate_physical, key=lambda pq: G.nodes[pq]['fidelity'])
        layout[lq] = best_candidate
        used_physical_qubits.add(best_candidate)

    # 最终检查连通性
    mapped_physical = list(layout.values())
    if len(mapped_physical) > 1:
        mapped_subgraph = G.subgraph(mapped_physical)
        if not nx.is_connected(mapped_subgraph):
            return None

    return layout

def calculate_mapping_cost(layout, circuit, G, w_dist, w_fid):
    """
    论文3.2.2节: 多目标代价函数。
    """
    cost = 0.0
    # 距离成本 (减少SWAP)
    if hasattr(circuit, 'interaction_graph'):
        for lq1, lq2, data in circuit.interaction_graph.edges(data=True):
            if lq1 in layout and lq2 in layout:
                pq1, pq2 = layout[lq1], layout[lq2]
                try:
                    dist = nx.shortest_path_length(G, pq1, pq2)
                    cost += w_dist * dist * data.get('weight', 1)
                except nx.NetworkXNoPath:
                    cost += w_dist * 1000  # 惩罚不连通

    # 保真度成本 (提高保真度)
    fid_cost = sum(G.nodes[pq]['fidelity'] for pq in layout.values())
    cost += w_fid * (len(layout) - fid_cost)  # 最小化 (N - sum_fidelity)

    return cost

def simulated_annealing_optimize(initial_layout, circuit, partition, G, max_iter=1000, T0=100.0, alpha=0.95):
    """
    论文3.2.2节: 动态加权的模拟退火全局优化。
    """
    current_layout = initial_layout.copy()
    best_layout = initial_layout.copy()
    current_cost = calculate_mapping_cost(current_layout, circuit, G, w_dist=0.7, w_fid=0.3) # 初始权重
    best_cost = current_cost
    T = T0

    # 动态权重参数
    w_dist_base, w_fid_base = 0.7, 0.3
    partition_qubits = list(partition)

    for iteration in range(max_iter):
        if T < 1e-3:
            break

        # 动态调整权重：初期重距离，后期重保真度
        progress = iteration / max_iter
        w_dist = w_dist_base * (1 - progress) + w_fid_base * progress
        w_fid = w_fid_base * (1 - progress) + w_dist_base * progress

        # 生成新候选解：随机交换两个逻辑比特的物理位置
        lq_list = list(current_layout.keys())
        if len(lq_list) < 2:
            break
        lq_a, lq_b = random.sample(lq_list, 2)
        new_layout = current_layout.copy()
        new_layout[lq_a], new_layout[lq_b] = new_layout[lq_b], new_layout[lq_a]

        # 确保新布局仍在分区内
        if not all(pq in partition for pq in new_layout.values()):
            T *= alpha
            continue

        # 检查连通性（可选，为了效率可以省略，由代价函数惩罚）
        # mapped_physical = list(new_layout.values())
        # if len(mapped_physical) > 1:
        #     mapped_subgraph = G.subgraph(mapped_physical)
        #     if not nx.is_connected(mapped_subgraph):
        #         T *= alpha
        #         continue

        new_cost = calculate_mapping_cost(new_layout, circuit, G, w_dist, w_fid)
        delta_E = new_cost - current_cost

        if delta_E < 0 or random.random() < np.exp(-delta_E / T):
            current_layout = new_layout
            current_cost = new_cost
            if current_cost < best_cost:
                best_layout = current_layout.copy()
                best_cost = current_cost

        T *= alpha

    return best_layout

def adaptive_mapping(circuit, partition, G, THRESH=4):
    """
    论文算法3: 自适应映射算法。
    """
    num_qubits = circuit.num_qubits
    if num_qubits <= THRESH:
        # 对于小线路，此处简化为直接使用贪心，实际可实现精确搜索
        layout = generate_initial_layout_greedy(circuit, partition, G)
        return layout, partition, 0.0 if layout is None else sum(G.nodes[p]['fidelity'] for p in layout.values())
    else:
        # 1. 生成贪心初始布局
        initial_layout = generate_initial_layout_greedy(circuit, partition, G)
        if initial_layout is None:
            return None, None, 0.0

        # 2. 模拟退火全局优化
        optimized_layout = simulated_annealing_optimize(initial_layout, circuit, partition, G)

        final_score = sum(G.nodes[p]['fidelity'] for p in optimized_layout.values())
        return optimized_layout, partition, final_score

def allocate_resources(circuits, partitions, G):
    """
    论文算法2: 资源分配算法。
    """
    used_qubits = set()
    allocations = []
    current_partitions = [set(p) for p in partitions]  # 转为set方便操作
    t_max = 2  # 最大尝试次数

    # 1. 按 CNOT 密度降序排序 (优先级队列)
    circuits_sorted = sorted(circuits, key=lambda x: x.cx_density, reverse=True)

    for circuit in circuits_sorted:
        print(f"\n尝试为线路 {circuit.name} 分配资源 (需要 {circuit.num_qubits} 量子比特):")
        success = False
        t = 1
        local_partitions = current_partitions.copy()

        while t <= t_max and not success:
            best_layout = None
            best_partition = None
            best_score = -1

            for partition in local_partitions:
                available_qubits_in_partition = set(partition) - used_qubits
                if len(available_qubits_in_partition) < circuit.num_qubits:
                    continue

                # 检查可用子图连通性
                if len(available_qubits_in_partition) > 1:
                    available_subgraph = G.subgraph(available_qubits_in_partition)
                    if not nx.is_connected(available_subgraph):
                        # 尝试找最大连通分量
                        largest_comp = max(nx.connected_components(available_subgraph), key=len)
                        if len(largest_comp) < circuit.num_qubits:
                            continue
                        available_qubits_in_partition = largest_comp

                # 尝试映射
                layout, _, score = adaptive_mapping(circuit, available_qubits_in_partition, G)
                if layout is not None:
                    current_mapped_physicals = set(layout.values())
                    if not current_mapped_physicals.intersection(used_qubits):
                        if score > best_score:
                            best_score = score
                            best_layout = layout
                            best_partition = partition

            if best_layout is not None:
                final_used_physicals = set(best_layout.values())
                if not final_used_physicals.intersection(used_qubits):
                    mapped_subgraph = G.subgraph(final_used_physicals)
                    if len(final_used_physicals) <= 1 or nx.is_connected(mapped_subgraph):
                        allocations.append((circuit, best_layout, best_partition))
                        used_qubits.update(final_used_physicals)
                        # 从当前分区列表中移除已使用的分区
                        current_partitions = [p for p in current_partitions if p != best_partition]
                        success = True
                        print(f"\n线路 {circuit.name} 资源分配成功:")
                        print(f" 分配到分区: {sorted(best_partition)}")
                        print(f" 物理布局: {best_layout}")
                        print(f" 实际使用量子比特: {sorted(final_used_physicals)}")
            else:
                if t < t_max:
                    # 触发按需动态分区合并
                    merged_partitions = merge_partitions_for_circuit(circuit, local_partitions, used_qubits, G)
                    if merged_partitions is not None:
                        local_partitions = merged_partitions
                        print(f"  第{t}次分配失败，尝试合并分区...")
                    else:
                        print(f"  第{t}次分配失败，无法合并分区。")
                        break
                else:
                    print(f"\n分配失败: 线路 {circuit.name} 在 {t_max} 次尝试后仍无法分配。")

            t += 1

    return allocations

# ==================== 以下部分保持不变 ====================
def create_parallel_error_model(backend):
    """创建优化的并行门错误增强噪声模型，并根据Ref[4]计算ZZ串扰概率（针对每个两量子比特门动态计算）"""
    noise_model = NoiseModel()
    properties = backend.properties()
    config = backend.configuration()

    # 从后端属性提取每个两量子比特门对的门时间
    two_qubit_gate_times = {}  # 存储 (control_idx, target_idx) -> gate_time (秒)
    # Brisbane 使用 ecr 门，但我们也支持 cx 门
    two_qubit_gate_names = ['ecr', 'cx']
    for gate_name in two_qubit_gate_names:
        if hasattr(properties, 'gates'):
            for gate_prop in properties.gates:
                if gate_prop.gate == gate_name:
                    qubits_list = gate_prop.qubits  # [control, target]
                    qubits_tuple_key = tuple(qubits_list)
                    try:
                        actual_gate_time_sec = properties.gate_length(gate_name, qubits_list)
                        if actual_gate_time_sec is not None and actual_gate_time_sec > 0:
                            two_qubit_gate_times[qubits_tuple_key] = actual_gate_time_sec
                        else:
                            print(f"WARNING: {gate_name} gate time for {qubits_tuple_key} is invalid: {actual_gate_time_sec}")
                    except Exception as e:
                        print(f"WARNING: Failed to get gate_length for {gate_name} {qubits_tuple_key}: {e}")

    all_valid_times = [t for t in two_qubit_gate_times.values() if t > 0]
    fallback_t_gate = 400e-9  # 默认 400 ns
    if all_valid_times:
        avg_time = sum(all_valid_times) / len(all_valid_times)
        if 100e-9 < avg_time < 1000e-9:
            fallback_t_gate = avg_time

    # 1. 添加读取错误
    for qubit in range(config.n_qubits):
        try:
            readout_error = properties.readout_error(qubit)
            if readout_error is not None and 0 <= readout_error <= 1:
                noise_model.add_readout_error(
                    ReadoutError([[1 - readout_error, readout_error], [readout_error, 1 - readout_error]]),
                    [qubit]
                )
        except Exception as e:
            print(f"Failed to add readout error for qubit {qubit}: {e}")

    # 2. 单量子位门错误
    single_qubit_gates = ['x', 'y', 'z', 'h', 's', 't', 'rx', 'ry', 'rz', 'u1', 'u2', 'u3']
    for qubit in range(config.n_qubits):
        for gate_name in single_qubit_gates:
            try:
                error_rate = properties.gate_error(gate_name, [qubit])
                if error_rate is not None and 0 < error_rate < 1:
                    # 使用去极化噪声近似
                    depol_error = depolarizing_error(error_rate, 1)
                    noise_model.add_quantum_error(depol_error, gate_name, [qubit])
            except:
                continue  # 跳过不支持的门

    # 3. 两量子位门错误（含串扰增强）
    for u, v in config.coupling_map:
        # 确定实际使用的门类型（Brisbane 主要用 ecr）
        gate_name = 'ecr'
        try:
            base_error = properties.gate_error(gate_name, [u, v])
        except:
            try:
                gate_name = 'cx'
                base_error = properties.gate_error(gate_name, [u, v])
            except:
                print(f"Skipping edge ({u},{v}): no valid two-qubit gate")
                continue

        if base_error is None or not (0 < base_error < 1):
            continue

        # 获取门时间
        gate_time = two_qubit_gate_times.get((u, v), fallback_t_gate)

        # 计算 ZZ 串扰增强因子
        zz_pair = tuple(sorted([u, v]))
        gamma_zz = GAMMA_ZZ_HZ_DICT.get(zz_pair, DEFAULT_GAMMA_ZZ_HZ)
        # 根据 Ref[4]: P_zz ≈ (γ_zz * t_gate)^2 / 2
        p_zz = min(0.5, (gamma_zz * gate_time) ** 2 / 2.0)
        srb_amp = SRB_AMP_DICT.get((u, v), SRB_AMP_DICT.get((v, u), DEFAULT_SRB_AMP))
        enhanced_error = min(0.99, base_error * srb_amp + p_zz)

        # 添加去极化错误
        depol_error = depolarizing_error(enhanced_error, 2)
        noise_model.add_quantum_error(depol_error, gate_name, [u, v])

        # 添加旁观者空闲错误（spectator idle error）
        all_qubits = set(range(config.n_qubits))
        neighbors = set(G_full.neighbors(u)) | set(G_full.neighbors(v)) if 'G_full' in globals() else set()
        spectators = list(neighbors - {u, v})
        if spectators and (tuple(sorted([u, v])), tuple(spectators)) in IDT_ERROR_DICT:
            idt_error = IDT_ERROR_DICT[(tuple(sorted([u, v])), tuple(spectators))]
            # 注意：Qiskit 噪声模型对多体错误支持有限，此处简化为忽略或警告
            # 实际可考虑将旁观者错误作为独立的 idle 错误添加（需更复杂处理）
            pass  # 暂不实现，避免复杂性

    return noise_model

def calculate_parallel_pst(circuits, backend, layouts, partitions, G):
    """计算并行执行时的各个线路的PST值"""
    seed = int(time.time())
    ideal_results = []  # 存储每个量子线路的理想结果（即无噪声情况下的正确输出）
    noisy_counts_list = []  # 存储每个量子线路在噪声情况下的执行结果
    individual_psts = []  # 存储每个线路的PST值
    mapped_depths = []  # 存储映射后的线路深度

    # 1. 获取每个线路的理想结果
    ideal_sim = Aer.get_backend('qasm_simulator')
    for circuit in circuits:
        try:
            ideal_circuit = transpile(circuit, backend=ideal_sim)
            ideal_result = ideal_sim.run(ideal_circuit, shots=8192, seed_simulator=seed).result()
            ideal_counts = ideal_result.get_counts(ideal_circuit)
            if not ideal_counts:
                print(f"警告：线路 {circuit.name} 的理想结果为空，跳过")
                return [0.0] * len(circuits), [0] * len(circuits)
            correct_outcome = max(ideal_counts, key=lambda k: ideal_counts[k])
            ideal_results.append(correct_outcome)
        except Exception as e:
            print(f"计算线路 {circuit.name} 的理想结果时出错: {str(e)}")
            return [0.0] * len(circuits), [0] * len(circuits)

    # 2. 定义一个内部函数，在噪声环境下并行执行所有量子线路，并收集噪声结果
    def run_circuit(circuit, layout, partition, G):

        try:
            qreg = QuantumRegister(circuit.num_qubits, 'q')
            initial_layout = {qreg[i]: layout[i] for i in range(circuit.num_qubits)}
            coupling_map = get_partition_coupling_map(G, partition)

            noisy_circuit = transpile(
                circuit,
                backend=backend,
                initial_layout=initial_layout,
                coupling_map=coupling_map,
                routing_method='sabre',
                seed_transpiler=seed,
                optimization_level=0
            )

            # 统计映射后的两量子比特门数和深度
            mapped_two_qubit_count = sum(1 for inst in noisy_circuit.data if inst.operation.name in ['cx', 'ecr'])
            two_qubit_increase = mapped_two_qubit_count - circuit.original_cx_count
            mapped_depth = noisy_circuit.depth()

            print(
                f"线路 {circuit.name} 两量子比特门统计 - 原始: {circuit.original_cx_count}, 映射后: {mapped_two_qubit_count}, 增加: {two_qubit_increase}")

            job = backend.run(noisy_circuit, shots=8192, seed_simulator=seed)
            noisy_result = job.result()
            noisy_counts = noisy_result.get_counts(noisy_circuit)

            return noisy_counts, mapped_depth
        except Exception as e:
            print(f"执行线路 {circuit.name} 时出错: {str(e)}")
            return None, 0

    # 使用线程池并行执行所有量子线路
    with ThreadPoolExecutor(max_workers=len(circuits)) as executor:
        futures = []
        for circuit, layout, partition in zip(circuits, layouts, partitions):
            futures.append(executor.submit(run_circuit, circuit, layout, partition, G))

        for future in futures:
            result = future.result()
            if result[0] is not None:
                noisy_counts_list.append(result[0])
                mapped_depths.append(result[1])
            else:
                return [0.0] * len(circuits), [0] * len(circuits)

    # 3. 检查结果一致性
    if len(ideal_results) != len(noisy_counts_list):
        print(f"错误：理想结果数 ({len(ideal_results)}) 和噪声结果数 ({len(noisy_counts_list)}) 不一致")
        return [0.0] * len(circuits), [0] * len(circuits)

    # 4. 计算每个线路的PST值
    for j in range(len(ideal_results)):
        correct_outcome = ideal_results[j]
        noisy_counts = noisy_counts_list[j]
        success_count = noisy_counts.get(correct_outcome, 0)
        individual_pst = success_count / 8192
        individual_psts.append(individual_pst)

    return individual_psts, mapped_depths


def build_coupling_graph_from_backend(backend):
    """从后端构建耦合图并添加串扰噪声参数"""
    G = nx.Graph()
    config = backend.configuration()
    properties = backend.properties()

    # 基础错误率
    for qubit in range(config.n_qubits):
        readout_error = properties.readout_error(qubit)
        G.add_node(qubit, readout_error=readout_error)

    # 添加基础两量子比特门错误和串扰增强
    for u, v in config.coupling_map:
        # 优先使用 ecr 门错误率，如果没有则使用 cx
        try:
            gate_error = properties.gate_error('ecr', [u, v])
        except:
            try:
                gate_error = properties.gate_error('cx', [u, v])
            except:
                gate_error = 0.01  # 默认值

        enhanced_error = min(gate_error * 1.5, 1.0)  # 增强串扰效应
        G.add_edge(u, v, weight=enhanced_error)
        G.add_edge(v, u, weight=enhanced_error)

    return G


def compute_metrics(G):
    num_nodes = G.number_of_nodes()
    for node in G.nodes:
        # 计算连通性指标
        connectivity = G.degree(node) / (num_nodes - 1) if num_nodes > 1 else 0
        G.nodes[node]['connectivity'] = connectivity

    for node in G.nodes:
        readout_error = G.nodes[node]['readout_error']

        # 计算平均两量子比特门错误率
        gate_errors = [d['weight'] for u, v, d in G.edges(node, data=True)]
        avg_gate_error = sum(gate_errors) / len(gate_errors) if gate_errors else 0

        alpha, beta, gamma = 0.1, 0.1, 0.8  # 权重系数
        fidelity = (alpha * (1 - readout_error) +
                    beta * (1 - avg_gate_error) +
                    gamma * G.nodes[node]['connectivity'])
        G.nodes[node]['fidelity'] = fidelity

    edge_errors = [d['weight'] for _, _, d in G.edges(data=True)]
    max_edge_error = max(edge_errors)
    min_edge_error = min(edge_errors)

    node_fidelities = [d['fidelity'] for n, d in G.nodes(data=True)]
    max_fidelity = max(node_fidelities)
    min_fidelity = min(node_fidelities)

    for u, v, d in G.edges(data=True):
        normalized_edge = 1 - (d['weight'] - min_edge_error) / (max_edge_error - min_edge_error)

        node_u = (G.nodes[u]['fidelity'] - min_fidelity) / (max_fidelity - min_fidelity)
        node_v = (G.nodes[v]['fidelity'] - min_fidelity) / (max_fidelity - min_fidelity)
        normalized_node = (node_u + node_v) / 2

        d['improved_weight'] = (1 - normalized_edge) + (1 - normalized_node)

    return G


def partition_quality(G, partitions):
    total_quality = 0
    crosstalk_heatmap = build_crosstalk_heatmap(G)

    for part in partitions:
        subgraph = G.subgraph(part)
        if not nx.is_connected(subgraph):
            return 0

        internal_edges = subgraph.edges(data=True)
        max_improved_weight = max(d['improved_weight'] for _, _, d in internal_edges) if internal_edges else 1
        edge_quality = sum(1 - d['improved_weight'] / max_improved_weight for _, _, d in internal_edges)
        node_quality = sum(G.nodes[n]['fidelity'] for n in part)
        D = nx.diameter(subgraph)
        L_avg = nx.average_shortest_path_length(subgraph) if subgraph.number_of_nodes() > 1 else 1
        topology_penalty = (D * len(part)) / L_avg if L_avg != 0 else float('inf')
        cohesion = (edge_quality + node_quality) / topology_penalty
        total_quality += cohesion

    separation = 0
    if len(partitions) > 1:
        total_crosstalk = 0
        for i in range(len(partitions)):
            for j in range(i + 1, len(partitions)):
                cut_edges = list(nx.edge_boundary(G, partitions[i], partitions[j]))
                if cut_edges:
                    crosstalk_sum = sum(crosstalk_heatmap.get((min(u, v), max(u, v)), 0) for u, v in cut_edges)
                    total_crosstalk += crosstalk_sum

        max_possible_crosstalk = sum(crosstalk_heatmap.values())
        separation = 1 - (total_crosstalk / max_possible_crosstalk) if max_possible_crosstalk > 0 else 1

    alpha, beta = 0.5, 0.5
    quality = alpha * total_quality + beta * separation
    return quality


def evaluate_partition_connectivity(partition, G):
    """评估分区的连通性质量"""
    subgraph = G.subgraph(partition)
    if not nx.is_connected(subgraph):
        return 0.0

    # 计算平均节点度数
    avg_degree = sum(dict(subgraph.degree()).values()) / len(partition)
    # 计算连通子图的直径
    diameter = nx.diameter(subgraph)
    # 分区连通性得分 (越高越好)
    conn_score = avg_degree / (diameter + 1)  # 加1避免除零错误
    return conn_score


def dynamic_partition_disconnected(G, circuits=None):
    components = list(nx.connected_components(G))
    print(f"\n找到 {len(components)} 个连通分量")
    crosstalk_heatmap = build_crosstalk_heatmap(G)

    all_partitions = []
    for component in components:
        if len(component) < 5:
            all_partitions.append(component)
            continue

        subgraph = G.subgraph(component)
        current_partitions = [set(subgraph.nodes)]
        current_quality = partition_quality(subgraph, current_partitions)
        current_connectivity = evaluate_partition_connectivity(current_partitions[0], subgraph)

        min_size = max(5, int(5 + 5 * sum(c.cx_density for c in circuits) / len(circuits)) if circuits else 5)

        while True:
            best_gain = 0
            best_new_partitions = current_partitions.copy()
            best_new_connectivity = current_connectivity

            for idx, part in enumerate(current_partitions):
                if len(part) < 2 * min_size:
                    continue

                subgraph_part = subgraph.subgraph(part)
                mst = nx.minimum_spanning_tree(subgraph_part, weight='improved_weight')

                candidate_edges = sorted(
                    mst.edges(data=True),
                    key=lambda x: crosstalk_heatmap.get((min(x[0], x[1]), max(x[0], x[1])), 0) * x[2][
                        'improved_weight'],
                    reverse=True
                )

                for u, v, d in candidate_edges[:5]:
                    temp_mst = mst.copy()
                    temp_mst.remove_edge(u, v)
                    new_parts = list(nx.connected_components(temp_mst))

                    if any(len(p) < min_size for p in new_parts):
                        continue

                    avg_conn = sum(evaluate_partition_connectivity(p, subgraph) for p in new_parts) / len(new_parts)
                    if avg_conn < current_connectivity * 0.7:
                        continue

                    temp_partitions = current_partitions.copy()
                    temp_partitions.pop(idx)
                    temp_partitions.extend(new_parts)
                    new_quality = partition_quality(subgraph, temp_partitions)

                    conn_weight = 0.3
                    quality_gain = new_quality - current_quality + conn_weight * (avg_conn - current_connectivity)

                    if quality_gain > best_gain:
                        best_gain = quality_gain
                        best_new_partitions = temp_partitions
                        best_new_connectivity = avg_conn

            if best_gain > 0:
                current_partitions = best_new_partitions
                current_quality += best_gain
                current_connectivity = best_new_connectivity
            else:
                break

        all_partitions.extend(current_partitions)

    return all_partitions


def allocate_resources(circuits, partitions, G):
    used_qubits = set()
    allocations = []

    connected_partitions = []
    for p in partitions:
        subgraph = G.subgraph(p)
        if nx.is_connected(subgraph):
            conn_score = evaluate_partition_connectivity(p, G)
            quality_score = sum(G.nodes[n]['fidelity'] for n in p) / len(p) if p else 0
            total_score = 0.7 * quality_score + 0.3 * conn_score
            connected_partitions.append((p, total_score))

    sorted_partitions = [p for p, _ in sorted(connected_partitions, key=lambda x: x[1], reverse=True)]

    circuits_sorted = sorted(circuits, key=lambda x: (x.cx_density, x.depth), reverse=True)

    for circuit in circuits_sorted:
        best_layout = None
        best_partition = None
        best_score = -1
        # 打印当前线路信息
        print(f"\n尝试为线路 {circuit.name} 分配资源 (需要 {circuit.num_qubits} 量子比特):")

        for partition in sorted_partitions:
            available_qubits_in_partition = set(partition) - used_qubits
            if len(available_qubits_in_partition) < circuit.num_qubits:
                continue

            # 检查当前分区减去已使用比特后的连通性
            available_subgraph = G.subgraph(available_qubits_in_partition)
            if not nx.is_connected(available_subgraph) and len(available_qubits_in_partition) > 1:
                # 寻找最大连通子图
                largest_component = max(nx.connected_components(available_subgraph), key=len)
                if len(largest_component) < circuit.num_qubits:
                    continue
                # 使用最大连通子图作为可用比特集
                available_qubits_in_partition = largest_component

            # ✅ 修复点：使用 adaptive_mapping 而不是不存在的 map_circuit_greedy
            layout, mapped_partition, score = adaptive_mapping(circuit, available_qubits_in_partition, G)

            if layout:
                # 检查映射使用的物理比特是否与已使用的冲突
                current_mapped_physicals = set(layout.values())
                if not current_mapped_physicals.intersection(used_qubits):
                    if score > best_score:
                        best_score = score
                        best_layout = layout
                        best_partition = partition

        if best_layout:
            # 确认最终使用的物理比特
            final_used_physicals = set(best_layout.values())
            # 再次检查冲突
            if not final_used_physicals.intersection(used_qubits):
                # 确认映射结果是连通的
                mapped_subgraph = G.subgraph(final_used_physicals)
                if nx.is_connected(mapped_subgraph) or len(final_used_physicals) <= 1:
                    allocations.append((circuit, best_layout, best_partition))
                    used_qubits.update(final_used_physicals)
                    print(f"\n线路 {circuit.name} 资源分配成功:")
                    print(f"  分配到分区: {sorted(best_partition)}")
                    print(f"  物理布局: {best_layout}")
                    print(f"  实际使用量子比特: {sorted(final_used_physicals)}")
                else:
                    print(f"分配失败 (最终映射不连通): {circuit.name}")
            else:
                print(f"分配失败 (最终检查冲突): {circuit.name}")

        else:
            print(f"\n分配失败: 线路 {circuit.name} 无法在任何可用分区中找到合适的映射。")

    return allocations


def execute_parallel_circuits(circuits, layouts, partitions, backend, G):
    """并行执行多个量子线路并计算PST"""
    print(f"开始并行执行{len(circuits)}个线路")

    # 计算PST和获取映射后的深度
    individual_psts, mapped_depths = calculate_parallel_pst(circuits, backend, layouts, partitions, G)

    # 打印每个线路的深度和PST值
    print("\n线路深度和PST值统计:")
    print("=" * 60)
    print(f"{'线路名称':<20} {'原始深度':<0} {'映射后深度':<5} {'深度增加':<5} {'PST值':<15}")
    print("-" * 60)
    for i, (circuit, pst, mapped_depth) in enumerate(zip(circuits, individual_psts, mapped_depths)):
        original_depth = circuit.depth
        depth_increase = mapped_depth - original_depth
        print(f"{circuit.name:<20} {original_depth:<10} {mapped_depth:<10} {depth_increase:<10} {pst:.4f}")
    print("=" * 60)

    avg_pst = sum(individual_psts) / len(individual_psts) if individual_psts else 0.0
    print(f"\n平均PST值: {avg_pst:.4f}")


if __name__ == "__main__":
    cleanup_visualizations()
    # 修改为 FakeBrisbane
    backend = FakeBrisbane()

    noise_model = create_parallel_error_model(backend)
    noise_backend = AerSimulator.from_backend(backend)
    noise_backend.set_options(noise_model=noise_model)

    # 构建耦合图
    G = build_coupling_graph_from_backend(backend)

    filtered_G = preprocess_coupling_graph(G, backend, node_percentile=85, edge_percentile=85)

    filtered_G = compute_metrics(filtered_G)

    final_partitions = dynamic_partition_disconnected(filtered_G)

    # 输出分区结果
    print("\n分区结果：")
    for i, part in enumerate(final_partitions):
        print(f"分区{i + 1}: {sorted(part)}")

    # ---------- 可视化 1：分区动态演示 ----------
    animate_partitions(filtered_G, final_partitions, save_path="partitions.gif")

    # 从QASM目录加载线路
    qasm_dir = "./tiny_sized/"  # 修改为自己的QASM文件目录路径
    selected_files = None
    circuits = load_qasm_circuits(qasm_dir, selected_files)
    if not circuits:
        print("未找到有效的QASM文件，程序终止")
        exit()

    allocations = allocate_resources(circuits, final_partitions, filtered_G)

    # 并行执行所有成功分配资源的线路
    if allocations:
        circuits_to_run = [a[0] for a in allocations]
        layouts = [a[1] for a in allocations]
        partitions = [a[2] for a in allocations]

        # ---------- 可视化 2：映射动态演示（只取第一个成功的） ----------
        for i, (circuit, layout, partition) in enumerate(allocations):
            animate_mapping(filtered_G, layout, partition, circuit_name=circuit.name, save_path=f"mapping_{i}.gif")

        # 检查线路数量是否一致
        if len(circuits_to_run) == len(layouts) == len(partitions):
            parallel_backend = noise_backend
            individual_psts, mapped_depths = calculate_parallel_pst(
                circuits_to_run, parallel_backend, layouts, partitions, G
            )

            execute_parallel_circuits(circuits_to_run, layouts, partitions, parallel_backend, G)

            # ---------- 可视化 3：结果图表 ----------
            plot_results(circuits_to_run, individual_psts, mapped_depths)

        else:
            print("错误：线路、布局或分区数量不一致")
    else:
        print("没有线路成功分配资源，无法执行")