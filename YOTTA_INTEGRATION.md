# Yotta 接入 SkyPilot 实现方案

## 📋 项目概览

当前项目是 SkyPilot 的 fork，用于开发 Yotta 云提供商集成。Yotta 基于 Kubernetes pods 作为底层基础设施。

**状态**: ✅ 85%完成 - 核心功能已实现，缺少catalog数据

---

## 🏗️ 架构设计

### SkyPilot 云提供商三层架构

```
┌─────────────────────────────────────┐
│ 1. Cloud Interface Layer            │
│    sky/clouds/yotta.py              │ ← 资源定义、定价、区域
├─────────────────────────────────────┤
│ 2. Provisioner Layer                │
│    sky/provision/yotta/             │ ← VM/Pod 生命周期管理
│    ├── instance.py                   │
│    ├── yotta_utils.py (API Client)  │
│    └── config.py                     │
├─────────────────────────────────────┤
│ 3. Template Layer                   │
│    sky/templates/yotta-ray.yml.j2   │ ← Ray 集群配置
└─────────────────────────────────────┘
```

### Yotta 架构特点

- **底层**: Kubernetes pods (类似 SkyPilot 的 K8s cloud)
- **Provisioner 版本**: SKYPILOT (v3, 最新版)
- **API Endpoint**: `https://api.dev.yottalabs.ai/sdk/api`
- **认证**: `~/.yotta/credentials` (userId + apikey)

---

## 📂 已实现的组件

### ✅ 1. Cloud Provider (`sky/clouds/yotta.py` - 305行)

**注册到系统**:
```python
@registry.CLOUD_REGISTRY.register
class Yotta(clouds.Cloud):
    _REPR = 'Yotta'
    PROVISIONER_VERSION = clouds.ProvisionerVersion.SKYPILOT
```

**不支持的特性**:
- ❌ STOP (无法停止实例)
- ❌ CUSTOM_DISK_TIER
- ❌ STORAGE_MOUNTING (使用 COPY 模式)
- ❌ MULTI_NODE (待确认 Yotta API 是否支持)

**实例类型** (来自 `yotta_utils.py`):
```python
GPU_NAME_MAP = {
    '1x_A10_SECURE': 'NVIDIA_A10_24G',
    '1x_L4_SECURE': 'NVIDIA_L4_24G',
    '2x_L4_SECURE': 'NVIDIA_L4_24G',
}
```

### ✅ 2. Provisioner (`sky/provision/yotta/`)

**文件结构**:
```
yotta/
├── __init__.py          # 模块导出
├── config.py            # Bootstrap 配置
├── instance.py          # 实例生命周期 (280行)
└── yotta_utils.py       # API 客户端 (302行)
```

**API 客户端功能** (`YottaClient`):
```python
check_api_key()              # 验证凭证
get_pod_by_labels()          # 查询集群实例
launch()                     # 创建新 pods
destroy_pods()               # 销毁 pods
get_or_add_ssh_key()         # SSH密钥管理
```

**Pod 状态映射**:
```
Yotta PodStatus          → SkyPilot ClusterStatus
─────────────────────────────────────────────────
INITIALIZE (0)           → INIT
RUNNING (1)              → UP
PAUSING (2)              → UP
PAUSED (3)               → STOPPED
TERMINATING (4)          → UP
TERMINATED (5)           → STOPPED
FAILED (6)               → STOPPED
```

### ✅ 3. 认证系统 (`sky/authentication.py`)

**集成点** (Line 598-610):
```python
def setup_yotta_authentication(config: Dict[str, Any]) -> Dict[str, Any]:
    """Sets up SSH authentication for Yotta.
    - Generates SSH key pair if not exists
    - Adds public key to Yotta account
    """
    _, public_key_path = get_or_generate_keys()
    with open(public_key_path, 'r', encoding='UTF-8') as pub_key_file:
        public_key = pub_key_file.read().strip()
        yotta_client.get_or_add_ssh_key(public_key)
    
    config['auth']['ssh_public_key'] = public_key_path
    return configure_ssh_info(config)
```

