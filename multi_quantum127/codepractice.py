from itertools import combinations
from itertools import permutations
from qiskit import QuantumCircuit
from collections import defaultdict, deque
import networkx as nx

import itertools
import numpy as np
import math
import random
from copy import deepcopy
import copy
from functools import lru_cache


def remove_single_qubit_gates(gates):
    """
    移除 gates 列表中所有只作用于一个 qubit 的单门操作。

    参数:
        gates (List[List]): 每个门是一个列表，第一个元素是门类型，后面是作用的 qubit。

    返回:
        List[List]: 移除单门后的门列表。
    """
    return [gate for gate in gates if len(gate) > 2]


#统计当前门集中的量子比特有哪些
def calculate_qubits(gates):

    qubits = {qubit for gate in gates for qubit in gate[1:]}  # 直接从索引 1 开始提取
    return sorted(qubits)  # 按顺序返回量子比特列表



def circuit_visualization(num_qubits, gates):
    qc = QuantumCircuit(num_qubits)

    for gate in gates:
        gate_name = gate[0]
        qubits = gate[1:]

        # 使用正确的方法添加门到电路中，避免并行执行
        if gate_name == 'cx':
            qc.cx(*qubits)
        elif gate_name == 'h':
            qc.h(qubits[0])
        elif gate_name == 'x':
            qc.x(qubits[0])
        elif gate_name == 't':
            qc.t(qubits[0])
        elif gate_name == 'tdg':
            qc.tdg(qubits[0])
        elif gate_name == 'cz':
            qc.cz(qubits[0], qubits[1])
        elif gate_name == 's':
            qc.s(qubits[0])
        elif gate_name == 'sdg':
            qc.sdg(qubits[0])
        elif gate_name == 'reuse_barrier':
            qc.barrier(qubits[0])

    print("量子线路图:")
    print(qc.draw("text", fold=300))




# 统计每个量子比特的开始时间和结束时间
def calculate_time(gates, num_qubits):
    times = []
    for i in range(num_qubits):
        star_time = -1
        end_time = -1
        for t, gate in enumerate(gates):
            if i in gate:  # 如果当前量子比特 i 在这个门操作中
                if star_time == -1:
                    star_time = t  # 第一次出现，记录开始时间
                end_time = t  # 每次出现都更新结束时间
        times.append([star_time, end_time])
    return times


# 判断复用对
def reuse_pairs(times):
    pairs = []
    for i in range(len(times)):
        for j in range(i + 1, len(times)):
            if times[i][1] < times[j][0]:
                pairs.append([i, j])  # 如果量子比特i门操作结束的时候j的门操作还未开始，就可以用i复用j

    return pairs

#寻找当前线路的所有可能的复用对
def find_reuse_pairs(gates, qubits):
    # 生成所有可能的复用对
    possible_pairs = [list(pair) for pair in permutations(qubits, 2)]

    last_pairs = []
    # 过滤掉 gates 中已经出现的比特对
    filtered_pairs = [p for p in possible_pairs if p not in gates and p[::-1] not in gates]

    for filtered_pair in filtered_pairs:
        head_flag = 0  # 用来寻找被复用的量子比特的开始时间
        tail_flag = len(gates) - 1  # 用来寻找复用的量子比特的结束时间

        while head_flag < len(gates):
            gate = gates[head_flag]
            if (len(gate) == 2 and gate[1] != filtered_pair[1]) or (len(gate) == 3 and filtered_pair[1] not in gate[1:]):
                head_flag += 1
                continue
            else:
                break

        while tail_flag >= 0:
            gate = gates[tail_flag]
            if (len(gate) == 2 and gate[1] != filtered_pair[0]) or (len(gate) == 3 and filtered_pair[0] not in gate[1:]):
                tail_flag -= 1
                continue
            else:
                break

        if head_flag > tail_flag:  # 说明该复用对满足复用条件
            last_pairs.append(filtered_pair)

    return last_pairs







