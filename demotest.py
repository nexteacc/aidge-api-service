import asyncio
import aiohttp
import time
import hmac
import hashlib
import json
import os
from dotenv import load_dotenv

load_dotenv()

class AsyncApiConfig:
    """异步API配置类"""
    access_key_name = os.getenv("AIDGE_API_KEY_NAME", "your api key name")
    access_key_secret = os.getenv("AIDGE_API_KEY_SECRET", "your api key secret")
    api_domain = os.getenv("AIDGE_API_DOMAIN", "your api domain")
    use_trial_resource = os.getenv("AIDGE_USE_TRIAL_RESOURCE", "false").lower() == "true"

class AsyncApiClient:
    def __init__(self, max_concurrent_requests=10, timeout=60):
        """初始化异步API客户端
        
        Args:
            max_concurrent_requests: 最大并发请求数
            timeout: 请求超时时间(秒)
        """
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.timeout = timeout
        self.session = None
    
    async def __aenter__(self):
        """创建HTTP会话"""
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """关闭HTTP会话"""
        if self.session:
            await self.session.close()
    
    async def invoke_api(self, api_name, data, is_get=False):
        """调用API
        
        Args:
            api_name: API名称
            data: 请求数据
            is_get: 是否为GET请求
        
        Returns:
            API响应结果
        """
        async with self.semaphore:  # 限制并发请求数
            timestamp = str(int(time.time() * 1000))
            
            # 计算签名
            sign_string = AsyncApiConfig.access_key_secret + timestamp
            sign = hmac.new(AsyncApiConfig.access_key_secret.encode('utf-8'), 
                           sign_string.encode('utf-8'),
                           hashlib.sha256).hexdigest().upper()
            
            url = f"https://{AsyncApiConfig.api_domain}/rest{api_name}?partner_id=aidge&sign_method=sha256&sign_ver=v2&app_key={AsyncApiConfig.access_key_name}&timestamp={timestamp}&sign={sign}"
            
            headers = {
                "Content-Type": "application/json",
                "x-iop-trial": str(AsyncApiConfig.use_trial_resource).lower()
            }
            
            try:
                if is_get:
                    async with self.session.get(url, params=data, headers=headers) as response:
                        return await response.text()
                else:
                    async with self.session.post(url, data=data, headers=headers) as response:
                        return await response.text()
            except Exception as e:
                print(f"API调用异常: {e}")
                return json.dumps({"code": -1, "message": f"API调用异常: {e}"})
    
    async def submit_task(self, api_name, request_params):
        """提交任务
        
        Args:
            api_name: API名称
            request_params: 请求参数
        
        Returns:
            任务ID
        """
        if api_name.startswith("/ai/image/translation"):
            submit_request = {"paramJson": json.dumps(request_params)}
        else:
            submit_request = {"requestParams": json.dumps(request_params)}
        
        submit_request_json = json.dumps(submit_request)
        submit_result = await self.invoke_api(api_name, submit_request_json, False)
        
        try:
            submit_result_json = json.loads(submit_result)
            task_id = submit_result_json.get("data", {}).get("result", {}).get("taskId")
            if not task_id:
                task_id = submit_result_json.get("data", {}).get("taskId")
            return task_id
        except Exception as e:
            print(f"解析任务ID异常: {e}")
            return None
    
    async def poll_task_status(self, query_api_name, task_id, max_retries=60, initial_delay=1, max_delay=10):
        """轮询任务状态（使用指数退避策略）
        
        Args:
            query_api_name: 查询API名称
            task_id: 任务ID
            max_retries: 最大重试次数
            initial_delay: 初始延迟时间(秒)
            max_delay: 最大延迟时间(秒)
        
        Returns:
            任务结果
        """
        if "/ai/virtual/" in query_api_name:
            query_request = json.dumps({"task_id": task_id})
        else:
            query_request = {"taskId": task_id}
        
        delay = initial_delay
        for _ in range(max_retries):
            try:
                query_result = await self.invoke_api(query_api_name, query_request, "/results" in query_api_name)
                query_result_json = json.loads(query_result)
                task_status = query_result_json.get("data", {}).get("taskStatus")
                
                if task_status == "finished" or task_status == "failed":
                    return query_result
                
                # 指数退避策略
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, max_delay)
            except Exception as e:
                print(f"轮询任务状态异常: {e}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)
        
        return json.dumps({"code": -1, "message": "任务轮询超时"})

async def process_batch_requests(requests_data, max_concurrent=10):
    """处理批量请求
    
    Args:
        requests_data: 请求数据列表
        max_concurrent: 最大并发数
    
    Returns:
        处理结果列表
    """
    async with AsyncApiClient(max_concurrent_requests=max_concurrent) as client:
        tasks = []
        for req in requests_data:
            api_name = req.get("api_name")
            params = req.get("params")
            query_api = req.get("query_api")
            
            task = asyncio.create_task(process_single_request(client, api_name, params, query_api))
            tasks.append(task)
        
        return await asyncio.gather(*tasks)

async def process_single_request(client, api_name, params, query_api):
    """处理单个请求
    
    Args:
        client: API客户端
        api_name: API名称
        params: 请求参数
        query_api: 查询API名称
    
    Returns:
        处理结果
    """
    task_id = await client.submit_task(api_name, params)
    if not task_id:
        return {"status": "failed", "message": "提交任务失败"}
    
    result = await client.poll_task_status(query_api, task_id)
    return {"status": "success", "task_id": task_id, "result": result}

# 示例使用
async def main():
    # 构造批量请求
    requests = [
        {
            "api_name": "/ai/image/translation_mllm/batch",
            "params": [
                {
                    "imageUrl": "https://res.cloudinary.com/duztv9eof/image/upload/v1751276165/cdb6we3yqvpygfh74spf.png",
                    "sourceLanguage": "vi",
                    "targetLanguage": "zh",
                    "includingProductArea": "false"
                }
            ],
            "query_api": "/ai/image/translation_mllm/results"
        },
        # 可以添加更多请求...
    ]
    
    results = await process_batch_requests(requests, max_concurrent=5)
    for i, result in enumerate(results):
        print(f"请求 {i+1} 结果: {result}")

if __name__ == "__main__":
    asyncio.run(main())