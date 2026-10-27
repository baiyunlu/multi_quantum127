import json
import os
import time
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

matplotlib.use("Agg")  # ✅ 禁用 Tkinter
matplotlib.rcParams['font.family'] = ['SimHei']  # ✅ 中文字体
matplotlib.rcParams['axes.unicode_minus'] = False

import matplotlib.pyplot as plt
import matplotlib.animation as animation
import networkx as nx

import glob
import os


def cleanup_visualizations():
    """删除上一次生成的GIF和PNG可视化文件"""
    patterns = ["*.gif", "*.png"]  # 可按需添加其他类型
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
    fig, ax = plt.subplots(figsize=(12, 10))  # 增大图形尺寸以适应更多量子比特

    colors = ["red", "blue", "green", "orange", "purple", "cyan", "magenta", "yellow", "brown", "pink"]
    node_color_map = {n: "lightgray" for n in G.nodes()}

    frames = []
    for i, part in enumerate(partitions):
        for node in part:
            node_color_map[node] = colors[i % len(colors)]
        frames.append(node_color_map.copy())

    def update(frame):
        ax.clear()
        nx.draw(G, pos, ax=ax,
                node_color=[frame[n] for n in G.nodes()],
                with_labels=True, node_size=300, font_size=8)  # 调整节点大小和字体
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
        nx.draw(subG, pos, ax=ax, node_color=node_colors,
                with_labels=True, node_size=500, font_size=8)
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
        gamma_norm = gamma_val / gamma_data["default"]  # 以默认值为基准

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
SRB_AMP_DICT = {tuple(map(int, k.split(","))): v
                for k, v in _srb_amp_raw.items()}

DEFAULT_SRB_AMP = 1.28  # 若某条 CX 没测到，仍用论文默认值

# ── ZZ-interaction γ_ij (Hz) ───────────────────────────────
with open("gamma_zz_hz.json", "r") as _f:
    _gamma_raw = json.load(_f)

# 单独处理 default
DEFAULT_GAMMA_ZZ_HZ = _gamma_raw.get("default", 15000)

# 其余键才解析为 (ctrl,tgt)
GAMMA_ZZ_HZ_DICT = {
    tuple(sorted(map(int, k.split(",")))): v
    for k, v in _gamma_raw.items()
    if k != "default"
}
# ────────────────────────────────────────────────────────────


# ── spectator-idle error dictionary ─────────────
with open("idt_error_dict.json", "r") as _f:
    _idt_raw = json.load(_f)

# 解析成 { (driver_pair, spectators_tuple): QuantumError }
IDT_ERROR_DICT = {}
for k, pauli_map in _idt_raw.items():
    driver_str, spectator_str = k.split("->")
    driver = tuple(sorted(eval(driver_str)))  # (0,1)
    spectators = tuple(eval(spectator_str))  # (2,) 或 (3,4)
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
                    if inst.operation.name in ['cx', 'ecr']:  # 包括 ecr 门
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
        coupling_map.append([v, u])  # 双向耦合
    return coupling_map


