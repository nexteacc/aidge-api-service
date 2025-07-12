# AIDGE API Service

这是一个**AIDGE API服务**项目，是一个基于FastAPI的高并发API调用服务。

## 项目结构
- **api_server.py**: FastAPI服务器主文件
- **demotest.py**: 异步API客户端实现
- **requirements.txt**: Python依赖包
- **Dockerfile**: 容器化配置
- **fly.toml**: Fly.io部署配置

## 核心功能
1. **单个API请求处理** (`/api/process`)
2. **批量异步处理** (`/api/batch`)
3. **任务状态查询** (`/api/batch/{batch_id}`)
4. **健康检查** (`/health`)

## 技术特点
- 使用**异步编程**提高并发性能
- 支持**批量任务**处理和后台执行
- 实现**任务轮询**机制获取结果
- 包含**HMAC签名认证**
- 支持**指数退避**重试策略
- **容器化部署**支持

## 主要用途
专门用于调用AIDGE平台的AI服务API，特别是图像翻译相关功能，提供高并发、高可用的API网关服务。