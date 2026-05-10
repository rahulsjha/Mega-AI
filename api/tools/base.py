"""
Tool interface and base class with failure contracts.

Every tool implements a strict interface:
- call() — execute the tool
- on_timeout() — handle timeout
- on_empty() — handle empty result
- on_malformed() — handle parse errors
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List
from datetime import datetime
import logging
import hashlib

logger = logging.getLogger(__name__)


@dataclass
class ToolInput:
    """Input to a tool."""
    data: Dict[str, Any] = field(default_factory=dict)
    
    def to_hash(self) -> str:
        """Generate SHA256 hash of input."""
        import json
        text = json.dumps(self.data, sort_keys=True, default=str)
        return hashlib.sha256(text.encode()).hexdigest()


@dataclass
class ToolResult:
    """Result from a tool call."""
    success: bool
    data: Any = None
    error_type: Optional[str] = None  # timeout, empty, malformed, other
    error_message: Optional[str] = None
    output_hash: Optional[str] = None
    
    def to_hash(self) -> str:
        """Generate SHA256 hash of output."""
        import json
        text = json.dumps({
            "success": self.success,
            "data": str(self.data),
            "error_type": self.error_type
        }, default=str)
        return hashlib.sha256(text.encode()).hexdigest()


class Tool(ABC):
    """Abstract base class for all tools."""
    
    def __init__(self, name: str, timeout_seconds: float = 30.0):
        """
        Initialize a tool.
        
        Args:
            name: Name of the tool
            timeout_seconds: Timeout for tool execution
        """
        self.name = name
        self.timeout_seconds = timeout_seconds
        self.call_count = 0
        self.failed_count = 0
    
    @abstractmethod
    async def call(self, input: ToolInput) -> ToolResult:
        """
        Execute the tool.
        
        Args:
            input: Tool input
            
        Returns:
            ToolResult with result or error
            
        Raises:
            TimeoutError: If tool takes too long
        """
        pass
    
    def on_timeout(self) -> ToolResult:
        """
        Handle timeout - return structured error.
        
        Returns:
            ToolResult indicating timeout
        """
        logger.warning(f"Tool {self.name} timed out after {self.timeout_seconds}s")
        return ToolResult(
            success=False,
            error_type="timeout",
            error_message=f"Tool execution exceeded {self.timeout_seconds} second timeout"
        )
    
    def on_empty(self) -> ToolResult:
        """
        Handle empty result - return structured empty.
        
        Returns:
            ToolResult with empty data
        """
        logger.warning(f"Tool {self.name} returned empty result")
        return ToolResult(
            success=False,
            error_type="empty",
            error_message="Tool returned no data",
            data=[]
        )
    
    def on_malformed(self, error: Exception) -> ToolResult:
        """
        Handle malformed output - return structured error.
        
        Args:
            error: The exception that occurred
            
        Returns:
            ToolResult indicating parse error
        """
        logger.error(f"Tool {self.name} produced malformed output: {str(error)}")
        return ToolResult(
            success=False,
            error_type="malformed",
            error_message=f"Failed to parse tool output: {str(error)}"
        )
    
    async def execute_with_timeout(self, input: ToolInput) -> ToolResult:
        """
        Execute tool with timeout handling.
        
        Args:
            input: Tool input
            
        Returns:
            ToolResult
        """
        import asyncio
        
        self.call_count += 1
        
        try:
            # Set timeout using asyncio
            result = await asyncio.wait_for(
                self.call(input),
                timeout=self.timeout_seconds
            )
            return result
        except asyncio.TimeoutError:
            self.failed_count += 1
            return self.on_timeout()
        except Exception as e:
            self.failed_count += 1
            logger.error(f"Tool {self.name} raised exception: {str(e)}")
            return ToolResult(
                success=False,
                error_type="error",
                error_message=str(e)
            )


class WebSearchTool(Tool):
    """
    Web search tool - returns search results with snippets and relevance scores.
    
    Simulates occasional timeouts (~10% of calls) as per spec.
    """
    
    def __init__(self):
        super().__init__("web_search", timeout_seconds=10.0)
        self.timeout_rate = 0.1  # 10% timeout rate
    
    async def call(self, input: ToolInput) -> ToolResult:
        """
        Execute web search.
        
        Args:
            input: Should contain "query" field
            
        Returns:
            ToolResult with list of search results
        """
        import random
        import asyncio
        
        query = input.data.get("query", "")
        
        if not query:
            return self.on_empty()
        
        # Simulate occasional timeouts
        if random.random() < self.timeout_rate:
            await asyncio.sleep(self.timeout_seconds + 1)
            return self.on_timeout()
        
        # Simulate network delay
        await asyncio.sleep(random.uniform(0.1, 0.5))
        
        # Generate mock results
        results = [
            {
                "url": f"https://example.com/article-{i}",
                "snippet": f"Result {i} for '{query}': This is a relevant snippet about {query}",
                "relevance_score": 1.0 - (i * 0.15)  # Decreasing relevance
            }
            for i in range(1, 4)
        ]
        
        return ToolResult(
            success=True,
            data=results,
            output_hash=hashlib.sha256(
                str(results).encode()
            ).hexdigest()
        )


class CodeExecutionTool(Tool):
    """
    Code execution tool - runs Python code with 10-second timeout.
    
    Returns stdout, stderr, exit code, and latency.
    """
    
    def __init__(self):
        super().__init__("code_execution", timeout_seconds=10.0)
    
    async def call(self, input: ToolInput) -> ToolResult:
        """
        Execute Python code.
        
        Args:
            input: Should contain "code" field
            
        Returns:
            ToolResult with execution results
        """
        import subprocess
        import asyncio
        import time
        from datetime import datetime
        
        code = input.data.get("code", "")
        
        if not code:
            return self.on_empty()
        
        try:
            # Create a temporary file to execute
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.py',
                delete=False
            ) as f:
                f.write(code)
                temp_file = f.name
            
            try:
                # Execute with timeout
                start_time = time.time()
                process = await asyncio.create_subprocess_exec(
                    "python",
                    temp_file,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self.timeout_seconds
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    return self.on_timeout()
                
                latency_ms = (time.time() - start_time) * 1000
                
                result = {
                    "stdout": stdout.decode('utf-8', errors='ignore'),
                    "stderr": stderr.decode('utf-8', errors='ignore'),
                    "exit_code": process.returncode,
                    "latency_ms": latency_ms
                }
                
                return ToolResult(
                    success=True,
                    data=result,
                    output_hash=hashlib.sha256(
                        str(result).encode()
                    ).hexdigest()
                )
            finally:
                os.unlink(temp_file)
        
        except Exception as e:
            return self.on_malformed(e)


class StructuredDataTool(Tool):
    """
    Structured data tool - queries a local database.
    
    Agent generates natural language queries that are converted to SQL.
    Returns rows from execution.
    """
    
    def __init__(self):
        super().__init__("structured_data", timeout_seconds=30.0)
        self.sample_tables = {
            "companies": [
                {"id": 1, "name": "TechCorp", "industry": "Technology", "founded": 2010},
                {"id": 2, "name": "FinServ", "industry": "Finance", "founded": 2005},
                {"id": 3, "name": "RetailCo", "industry": "Retail", "founded": 2015},
            ],
            "products": [
                {"id": 1, "name": "Product A", "company_id": 1, "price": 99.99},
                {"id": 2, "name": "Product B", "company_id": 2, "price": 149.99},
                {"id": 3, "name": "Product C", "company_id": 1, "price": 79.99},
            ]
        }
    
    async def call(self, input: ToolInput) -> ToolResult:
        """
        Execute structured query.
        
        Args:
            input: Should contain "query" or "table_name" field
            
        Returns:
            ToolResult with query results
        """
        import asyncio
        
        query = input.data.get("query")
        table_name = input.data.get("table_name")
        
        if not query and not table_name:
            return self.on_empty()
        
        # Simulate query execution time
        await asyncio.sleep(0.1)
        
        try:
            if table_name and table_name in self.sample_tables:
                results = self.sample_tables[table_name]
            elif query:
                # In production, this would parse and execute SQL
                # For now, simulate a generic query
                results = self.sample_tables.get("companies", [])
            else:
                return self.on_empty()
            
            return ToolResult(
                success=True,
                data=results,
                output_hash=hashlib.sha256(
                    str(results).encode()
                ).hexdigest()
            )
        except Exception as e:
            return self.on_malformed(e)


class SelfReflectionTool(Tool):
    """
    Self-reflection tool - examines an agent's own prior outputs.
    
    Scans context.agent_outputs for the calling agent and returns a diff
    of any contradictions found.
    """
    
    def __init__(self):
        super().__init__("self_reflection", timeout_seconds=5.0)
    
    async def call(self, input: ToolInput) -> ToolResult:
        """
        Perform self-reflection.
        
        Args:
            input: Should contain "agent_name" and "current_output"
            
        Returns:
            ToolResult with contradiction analysis
        """
        import asyncio
        
        agent_name = input.data.get("agent_name")
        current_output = input.data.get("current_output")
        
        if not agent_name or not current_output:
            return self.on_empty()
        
        # Simulate analysis
        await asyncio.sleep(0.05)
        
        try:
            # In production, would compare against context.agent_outputs[agent_name]
            # For now, return a sample analysis
            analysis = {
                "agent_name": agent_name,
                "contradictions_found": 0,
                "confidence_score": 0.95,
                "details": "No major contradictions detected in this output"
            }
            
            return ToolResult(
                success=True,
                data=analysis,
                output_hash=hashlib.sha256(
                    str(analysis).encode()
                ).hexdigest()
            )
        except Exception as e:
            return self.on_malformed(e)