def map_circuit_greedy(circuit, partition, G):
    # 检查线路是否有交互图
    if not hasattr(circuit, 'interaction_graph'):
        print(f"错误: 线路 {circuit.name} 缺少 'interaction_graph' 属性。跳过映射。")
        return None, None, 0.0

    num_qubits_needed = circuit.num_qubits
    partition_qubits = list(partition)

    if len(partition_qubits) < num_qubits_needed:
        print(
            f"映射失败 (分区太小): 分区 {sorted(partition_qubits)} ({len(partition_qubits)} qubits) 需要 {num_qubits_needed} qubits for {circuit.name}")
        return None, None, 0.0

    physical_subgraph = G.subgraph(partition_qubits)
    if not partition_qubits:  # 处理空分区情况
        print(f"映射失败 (空分区): {circuit.name}")
        return None, None, 0.0

    layout = {}
    used_physical_qubits = set()

    logical_edges = sorted(
        circuit.interaction_graph.edges(data=True),
        key=lambda x: x[2].get('weight', 0),
        reverse=True
    )

    seed_mapped = False
    if logical_edges:
        lq0, lq1, data = logical_edges[0]
        best_physical_pair = None
        max_seed_score = -1

        # 寻找最佳物理对
        for pq0 in partition_qubits:
            for pq1 in physical_subgraph.neighbors(pq0):  # 确保是连接的对
                if pq1 in partition_qubits:  # 邻居也在分区内
                    w_f, w_e, w_c = 0.3, 0.3, 0.4

                    pq0_neighbors = set(physical_subgraph.neighbors(pq0))
                    pq1_neighbors = set(physical_subgraph.neighbors(pq1))
                    common_neighbors = len(pq0_neighbors & pq1_neighbors)
                    total_neighbors = len(pq0_neighbors | pq1_neighbors) - 2
                    connectivity_potential = common_neighbors / total_neighbors if total_neighbors > 0 else 0

                    try:
                        edge_weight = G.edges[pq0, pq1]['improved_weight']
                        score = (w_f * (G.nodes[pq0]['fidelity'] + G.nodes[pq1]['fidelity']) +
                                 w_e * (1 - edge_weight) +
                                 w_c * connectivity_potential)
                        if score > max_seed_score:
                            max_seed_score = score
                            best_physical_pair = (pq0, pq1)
                    except KeyError:  # 边或节点属性可能缺失
                        continue

        if best_physical_pair:
            pq0, pq1 = best_physical_pair
            layout[lq0] = pq0
            layout[lq1] = pq1
            used_physical_qubits.add(pq0)
            used_physical_qubits.add(pq1)
            seed_mapped = True

    # 如果没有交互或找不到合适的物理对，进行单点种子映射
    if not seed_mapped and circuit.num_qubits > 0:
        logical_qubits_sorted_by_degree = sorted(
            circuit.interaction_graph.degree(), key=lambda item: item[1], reverse=True
        )
        if logical_qubits_sorted_by_degree:
            lq_seed = logical_qubits_sorted_by_degree[0][0]
        else:  # 如果没有交互图节点（例如单量子比特线路）
            lq_seed = 0  # 假设逻辑比特从0开始

        # 找到分区中连通性最高的物理比特
        best_pq_seed = -1
        max_connectivity_score = -1
        available_physical = list(set(partition_qubits) - used_physical_qubits)
        if not available_physical:
            return None, None, 0.0

        for pq in available_physical:
            # 计算连通度和保真度的综合得分
            connectivity = len(list(physical_subgraph.neighbors(pq))) / len(partition_qubits)
            fidelity = G.nodes[pq]['fidelity']
            connectivity_score = 0.6 * connectivity + 0.4 * fidelity

            if connectivity_score > max_connectivity_score:
                max_connectivity_score = connectivity_score
                best_pq_seed = pq

        if best_pq_seed != -1:
            layout[lq_seed] = best_pq_seed
            used_physical_qubits.add(best_pq_seed)
        else:  # 无法找到种子物理比特
            return None, None, 0.0

    unmapped_logical = set(range(num_qubits_needed)) - set(layout.keys())

    while unmapped_logical:
        lq_next = -1
        max_connection_strength = -1

        for lq_candidate in unmapped_logical:
            current_strength = 0
            for mapped_lq in layout.keys():
                if circuit.interaction_graph.has_edge(lq_candidate, mapped_lq):
                    current_strength += circuit.interaction_graph.get_edge_data(
                        lq_candidate, mapped_lq, default={'weight': 0}
                    )['weight']
            if current_strength > max_connection_strength:
                max_connection_strength = current_strength
                lq_next = lq_candidate
            # 如果没有连接到已映射的比特，选择第一个未映射的
            elif lq_next == -1:
                lq_next = lq_candidate

        if lq_next == -1 and unmapped_logical:  # 处理所有剩余比特都未连接的情况
            lq_next = list(unmapped_logical)[0]  # 随机选一个

        # b. 寻找最佳物理位置，考虑连通性
        candidate_physical_qubits = set()
        mapped_physical_neighbors = set()
        for mapped_lq, mapped_pq in layout.items():
            if circuit.interaction_graph.has_edge(lq_next, mapped_lq):
                mapped_physical_neighbors.add(mapped_pq)

                for neighbor in physical_subgraph.neighbors(mapped_pq):
                    if neighbor in partition_qubits and neighbor not in used_physical_qubits:
                        candidate_physical_qubits.add(neighbor)

        if not candidate_physical_qubits:
            candidate_physical_qubits = set(partition_qubits) - used_physical_qubits
            if not candidate_physical_qubits:
                print(f"映射失败 (迭代中无可用物理比特): {circuit.name}")
                return None, None, 0.0  # 没有可用物理比特了

        # 筛选能保持连通性的候选物理比特
        connected_candidates = []
        for pc in candidate_physical_qubits:
            # 创建临时布局来测试连通性
            temp_layout = layout.copy()
            temp_layout[lq_next] = pc
            temp_physical_qubits = list(temp_layout.values())
            temp_subgraph = physical_subgraph.subgraph(temp_physical_qubits)
            if len(temp_physical_qubits) <= 1 or nx.is_connected(temp_subgraph):
                connected_candidates.append(pc)

        # 如果有保持连通性的候选者，优先使用它们
        if connected_candidates:
            candidate_physical_qubits = connected_candidates

        # c. 评分并选择最佳物理比特
        pq_best = -1
        max_physical_score = -1
        w_c, w_f, w_conn = 0.4, 0.3, 0.3

        for pc in candidate_physical_qubits:
            fidelity_score = G.nodes[pc]['fidelity']
            connection_score = 0
            num_connections = 0

            # 计算与已映射物理邻居的连接得分
            for mapped_pq_neighbor in mapped_physical_neighbors:
                if physical_subgraph.has_edge(pc, mapped_pq_neighbor):
                    # 找到对应的逻辑邻居
                    lq_neighbor = [lq for lq, pq in layout.items() if pq == mapped_pq_neighbor][0]
                    interaction_weight = circuit.interaction_graph.get_edge_data(
                        lq_next, lq_neighbor, default={'weight': 0}
                    )['weight']
                    try:
                        physical_link_quality = (1 - G.edges[pc, mapped_pq_neighbor]['improved_weight'])
                        connection_score += interaction_weight * physical_link_quality
                        num_connections += 1
                    except KeyError:
                        continue  # 忽略缺失数据的边

            pc_neighbors = set(physical_subgraph.neighbors(pc))
            mapped_neighbors = pc_neighbors.intersection(used_physical_qubits)
            connectivity_score = len(mapped_neighbors) / max(1, len(used_physical_qubits))

            avg_connection_score = connection_score  # 使用总和而非平均
            total_score = w_c * avg_connection_score + w_f * fidelity_score + w_conn * connectivity_score

            if total_score > max_physical_score:
                max_physical_score = total_score
                pq_best = pc

        # d. 执行映射
        if pq_best != -1:
            # 再次检查添加此物理比特后是否保持连通
            temp_layout = layout.copy()
            temp_layout[lq_next] = pq_best
            temp_physical_qubits = list(temp_layout.values())
            temp_subgraph = physical_subgraph.subgraph(temp_physical_qubits)

            if len(temp_physical_qubits) <= 1 or nx.is_connected(temp_subgraph):
                layout[lq_next] = pq_best
                used_physical_qubits.add(pq_best)
                unmapped_logical.remove(lq_next)
            else:
                print(f"映射失败 (添加后不连通): 逻辑比特 {lq_next} 到物理比特 {pq_best} in {circuit.name}")
                return None, None, 0.0
        else:
            print(f"映射错误: 无法为 {lq_next} 选择最佳物理比特 in {circuit.name}")
            return None, None, 0.0

    # --- 3. 最终检查 ---
    if len(layout) != num_qubits_needed:
        print(f"映射失败 (数量不匹配): {circuit.name}, Mapped {len(layout)} / {num_qubits_needed}")
        return None, None, 0.0

    # 检查连通性
    mapped_physical_qubits = list(layout.values())
    mapped_subgraph = G.subgraph(mapped_physical_qubits)
    if not nx.is_connected(mapped_subgraph):
        print(f"\n警告: 贪心映射结果不连通: {sorted(mapped_physical_qubits)} for {circuit.name}. 映射失败。")
        return None, None, 0.0
    final_score = sum(G.nodes[p]['fidelity'] for p in layout.values())

    return layout, partition, final_score


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
                        # 假设 properties.gate_length() 直接返回以秒为单位的时间
                        actual_gate_time_sec = properties.gate_length(gate_name, qubits_list)

                        if actual_gate_time_sec is not None and actual_gate_time_sec > 0:
                            two_qubit_gate_times[qubits_tuple_key] = actual_gate_time_sec
                        else:
                            print(
                                f"WARNING: {gate_name} gate time for {qubits_tuple_key} is None or not positive: {actual_gate_time_sec}")
                    except Exception as e:
                        print(f"WARNING: Failed to get gate_length for {gate_name} {qubits_tuple_key}: {e}")

    all_valid_times = [t for t in two_qubit_gate_times.values() if t > 0]
    if not all_valid_times:
        fallback_t_gate = 400e-9  # 秒
    else:
        fallback_t_gate = sum(all_valid_times) / len(all_valid_times)  # 单位是秒
        # 增加一个检查，如果平均时间依然不合理，则覆盖为标准值
        if not (100e-9 < fallback_t_gate < 1000e-9):  # 检查是否在100ns到1000ns的典型范围
            fallback_t_gate = 400e-9  # 秒

    # 1. 收集所有需要处理的量子门类型（排除reset等没有错误率的门）
    processed_gates = set()
    gate_types = set()

    for gate in properties.gates:
        try:
            if gate.gate == 'reset':
                continue
            error = properties.gate_error(gate.gate, gate.qubits)
            if error is not None:
                gate_key = (gate.gate, tuple(gate.qubits))
                if gate_key not in processed_gates:
                    gate_types.add(gate_key)
                    processed_gates.add(gate_key)
        except:
            continue

    # 2. 添加读取错误 (这部分逻辑保持不变)
    processed_qubits = set()
    for qubit in range(config.n_qubits):
        if qubit not in processed_qubits:
            try:
                readout_error = properties.readout_error(qubit)
                if readout_error is not None:
                    noise_model.add_readout_error(
                        ReadoutError([[1 - readout_error, readout_error], [readout_error, 1 - readout_error]]),
                        [qubit]
                    )
                    processed_qubits.add(qubit)
            except:
                continue

    # 3. 单量子位门错误处理 (这部分逻辑保持不变)
    single_qubit_processed = set()
    for gate, qubits_tuple_key_for_gate_type in gate_types:
        if len(qubits_tuple_key_for_gate_type) == 1 and \
                (gate, qubits_tuple_key_for_gate_type[0]) not in single_qubit_processed:
            qubit = qubits_tuple_key_for_gate_type[0]
            try:
                error_rate = properties.gate_error(gate, [qubit])  # 从后端获取单门错误率
                if error_rate is None:
                    error_rate = 0

                combined_error = depolarizing_error(error_rate, 1)  # 构建 depolarizing 噪声

                if hasattr(properties, 't1') and hasattr(properties, 't2'):
                    try:
                        t1 = properties.t1(qubit)
                        t2 = properties.t2(qubit)
                        gate_time = properties.gate_length(gate, [qubit])

                        if t1 is not None and t1 > 0 and \
                                t2 is not None and t2 > 0 and \
                                gate_time is not None and gate_time > 0:
                            actual_t2 = min(t2, t1)
                            thermal_error = thermal_relaxation_error(t1, actual_t2, gate_time)
                            combined_error = combined_error.compose(thermal_error)
                    except Exception:
                        pass  # 忽略热弛豫错误添加失败的情况
                noise_model.add_quantum_error(combined_error, [gate], [qubit])  # 添加到噪声模型
                single_qubit_processed.add((gate, qubit))
            except Exception:
                continue  # 忽略此单比特门错误处理失败的情况

    # 4. 两量子比特门错误处理 (ecr 和 cx)
    two_qubit_processed_for_base_error = set()
    two_qubit_base_errors = {}

    # 处理所有两量子比特门
    for gate_name in two_qubit_gate_names:
        for gate_props in properties.gates:
            if gate_props.gate == gate_name:
                qubit_indices_tuple = tuple(gate_props.qubits)
                if qubit_indices_tuple not in two_qubit_processed_for_base_error:
                    try:
                        error_rate = properties.gate_error(gate_name, list(qubit_indices_tuple))
                        if error_rate is not None:
                            two_qubit_base_errors[qubit_indices_tuple] = error_rate
                        else:
                            two_qubit_base_errors[qubit_indices_tuple] = 0.01
                        two_qubit_processed_for_base_error.add(qubit_indices_tuple)
                    except Exception as e:
                        if qubit_indices_tuple not in two_qubit_base_errors:
                            two_qubit_base_errors[qubit_indices_tuple] = 0.01
                        two_qubit_processed_for_base_error.add(qubit_indices_tuple)

    processed_two_qubit_pairs_for_direct_error = set()
    added_idle_errors = set()

    for qubits_tuple_key, base_error in two_qubit_base_errors.items():
        if qubits_tuple_key in processed_two_qubit_pairs_for_direct_error:
            continue

        # 获取此特定门对的门时间
        specific_t_gate = two_qubit_gate_times.get(qubits_tuple_key)
        current_t_gate_for_calc = fallback_t_gate  # 默认使用fallback
        if specific_t_gate is not None and specific_t_gate > 0:
            current_t_gate_for_calc = specific_t_gate

        # 动态增强门错误率
        pair_key = tuple(sorted(qubits_tuple_key))  # (0,1) 与 (1,0) 归一化
        amp = SRB_AMP_DICT.get(pair_key, DEFAULT_SRB_AMP)  # 获取并行放大系数
        current_error_rate = min(base_error * amp, 0.99)  # 增强后的错误率

        p_ct_zz_dynamic = 0.0
        if current_t_gate_for_calc > 0:
            # 根据 γ_zz 和门时间计算 ZZ 串扰概率
            gamma_hz = GAMMA_ZZ_HZ_DICT.get(pair_key, DEFAULT_GAMMA_ZZ_HZ)
            arg = np.pi * gamma_hz * current_t_gate_for_calc / 2.0  # 动态计算

            try:
                sin_val = np.sin(arg)
                p_ct_zz_dynamic = sin_val * sin_val  # ZZ 串扰概率
            except FloatingPointError:
                p_ct_zz_dynamic = 0.0
            if p_ct_zz_dynamic < 0: p_ct_zz_dynamic = 0.0

        error_channel_gate = depolarizing_error(current_error_rate, 2)
        error_channel_zz_after_gate = depolarizing_error(p_ct_zz_dynamic, 2)  # 构建噪声
        combined_error_on_qubits = error_channel_gate.compose(error_channel_zz_after_gate)

        try:
            # 为这个特定的量子比特对添加组合错误
            # 为所有两量子比特门类型添加相同的错误模型
            for gate_name in two_qubit_gate_names:
                noise_model.add_quantum_error(combined_error_on_qubits, [gate_name], list(qubits_tuple_key))

            driver_key = tuple(sorted(qubits_tuple_key))

            for (drv, specs), qerr in IDT_ERROR_DICT.items():
                if drv != driver_key:
                    continue  # 只处理当前驱动

                key = (tuple(specs), qerr.to_dict())  # 用 spectator 组 + 通道内容做唯一键
                if key in added_idle_errors:
                    continue  # 已写入 → 跳过

                noise_model.add_quantum_error(qerr, ['idle'], list(specs))
                added_idle_errors.add(key)

            processed_two_qubit_pairs_for_direct_error.add(qubits_tuple_key)
        except Exception as e:
            print(f"警告: 无法为两量子比特门 {qubits_tuple_key} 添加特定的组合错误: {e}")

    # 确保基础门仍在噪声模型中，并添加'idle'指令
    noise_model.add_basis_gates(['u3', 'cx', 'ecr', 'id', 'idle', 'rz', 'sx'])

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

            layout, mapped_partition, score = map_circuit_greedy(circuit, available_qubits_in_partition, G)

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
    qasm_dir = "uploads/"  # 修改为自己的QASM文件目录路径
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