# 门交换规则
def gate_swap_rule(gate1, gate2):#需要确保传入的两个门是DAG图上相邻的

    type1, *qubits1 = gate1
    type2, *qubits2 = gate2

    # 如果两个门作用的量子比特完全不同，一定可以交换
    if not set(qubits1) & set(qubits2):
        return True

    #单比特门之间的交换
    single_qubit_gates = {'x', 'y', 'z', 'h', 's', 't', 'sdg', 'tdg', 'rx', 'ry', 'rz'}
    # if type1 in single_qubit_gates and type2 in single_qubit_gates:
    #     return qubits1[0] != qubits2[0]  # 同一个量子比特上的单比特门一般不可交换

    # CNOT 门之间的交换规则
    if type1 == 'cx' and type2 == 'cx':
        c1, t1 = qubits1
        c2, t2 = qubits2
        # 情况1：控制位相同，目标位不同 -> 可以交换
        if c1 == c2 and t1 != t2:
            return True
        # 情况2：目标位相同，控制位不同 -> 可以交换
        if t1 == t2 and c1 != c2:
            return True
        # 情况3：控制位和目标位交叉相同 -> 不可交换
        # if {c1, t1} & {c2, t2} == {c1, t1}:
        #     return False
        # 其他情况（如完全不相交）已经在开头判断

    # 单比特门和 CNOT 的交换
    if type1 in single_qubit_gates and type2 == 'cx':
        q = qubits1[0]
        c, t = qubits2
        # 单比特门作用在 CNOT 的控制位 -> 可以交换
        if q == c and type1 in {'t', 'tdg', 'z', 'h', 's', 'sdg'}:
            return True
        # 单比特门作用在 CNOT 的目标位 -> 可以交换
        if q == t and type1 in {'x', 'rx'}:
            return True
        return False

    if type1 == 'cx' and type2 in single_qubit_gates:
        return gate_swap_rule(gate2, gate1)  # 利用对称性

    # 默认情况：不能交换
    return False



#计算分区之间需要的传态次数(考虑了通信比特为1)
def calculate_teleportation(gates, partition1, partition2, alpha=3, beta=1):
    partition1, partition2 = set(partition1), set(partition2)

    global_gates = []
    for i, gate in enumerate(gates):
        if len(gate) > 2:
            qubits = set(gate[1:])
            if any(q in partition1 for q in qubits) and any(q in partition2 for q in qubits):
                global_gates.append({
                    'index': i,
                    'gate': gate,
                    'qubits': qubits
                })

    if not global_gates:
        return 0

    def has_interference(start, end, teleport_qubit):
        for idx in range(start + 1, end):
            if teleport_qubit in gates[idx][1:]:
                return True
        return False

    def used_later(start_idx, teleport_qubit):
        for idx in range(start_idx + 1, len(gates)):
            if teleport_qubit in gates[idx][1:]:
                return True
        return False

    def score_teleport_qubit(tq, current_idx):
        merge_count = 0
        for g in global_gates:
            future_idx = g['index']
            if future_idx <= current_idx:
                continue
            if tq in g['qubits'] and not has_interference(current_idx, future_idx, tq):
                merge_count += 1
        return merge_count

    def overlaps(start1, end1, start2, end2):
        return not (end1 < start2 or end2 < start1)

    def has_time_conflict(new_start, new_end, current_group=None):
        for group in groups:
            if group is current_group:
                continue
            if overlaps(new_start, new_end, group['start_idx'], group['end_idx']):
                return True
        return False

    groups = []

    for g in global_gates:
        idx = g['index']
        qubits = list(g['qubits'])

        # 尝试合并已有组
        best_group = None
        best_qubit = None
        best_score = float('-inf')

        for group in groups:
            tq = group['teleport_qubit']
            new_start = group['start_idx']
            new_end = idx
            if tq in g['qubits'] and not has_interference(group['end_idx'], idx, tq):
                if has_time_conflict(new_start, new_end, current_group=group):
                    continue  # 时间重叠，不允许合并
                score = - (idx - group['end_idx'])
                if score > best_score:
                    best_score = score
                    best_group = group
                    best_qubit = tq

        if best_group:
            best_group['gates'].append(g)
            best_group['end_idx'] = idx
        else:
            # 创建新组，选择不会产生时间重叠的 teleport_qubit
            best_tq = None
            best_score = float('-inf')

            for tq in qubits:
                mergeability = score_teleport_qubit(tq, idx)
                return_penalty = 1 if used_later(idx, tq) else 0
                score = alpha * mergeability - beta * return_penalty

                if has_time_conflict(idx, idx):
                    continue  # 时间冲突，跳过

                if score > best_score:
                    best_score = score
                    best_tq = tq

            if best_tq is not None:
                groups.append({
                    'teleport_qubit': best_tq,
                    'gates': [g],
                    'start_idx': idx,
                    'end_idx': idx
                })

    total_teleportation = 0
    for group in groups:
        k = len(group['gates'])  # 这个组里包含的远程门数
        tq = group['teleport_qubit']

        if k == 1:
            # —— 用 telegate ——
            total_teleportation += 1
        else:
            # —— 用 teledata（合并传态） ——
            if used_later(group['end_idx'], tq):
                total_teleportation += 2
            else:
                total_teleportation += 1

    return total_teleportation




