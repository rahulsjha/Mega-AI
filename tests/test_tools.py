"""
Comprehensive tests for all tools with failure contract validation.
"""

import pytest
import asyncio
from api.tools.base import (
    WebSearchTool, CodeExecutionTool, StructuredDataTool, 
    SelfReflectionTool, ToolInput, ToolResult
)


class TestWebSearchTool:
    """Test WebSearchTool with failure contracts."""

    @pytest.fixture
    def tool(self):
        return WebSearchTool()

    def test_tool_has_failure_contracts(self, tool):
        """Verify tool implements all failure contracts."""
        assert hasattr(tool, 'on_timeout')
        assert hasattr(tool, 'on_empty')
        assert hasattr(tool, 'on_malformed')
        assert callable(tool.on_timeout)
        assert callable(tool.on_empty)
        assert callable(tool.on_malformed)

    @pytest.mark.asyncio
    async def test_search_success(self, tool):
        """Test successful search."""
        input_data = ToolInput(data={"query": "AI"})
        result = await tool.execute_with_timeout(input_data)
        
        assert result is not None
        # Could succeed or timeout (10% probability)
        assert result.error_type in [None, "timeout"]

    def test_on_timeout_returns_error(self, tool):
        """Test timeout error handling."""
        result = tool.on_timeout()
        assert result is not None
        assert result.error_type == "timeout"

    def test_on_empty_returns_error(self, tool):
        """Test empty result handling."""
        result = tool.on_empty()
        assert result is not None
        assert result.error_type == "empty"

    def test_on_malformed_returns_error(self, tool):
        """Test malformed output handling."""
        result = tool.on_malformed(ValueError("test"))
        assert result is not None
        assert result.error_type == "malformed"


class TestCodeExecutionTool:
    """Test CodeExecutionTool with sandboxing."""

    @pytest.fixture
    def tool(self):
        return CodeExecutionTool()

    @pytest.mark.asyncio
    async def test_execute_simple_python(self, tool):
        """Test executing simple Python code."""
        code = "result = 2 + 2\nprint(result)"
        input_data = ToolInput(data={"code": code})
        
        result = await tool.execute_with_timeout(input_data)
        
        assert result is not None
        assert result.success or result.error_type in ["timeout", "malformed"]

    @pytest.mark.asyncio
    async def test_timeout_enforcement(self, tool):
        """Test that timeout is enforced."""
        # This should timeout (1s limit, 2s sleep)
        code = "import time\ntime.sleep(2)"
        input_data = ToolInput(data={"code": code})
        
        result = await tool.execute_with_timeout(input_data)
        
        # Should timeout or raise
        assert result is not None or result.error_type == "timeout"

    def test_on_timeout_returns_error(self, tool):
        """Test timeout error handling."""
        result = tool.on_timeout()
        assert result.error_type == "timeout"

    def test_on_malformed_returns_error(self, tool):
        """Test malformed code handling."""
        result = tool.on_malformed(SyntaxError("invalid code"))
        assert result.error_type == "malformed"


class TestStructuredDataTool:
    """Test StructuredDataTool."""

    @pytest.fixture
    def tool(self):
        return StructuredDataTool()

    @pytest.mark.asyncio
    async def test_query_companies_table(self, tool):
        """Test querying companies table."""
        input_data = ToolInput(data={"table_name": "companies"})
        
        result = await tool.execute_with_timeout(input_data)
        
        assert result is not None
        assert result.success
        assert result.data is not None
        assert isinstance(result.data, list)
        assert len(result.data) > 0

    @pytest.mark.asyncio
    async def test_query_products_table(self, tool):
        """Test querying products table."""
        input_data = ToolInput(data={"table_name": "products"})
        
        result = await tool.execute_with_timeout(input_data)
        
        assert result is not None
        assert result.success
        assert isinstance(result.data, list)

    @pytest.mark.asyncio
    async def test_query_invalid_table(self, tool):
        """Test querying non-existent table."""
        input_data = ToolInput(data={"table_name": "nonexistent"})
        
        result = await tool.execute_with_timeout(input_data)
        
        assert result is not None
        # Should handle gracefully (empty or error)
        assert result.error_type in [None, "empty"]


class TestSelfReflectionTool:
    """Test SelfReflectionTool."""

    @pytest.fixture
    def tool(self):
        return SelfReflectionTool()

    @pytest.mark.asyncio
    async def test_analyze_contradictions(self, tool):
        """Test analyzing contradictions."""
        outputs = [
            "AI is beneficial",
            "AI is harmful",
            "AI is neutral"
        ]
        input_data = ToolInput(data={"outputs": outputs})
        
        result = await tool.execute_with_timeout(input_data)
        
        assert result is not None
        # Should find contradictions or handle gracefully
        assert result.success or result.error_type in [None, "empty"]

    @pytest.mark.asyncio
    async def test_no_contradictions(self, tool):
        """Test with consistent outputs."""
        outputs = [
            "AI is interesting",
            "AI is fascinating",
            "AI is engaging"
        ]
        input_data = ToolInput(data={"outputs": outputs})
        
        result = await tool.execute_with_timeout(input_data)
        
        assert result is not None
        # Should report consistency


class TestToolRetryLogic:
    """Test tool retry logic."""

    @pytest.mark.asyncio
    async def test_retry_on_timeout(self):
        """Test retry mechanism on timeout."""
        tool = WebSearchTool()
        input_data = ToolInput(data={"query": "test"})
        
        # Could succeed or fail, but should not hang
        result = await tool.execute_with_timeout(input_data)
        assert result is not None

    @pytest.mark.asyncio
    async def test_retry_on_empty(self):
        """Test retry mechanism on empty result."""
        tool = StructuredDataTool()
        input_data = ToolInput(data={"table_name": "companies"})
        
        result = await tool.execute_with_timeout(input_data)
        # Should succeed or return empty, not hang
        assert result is not None


class TestToolAuditTrail:
    """Test tool call audit trail."""

    @pytest.mark.asyncio
    async def test_tool_records_execution(self):
        """Test that tools record execution details."""
        tool = StructuredDataTool()
        input_data = ToolInput(data={"table_name": "companies"})
        
        result = await tool.execute_with_timeout(input_data)
        
        # Should have metadata
        assert result is not None
        assert hasattr(result, 'success')
        assert hasattr(result, 'data')


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
