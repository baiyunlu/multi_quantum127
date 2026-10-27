// 文件上传和预览功能
$(document).ready(function() {
    // 检查模块状态
    checkModuleStatus();

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
                    // 显示详细进度
                    $('#detailedProgress').show();
                    // 开始轮询状态
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
    // 更新基础信息
    $('#currentStep').text(status.current_step || '处理中...');
    $('#message').text(status.message || '');
    $('#progressPercent').text(status.progress + '%');
    $('#progressBar')
        .css('width', status.progress + '%')
        .attr('aria-valuenow', status.progress);

    // 记录步骤历史
    if (status.current_step && !stepHistory.includes(status.current_step)) {
        stepHistory.push(status.current_step);
        addStepDetail(status.current_step, status.message, status.progress);
    }

    // 错误处理
    if (status.error) {
        showError(status.error);
        clearInterval(pollingInterval);
        resetForm();
    }

    // 结果处理
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
}

// 显示结果
function showResults(result) {
    $('#progressCard').hide();
    $('#resultSection').show();

    // 显示分区概览
    showPartitionOverview(result.partitions);

    // 显示GIF文件
    showGifFiles(result.gif_files);

    // 显示结果表格
    showResultTable(result);

    // 显示统计信息
    showStatistics(result);

    // 设置下载按钮
    setupDownloadButton(result);
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
        // 分组显示：分区动画、映射动画、结果图表
        const partitions = gifFiles.filter(f => f.includes('partitions'));
        const mappings = gifFiles.filter(f => f.includes('mapping'));
        const results = gifFiles.filter(f => f.includes('results') || f.includes('.png'));

        // 显示分区动画
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

        // 显示映射动画
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

        // 显示结果图表
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
        let totalPST = 0;

        result.circuit_names.forEach((name, index) => {
            const pst = result.pst_values[index];
            totalPST += pst;

            const mappedDepth = result.mapped_depths?.[index] || '-';

            // 根据PST值设置样式
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

    // 性能统计
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

    // 执行信息
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

// 设置下载按钮
function setupDownloadButton(result) {
    $('#btnDownload').off('click').on('click', function() {
        if (result.gif_files && result.gif_files.length > 0) {
            // 下载所有GIF和PNG文件
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

                    // 所有文件下载完成后，下载JSON
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

                            // 通知用户
                            alert(`成功下载 ${result.gif_files.length + 1} 个文件\n包含：${result.gif_files.length}个可视化文件 + 1个JSON结果文件`);
                        }, 500);
                    }
                }, index * 500); // 避免同时下载所有文件
            });
        } else {
            alert('没有可下载的文件');
        }
    });
}