import os
import json
import threading
import tempfile
import shutil
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import sys

# 添加量子分区模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 尝试导入量子模块 - 标准算法
try:
    from quantum_partition import (
        cleanup_visualizations as standard_cleanup,
        animate_partitions as standard_animate_partitions,
        animate_mapping as standard_animate_mapping,
        plot_results as standard_plot_results,
        FakeBrisbane,
        create_parallel_error_model as standard_create_error_model,
        AerSimulator,
        build_coupling_graph_from_backend as standard_build_graph,
        preprocess_coupling_graph as standard_preprocess,
        compute_metrics as standard_compute_metrics,
        dynamic_partition_disconnected as standard_dynamic_partition,
        load_qasm_circuits as standard_load_circuits,
        allocate_resources as standard_allocate_resources,
        calculate_parallel_pst as standard_calculate_pst,
    )
    STANDARD_MODULE_AVAILABLE = True
    print("✓ 标准量子分区模块加载成功")
except ImportError as e:
    print(f"✗ 标准量子分区模块加载失败: {e}")
    STANDARD_MODULE_AVAILABLE = False

# 尝试导入自适应算法模块
try:
    from quantum_partition_zishiying1 import (
        cleanup_visualizations as adaptive_cleanup,
        animate_partitions as adaptive_animate_partitions,
        animate_mapping as adaptive_animate_mapping,
        plot_results as adaptive_plot_results,
        FakeBrisbane,
        create_parallel_error_model as adaptive_create_error_model,
        AerSimulator,
        build_coupling_graph_from_backend as adaptive_build_graph,
        preprocess_coupling_graph as adaptive_preprocess,
        compute_metrics as adaptive_compute_metrics,
        dynamic_partition_disconnected as adaptive_dynamic_partition,
        load_qasm_circuits as adaptive_load_circuits,
        allocate_resources as adaptive_allocate_resources,
        calculate_parallel_pst as adaptive_calculate_pst,
    )
    ADAPTIVE_MODULE_AVAILABLE = True
    print("✓ 自适应量子分区模块加载成功")
except ImportError as e:
    print(f"✗ 自适应量子分区模块加载失败: {e}")
    ADAPTIVE_MODULE_AVAILABLE = False

# 尝试导入线路逻辑比特分区与拓扑映射模块（融合自「代码/」项目）
try:
    import routing_partition
    ROUTING_MODULE_AVAILABLE = True
    print("✓ 线路分区与拓扑映射模块加载成功")
except ImportError as e:
    routing_partition = None
    ROUTING_MODULE_AVAILABLE = False
    print(f"✗ 线路分区与拓扑映射模块加载失败: {e}")

app = Flask(__name__)
app.secret_key = 'quantum-parallel-visualization'

# 数据库配置
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 文件上传配置
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'qasm'}
app.config['TEMPLATES_AUTO_RELOAD'] = True

# 初始化扩展
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录以访问此页面'

# 创建上传目录
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 全局处理状态
processing_status = {
    'is_processing': False,
    'progress': 0,
    'current_step': '',
    'message': '',
    'result': None,
    'error': None,
    'files': [],
    'gif_files': []
}

# 线路分区与拓扑映射功能的处理状态（独立于上方的量子模拟处理状态）
routing_status = {
    'is_processing': False,
    'progress': 0,
    'current_step': '',
    'message': '',
    'result': None,
    'error': None
}

# 用户模型
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# 创建数据库
with app.app_context():
    db.create_all()
    # 创建默认用户（如果不存在）
    if not User.query.filter_by(username='admin').first():
        hashed_password = generate_password_hash('admin123')
        admin = User(username='admin', email='admin@quantum.com', password=hashed_password)
        db.session.add(admin)
        db.session.commit()


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def process_quantum_files(filepaths, selected_files=None, algorithm='standard'):
    """处理量子线路的主函数，支持算法选择"""
    global processing_status

    # 根据算法选择对应的模块函数
    if algorithm == 'adaptive' and ADAPTIVE_MODULE_AVAILABLE:
        print(f"使用自适应算法处理 {len(filepaths)} 个文件")
        return process_quantum_files_adaptive(filepaths, selected_files)
    else:
        print(f"使用标准算法处理 {len(filepaths)} 个文件")
        return process_quantum_files_standard(filepaths, selected_files)