#用门交换规则来增加合并传输
def optimize_gate_order(gates, partitions):
    optimized_gates = gates[:]
    best_cost = 0

    # 对每一对分区进行优化
    for i in range(len(partitions) - 1):
        for j in range(i + 1, len(partitions)):
            partition1 = partitions[i]
            partition2 = partitions[j]

            # 对每一对分区优化门顺序
            optimized_gates, pair_cost = optimize_gate_order_with_sa(optimized_gates, partition1, partition2)
            best_cost += pair_cost

    return optimized_gates, best_cost



def compute_qubit_gate_map(gates, bit2partition=None):
    qubit_gate_map = defaultdict(list)
    for idx, gate in enumerate(gates):
        if len(gate) == 2:
            _, q = gate
            qubit_gate_map[q].append(idx)
        elif len(gate) == 3:
            _, q1, q2 = gate
            if bit2partition and bit2partition.get(q1) == bit2partition.get(q2):
                # 局部门：统一映射为 -1
                qubit_gate_map[-1].append(idx)
            else:
                qubit_gate_map[q1].append(idx)
                qubit_gate_map[q2].append(idx)
    return qubit_gate_map


def compute_interaction_matrix(gates):
    interaction = defaultdict(lambda: defaultdict(int))
    for gate in gates:
        if len(gate) == 3:
            _, q1, q2 = gate
            interaction[q1][q2] += 1
            interaction[q2][q1] += 1
    return interaction

def compute_colored_sequence(qubit_gate_map, candidate_qubits):
    color_sequence = []
    for q in candidate_qubits:
        for idx in qubit_gate_map[q]:
            color_sequence.append((idx, q))
    color_sequence.sort()
    return [q for _, q in color_sequence]

def count_color_segments(color_sequence):
    if not color_sequence:
        return 0
    count = 1
    for i in range(1, len(color_sequence)):
        if color_sequence[i] != color_sequence[i - 1]:
            count += 1
    return count


#评分函数
def compute_score(inter_score, span, b1=10, b2=2, alpha=2, beta=1):
    # score = (b1 ** (alpha * inter_score)) * (b2 ** (-beta * span))
    score = alpha * inter_score * math.log(b1) - beta * span * math.log(b2)
    return score

#网格搜索最优参数
from mpl_toolkits.mplot3d import Axes3D
import matplotlib.pyplot as plt
import numpy as np

