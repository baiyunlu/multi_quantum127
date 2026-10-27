// 文件上传和预览功能
$(document).ready(function() {
    // 检查模块状态
    checkModuleStatus();

    // 初始化悬浮二级菜单
    initHoverSubmenu();

    // 文件选择预览
    $('#qasmFiles').on('change', function(e) {
        const files = e.target.files;
        const fileList = $('#fileList');
        const filePreview = $('#filePreview');

        if (files.length > 0) {
            fileList.empty();
            filePreview.show();

            for (let i = 0; i < files.length; i++) {
                const file = files[i];
                const fileSize = (file.size / 1024).toFixed(2);
                const fileItem = `
                    <div class="file-list-item">
                        <i class="fas fa-file-code me-2 text-primary"></i>
                        ${file.name} <span class="text-muted">(${fileSize} KB)</span>
                    </div>
                `;
                fileList.append(fileItem);
            }
        } else {
            filePreview.hide();
        }
    });

    // 表单提交处理
    $('#uploadForm').submit(function(e) {
        e.preventDefault();

        const form = $(this)[0];
        const formData = new FormData(form);
        const files = $('#qasmFiles')[0].files;

        if (files.length === 0) {
            alert('请选择至少一个QASM文件');
            return;
        }

        // 获取当前选中的算法
        const selectedAlgorithm = localStorage.getItem('selectedAlgorithm') || 'standard';
        formData.append('algorithm', selectedAlgorithm);

        // 显示进度区域
        $('#progressCard').show();
        $('#resultSection').hide();
        $('#errorAlert').hide();
        $('#detailedProgress').hide();
        $('#progressCard .card-header').removeClass('bg-danger');

        // 禁用提交按钮
        const submitBtn = $('#uploadForm button[type="submit"]');
        submitBtn.prop('disabled', true)
                .html('<i class="fas fa-spinner fa-spin me-2"></i>处理中...')
                .addClass('disabled');

        // 发送请求
        $.ajax({
            url: '/upload',
            type: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            success: function(response) {
                if (response.success) {
                    $('#detailedProgress').show();
                    startPolling();
                } else {
                    showError(response.error);
                    resetForm();
                }
            },
            error: function(xhr) {
                showError('上传失败: ' + (xhr.responseJSON?.error || '服务器错误'));
                resetForm();
            }
        });
    });

    // 新分析按钮
    $('#btnNewAnalysis').click(function() {
        if (confirm('确定要开始新的分析吗？当前结果将会被清除。')) {
            location.reload();
        }
    });
});

// ========== 鼠标悬浮右侧弹出二级菜单功能 ==========

function initHoverSubmenu() {
    // 加载保存的算法选择
    loadSavedAlgorithm();

    // 添加当前算法指示器
    addAlgorithmIndicator();

    // 悬浮菜单项点击处理
    $('.submenu-item').on('click', function(e) {
        e.preventDefault();

        const algo = $(this).data('algo');

        // 移除所有active类
        $('.submenu-item').removeClass('active');

        // 添加active类到当前选项
        $(this).addClass('active');

        // 保存选择并更新显示
        selectAlgorithm(algo);

        // 移动端点击后关闭菜单
        if (window.innerWidth <= 768) {
            setTimeout(() => {
                $('.hover-submenu').css('visibility', 'hidden');
            }, 200);
        }
    });

    // 桌面端悬浮效果增强
    if (window.innerWidth > 768) {
        $('.sidebar-item-has-children').hover(
            function() {
                // mouse enter - 箭头旋转
                $(this).find('.arrow-icon').css('transform', 'rotate(90deg)');
            },
            function() {
                // mouse leave - 箭头复位
                $(this).find('.arrow-icon').css('transform', 'rotate(0deg)');
            }
        );
    }

    // 防止菜单在鼠标快速移过时闪烁
    $('.hover-submenu').hover(
        function() {
            $(this).closest('.sidebar-item-has-children').addClass('hover-active');
        },
        function() {
            $(this).closest('.sidebar-item-has-children').removeClass('hover-active');
        }
    );

    // 键盘ESC关闭菜单
    $(document).on('keydown', function(e) {
        if (e.key === 'Escape') {
            $('.hover-submenu').css('visibility', 'hidden');
        }
    });
}

