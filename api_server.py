import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 导入我们的异步API客户端
from demotest import AsyncApiClient, process_single_request

app = FastAPI(
    title="AIDGE API服务", 
    description="高并发AIDGE API调用服务",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 保存任务状态
task_results = {}

# 请求模型
class ApiRequest(BaseModel):
    api_name: str
    params: Any  # 修改为Any类型，以支持不同API的参数格式（列表或字典）
    query_api: str
    
    class Config:
        schema_extra = {
            "example": {
                "api_name": "/ai/image/translation_mllm/batch",
                "params": [
                    {
                        "imageUrl": "https://example.com/image.jpg",
                        "sourceLanguage": "zh",
                        "targetLanguage": "en"
                    }
                ],
                "query_api": "/ai/image/translation_mllm/results"
            }
        }

# 批量请求模型
class BatchApiRequest(BaseModel):
    requests: List[ApiRequest]
    max_concurrent: Optional[int] = 5
    
    class Config:
        schema_extra = {
            "example": {
                "requests": [
                    {
                        "api_name": "/ai/image/translation_mllm/batch",
                        "params": [
                            {
                                "imageUrl": "https://example.com/image1.jpg",
                                "sourceLanguage": "zh",
                                "targetLanguage": "en"
                            }
                        ],
                        "query_api": "/ai/image/translation_mllm/results"
                    },
                    {
                        "api_name": "/ai/image/translation_mllm/batch",
                        "params": [
                            {
                                "imageUrl": "https://example.com/image2.jpg",
                                "sourceLanguage": "zh",
                                "targetLanguage": "ko"
                            }
                        ],
                        "query_api": "/ai/image/translation_mllm/results"
                    }
                ],
                "max_concurrent": 5
            }
        }

# 单个API请求
@app.post("/api/process", description="处理单个API请求，提交任务并轮询结果")
async def process_api(request: ApiRequest):
    logger.info(f"处理API请求: {request.api_name}, 参数类型: {type(request.params)}")
    try:
        async with AsyncApiClient() as client:
            task_id = await client.submit_task(request.api_name, request.params)
            if not task_id:
                logger.error(f"提交任务失败: {request.api_name}, 参数: {request.params}")
                raise HTTPException(status_code=400, detail="提交任务失败")
            
            logger.info(f"任务提交成功，任务ID: {task_id}")
            result = await client.poll_task_status(request.query_api, task_id)
            return {"task_id": task_id, "result": json.loads(result)}
    except Exception as e:
        logger.error(f"处理API请求异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理请求异常: {str(e)}")

# 异步批量处理API请求
@app.post("/api/batch", description="异步批量处理多个API请求，返回批处理ID")
async def process_batch(request: BatchApiRequest, background_tasks: BackgroundTasks):
    # 生成批处理ID
    batch_id = f"batch_{len(task_results) + 1}"
    logger.info(f"创建批处理任务: {batch_id}, 请求数量: {len(request.requests)}")
    
    # 将请求转换为process_batch_requests所需的格式
    requests_data = [
        {
            "api_name": req.api_name,
            "params": req.params,
            "query_api": req.query_api
        } for req in request.requests
    ]
    
    # 在后台处理批量请求
    background_tasks.add_task(process_batch_and_save, batch_id, requests_data, request.max_concurrent)
    
    return {"batch_id": batch_id, "message": "批处理任务已提交，请使用批处理ID查询结果"}

# 查询批处理结果
@app.get("/api/batch/{batch_id}", description="查询批处理任务的结果")
async def get_batch_result(batch_id: str):
    if batch_id not in task_results:
        logger.warning(f"批处理ID不存在: {batch_id}")
        raise HTTPException(status_code=404, detail="批处理ID不存在")
    
    logger.info(f"查询批处理结果: {batch_id}, 状态: {task_results[batch_id]['status']}")
    return task_results[batch_id]

# 后台处理批量请求并保存结果
async def process_batch_and_save(batch_id, requests_data, max_concurrent):
    logger.info(f"开始处理批处理任务: {batch_id}, 并发数: {max_concurrent}")
    task_results[batch_id] = {"status": "processing", "results": []}
    
    async with AsyncApiClient(max_concurrent_requests=max_concurrent) as client:
        tasks = []
        for i, req in enumerate(requests_data):
            logger.debug(f"创建子任务 {i}: {req['api_name']}")
            task = asyncio.create_task(
                process_single_request(
                    client, 
                    req["api_name"], 
                    req["params"], 
                    req["query_api"]
                )
            )
            tasks.append((i, task))
        
        results = []
        for i, task in tasks:
            try:
                logger.debug(f"等待子任务 {i} 完成")
                result = await task
                results.append({"index": i, "result": result})
                logger.debug(f"子任务 {i} 完成")
            except Exception as e:
                logger.error(f"子任务 {i} 异常: {str(e)}")
                results.append({"index": i, "error": str(e)})
        
        logger.info(f"批处理任务完成: {batch_id}, 结果数量: {len(results)}")
        task_results[batch_id] = {"status": "completed", "results": results}

# API文档说明
@app.get("/", include_in_schema=False)
async def api_info():
    return {
        "message": "AIDGE API服务",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
        "endpoints": [
            "/api/process - 处理单个API请求",
            "/api/batch - 批量处理API请求",
            "/api/batch/{batch_id} - 查询批处理结果"
        ],
        "note": "注意：不同的API可能需要不同格式的params参数。例如，图像翻译API需要params为列表类型。"
    }

# 健康检查端点
@app.get("/health", description="健康检查端点")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("api_server:app", host="0.0.0.0", port=port)