def plot_3d_wireframe(b1_list, b2_list, teleport_dict):
    X, Y = np.meshgrid(b2_list, b1_list)
    Z = np.zeros_like(X, dtype=float)

    for i, b1 in enumerate(b1_list):
        for j, b2 in enumerate(b2_list):
            Z[i, j] = teleport_dict.get((b1, b2), np.nan)

    fig = plt.figure(figsize=(10, 7))
    ax = fig.add_subplot(111, projection='3d')
    ax.plot_wireframe(X, Y, Z, rstride=1, cstride=1)

    ax.set_xlabel('b2 ')
    ax.set_ylabel('b1 ')
    ax.set_zlabel('teleportations')
    plt.tight_layout()
    plt.savefig("figure10.svg", bbox_inches='tight')
    plt.show()

def grid_search_partitioning(gates, qubits, num_partitions, b1_list, b2_list, max_imbalance=1):
    best_result = None
    best_teleport = float('inf')
    best_global = float('inf')
    best_b1 = None
    best_b2 = None

    # 用于存储每个 (b1, b2) 对应的传态次数
    teleport_dict = {}

    for b1 in b1_list:
        for b2 in b2_list:
            result = greedy_partition_multi_start_search(
                gates, qubits, num_partitions, max_imbalance, b1=b1, b2=b2
            )
            if result is None:
                continue
            _, _, teleport, global_gates = result
            teleport_dict[(b1, b2)] = teleport

            if teleport < best_teleport or (teleport == best_teleport and global_gates < best_global):
                best_result = result
                best_teleport = teleport
                best_global = global_gates
                best_b1 = b1
                best_b2 = b2

    plot_3d_wireframe(b1_list, b2_list, teleport_dict)

    return best_result, best_b1, best_b2






def greedy_partition_multi_start_search(
    gates,
    qubits,
    num_partitions,
    max_imbalance=0,
    b1=10,
    b2=2,
    alpha=3,
    beta=1
):
    qubit_gate_map = compute_qubit_gate_map(gates)
    interaction = compute_interaction_matrix(gates)

    # 1. 多起点候选：门数最多的前 k 个比特
    k = 15
    sorted_qubits = sorted(
        qubit_gate_map.items(),
        key=lambda item: len(item[1]),
        reverse=True
    )
    candidate_starts = [q for q, _ in sorted_qubits[:k]]

    best_result = None
    best_teleport = float('inf')
    best_global = float('inf')

    # 目标分区大小（近似均衡）
    target_size = (len(qubits) // num_partitions) + max_imbalance - 1

    # —— 分区贪心扩展函数 ——
    def expand_partition(partition, unassigned):
        while len(partition) < target_size and unassigned:
            best_score = float('-inf')
            best_q = None

            for q in unassigned:
                inter_score = sum(interaction[q][other] for other in partition)
                color_seq = compute_colored_sequence(
                    qubit_gate_map,
                    partition + [q]
                )
                color_seg = count_color_segments(color_seq)

                score = compute_score(
                    inter_score,
                    color_seg,
                    b1=b1,
                    b2=b2,
                    alpha=alpha,
                    beta=beta
                )

                if score > best_score:
                    best_score = score
                    best_q = q

            if best_q is None:
                break

            partition.append(best_q)
            unassigned.remove(best_q)

    # 2. 多起点搜索
    for start in candidate_starts:
        unassigned = set(qubits)
        partitions = []

        # —— 第一个分区：由 start 触发，并参与完整贪心扩展 ——
        first_partition = [start]
        unassigned.remove(start)
        expand_partition(first_partition, unassigned)
        partitions.append(first_partition)

        # —— 构建剩余分区 ——
        for _ in range(num_partitions - 1):
            if not unassigned:
                break

            new_seed = max(unassigned, key=lambda q: len(qubit_gate_map[q]))
            new_partition = [new_seed]
            unassigned.remove(new_seed)

            expand_partition(new_partition, unassigned)
            partitions.append(new_partition)

        # —— 均衡回填剩余比特（此时不会污染某一特定分区） ——
        if len(partitions) < num_partitions:
            partitions.append(list(unassigned))
        else:
            for q in unassigned:
                min_part = min(partitions, key=lambda part: len(part))
                min_part.append(q)

        # 3. 评估该分区方案
        optimized_gates, teleportations = optimize_gate_order(
            gates,
            partitions
        )
        global_gates = evaluate_global_gates_all_partitions(
            partitions,
            optimized_gates
        )

        if (
            teleportations < best_teleport or
            (teleportations == best_teleport and global_gates < best_global)
        ):
            best_result = (
                partitions,
                optimized_gates,
                teleportations,
                global_gates
            )
            best_teleport = teleportations
            best_global = global_gates

    return best_result





def genetic_multi_partitioning(
    gates, qubits, num_partitions, max_imbalance=1,
    search=False, b1_list=None, b2_list=None,
    b1=10, b2=2, alpha=1, beta=1
):
    if search:
        if b1_list is None:
            b1_list = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]

        if b2_list is None:
            b2_list = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]

        best_result, best_b1, best_b2 = grid_search_partitioning(
            gates, qubits, num_partitions, b1_list, b2_list, max_imbalance
        )
        return best_result, best_b1, best_b2
    else:
        result = greedy_partition_multi_start_search(
            gates, qubits, num_partitions, max_imbalance,
            b1=b1, b2=b2, alpha=alpha, beta=beta
        )
        return result