def process_quantum_files_standard(filepaths, selected_files=None):
    """标准算法处理函数"""
    global processing_status

    try:
        # 步骤1: 初始化
        processing_status['is_processing'] = True
        processing_status['progress'] = 10
        processing_status['current_step'] = '初始化系统'
        processing_status['message'] = '正在清理旧文件...'

        standard_cleanup()

        # 步骤2: 初始化后端
        processing_status['progress'] = 20
        processing_status['current_step'] = '初始化量子后端'
        processing_status['message'] = '正在创建噪声模型...'

        backend = FakeBrisbane()
        noise_model = standard_create_error_model(backend)
        noise_backend = AerSimulator.from_backend(backend)
        noise_backend.set_options(noise_model=noise_model)

        # 步骤3: 构建耦合图
        processing_status['progress'] = 30
        processing_status['current_step'] = '构建耦合图'
        processing_status['message'] = '正在构建和优化耦合图...'

        G = standard_build_graph(backend)
        filtered_G = standard_preprocess(G, backend, node_percentile=85, edge_percentile=85)
        filtered_G = standard_compute_metrics(filtered_G)

        # 步骤4: 动态分区
        processing_status['progress'] = 40
        processing_status['current_step'] = '动态分区'
        processing_status['message'] = '正在进行量子比特分区...'

        final_partitions = standard_dynamic_partition(filtered_G)

        # 步骤5: 加载线路
        processing_status['progress'] = 50
        processing_status['current_step'] = '加载量子线路'
        processing_status['message'] = f'正在加载{len(filepaths)}个线路文件...'

        # 创建临时目录存放文件
        temp_dir = tempfile.mkdtemp()
        for filepath in filepaths:
            filename = os.path.basename(filepath)
            dest_path = os.path.join(temp_dir, filename)
            shutil.copy2(filepath, dest_path)

        circuits = standard_load_circuits(temp_dir, selected_files)

        if not circuits:
            raise Exception("没有找到有效的QASM线路")

        # 步骤6: 资源分配
        processing_status['progress'] = 60
        processing_status['current_step'] = '分配资源'
        processing_status['message'] = '正在分配量子比特资源...'

        allocations = standard_allocate_resources(circuits, final_partitions, filtered_G)

        if not allocations:
            raise Exception("资源分配失败")

        # 步骤7: 生成可视化
        processing_status['progress'] = 70
        processing_status['current_step'] = '生成可视化'
        processing_status['message'] = '正在生成GIF动画...'

        # 生成分区动画
        partitions_gif = "partitions.gif"
        standard_animate_partitions(filtered_G, final_partitions, save_path=partitions_gif)

        # 生成映射动画
        mapping_gifs = []
        for i, (circuit, layout, partition) in enumerate(allocations[:3]):  # 只生成前3个
            gif_name = f"mapping_{i}_{circuit.name.replace('.qasm', '')}.gif"
            standard_animate_mapping(filtered_G, layout, partition,
                                     circuit_name=circuit.name,
                                     save_path=gif_name)
            mapping_gifs.append(gif_name)

        # 步骤8: 执行线路
        processing_status['progress'] = 80
        processing_status['current_step'] = '执行量子线路'
        processing_status['message'] = '正在并行执行量子线路...'

        circuits_to_run = [a[0] for a in allocations]
        layouts = [a[1] for a in allocations]
        partitions = [a[2] for a in allocations]

        individual_psts, mapped_depths = standard_calculate_pst(
            circuits_to_run, noise_backend, layouts, partitions, G
        )

        # 步骤9: 生成结果图表
        processing_status['progress'] = 90
        processing_status['current_step'] = '生成结果图表'
        processing_status['message'] = '正在生成结果图表...'

        results_png = "results.png"
        standard_plot_results(circuits_to_run, individual_psts, mapped_depths, save_path=results_png)

        # 步骤10: 整理结果
        processing_status['progress'] = 100
        processing_status['current_step'] = '完成'
        processing_status['message'] = '处理完成'

        # 收集所有生成的文件
        gif_files = [partitions_gif] + mapping_gifs + [results_png]

        result = {
            'success': True,
            'algorithm': 'standard',
            'circuits_processed': len(circuits_to_run),
            'circuit_names': [c.name for c in circuits_to_run],
            'pst_values': individual_psts,
            'mapped_depths': mapped_depths,
            'gif_files': gif_files,
            'partitions': [sorted(p) for p in final_partitions],
            'allocations_count': len(allocations)
        }

        processing_status['result'] = result
        processing_status['gif_files'] = gif_files

        # 清理临时目录
        shutil.rmtree(temp_dir)

        return result

    except Exception as e:
        processing_status['error'] = str(e)
        raise
    finally:
        processing_status['is_processing'] = False