**认证流程**:
```
User: sky launch
    ↓
backend_utils.write_cluster_config()
    ↓
auth.setup_yotta_authentication()
    ↓
yotta_client.get_or_add_ssh_key()
    ↓
API: POST /compute/create/publicKey
```

### ✅ 4. Catalog 模块 (`sky/catalog/yotta_catalog.py`)

已实现所有必需函数：
- `instance_type_exists()`
- `validate_region_zone()`
- `get_hourly_cost()`
- `get_vcpus_mem_from_instance_type()`
- `get_default_instance_type()`
- 等等...

### ✅ 5. Ray 模板 (`sky/templates/yotta-ray.yml.j2` - 102行)

```yaml
provider:
  type: external
  module: sky.provision.yotta
  region: "{{region}}"
  availability_zone: "{{availability_zone}}"
  disable_launch_config_check: true

auth:
  ssh_user: ubuntu
```

---

## ⚠️ 缺失的组件

### 1. Catalog 数据文件 ✅ 已创建

**位置**: `~/.sky/catalogs/v7/yotta/vms.csv`

**格式** (基于 RunPod):
```csv
InstanceType,AcceleratorName,AcceleratorCount,vCPUs,MemoryGiB,GpuInfo,Region,SpotPrice,Price,AvailabilityZone
1x_A10_SECURE,A10,1.0,32.0,128.0,A10:24GB,us-central1,,,us-central1-a
1x_L4_SECURE,L4,1.0,16.0,64.0,L4:24GB,us-central1,,,us-central1-a
2x_L4_SECURE,L4,2.0,32.0,128.0,L4:24GB,us-central1,,,us-central1-a
```

**注意**: 
- SpotPrice 和 Price 留空（Yotta 不支持 spot）
- 需要从 Yotta API 或配置文件获取真实数据

### 2. Data Fetcher (可选)

**位置**: `sky/catalog/data_fetchers/fetch_yotta.py`

**用途**: 自动从 Yotta API 获取并更新 catalog 数据

**参考**: `fetch_runpod.py`, `fetch_lambda.py`

### 3. setup.py 依赖

**需要添加**:
```python
extras_require = {
    ...
    'yotta': ['requests'],  # Yotta API 所需
    ...
}
```

---

## 🔧 开发环境设置

### 为什么需要隔离环境？

作为contributor，你当前 `~/.sky` 目录是由系统安装的 SkyPilot 创建的。使用虚拟环境的好处：

✅ **开发环境隔离**: 代码修改立即生效，不影响系统版本  
✅ **editable install**: `pip install -e .` 使修改无需重新安装  
✅ **独立配置**: 可以使用独立的 SkyPilot 配置  
✅ **无冲突测试**: 测试 Yotta 不会破坏现有环境

### 环境已创建 ✅

```bash
# 1. 虚拟环境已创建并安装
venv-dev/  # 开发专用虚拟环境

# 2. 启动开发环境
./start-dev.sh  # 自动激活环境并显示状态

# 3. 或者手动激活
source venv-dev/bin/activate

# 4. 退出
deactivate
```

### 配置凭证

创建 `~/.yotta/credentials`:
```
userId=<your-user-id>
apikey=<your-api-key>
```

---

## 🚀 测试流程

### 1. 基础测试

```bash
# 激活开发环境
source venv-dev/bin/activate

# 检查 Yotta 是否被识别
sky check

# 查看 Yotta GPU 资源
sky show-gpus --cloud yotta

# 验证 catalog
python3 -c "from sky.catalog import yotta_catalog; print(yotta_catalog._df)"
```

### 2. 启动简单示例

创建 `test-yotta.yaml`:
```yaml
resources:
  cloud: yotta
  instance_type: 1x_L4_SECURE
  
setup: |
  echo "Hello from Yotta!"
  nvidia-smi

run: |
  python3 -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

运行:
```bash
sky launch -c yotta-test test-yotta.yaml
```

### 3. 验证核心功能

```bash
# 查看集群状态
sky status

# SSH 到集群
sky ssh yotta-test