def optimize_gate_order_with_sa(gates, partition1, partition2, alpha=4, beta=1):
    new_gates = copy.deepcopy(gates)

    global_gates = []
    for i, gate in enumerate(new_gates):
        if len(gate) > 2:
            qubits = set(gate[1:])
            if any(q in partition1 for q in qubits) and any(q in partition2 for q in qubits):
                global_gates.append({
                    'index': i,
                    'gate': gate,
                    'qubits': qubits
                })


    if not global_gates:
        return new_gates, 0


    def has_interference(start, end, teleport_qubit):
        for idx in range(start + 1, end):
            if teleport_qubit in new_gates[idx][1:]:
                return True
        return False

    def used_later_accurate(new_gates, teleport_qubit, global_gates):
        """
        new_gates: 门列表
        teleport_qubit: 当前传态比特
        global_gates: 已经识别出的所有跨区门，列表里每个元素包含 'index' 和 'qubits'
        """
        # 找到作用在 tq 上的所有跨区门索引
        cross_indices = [g['index'] for g in global_gates if teleport_qubit in g['qubits']]

        if not cross_indices:
            return False  # 没有跨区门，不需要返回

        last_cross_idx = max(cross_indices)

        # 判断最后一个跨区门之后，tq 是否还有门
        for idx in range(last_cross_idx + 1, len(new_gates)):
            if teleport_qubit in new_gates[idx][1:]:
                return True  # 需要返回
        return False

    def score_teleport_qubit(tq, current_idx):
        merge_count = 0
        for g in global_gates:
            future_idx = g['index']
            if future_idx <= current_idx:
                continue
            if tq in g['qubits']:
                merge_count += 1
        return merge_count

    def get_forward_dependency_chain(gates, start_idx, end_idx):
        chain = set([start_idx])
        frontier = [start_idx]

        while frontier:
            cur = frontier.pop()
            cur_qubits = set(gates[cur][1:])

            for i in range(cur + 1, end_idx):
                if i in chain:
                    continue

                next_qubits = set(gates[i][1:])

                if cur_qubits & next_qubits:
                    if not gate_swap_rule(gates[cur], gates[i]):
                        chain.add(i)
                        frontier.append(i)

        return sorted(chain)

    def can_move_block(gates, block, target_idx):
        block_set = set(block)

        for i in block:
            gate = gates[i]
            qubits = set(gate[1:])

            for j in range(i + 1, target_idx + 1):
                if j in block_set:
                    continue

                other = gates[j]
                other_qubits = set(other[1:])

                if qubits & other_qubits:
                    if not gate_swap_rule(gate, other):
                        return False

        return True

    def move_block_after(gates, block, target_idx):
        block_gates = [gates[i] for i in block]

        for i in sorted(block, reverse=True):
            gates.pop(i)

        shift = sum(1 for i in block if i < target_idx)
        insert_pos = target_idx - shift + 1

        for i, g in enumerate(block_gates):
            gates.insert(insert_pos + i, g)

    groups = []

    for g in global_gates:
        idx = g['index']
        qubits = list(g['qubits'])

        best_group = None
        best_qubit = None
        best_score = float('-inf')

        # ✅ 修改1：去掉 has_interference 限制
        for group in groups:
            tq = group['teleport_qubit']
            if tq in g['qubits']:
                score = -(idx - group['end_idx'])
                if score > best_score:
                    best_score = score
                    best_group = group
                    best_qubit = tq




        if best_group:
            teleport_qubit = best_qubit
            start = best_group['end_idx'] + 1
            end = idx

            # ✅ 判断是否有干扰（但不阻止进入）
            has_conflict = has_interference(best_group['end_idx'], idx, teleport_qubit)

            if has_conflict:
                interfering_indices = []
                for i in range(start, end):
                    gate_qubits = set(new_gates[i][1:])
                    if teleport_qubit in gate_qubits:
                        if gate_qubits.issubset(partition1) or gate_qubits.issubset(partition2):
                            interfering_indices.append(i)

                for i in interfering_indices:
                    moved = False

                    # 👉 向左移动（先尝试左移）
                    A_idx = best_group['end_idx']  # 你原来的左移边界
                    chain = get_forward_dependency_chain(new_gates, A_idx, i)

                    if can_move_block(new_gates, chain, i):
                        move_block_after(new_gates, chain, i)
                        moved = True

                    # 👉 向右移动（如果左移失败再尝试右移）
                    if not moved:
                        chain = get_forward_dependency_chain(new_gates, i, idx)
                        if can_move_block(new_gates, chain, idx):
                            move_block_after(new_gates, chain, idx)
                            moved = True

            # ✅ 再判断一次：干扰是否已消除
            if not has_interference(best_group['end_idx'], idx, teleport_qubit):
                best_group['gates'].append(g)
                best_group['end_idx'] = idx
            else:
                # ❌ 移动失败，不合并
                groups.append({
                    'teleport_qubit': teleport_qubit,
                    'gates': [g],
                    'start_idx': idx,
                    'end_idx': idx
                })

        else:
            best_tq = None
            best_score = float('-inf')


            for tq in qubits:
                mergeability = score_teleport_qubit(tq, idx)
                return_penalty = 1 if used_later_accurate(new_gates, tq, global_gates) else 0
                score = alpha * mergeability - beta * return_penalty

                if score > best_score:
                    best_score = score
                    best_tq = tq

            groups.append({
                'teleport_qubit': best_tq,
                'gates': [g],
                'start_idx': idx,
                'end_idx': idx
            })

    total_teleportation = calculate_teleportation(new_gates, partition1, partition2)

    return new_gates, total_teleportation








def evaluate_global_gates_all_partitions(partitions, gates):
    """计算每对分区之间的全局门数量，并累加"""
    qubit_to_partition = {}
    for idx, partition in enumerate(partitions):
        for qubit in partition:
            qubit_to_partition[qubit] = idx

    partition_count = len(partitions)
    total_global_gates = 0

    for gate in gates:
        if len(gate) < 3:
            continue
        q1, q2 = gate[1], gate[2]
        p1 = qubit_to_partition.get(q1, -1)
        p2 = qubit_to_partition.get(q2, -1)
        if p1 != -1 and p2 != -1 and p1 != p2:
            total_global_gates += 1

    return total_global_gates