def process_quantum_files_adaptive(filepaths, selected_files=None):
    """自适应算法处理函数"""
    global processing_status

    try:
        # 步骤1: 初始化
        processing_status['is_processing'] = True
        processing_status['progress'] = 10
        processing_status['current_step'] = '初始化系统'
        processing_status['message'] = '正在清理旧文件...'

        adaptive_cleanup()

        # 步骤2: 初始化后端
        processing_status['progress'] = 20
        processing_status['current_step'] = '初始化量子后端'
        processing_status['message'] = '正在创建噪声模型...'

        backend = FakeBrisbane()
        noise_model = adaptive_create_error_model(backend)
        noise_backend = AerSimulator.from_backend(backend)
        noise_backend.set_options(noise_model=noise_model)

        # 步骤3: 构建耦合图
        processing_status['progress'] = 30
        processing_status['current_step'] = '构建耦合图'
        processing_status['message'] = '正在构建和优化耦合图...'

        G = adaptive_build_graph(backend)
        filtered_G = adaptive_preprocess(G, backend, node_percentile=85, edge_percentile=85)
        filtered_G = adaptive_compute_metrics(filtered_G)

        # 步骤4: 动态分区
        processing_status['progress'] = 40
        processing_status['current_step'] = '动态分区'
        processing_status['message'] = '正在进行量子比特分区...'

        final_partitions = adaptive_dynamic_partition(filtered_G)

        # 步骤5: 加载线路
        processing_status['progress'] = 50
        processing_status['current_step'] = '加载量子线路'
        processing_status['message'] = f'正在加载{len(filepaths)}个线路文件...'

        # 创建临时目录存放文件
        temp_dir = tempfile.mkdtemp()
        for filepath in filepaths:
            filename = os.path.basename(filepath)
            dest_path = os.path.join(temp_dir, filename)
            shutil.copy2(filepath, dest_path)

        circuits = adaptive_load_circuits(temp_dir, selected_files)

        if not circuits:
            raise Exception("没有找到有效的QASM线路")

        # 步骤6: 资源分配
        processing_status['progress'] = 60
        processing_status['current_step'] = '分配资源'
        processing_status['message'] = '正在分配量子比特资源...'

        allocations = adaptive_allocate_resources(circuits, final_partitions, filtered_G)

        if not allocations:
            raise Exception("资源分配失败")

        # 步骤7: 生成可视化
        processing_status['progress'] = 70
        processing_status['current_step'] = '生成可视化'
        processing_status['message'] = '正在生成GIF动画...'

        # 生成分区动画
        partitions_gif = "partitions_adaptive.gif"
        adaptive_animate_partitions(filtered_G, final_partitions, save_path=partitions_gif)

        # 生成映射动画
        mapping_gifs = []
        for i, (circuit, layout, partition) in enumerate(allocations[:3]):  # 只生成前3个
            gif_name = f"mapping_adaptive_{i}_{circuit.name.replace('.qasm', '')}.gif"
            adaptive_animate_mapping(filtered_G, layout, partition,
                                     circuit_name=circuit.name,
                                     save_path=gif_name)
            mapping_gifs.append(gif_name)

        # 步骤8: 执行线路
        processing_status['progress'] = 80
        processing_status['current_step'] = '执行量子线路'
        processing_status['message'] = '正在并行执行量子线路...'

        circuits_to_run = [a[0] for a in allocations]
        layouts = [a[1] for a in allocations]
        partitions = [a[2] for a in allocations]

        individual_psts, mapped_depths = adaptive_calculate_pst(
            circuits_to_run, noise_backend, layouts, partitions, G
        )

        # 步骤9: 生成结果图表
        processing_status['progress'] = 90
        processing_status['current_step'] = '生成结果图表'
        processing_status['message'] = '正在生成结果图表...'

        results_png = "results_adaptive.png"
        adaptive_plot_results(circuits_to_run, individual_psts, mapped_depths, save_path=results_png)

        # 步骤10: 整理结果
        processing_status['progress'] = 100
        processing_status['current_step'] = '完成'
        processing_status['message'] = '处理完成'

        # 收集所有生成的文件
        gif_files = [partitions_gif] + mapping_gifs + [results_png]

        result = {
            'success': True,
            'algorithm': 'adaptive',
            'circuits_processed': len(circuits_to_run),
            'circuit_names': [c.name for c in circuits_to_run],
            'pst_values': individual_psts,
            'mapped_depths': mapped_depths,
            'gif_files': gif_files,
            'partitions': [sorted(p) for p in final_partitions],
            'allocations_count': len(allocations)
        }

        processing_status['result'] = result
        processing_status['gif_files'] = gif_files

        # 清理临时目录
        shutil.rmtree(temp_dir)

        return result

    except Exception as e:
        processing_status['error'] = str(e)
        raise
    finally:
        processing_status['is_processing'] = False


# ========== 用户认证路由 ==========

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('home'))
        else:
            flash('用户名或密码错误', 'error')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ========== 主页面路由 ==========