// 选择算法
function selectAlgorithm(algo) {
    localStorage.setItem('selectedAlgorithm', algo);
    updateAlgorithmIndicator(algo);
    updateUploadButtonText(algo);
    showAlgorithmNotification(algo);

    // 触发自定义事件
    $(document).trigger('algorithmChanged', [algo]);

    // 控制台输出
    console.log(`算法已切换为: ${getAlgorithmName(algo)}`);
}

// 获取算法名称
function getAlgorithmName(algo) {
    const names = {
        'standard': '标准分区算法',
        'adaptive': '自适应分区算法',
        'compare': '算法对比模式'
    };
    return names[algo] || '未知算法';
}

// 加载保存的算法
function loadSavedAlgorithm() {
    const savedAlgorithm = localStorage.getItem('selectedAlgorithm') || 'standard';

    // 设置active类
    $(`.submenu-item[data-algo="${savedAlgorithm}"]`).addClass('active');

    // 更新显示
    updateAlgorithmIndicator(savedAlgorithm);
    updateUploadButtonText(savedAlgorithm);
}

// 添加算法指示器
function addAlgorithmIndicator() {
    if ($('#currentAlgoIndicator').length > 0) return;

    const algoNames = {
        'standard': '标准分区算法',
        'adaptive': '自适应分区算法',
        'compare': '算法对比模式'
    };

    const algoIcons = {
        'standard': 'fa-microchip',
        'adaptive': 'fa-brain',
        'compare': 'fa-chart-line'
    };

    const savedAlgorithm = localStorage.getItem('selectedAlgorithm') || 'standard';

    const indicator = $(`
        <div class="current-algo-indicator" id="currentAlgoIndicator">
            <i class="fas ${algoIcons[savedAlgorithm]}"></i>
            <span class="algo-name">${algoNames[savedAlgorithm]}</span>
            <span class="badge">当前算法</span>
        </div>
    `);

    $('body').append(indicator);
}

// 更新算法指示器
function updateAlgorithmIndicator(algo) {
    const algoNames = {
        'standard': '标准分区算法',
        'adaptive': '自适应分区算法',
        'compare': '算法对比模式'
    };

    const algoIcons = {
        'standard': 'fa-microchip',
        'adaptive': 'fa-brain',
        'compare': 'fa-chart-line'
    };

    const indicator = $('#currentAlgoIndicator');
    if (indicator.length) {
        indicator.find('i').attr('class', `fas ${algoIcons[algo]}`);
        indicator.find('.algo-name').text(algoNames[algo]);
    }
}

// 更新上传按钮文本
function updateUploadButtonText(algo) {
    const uploadBtn = $('#uploadForm button[type="submit"]');
    if (uploadBtn.length && !uploadBtn.prop('disabled')) {
        const btnTexts = {
            'standard': '<i class="fas fa-microchip me-2"></i>使用标准算法分析',
            'adaptive': '<i class="fas fa-brain me-2"></i>使用自适应算法分析',
            'compare': '<i class="fas fa-chart-line me-2"></i>运行算法对比'
        };
        uploadBtn.html(btnTexts[algo]);
    }
}

// 显示算法切换通知
function showAlgorithmNotification(algo) {
    const algoNames = {
        'standard': '标准分区算法',
        'adaptive': '自适应分区算法',
        'compare': '算法对比模式'
    };

    const algoIcons = {
        'standard': 'fa-microchip',
        'adaptive': 'fa-brain',
        'compare': 'fa-chart-line'
    };

    // 移除旧的通知
    $('.algo-notification').remove();

    // 创建新通知
    const notification = $(`
        <div class="algo-notification">
            <i class="fas ${algoIcons[algo]}" style="color: var(--quantum-accent);"></i>
            <span>已切换到 <strong>${algoNames[algo]}</strong></span>
        </div>
    `);

    $('body').append(notification);

    // 2秒后自动消失
    setTimeout(() => {
        notification.fadeOut(300, function() {
            $(this).remove();
        });
    }, 2000);
}

// 修改表单提交，添加算法参数
$(document).on('submit', '#uploadForm', function(e) {
    const form = $(this);
    const algo = localStorage.getItem('selectedAlgorithm') || 'standard';

    // 删除已有的algorithm字段
    form.find('input[name="algorithm"]').remove();

    // 添加新的algorithm字段
    form.append(`<input type="hidden" name="algorithm" value="${algo}">`);
});

// ========== 其他功能函数 ==========