# 查看日志
sky logs yotta-test

# 停止集群 (注意: Yotta 不支持 stop)
sky down yotta-test
```

---

## 📋 接入点总结

### Yotta → SkyPilot SaaS API 的接入点

| 接入点 | 文件 | 功能 | API 端点 |
|--------|------|------|----------|
| 1. 认证 | `sky/authentication.py` | SSH 密钥注册 | `POST /compute/create/publicKey` |
| 2. 创建实例 | `sky/provision/yotta/instance.py` | Pod 创建 | `POST /compute/create` |
| 3. 查询状态 | `sky/provision/yotta/yotta_utils.py` | 集群查询 | `GET /compute/list` |
| 4. 销毁实例 | `sky/provision/yotta/instance.py` | Pod 删除 | `POST /compute/delete` |
| 5. 端口映射 | `sky/provision/yotta/instance.py` | 查询端口 | 从 pod metadata 获取 |

### API 请求格式示例

**创建 Pod**:
```python
payload = {
    'gpu_type': 'NVIDIA_A10_24G',
    'gpu_count': 1,
    'image': 'yottalabsai/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04-2025050802',
    'cloud_type': CloudType.SECURE.value,
    'disk_size': 100,
    'timeout_seconds': timeout,
}
response = requests.post(f'{ENDPOINT}/compute/create', json=payload, headers=headers)
```

**查询 Pods**:
```python
params = {'cluster_name': cluster_name}
response = requests.get(f'{ENDPOINT}/compute/list', params=params, headers=headers)
```

---

## 🎯 下一步行动

### Priority 1: 完成缺失组件 ✅

1. ✅ **创建 catalog CSV** - 已完成
2. ✅ **创建开发环境** - 已完成
3. ⏳ **更新 setup.py** - 添加 Yotta 依赖

### Priority 2: 测试和验证

4. **配置凭证** - 创建 `~/.yotta/credentials`
5. **基础测试** - `sky check`, `sky show-gpus --cloud yotta`
6. **启动测试** - 使用 Yotta k8s pods 运行 `examples/minimal.yaml`
7. **验证功能** - SSH, 端口转发, job 执行

### Priority 3: 增强和优化

8. **Multi-node支持** - 确认 Yotta API 是否支持多节点
9. **错误处理** - 替换宽泛的 Exception 捕获
10. **文档** - 添加用户指南和示例
11. **测试** - 编写单元测试和集成测试

---

## 📝 已知限制

1. **不支持 STOP**: Yotta pods 不能暂停，只能销毁
2. **无 Spot 实例**: 目前不支持抢占式实例
3. **固定镜像**: 使用预定义的 Docker 镜像
4. **Launch-only 端口**: 端口只能在启动时配置
5. **Multi-node 未知**: 需要确认 Yotta 是否支持多节点集群

---

## 🔗 参考资源

- **SkyPilot 官方文档**: https://docs.skypilot.co/en/latest/developers/index.html
- **添加新云指南**: https://docs.google.com/document/d/1oWox3qb3Kz3wXXSGg9ZJWijijoa99a3PIQUHBR8UgEGs/edit
- **参考实现**: 
  - RunPod: `sky/clouds/runpod.py` (GPU cloud, container-based, 类似 Yotta)
  - Kubernetes: `sky/clouds/kubernetes.py` (pod-based, 架构参考)
  - Lambda: `sky/clouds/lambda_cloud.py` (GPU cloud, catalog 示例)

---

## 📊 进度追踪

- [x] Cloud interface 实现
- [x] Provisioner 实现
- [x] 认证系统集成
- [x] Catalog 模块
- [x] Ray 模板配置
- [x] Catalog CSV 数据文件
- [x] 开发环境设置
- [ ] setup.py 依赖
- [ ] Data fetcher (可选)
- [ ] 单元测试
- [ ] 文档和示例
- [ ] 端到端测试

**当前完成度**: 85% → 90% (完成catalog和开发环境)

---

生成时间: 2026-01-15  
作者: SkyPilot Yotta Integration Team