@app.route('/')
@login_required
def home():
    """首页 - 使用index.html作为主页"""
    return render_template('index.html')


@app.route('/simulator')
@login_required
def simulator():
    """量子模拟器页面 - 原simulator.html功能"""
    return render_template('simulator.html')


# ========== 其他功能页面路由 ==========

@app.route('/framework')
@login_required
def framework():
    return render_template('framework.html')


@app.route('/News')
@login_required
def News():
    return render_template('News.html')


@app.route('/demos')
@login_required
def demos():
    return render_template('demos.html')


@app.route('/results')
@login_required
def results():
    return render_template('results.html')


@app.route('/about')
@login_required
def about():
    return render_template('about.html')


@app.route('/qubit-routing')
@login_required
def qubit_routing():
    return render_template('qubit-routing.html')


@app.route('/circuit-partition')
@login_required
def circuit_partition():
    """线路逻辑比特分区与拓扑映射页面"""
    return render_template('circuit-partition.html')


# ========== 线路分区与拓扑映射 API ==========

@app.route('/circuit_partition/status')
@login_required
def circuit_partition_status():
    """获取线路分区处理状态"""
    return jsonify(routing_status)


@app.route('/circuit_partition/run', methods=['POST'])
@login_required
def circuit_partition_run():
    """接收 QASM 文件 + 拓扑参数，后台执行线路分区与拓扑映射"""
    global routing_status

    if not ROUTING_MODULE_AVAILABLE:
        return jsonify({
            'success': False,
            'error': '线路分区模块不可用，请检查依赖（qiskit / networkx / matplotlib）'
        }), 500

    if routing_status['is_processing']:
        return jsonify({'success': False, 'error': '系统正在处理上一个请求，请稍后再试'})

    if 'qasm_file' not in request.files:
        return jsonify({'success': False, 'error': '没有选择文件'})

    file = request.files['qasm_file']
    if file.filename == '':
        return jsonify({'success': False, 'error': '没有选择文件'})

    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': '仅支持 .qasm 文件'})

    # 分区数
    try:
        num_partitions = int(request.form.get('num_partitions', 2))
        num_partitions = max(2, min(num_partitions, 8))
    except ValueError:
        num_partitions = 2

    # 是否启用 b1/b2 网格搜索（慢）
    search = request.form.get('search', 'false').lower() in ('true', '1', 'yes', 'on')

    # 目标拓扑边列表（JSON 数组 [[u,v], ...]，0 起始）
    target_edges = None
    topology_raw = request.form.get('target_edges', '')
    if topology_raw:
        try:
            edges = json.loads(topology_raw)
            if isinstance(edges, list):
                target_edges = [[int(u), int(v)] for u, v in edges]
        except (ValueError, TypeError, json.JSONDecodeError):
            return jsonify({'success': False, 'error': '目标拓扑边列表格式错误，应为 [[u,v],...] 的 JSON 数组'})

    # 保存上传文件
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    # 后台线程执行
    def run_in_background():
        global routing_status
        try:
            routing_status['is_processing'] = True
            routing_status['error'] = None
            routing_status['result'] = None
            routing_status['progress'] = 10
            routing_status['current_step'] = '解析线路'
            routing_status['message'] = '正在加载 QASM 并解析门列表...'

            result = routing_partition.run_routing(
                filepath,
                num_partitions=num_partitions,
                target_edges=target_edges,
                search=search
            )

            routing_status['progress'] = 100
            routing_status['current_step'] = '完成'
            routing_status['message'] = '分区与映射完成'
            routing_status['result'] = result
        except Exception as e:
            print(f"线路分区处理失败: {str(e)}")
            import traceback
            traceback.print_exc()
            routing_status['error'] = str(e)
        finally:
            routing_status['is_processing'] = False

    thread = threading.Thread(target=run_in_background)
    thread.daemon = True
    thread.start()

    return jsonify({
        'success': True,
        'message': f'开始处理 {filename}，分区数 {num_partitions}',
        'num_partitions': num_partitions
    })


# ========== 量子模拟器API路由 ==========

@app.route('/check_module')
@login_required
def check_module():
    """检查量子模块是否可用"""
    return jsonify({
        'standard_available': STANDARD_MODULE_AVAILABLE,
        'adaptive_available': ADAPTIVE_MODULE_AVAILABLE,
        'standard_message': '标准算法模块' + ('可用' if STANDARD_MODULE_AVAILABLE else '不可用'),
        'adaptive_message': '自适应算法模块' + ('可用' if ADAPTIVE_MODULE_AVAILABLE else '不可用')
    })