// 检查模块状态
function checkModuleStatus() {
    fetch('/check_module')
        .then(response => response.json())
        .then(data => {
            const statusText = $('#moduleStatusText');
            const moduleAlert = $('#moduleAlert');
            const moduleMessage = $('#moduleMessage');

            if (data.available) {
                statusText.html('<span class="text-success"><i class="fas fa-check-circle me-1"></i>量子模块已加载</span>');
            } else {
                statusText.html('<span class="text-danger"><i class="fas fa-times-circle me-1"></i>量子模块未加载</span>');
                moduleMessage.text(data.message);
                moduleAlert.show();
                $('#uploadForm button').prop('disabled', true)
                    .html('<i class="fas fa-exclamation-triangle me-2"></i>系统不可用')
                    .removeClass('btn-primary').addClass('btn-secondary');
            }
        })
        .catch(error => {
            console.error('检查模块状态失败:', error);
            $('#moduleStatusText').html('<span class="text-warning"><i class="fas fa-exclamation-triangle me-1"></i>状态检查失败</span>');
        });
}

// 轮询处理状态
let pollingInterval = null;
let stepHistory = [];

function startPolling() {
    if (pollingInterval) clearInterval(pollingInterval);
    stepHistory = [];
    pollingInterval = setInterval(pollStatus, 1000);
}

function pollStatus() {
    $.get('/status')
        .then(updateProgress)
        .catch(error => {
            console.error('轮询错误:', error);
            if (pollingInterval) clearInterval(pollingInterval);
        });
}

// 更新进度显示
function updateProgress(status) {
    $('#currentStep').text(status.current_step || '处理中...');
    $('#message').text(status.message || '');
    $('#progressPercent').text(status.progress + '%');
    $('#progressBar')
        .css('width', status.progress + '%')
        .attr('aria-valuenow', status.progress);

    if (status.current_step && !stepHistory.includes(status.current_step)) {
        stepHistory.push(status.current_step);
        addStepDetail(status.current_step, status.message, status.progress);
    }

    if (status.error) {
        showError(status.error);
        clearInterval(pollingInterval);
        resetForm();
    }

    if (status.result) {
        clearInterval(pollingInterval);
        showResults(status.result);
    }
}

// 添加步骤详情
function addStepDetail(step, message, progress) {
    const stepDetails = $('#stepDetails');
    const timestamp = new Date().toLocaleTimeString();
    const stepItem = `
        <div class="d-flex align-items-center mb-2">
            <div class="me-3">
                <i class="fas fa-check-circle text-success"></i>
            </div>
            <div>
                <div><strong>${step}</strong> <small class="text-muted">${timestamp}</small></div>
                <div class="small">${message}</div>
            </div>
            <div class="ms-auto">
                <span class="badge bg-info">${progress}%</span>
            </div>
        </div>
    `;
    stepDetails.append(stepItem);
}

// 显示错误
function showError(message) {
    $('#errorMessage').text(message);
    $('#errorAlert').show();
    $('#progressCard .card-header').addClass('bg-danger text-white');
}

// 重置表单
function resetForm() {
    const submitBtn = $('#uploadForm button[type="submit"]');
    submitBtn.prop('disabled', false)
            .html('<i class="fas fa-rocket me-2"></i>开始量子线路分析')
            .removeClass('disabled');
    updateUploadButtonText(localStorage.getItem('selectedAlgorithm') || 'standard');
}

// 显示结果
function showResults(result) {
    $('#progressCard').hide();
    $('#resultSection').show();

    showPartitionOverview(result.partitions);
    showGifFiles(result.gif_files);
    showResultTable(result);
    showStatistics(result);
    setupDownloadButton(result);

    // 如果是对比模式，显示对比结果
    if (localStorage.getItem('selectedAlgorithm') === 'compare' && result.comparison) {
        showComparisonResults(result);
    }
}

// 显示分区概览
function showPartitionOverview(partitions) {
    const container = $('#partitionOverview');
    container.empty();

    if (partitions && partitions.length > 0) {
        partitions.forEach((part, index) => {
            const colSize = partitions.length > 2 ? '4' : '6';
            const col = $(`
                <div class="col-md-${colSize} mb-3">
                    <div class="card">
                        <div class="card-body">
                            <h6 class="card-title">
                                <i class="fas fa-microchip me-2 text-primary"></i>
                                分区 ${index + 1}
                            </h6>
                            <p class="mb-2">量子比特数: <strong>${part.length}</strong></p>
                            <div class="mb-2">
                                <small class="text-muted">量子比特索引:</small>
                                <div class="d-flex flex-wrap gap-1 mt-1">
                                    ${part.map(qbit => `<span class="badge bg-secondary">Q${qbit}</span>`).join('')}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `);
            container.append(col);
        });
    }
}

