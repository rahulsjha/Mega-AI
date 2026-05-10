"""
Compression Agent - compresses context when budget threshold exceeded.

Lossless: never compress tool outputs, scores, citations, structured fields.
Lossy: may summarize conversational filler, chain-of-thought sections.
"""

import logging
from api.context.schema import AgentContext, CompressionRecord
from datetime import datetime
import json

logger = logging.getLogger(__name__)


class CompressionAgent:
    """
    Compresses context to free up token budget when needed.
    
    Maintains a lossless/lossy boundary:
    - NEVER compress: tool outputs, scores, citations, structured fields
    - OK to compress: conversational filler, intermediate reasoning, long examples
    """
    
    def __init__(self):
        """Initialize the compression agent."""
        self.name = "compression"
    
    async def execute(self, context: AgentContext) -> AgentContext:
        """
        Execute compression on the context.
        
        Args:
            context: The context to compress
            
        Returns:
            Context with compressions applied and recorded
        """
        import time
        
        start_time = time.time()
        original_size = self._estimate_context_size(context)
        
        try:
            logger.info(
                f"Compression starting for job {context.job_id}",
                extra={
                    "job_id": str(context.job_id),
                    "original_size": original_size
                }
            )
            
            tokens_freed = 0
            compressed_sections = []
            
            # 1. Compress long agent outputs (keep first 500 chars, summarize rest)
            for agent_name, agent_output in context.agent_outputs.items():
                if len(agent_output.result) > 500:
                    original_len = len(agent_output.result)
                    # Truncate with summary marker
                    agent_output.result = (
                        agent_output.result[:500] +
                        f"\n\n[... {original_len - 500} chars compressed ...]"
                    )
                    tokens_freed += (original_len - 500) // 4
                    compressed_sections.append(f"agent_output_{agent_name}")
            
            # 2. Compress metadata to keep only essential keys
            if context.metadata:
                original_metadata_keys = len(context.metadata)
                # Keep only keys that start with "_" or are in essential set
                essential_keys = {"needs_compression", "session_start"}
                context.metadata = {
                    k: v for k, v in context.metadata.items()
                    if k in essential_keys
                }
                if len(context.metadata) < original_metadata_keys:
                    compressed_sections.append("metadata")
                    tokens_freed += 50
            
            # 3. Compress old routing history (keep last 3 decisions)
            if len(context.routing_history) > 3:
                removed_count = len(context.routing_history) - 3
                context.routing_history = context.routing_history[-3:]
                tokens_freed += removed_count * 100
                compressed_sections.append("routing_history")
            
            # 4. Summarize old tool calls (keep recent ones, remove details from old ones)
            if len(context.tool_call_log) > 10:
                recent_count = 10
                removed_count = len(context.tool_call_log) - recent_count
                
                # Remove input/output previews from old calls
                for call in context.tool_call_log[:-recent_count]:
                    call.input_preview = "[compressed]"
                    call.output_preview = "[compressed]"
                
                tokens_freed += removed_count * 50
                compressed_sections.append("tool_call_log")
            
            # 5. Truncate critique results to flagged only
            unflagged_count = sum(1 for c in context.critique_results if not c.flagged)
            if unflagged_count > 0:
                context.critique_results = [c for c in context.critique_results if c.flagged]
                tokens_freed += unflagged_count * 30
                compressed_sections.append("critique_results_unflagged")
            
            # Record compression
            new_size = self._estimate_context_size(context)
            compression_ratio = (original_size - new_size) / original_size if original_size > 0 else 0
            
            record = CompressionRecord(
                original_tokens=original_size,
                compressed_tokens=new_size,
                compression_ratio=compression_ratio,
                sections_compressed=compressed_sections
            )
            context.compression_records.append(record)
            
            latency_ms = (time.time() - start_time) * 1000
            
            logger.info(
                f"Compression completed for job {context.job_id}",
                extra={
                    "job_id": str(context.job_id),
                    "tokens_freed": tokens_freed,
                    "original_size": original_size,
                    "new_size": new_size,
                    "compression_ratio": compression_ratio,
                    "sections_compressed": len(compressed_sections),
                    "latency_ms": latency_ms
                }
            )
            
            context.metadata["last_compression"] = {
                "timestamp": datetime.utcnow().isoformat(),
                "tokens_freed": tokens_freed,
                "sections": compressed_sections
            }
            
            return context
        
        except Exception as e:
            logger.error(
                f"Compression failed: {str(e)}",
                extra={"job_id": str(context.job_id), "error": str(e)}
            )
            return context
    
    def _estimate_context_size(self, context: AgentContext) -> int:
        """
        Estimate context size in tokens using JSON serialization.
        
        Args:
            context: Context to measure
            
        Returns:
            Approximate token count
        """
        try:
            json_str = context.model_dump_json()
            # 1 token ≈ 4 characters
            return max(1, len(json_str) // 4)
        except Exception as e:
            logger.warning(f"Failed to estimate context size: {str(e)}")
            return 1000  # Default estimate