@app.route('/upload', methods=['POST'])
@login_required
def upload_files():
    """处理文件上传，支持算法选择"""
    global processing_status

    if processing_status['is_processing']:
        return jsonify({
            'success': False,
            'error': '系统正在处理上一个请求，请稍后再试'
        })

    if 'qasm_files' not in request.files:
        return jsonify({
            'success': False,
            'error': '没有选择文件'
        })

    # 获取算法选择参数
    algorithm = request.form.get('algorithm', 'standard')
    if algorithm not in ['standard', 'adaptive']:
        algorithm = 'standard'

    files = request.files.getlist('qasm_files')
    if not files or files[0].filename == '':
        return jsonify({
            'success': False,
            'error': '没有选择文件'
        })

    # 检查对应算法模块是否可用
    if algorithm == 'adaptive' and not ADAPTIVE_MODULE_AVAILABLE:
        return jsonify({
            'success': False,
            'error': '自适应算法模块不可用，请使用标准算法'
        })

    # 保存上传的文件
    saved_files = []
    for file in files:
        if allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            saved_files.append(filepath)

    if not saved_files:
        return jsonify({
            'success': False,
            'error': '没有有效的QASM文件'
        })

    # 在后台线程中处理文件
    def process_in_background():
        try:
            process_quantum_files(saved_files, algorithm=algorithm)
        except Exception as e:
            print(f"处理失败: {str(e)}")
            import traceback
            traceback.print_exc()
            processing_status['error'] = str(e)
            processing_status['is_processing'] = False

    thread = threading.Thread(target=process_in_background)
    thread.daemon = True
    thread.start()

    algo_name = '自适应算法' if algorithm == 'adaptive' else '标准算法'
    return jsonify({
        'success': True,
        'message': f'开始使用{algo_name}处理 {len(saved_files)} 个文件',
        'file_count': len(saved_files),
        'algorithm': algorithm
    })