// 显示GIF文件
function showGifFiles(gifFiles) {
    const container = $('#gifContainer');
    container.empty();

    if (gifFiles && gifFiles.length > 0) {
        const partitions = gifFiles.filter(f => f.includes('partitions'));
        const mappings = gifFiles.filter(f => f.includes('mapping'));
        const results = gifFiles.filter(f => f.includes('results') || f.includes('.png'));

        if (partitions.length > 0) {
            const col = $(`
                <div class="col-md-12 mb-4">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="fas fa-sitemap me-2"></i>量子比特分区动画</h5>
                        </div>
                        <div class="card-body text-center">
                            <div class="gif-preview">
                                <img src="/get_file/${partitions[0]}" class="img-fluid preview-image" alt="分区动画">
                            </div>
                        </div>
                    </div>
                </div>
            `);
            container.append(col);
        }

        if (mappings.length > 0) {
            mappings.forEach((file, index) => {
                const col = $(`
                    <div class="col-md-6 mb-4">
                        <div class="card h-100">
                            <div class="card-header">
                                <h6 class="mb-0">线路映射动画 ${index + 1}</h6>
                            </div>
                            <div class="card-body text-center">
                                <div class="gif-preview">
                                    <img src="/get_file/${file}" class="img-fluid preview-image" alt="映射动画">
                                </div>
                            </div>
                        </div>
                    </div>
                `);
                container.append(col);
            });
        }

        if (results.length > 0) {
            const col = $(`
                <div class="col-md-12 mb-4">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="fas fa-chart-bar me-2"></i>执行结果分析图表</h5>
                        </div>
                        <div class="card-body text-center">
                            <div class="gif-preview">
                                <img src="/get_file/${results[0]}" class="img-fluid preview-image" alt="结果图表">
                            </div>
                        </div>
                    </div>
                </div>
            `);
            container.append(col);
        }
    }
}

// 显示结果表格
function showResultTable(result) {
    const tableBody = $('#resultTable');
    tableBody.empty();

    if (result.circuit_names && result.pst_values) {
        result.circuit_names.forEach((name, index) => {
            const pst = result.pst_values[index];
            const mappedDepth = result.mapped_depths?.[index] || '-';

            let pstClass, pstText;
            if (pst > 0.7) {
                pstClass = 'bg-success';
                pstText = '高';
            } else if (pst > 0.4) {
                pstClass = 'bg-warning';
                pstText = '中';
            } else {
                pstClass = 'bg-danger';
                pstText = '低';
            }

            const row = $(`
                <tr>
                    <td>
                        <i class="fas fa-file-code me-2 text-primary"></i>
                        ${name}
                    </td>
                    <td>-</td>
                    <td>${mappedDepth}</td>
                    <td>
                        <span class="badge ${pstClass}">${pst.toFixed(4)}</span>
                        <small class="text-muted ms-2">${pstText}性能</small>
                    </td>
                    <td>
                        <span class="badge bg-success">
                            <i class="fas fa-check me-1"></i>完成
                        </span>
                    </td>
                </tr>
            `);
            tableBody.append(row);
        });
    }
}

// 显示统计信息
function showStatistics(result) {
    const performanceStats = $('#performanceStats');
    const executionInfo = $('#executionInfo');

    if (result.pst_values && result.pst_values.length > 0) {
        const avgPST = result.pst_values.reduce((a, b) => a + b, 0) / result.pst_values.length;
        const maxPST = Math.max(...result.pst_values);
        const minPST = Math.min(...result.pst_values);

        performanceStats.html(`
            <div class="mb-2">
                <small class="text-muted">平均PST:</small>
                <div class="h5 ${avgPST > 0.7 ? 'text-success' : avgPST > 0.4 ? 'text-warning' : 'text-danger'}">
                    ${avgPST.toFixed(4)}
                </div>
            </div>
            <div class="mb-2">
                <small class="text-muted">最高PST:</small>
                <div>${maxPST.toFixed(4)}</div>
            </div>
            <div>
                <small class="text-muted">最低PST:</small>
                <div>${minPST.toFixed(4)}</div>
            </div>
        `);
    }

    executionInfo.html(`
        <div class="mb-2">
            <small class="text-muted">处理线路数:</small>
            <div class="h5">${result.circuits_processed || 0}</div>
        </div>
        <div class="mb-2">
            <small class="text-muted">分区数量:</small>
            <div>${result.partitions?.length || 0}</div>
        </div>
        <div class="mb-2">
            <small class="text-muted">资源分配:</small>
            <div>${result.allocations_count || 0} 个线路已分配</div>
        </div>
        <div>
            <small class="text-muted">生成文件:</small>
            <div>${result.gif_files?.length || 0} 个可视化文件</div>
        </div>
    `);
}

// 显示对比结果
function showComparisonResults(result) {
    if ($('#compareResultsSection').length === 0) {
        addComparisonSection();
    }

    $('#compareResultsSection').show();

    if (result.comparison) {
        $('#stdAvgPst').text(result.comparison.standard?.avgPST.toFixed(4) || '-');
        $('#stdDepthInc').text(result.comparison.standard?.avgDepthInc || '-');
        $('#stdTime').text(result.comparison.standard?.executionTime ? result.comparison.standard.executionTime + 's' : '-');

        $('#adaAvgPst').text(result.comparison.adaptive?.avgPST.toFixed(4) || '-');
        $('#adaDepthInc').text(result.comparison.adaptive?.avgDepthInc || '-');
        $('#adaTime').text(result.comparison.adaptive?.executionTime ? result.comparison.adaptive.executionTime + 's' : '-');

        if (result.comparison.standard && result.comparison.adaptive) {
            const improvement = ((result.comparison.adaptive.avgPST - result.comparison.standard.avgPST) /
                                result.comparison.standard.avgPST * 100).toFixed(1);

            $('#improvementBar')
                .css('width', Math.max(0, improvement) + '%')
                .text(improvement + '%');
        }
    }
}

// 添加对比结果区域
function addComparisonSection() {
    const section = $(`
        <div id="compareResultsSection" class="comparison-results" style="display: none;">
            <h5 class="mb-4"><i class="fas fa-chart-line me-2" style="color: var(--quantum-accent);"></i>算法对比结果</h5>
            <div class="row">
                <div class="col-md-6 mb-3">
                    <div class="comparison-metric standard">
                        <div class="label">标准算法 平均PST</div>
                        <div class="value" id="stdAvgPst">-</div>
                        <div class="label mt-2">平均深度增加</div>
                        <div class="value" id="stdDepthInc">-</div>
                        <div class="label mt-2">执行时间</div>
                        <div class="value" id="stdTime">-</div>
                    </div>
                </div>
                <div class="col-md-6 mb-3">
                    <div class="comparison-metric adaptive">
                        <div class="label">自适应算法 平均PST</div>
                        <div class="value" id="adaAvgPst">-</div>
                        <div class="label mt-2">平均深度增加</div>
                        <div class="value" id="adaDepthInc">-</div>
                        <div class="label mt-2">执行时间</div>
                        <div class="value" id="adaTime">-</div>
                    </div>
                </div>
            </div>
            <div class="mt-4">
                <div class="label mb-2">性能提升</div>
                <div class="improvement-bar">
                    <div id="improvementBar" class="bar" style="width: 0%">0%</div>
                </div>
            </div>
        </div>
    `);

    $('#resultSection').append(section);
}

// 设置下载按钮
function setupDownloadButton(result) {
    $('#btnDownload').off('click').on('click', function() {
        if (result.gif_files && result.gif_files.length > 0) {
            let downloadedCount = 0;

            result.gif_files.forEach((file, index) => {
                setTimeout(() => {
                    const link = document.createElement('a');
                    link.href = `/get_file/${file}`;
                    link.download = file;
                    link.style.display = 'none';
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);

                    downloadedCount++;

                    if (downloadedCount === result.gif_files.length) {
                        setTimeout(() => {
                            const dataStr = JSON.stringify(result, null, 2);
                            const dataBlob = new Blob([dataStr], {type: 'application/json'});
                            const jsonUrl = URL.createObjectURL(dataBlob);

                            const jsonLink = document.createElement('a');
                            jsonLink.href = jsonUrl;
                            jsonLink.download = 'quantum_analysis_results.json';
                            document.body.appendChild(jsonLink);
                            jsonLink.click();
                            document.body.removeChild(jsonLink);

                            alert(`成功下载 ${result.gif_files.length + 1} 个文件`);
                        }, 500);
                    }
                }, index * 500);
            });
        } else {
            alert('没有可下载的文件');
        }
    });
}

// 页面卸载时清理
$(window).on('beforeunload', function() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
    }
});