@app.route('/cleanup', methods=['POST'])
@login_required
def cleanup():
    """清理生成的文件"""
    try:
        # 调用量子模块的清理函数
        if STANDARD_MODULE_AVAILABLE:
            from quantum_partition import cleanup_visualizations
            cleanup_visualizations()
        if ADAPTIVE_MODULE_AVAILABLE:
            from quantum_partition_zishiying1 import cleanup_visualizations as adaptive_cleanup
            adaptive_cleanup()
        return jsonify({'success': True, 'message': '清理完成'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
@app.route('/status')
@login_required
def get_status():
    """获取处理状态"""
    return jsonify(processing_status)


@app.route('/compare', methods=['POST'])
@login_required
def compare_algorithms():
    """同时运行标准算法和自适应算法进行对比"""
    global processing_status

    if processing_status['is_processing']:
        return jsonify({
            'success': False,
            'error': '系统正在处理上一个请求，请稍后再试'
        })

    if 'qasm_files' not in request.files:
        return jsonify({
            'success': False,
            'error': '没有选择文件'
        })

    files = request.files.getlist('qasm_files')
    if not files or files[0].filename == '':
        return jsonify({
            'success': False,
            'error': '没有选择文件'
        })

    # 检查两个算法模块是否都可用
    if not STANDARD_MODULE_AVAILABLE or not ADAPTIVE_MODULE_AVAILABLE:
        return jsonify({
            'success': False,
            'error': '算法对比需要标准算法和自适应算法都可用'
        })

    # 保存上传的文件
    saved_files = []
    for file in files:
        if allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            saved_files.append(filepath)

    if not saved_files:
        return jsonify({
            'success': False,
            'error': '没有有效的QASM文件'
        })

    # 在后台线程中处理文件对比
    def compare_in_background():
        try:
            compare_algorithms_background(saved_files)
        except Exception as e:
            print(f"对比失败: {str(e)}")
            import traceback
            traceback.print_exc()
            processing_status['error'] = str(e)
            processing_status['is_processing'] = False

    thread = threading.Thread(target=compare_in_background)
    thread.daemon = True
    thread.start()

    return jsonify({
        'success': True,
        'message': f'开始算法对比，处理 {len(saved_files)} 个文件',
        'file_count': len(saved_files)
    })


def compare_algorithms_background(filepaths):
    """后台执行算法对比"""
    global processing_status

    try:
        # 初始化状态
        processing_status['is_processing'] = True
        processing_status['progress'] = 0
        processing_status['current_step'] = '初始化对比'
        processing_status['message'] = '准备运行算法对比...'

        # 步骤1: 清理旧文件
        processing_status['progress'] = 5
        processing_status['message'] = '清理旧文件...'
        if STANDARD_MODULE_AVAILABLE:
            from quantum_partition import cleanup_visualizations as standard_cleanup
            standard_cleanup()
        if ADAPTIVE_MODULE_AVAILABLE:
            from quantum_partition_zishiying1 import cleanup_visualizations as adaptive_cleanup
            adaptive_cleanup()

        # 步骤2: 初始化后端
        processing_status['progress'] = 10
        processing_status['current_step'] = '初始化量子后端'
        processing_status['message'] = '创建量子后端...'

        backend = FakeBrisbane()

        # 创建临时目录存放文件
        temp_dir = tempfile.mkdtemp()
        for filepath in filepaths:
            filename = os.path.basename(filepath)
            dest_path = os.path.join(temp_dir, filename)
            shutil.copy2(filepath, dest_path)

        # ========== 运行标准算法 ==========
        processing_status['progress'] = 20
        processing_status['current_step'] = '运行标准算法'
        processing_status['message'] = '标准算法：构建耦合图...'

        # 标准算法：构建耦合图
        from quantum_partition import (
            build_coupling_graph_from_backend as standard_build_graph,
            preprocess_coupling_graph as standard_preprocess,
            compute_metrics as standard_compute_metrics,
            dynamic_partition_disconnected as standard_dynamic_partition,
            load_qasm_circuits as standard_load_circuits,
            allocate_resources as standard_allocate_resources,
            calculate_parallel_pst as standard_calculate_pst
        )

        G_standard = standard_build_graph(backend)
        filtered_G_standard = standard_preprocess(G_standard, backend, node_percentile=85, edge_percentile=85)
        filtered_G_standard = standard_compute_metrics(filtered_G_standard)

        processing_status['progress'] = 25
        processing_status['message'] = '标准算法：动态分区...'
        standard_partitions = standard_dynamic_partition(filtered_G_standard)

        processing_status['progress'] = 30
        processing_status['message'] = '标准算法：加载线路...'
        standard_circuits = standard_load_circuits(temp_dir, None)

        if not standard_circuits:
            raise Exception("没有找到有效的QASM线路")

        processing_status['progress'] = 35
        processing_status['message'] = '标准算法：分配资源...'
        standard_allocations = standard_allocate_resources(standard_circuits, standard_partitions, filtered_G_standard)

        if not standard_allocations:
            raise Exception("标准算法资源分配失败")

        processing_status['progress'] = 40
        processing_status['message'] = '标准算法：执行线路...'
        standard_circuits_to_run = [a[0] for a in standard_allocations]
        standard_layouts = [a[1] for a in standard_allocations]
        standard_partitions_list = [a[2] for a in standard_allocations]

        # 创建标准算法的噪声模型
        from quantum_partition import create_parallel_error_model as standard_create_error_model
        from qiskit_aer import AerSimulator
        standard_noise_model = standard_create_error_model(backend)
        standard_noise_backend = AerSimulator.from_backend(backend)
        standard_noise_backend.set_options(noise_model=standard_noise_model)

        standard_psts, standard_depths = standard_calculate_pst(
            standard_circuits_to_run, standard_noise_backend, standard_layouts, standard_partitions_list, G_standard
        )

        # ========== 运行自适应算法 ==========
        processing_status['progress'] = 50
        processing_status['current_step'] = '运行自适应算法'
        processing_status['message'] = '自适应算法：构建耦合图...'

        from quantum_partition_zishiying1 import (
            build_coupling_graph_from_backend as adaptive_build_graph,
            preprocess_coupling_graph as adaptive_preprocess,
            compute_metrics as adaptive_compute_metrics,
            dynamic_partition_disconnected as adaptive_dynamic_partition,
            load_qasm_circuits as adaptive_load_circuits,
            allocate_resources as adaptive_allocate_resources,
            calculate_parallel_pst as adaptive_calculate_pst
        )

        G_adaptive = adaptive_build_graph(backend)
        filtered_G_adaptive = adaptive_preprocess(G_adaptive, backend, node_percentile=85, edge_percentile=85)
        filtered_G_adaptive = adaptive_compute_metrics(filtered_G_adaptive)

        processing_status['progress'] = 55
        processing_status['message'] = '自适应算法：动态分区...'
        adaptive_partitions = adaptive_dynamic_partition(filtered_G_adaptive)

        processing_status['progress'] = 60
        processing_status['message'] = '自适应算法：加载线路...'
        adaptive_circuits = adaptive_load_circuits(temp_dir, None)

        processing_status['progress'] = 65
        processing_status['message'] = '自适应算法：分配资源...'
        adaptive_allocations = adaptive_allocate_resources(adaptive_circuits, adaptive_partitions, filtered_G_adaptive)

        if not adaptive_allocations:
            raise Exception("自适应算法资源分配失败")

        processing_status['progress'] = 70
        processing_status['message'] = '自适应算法：执行线路...'
        adaptive_circuits_to_run = [a[0] for a in adaptive_allocations]
        adaptive_layouts = [a[1] for a in adaptive_allocations]
        adaptive_partitions_list = [a[2] for a in adaptive_allocations]

        # 创建自适应算法的噪声模型
        from quantum_partition_zishiying1 import create_parallel_error_model as adaptive_create_error_model
        adaptive_noise_model = adaptive_create_error_model(backend)
        adaptive_noise_backend = AerSimulator.from_backend(backend)
        adaptive_noise_backend.set_options(noise_model=adaptive_noise_model)

        adaptive_psts, adaptive_depths = adaptive_calculate_pst(
            adaptive_circuits_to_run, adaptive_noise_backend, adaptive_layouts, adaptive_partitions_list, G_adaptive
        )

        # ========== 生成对比图表 ==========
        processing_status['progress'] = 80
        processing_status['current_step'] = '生成对比图表'
        processing_status['message'] = '生成算法对比结果...'

        # 生成对比图表
        compare_results_png = "compare_results.png"
        generate_comparison_chart(
            standard_circuits_to_run,
            standard_psts,
            standard_depths,
            adaptive_psts,
            adaptive_depths,
            save_path=compare_results_png
        )

        # 收集结果
        processing_status['progress'] = 90
        processing_status['message'] = '整理结果...'

        # 获取所有线路名称（取并集）
        all_circuit_names = list(set(
            [c.name for c in standard_circuits_to_run] +
            [c.name for c in adaptive_circuits_to_run]
        ))

        # 整理PST值对比数据
        pst_comparison = []
        for circuit_name in all_circuit_names:
            std_idx = next((i for i, c in enumerate(standard_circuits_to_run) if c.name == circuit_name), None)
            adp_idx = next((i for i, c in enumerate(adaptive_circuits_to_run) if c.name == circuit_name), None)

            pst_comparison.append({
                'circuit': circuit_name,
                'standard_pst': float(standard_psts[std_idx]) if std_idx is not None else None,
                'adaptive_pst': float(adaptive_psts[adp_idx]) if adp_idx is not None else None,
                'standard_depth': int(standard_depths[std_idx]) if std_idx is not None else None,
                'adaptive_depth': int(adaptive_depths[adp_idx]) if adp_idx is not None else None
            })

        # 计算平均PST
        avg_standard_pst = sum(standard_psts) / len(standard_psts) if standard_psts else 0
        avg_adaptive_pst = sum(adaptive_psts) / len(adaptive_psts) if adaptive_psts else 0

        # 计算提升百分比
        improvement = ((avg_adaptive_pst - avg_standard_pst) / avg_standard_pst * 100) if avg_standard_pst > 0 else 0

        # 步骤10: 完成
        processing_status['progress'] = 100
        processing_status['current_step'] = '完成'
        processing_status['message'] = '对比完成'

        result = {
            'success': True,
            'algorithm': 'compare',
            'standard': {
                'circuits_processed': len(standard_circuits_to_run),
                'circuit_names': [c.name for c in standard_circuits_to_run],
                'pst_values': [float(p) for p in standard_psts],
                'mapped_depths': [int(d) for d in standard_depths],
                'avg_pst': float(avg_standard_pst),
                'partitions': [sorted(p) for p in standard_partitions]
            },
            'adaptive': {
                'circuits_processed': len(adaptive_circuits_to_run),
                'circuit_names': [c.name for c in adaptive_circuits_to_run],
                'pst_values': [float(p) for p in adaptive_psts],
                'mapped_depths': [int(d) for d in adaptive_depths],
                'avg_pst': float(avg_adaptive_pst),
                'partitions': [sorted(p) for p in adaptive_partitions]
            },
            'comparison': {
                'pst_data': pst_comparison,
                'avg_standard_pst': float(avg_standard_pst),
                'avg_adaptive_pst': float(avg_adaptive_pst),
                'improvement': float(improvement),
                'chart_file': compare_results_png
            },
            'gif_files': [compare_results_png]
        }

        processing_status['result'] = result
        processing_status['gif_files'] = [compare_results_png]

        # 清理临时目录
        shutil.rmtree(temp_dir)

        return result

    except Exception as e:
        processing_status['error'] = str(e)
        raise
    finally:
        processing_status['is_processing'] = False


def generate_comparison_chart(standard_circuits, standard_psts, standard_depths,
                              adaptive_psts, adaptive_depths, save_path="compare_results.png"):
    """生成算法对比图表"""
    import matplotlib.pyplot as plt
    import numpy as np

    # 获取线路名称
    circuit_names = [c.name for c in standard_circuits]

    # 设置图表
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

    # 上半部分：PST值对比柱状图
    x = np.arange(len(circuit_names))
    width = 0.35

    bars1 = ax1.bar(x - width / 2, standard_psts, width, label='标准算法', color='#3a5afd', alpha=0.8)
    bars2 = ax1.bar(x + width / 2, adaptive_psts, width, label='自适应算法', color='#00a8ff', alpha=0.8)

    ax1.set_xlabel('线路文件')
    ax1.set_ylabel('PST值')
    ax1.set_title('标准算法 vs 自适应算法 - PST值对比')
    ax1.set_xticks(x)
    ax1.set_xticklabels(circuit_names, rotation=45, ha='right')
    ax1.legend()
    ax1.set_ylim(0, 1)
    ax1.grid(True, alpha=0.3)

    # 在柱状图上添加数值标签
    for i, (bar1, bar2) in enumerate(zip(bars1, bars2)):
        height1 = bar1.get_height()
        height2 = bar2.get_height()
        ax1.text(bar1.get_x() + bar1.get_width() / 2., height1 + 0.02,
                 f'{height1:.3f}', ha='center', va='bottom', fontsize=9)
        ax1.text(bar2.get_x() + bar2.get_width() / 2., height2 + 0.02,
                 f'{height2:.3f}', ha='center', va='bottom', fontsize=9)

    # 下半部分：深度对比折线图
    ax2.plot(x, standard_depths, 'o-', label='标准算法深度', color='#3a5afd', linewidth=2, markersize=8)
    ax2.plot(x, adaptive_depths, 's-', label='自适应算法深度', color='#00a8ff', linewidth=2, markersize=8)

    ax2.set_xlabel('线路文件')
    ax2.set_ylabel('线路深度')
    ax2.set_title('线路深度对比')
    ax2.set_xticks(x)
    ax2.set_xticklabels(circuit_names, rotation=45, ha='right')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # 添加统计信息
    avg_std_pst = sum(standard_psts) / len(standard_psts)
    avg_adp_pst = sum(adaptive_psts) / len(adaptive_psts)
    improvement = ((avg_adp_pst - avg_std_pst) / avg_std_pst * 100) if avg_std_pst > 0 else 0

    stats_text = f'平均PST - 标准: {avg_std_pst:.4f}, 自适应: {avg_adp_pst:.4f}\n'
    stats_text += f'性能提升: {improvement:+.2f}%'

    fig.text(0.5, 0.01, stats_text, ha='center', fontsize=12,
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()
    plt.subplots_adjust(bottom=0.15)
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
@app.route('/get_file/<filename>')
@login_required
def get_file(filename):
    """获取生成的文件"""
    safe_filename = secure_filename(filename)
    filepath = os.path.join('.', safe_filename)

    if os.path.exists(filepath):
        if filename.endswith('.gif'):
            return send_file(filepath, mimetype='image/gif')
        elif filename.endswith('.png'):
            return send_file(filepath, mimetype='image/png')
        else:
            return send_file(filepath)

    return jsonify({'error': '文件不存在'}), 404


@app.route('/reset', methods=['POST'])
@login_required
def reset():
    """重置处理状态"""
    global processing_status
    processing_status = {
        'is_processing': False,
        'progress': 0,
        'current_step': '',
        'message': '',
        'result': None,
        'error': None,
        'files': [],
        'gif_files': []
    }
    return jsonify({'success': True})


if __name__ == '__main__':
    print("=" * 70)
    print("量子线路并行分区可视化系统")
    print("=" * 70)
    print(f"标准算法模块: {'✓ 已加载' if STANDARD_MODULE_AVAILABLE else '✗ 未加载'}")
    print(f"自适应算法模块: {'✓ 已加载' if ADAPTIVE_MODULE_AVAILABLE else '✗ 未加载'}")
    print(f"数据库: {'✓ 已连接' if os.path.exists('users.db') else '✗ 未连接'}")
    print(f"上传目录: {app.config['UPLOAD_FOLDER']}")
    print(f"默认用户: admin / admin123")
    print("\n访问地址:")
    print("  http://127.0.0.1:5000")
    print("  http://localhost:5000")
    print("\n功能说明:")
    print("  1. 首次访问需要登录 (admin/admin123)")
    print("  2. 首页使用 index.html 模板")
    print("  3. 在/simulator页面可上传QASM文件进行量子线路分析")
    print("  4. 支持两种算法: 标准分区算法 和 自适应分区算法")
    print("  5. 自动生成分区和映射GIF动画")
    print("  6. 并行执行线路并计算PST值")
    print("  7. 下载生成的可视化结果")
    print("=" * 70)

    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)